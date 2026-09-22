"""Score station forecasts in fixed ERA5 1991--2020 percentile regimes.

This is the direct-ClickHouse counterpart of ``extract.py``. It preserves the
existing model/date matching, ensemble-mean scoring, and trailing-four-week
debiasing, but assigns each valid hour using country/day/hour climatological
thresholds from ``extract_climatology_thresholds.py``.

The script reads CH_HOST, CH_PORT, CH_USER, and CH_PASSWORD. Per-model results
are cached and the two output files are kept separate from the current-window
results for explicit comparison:

* data/derived/bucketed_metrics_climatology.parquet
* data/derived/solar_metrics_country_climatology.parquet

Run:
    uv run python scripts/extract_climatology_metrics.py [--workers N]
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import clickhouse_connect
import polars as pl
import yaml
from clickhouse_connect.driver.external import ExternalData

from qe_client import PROJECT_ROOT

CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())
COUNTRIES = [str(country) for country in CONFIG["countries"]]
MODEL_ATTRS = CONFIG["models"]

DERIVED_DIR = PROJECT_ROOT / "data" / "derived"
# Bump whenever the jointly matched model cohort or query semantics change.
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "climatology_metrics_paired_exact_v15"
THRESHOLDS_PATH = (
    DERIVED_DIR / "station_climatology_thresholds_era5_1991_2020.parquet"
)
SYNOPTIC_OUT = DERIVED_DIR / "bucketed_metrics_climatology.parquet"
SOLAR_OUT = DERIVED_DIR / "solar_metrics_country_climatology.parquet"
SYNOPTIC_WINDOW_OUT = DERIVED_DIR / "bucketed_metrics_window_matched.parquet"
SOLAR_WINDOW_OUT = DERIVED_DIR / "solar_metrics_country_window_matched.parquet"

DEFAULT_WORKERS = 6
INIT_HOURS = [0, 6, 12, 18]
TEMP = "air_temperature_at_height_level_2m"
WIND = "wind_speed_at_height_level_10m"
SOLAR = "surface_downwelling_shortwave_flux_sum_1h"
SYNOPTIC_VARIABLES = [WIND, TEMP]

TRACK_A_SOLAR_MODELS = [
    "ept2_1_helios",
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_e",
    "ept2_reasoning",
    "ecmwf_ifs_single",
    "noaa_gfs_single",
    "icon_global",
]
TRACK_MODELS = {
    "track_a": [
        "ept2_1_europa",
        "ept2_hrrr",
        "ept2_e",
        "ept2_reasoning",
        "aifs_ens",
        "aifs",
        "aurora",
        "ecmwf_ifs_single",
        "noaa_gfs_single",
        "icon_global",
        "ecmwf_ens",
    ],
    "track_b": [
        "ept2_1_europa",
        "ept2_hrrr",
        "icon_eu",
        "ecmwf_ifs_single",
    ],
}
TRACK_B_SOLAR_MODELS = [
    "ept2_1_helios",
    "ept2_1_europa",
    "ept2_hrrr",
    "icon_eu",
    "ecmwf_ifs_single",
]
SOLAR_MAX_LEAD_MINUTES = 48 * 60
TRACK_A_SOLAR_SNAPSHOTS = {
    "DE": "2026-07-19T10:16:51Z",
    "FR": "2026-07-19T10:17:40Z",
    "ES": "2026-07-19T10:16:24Z",
    "IT": "2026-07-19T10:16:54Z",
    "NL": "2026-07-19T10:16:53Z",
    "BE": "2026-07-19T11:25:25Z",
    "CH": "2026-07-19T11:25:54Z",
    "NO": "2026-07-19T10:17:10Z",
    "CZ": "2026-07-19T10:17:05Z",
    "DK": "2026-07-19T10:17:22Z",
}
SOLAR_EXCLUDED_COUNTRIES = {"AT"}
CANONICAL_SOURCE_SNAPSHOT = "2026-07-19T09:30:00Z"

ENSEMBLE_MODELS = {
    model
    for model, attrs in MODEL_ATTRS.items()
    if attrs.get("output") == "ensemble"
}
ENSEMBLE_MODELS.update({"ept2_1_helios"})

BIAS_COLUMNS = {
    TEMP: "bias_t2m",
    WIND: "bias_ws10",
    SOLAR: "bias_ssrd",
}

_thread_local = threading.local()
_threshold_lock = threading.Lock()


def _client():
    client = getattr(_thread_local, "clickhouse_client", None)
    if client is not None:
        return client
    missing = [
        key
        for key in ("CH_HOST", "CH_PORT", "CH_USER", "CH_PASSWORD")
        if not os.environ.get(key)
    ]
    if missing:
        raise RuntimeError(f"Missing ClickHouse environment variables: {missing}")
    client = clickhouse_connect.get_client(
        host=os.environ["CH_HOST"],
        port=int(os.environ["CH_PORT"]),
        username=os.environ["CH_USER"],
        password=os.environ["CH_PASSWORD"],
        secure=True,
        connect_timeout=900,
        send_receive_timeout=900,
    )
    _thread_local.clickhouse_client = client
    return client


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _climatology_day_sql(time_expr: str) -> str:
    year = f"toYear({time_expr})"
    leap = (
        f"(({year} % 4 = 0 AND {year} % 100 != 0) OR {year} % 400 = 0)"
    )
    return (
        f"toDayOfYear({time_expr})"
        f" - if({leap} AND toMonth({time_expr}) > 2, 1, 0)"
    )


@functools.cache
def _solar_stations(country: str) -> list[str]:
    result = _client().query(
        """
SELECT DISTINCT station
FROM production.synoptic_geo_mapping
WHERE country_key = {country:String}
  AND station IN (
    SELECT concat('solar:', station_id)
    FROM production.solar_station_meta
    WHERE is_clean = 1
  )
ORDER BY station
""",
        {"country": country},
    )
    return [row[0] for row in result.result_rows]


@functools.cache
def _threshold_file(country: str, variable: str) -> Path:
    short = {TEMP: "temp", WIND: "wind", SOLAR: "solar"}[variable]
    path = CACHE_DIR / "external_thresholds" / f"{country}_{short}.parquet"
    if path.exists():
        return path
    with _threshold_lock:
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.parquet")
        source = pl.scan_parquet(THRESHOLDS_PATH).filter(
            pl.col("variable") == variable
        )
        if variable == SOLAR:
            source = source.filter(pl.col("station").is_in(_solar_stations(country)))
        else:
            source = source.filter(pl.col("country") == country)
        (
            source
            .select(
                "station",
                "climatology_day",
                "hour",
                "q05",
                "q25",
                "q75",
                "q95",
            )
            .sort(["station", "climatology_day", "hour"])
            .sink_parquet(tmp)
        )
        if pl.scan_parquet(tmp).select(pl.len()).collect().item() == 0:
            tmp.unlink()
            raise RuntimeError(
                f"No climatology thresholds for {country} {variable}"
            )
        tmp.replace(path)
    return path


def _external_thresholds(country: str, variable: str) -> ExternalData:
    return ExternalData(
        file_path=str(_threshold_file(country, variable)),
        file_name="climatology_thresholds.parquet",
        fmt="Parquet",
        structure=(
            "station String, climatology_day UInt16, hour UInt8, "
            "q05 Float64, q25 Float64, q75 Float64, q95 Float64"
        ),
    )


def _common_dates(
    *,
    key: str,
    models: list[str],
    start: str,
    end: str,
) -> list[date]:
    path = CACHE_DIR / "common_dates" / f"{key}.json"
    if path.exists():
        return [date.fromisoformat(value) for value in json.loads(path.read_text())]
    query = """
SELECT date
FROM production.synoptic_station_error_dates
WHERE model IN {models:Array(String)}
  AND date >= toDate({start:DateTime})
  AND date < toDate({end:DateTime})
GROUP BY date
HAVING uniqExact(model) = {n_models:UInt16}
ORDER BY date
LIMIT 1000
SETTINGS max_execution_time = 30,
         max_rows_to_read = 1000000,
         max_result_rows = 2000,
         timeout_before_checking_execution_speed = 0
"""
    params = {
        "models": models,
        "start": _parse_utc(start),
        "end": _parse_utc(end),
        "n_models": len(models),
    }
    values = [row[0] for row in _client().query(query, params).result_rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([value.isoformat() for value in values]))
    return values


def _bias_cte(variable: str) -> str:
    bias_column = BIAS_COLUMNS[variable]
    state_column = f"{bias_column}_state"
    return f"""
bias AS (
  SELECT model, applies_to_week, init_hour, lead,
         1 AS bias_present,
         avgMerge({state_column}) AS bias_value
  FROM (
    SELECT bs.model AS model,
           toHour(bs.init_time) AS init_hour,
           bs.prediction_timedelta AS lead,
           arrayJoin(arrayMap(
             k -> toMonday(
                    bs.init_time
                    + toIntervalMinute(bs.prediction_timedelta)
                  ) + toIntervalWeek(k),
             range(1, 5)
           )) AS applies_to_week,
           bs.{state_column} AS {state_column}
    FROM production.synoptic_station_bias_europe AS bs
    WHERE bs.model IN {{models:Array(String)}}
      AND bs.init_time >= {{bias_start:DateTime}}
      AND bs.init_time < {{end:DateTime}}
  )
  GROUP BY model, applies_to_week, init_hour, lead
)"""


def _period_array_sql(*, solar: bool) -> str:
    if solar:
        month_start = (
            "greatest(toDateTime({start:DateTime}), "
            "toDateTime(toStartOfMonth(init_time)))"
        )
    else:
        month_start = "toDateTime(toStartOfMonth(init_time))"
    return (
        "[tuple('full', toDateTime({start:DateTime})), "
        f"tuple('month', {month_start})]"
    )


def _source_cte(
    *,
    variable: str,
    station_filter: str,
    extra_filter: str = "",
) -> str:
    def shared_where(alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return f"""
    AND {prefix}station IN ({station_filter})
    AND {prefix}init_time >= {{start:DateTime}}
    AND {prefix}init_time < {{end:DateTime}}
    AND {prefix}prediction_timedelta > 0
    AND {prefix}prediction_timedelta <= {{max_lead:UInt32}}
    AND toHour({prefix}init_time) IN {{init_hours:Array(UInt8)}}
    AND isFinite({prefix}{variable})
    AND ({prefix}{variable} IS NOT NULL)
    {extra_filter}"""

    return f"""
common_dates AS (
  SELECT toDate(init_time) AS init_date
  FROM production.synoptic_station_error_member
  WHERE model IN {{models:Array(String)}}
    {shared_where()}
  GROUP BY init_date
  HAVING uniqExact(model) = {{n_models:UInt16}}
),
common_points AS (
  SELECT station, init_time, prediction_timedelta
  FROM production.synoptic_station_error_member
  WHERE model IN {{models:Array(String)}}
    {shared_where()}
    AND toDate(init_time) IN (SELECT init_date FROM common_dates)
  GROUP BY station, init_time, prediction_timedelta
  HAVING uniqExact(model) = {{n_models:UInt16}}
),
model_points AS (
  SELECT model, station, init_time, prediction_timedelta,
         any(latitude) AS latitude, any(longitude) AS longitude,
         avg({variable}) AS raw_error
  FROM production.synoptic_station_error_member
  WHERE model IN {{models:Array(String)}}
    {shared_where()}
    AND toDate(init_time) IN (SELECT init_date FROM common_dates)
    AND (station, init_time, prediction_timedelta) IN (
      SELECT station, init_time, prediction_timedelta
      FROM common_points
    )
  GROUP BY model, station, init_time, prediction_timedelta
),
points AS (
  SELECT model, station, init_time, prediction_timedelta,
         latitude, longitude, raw_error
  FROM model_points
)"""


def _bucket_ctes_sql(period_array: str) -> str:
    return f"""
periodized AS (
  SELECT joined.*, period.1 AS period_kind, period.2 AS period_start
  FROM joined
  ARRAY JOIN {period_array} AS period
),
window_thresholds AS (
  SELECT period_kind, period_start,
         quantilesTDigest(0.05, 0.25, 0.75, 0.95)(obs_value) AS qs
  FROM periodized
  GROUP BY period_kind, period_start
),
bucketed AS (
  SELECT p.*,
         multiIf(
           p.obs_value < w.qs[1], 'lt_q5',
           p.obs_value < w.qs[2], 'q5_q25',
           p.obs_value < w.qs[3], 'q25_q75',
           p.obs_value < w.qs[4], 'q75_q95',
           'gt_q95'
         ) AS window_regime
  FROM periodized AS p
  INNER JOIN window_thresholds AS w
    ON w.period_kind = p.period_kind
   AND w.period_start = p.period_start
),
debiased_common_points AS (
  SELECT station_id, init_time, prediction_timedelta
  FROM bucketed
  WHERE bias_present = 1 AND isFinite(bias_value)
  GROUP BY station_id, init_time, prediction_timedelta
  HAVING uniqExact(model_name) = {{n_models:UInt16}}
)"""


def _metric_select_sql() -> str:
    return """
SELECT bucket_definition, model_name AS model, prediction_timedelta,
       score.1 AS debias, bucket AS obs_bucket,
       period_kind, period_start,
       sqrt(avg(score.2 * score.2)) AS rmse,
       avg(abs(score.2)) AS mae,
       avg(score.2) AS bias,
       count() AS sample_count
FROM bucketed
ARRAY JOIN [
  tuple(toUInt8(0), raw_error, toUInt8(1)),
  tuple(
    toUInt8(1),
    raw_error - bias_value,
    toUInt8(bias_present = 1 AND isFinite(bias_value))
  )
] AS score
ARRAY JOIN ['window', 'climatology'] AS bucket_definition
ARRAY JOIN if(
  bucket_definition = 'window',
  ['all', window_regime],
  if(threshold_present, ['all', regime], ['all', 'unclassified'])
) AS bucket
WHERE score.3 = 1
  AND (station_id, init_time, prediction_timedelta) IN (
    SELECT station_id, init_time, prediction_timedelta
    FROM debiased_common_points
  )
GROUP BY bucket_definition, model_name, prediction_timedelta, debias, obs_bucket,
         period_kind, period_start
ORDER BY bucket_definition, model_name, prediction_timedelta, debias, obs_bucket,
         period_kind, period_start
LIMIT 500000
SETTINGS max_execution_time = 900,
         max_rows_to_read = 0,
         max_result_rows = 500000,
         timeout_before_checking_execution_speed = 0,
         join_algorithm = 'auto',
         optimize_aggregation_in_order = 1
"""


def _synoptic_sql(variable: str, country: str) -> str:
    valid_time = "p.init_time + toIntervalMinute(p.prediction_timedelta)"
    clim_day = _climatology_day_sql(valid_time)
    station_filter = f"""
      SELECT station
      FROM production.synoptic_geo_mapping
      WHERE country_key = '{country}'
      LIMIT 10000"""
    source = _source_cte(
        variable=variable,
        station_filter=station_filter,
        extra_filter="AND inserted_at <= {source_as_of:DateTime}",
    )
    bias = _bias_cte(variable)
    period_array = _period_array_sql(solar=False)
    bucket_ctes = _bucket_ctes_sql(period_array)
    select = _metric_select_sql()
    return f"""
WITH
obs AS (
  SELECT station, time, toFloat32({variable}) / 10.0 AS obs_value
  FROM production.synoptic_station_data FINAL
  WHERE station IN ({station_filter})
    AND time >= {{start:DateTime}}
    AND time <= {{end:DateTime}} + toIntervalMinute({{max_lead:UInt32}})
    AND {variable} != 65535
),
{source},
{bias},
joined AS (
  SELECT p.model AS model_name, p.station AS station_id,
         p.init_time, p.prediction_timedelta,
         p.raw_error, o.obs_value,
         b.bias_present, b.bias_value,
         t.station != '' AS threshold_present,
         multiIf(
           o.obs_value < t.q05, 'lt_q5',
           o.obs_value < t.q25, 'q5_q25',
           o.obs_value < t.q75, 'q25_q75',
           o.obs_value < t.q95, 'q75_q95',
           'gt_q95'
         ) AS regime
  FROM points AS p
  INNER JOIN obs AS o
    ON o.station = p.station AND o.time = {valid_time}
  LEFT JOIN climatology_thresholds AS t
    ON t.station = p.station
   AND t.climatology_day = {clim_day}
   AND t.hour = toHour({valid_time})
  LEFT JOIN bias AS b
    ON b.model = p.model
   AND b.applies_to_week = toMonday({valid_time})
   AND b.init_hour = toHour(p.init_time)
   AND b.lead = p.prediction_timedelta
),
{bucket_ctes}
{select}
"""


def _solar_daylight_sql(valid_time: str) -> str:
    key = (
        f"toUInt32((toDayOfYear({valid_time}) - 1) * 2880"
        f" + (toHour({valid_time}) * 60 + toMinute({valid_time})) * 2"
        f" + intDiv(toSecond({valid_time}), 30))"
    )
    geometry = (
        "dictGet('production.solar_geometry_dict', "
        "('sin_decl', 'cos_decl', 'eqt'), "
        f"{key})"
    )
    fractional_hour = (
        f"(toHour({valid_time}) + toMinute({valid_time}) / 60.0"
        f" + toSecond({valid_time}) / 3600.0)"
    )
    true_solar_time = (
        f"({fractional_hour} * 60 + tupleElement({geometry}, 3)"
        " + 4 * p.longitude)"
    )
    wrapped_solar_time = (
        f"({true_solar_time} - 1440 * floor({true_solar_time} / 1440))"
    )
    hour_angle = f"radians({wrapped_solar_time} / 4.0 - 180.0)"
    return (
        f"(sin(radians(p.latitude)) * tupleElement({geometry}, 1)"
        f" + cos(radians(p.latitude)) * tupleElement({geometry}, 2)"
        f" * cos({hour_angle}) > 0)"
    )


def _solar_sql(country: str) -> str:
    valid_time = "p.init_time + toIntervalMinute(p.prediction_timedelta)"
    clim_day = _climatology_day_sql(valid_time)
    station_filter = f"""
      SELECT station
      FROM production.synoptic_geo_mapping
      WHERE country_key = '{country}'
        AND station IN (
          SELECT concat('solar:', station_id)
          FROM production.solar_station_meta
          WHERE is_clean = 1
        )
      LIMIT 10000"""
    source = _source_cte(
        variable=SOLAR,
        station_filter=station_filter,
        extra_filter="AND inserted_at <= {source_as_of:DateTime}",
    )
    bias = _bias_cte(SOLAR)
    period_array = _period_array_sql(solar=True)
    bucket_ctes = _bucket_ctes_sql(period_array)
    select = _metric_select_sql()
    daylight = _solar_daylight_sql(valid_time)
    return f"""
WITH
obs AS (
  SELECT concat('solar:', station_id) AS station, time,
         {SOLAR} AS obs_value
  FROM production.solar_station_obs
  WHERE concat('solar:', station_id) IN (
      {station_filter}
    )
    AND time >= {{start:DateTime}}
    AND time <= {{end:DateTime}} + toIntervalMinute({{max_lead:UInt32}})
),
{source},
{bias},
joined AS (
  SELECT p.model AS model_name, p.station AS station_id,
         p.init_time, p.prediction_timedelta,
         p.raw_error, o.obs_value,
         b.bias_present, b.bias_value,
         (t.station != '' AND t.q95 > 0) AS threshold_present,
         multiIf(
           o.obs_value < t.q05, 'lt_q5',
           o.obs_value < t.q25, 'q5_q25',
           o.obs_value < t.q75, 'q25_q75',
           o.obs_value < t.q95, 'q75_q95',
           'gt_q95'
         ) AS regime
  FROM points AS p
  INNER JOIN obs AS o
    ON o.station = p.station AND o.time = {valid_time}
  LEFT JOIN climatology_thresholds AS t
    ON t.station = p.station
   AND t.climatology_day = {clim_day}
   AND t.hour = toHour({valid_time})
  LEFT JOIN bias AS b
    ON b.model = p.model
   AND b.applies_to_week = toMonday({valid_time})
   AND b.init_hour = toHour(p.init_time)
   AND b.lead = p.prediction_timedelta
  WHERE {daylight}
),
{bucket_ctes}
{select}
"""


def _period_end(track: str, period_kind: str, period_start: datetime) -> datetime:
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    if period_kind == "full":
        return _parse_utc(CONFIG["tracks"][track]["end"])
    if period_start.month == 12:
        return period_start.replace(
            year=period_start.year + 1, month=1, day=1
        )
    return period_start.replace(month=period_start.month + 1, day=1)


def _format_period_columns(frame: pl.DataFrame) -> pl.DataFrame:
    expressions = []
    for column in ("period_start", "period_end"):
        if frame.schema[column].base_type() == pl.Datetime:
            expressions.append(
                pl.col(column).dt.strftime("%Y-%m-%dT%H:%M:%SZ").alias(column)
            )
        else:
            expressions.append(pl.col(column).cast(pl.String).alias(column))
    return frame.with_columns(expressions)


def _long_frame(
    result,
    *,
    track: str,
    country: str,
    variable: str,
) -> pl.DataFrame:
    wide = pl.DataFrame(
        result.result_rows, schema=result.column_names, orient="row"
    )
    if wide.is_empty():
        return pl.DataFrame()
    frames = []
    for metric in ("rmse", "mae", "bias"):
        frames.append(
            wide.select(
                "bucket_definition",
                "model",
                pl.lit(variable).alias("variable"),
                "prediction_timedelta",
                pl.lit(metric).alias("metric"),
                "obs_bucket",
                pl.col(metric).alias("avg"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_05"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_25"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_50"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_75"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_95"),
                "sample_count",
                pl.lit(track).alias("track"),
                "period_kind",
                "period_start",
                pl.lit(country).alias("country"),
                pl.col("debias").cast(pl.Boolean),
                pl.lit("mean").alias("family"),
            )
        )
    long = pl.concat(frames)
    return _format_period_columns(
        long.with_columns(
            pl.struct(["period_kind", "period_start"])
            .map_elements(
                lambda row: _period_end(
                    track, row["period_kind"], row["period_start"]
                ),
                return_dtype=pl.Datetime("us", "UTC"),
            )
            .alias("period_end")
        )
    )


def _cell_path(track: str, country: str, variable: str, model: str) -> Path:
    var = {TEMP: "temp", WIND: "wind", SOLAR: "solar"}[variable]
    return CACHE_DIR / "metrics" / f"{track}_{country}_{var}_{model}.parquet"


def _run_cell(cell: dict) -> tuple[dict, int, float]:
    path = _cell_path(
        cell["track"], cell["country"], cell["variable"], cell["model"]
    )
    if path.exists():
        return cell, pl.read_parquet(path).height, 0.0

    start = cell["start"]
    end = cell["end"]
    params = {
        "models": cell["models"],
        "n_models": len(cell["models"]),
        "start": _parse_utc(start),
        "end": _parse_utc(end),
        "bias_start": _parse_utc(start) - timedelta(days=35),
        "max_lead": cell["max_lead"],
        "init_hours": INIT_HOURS,
        "source_as_of": _parse_utc(CANONICAL_SOURCE_SNAPSHOT),
    }
    if cell["variable"] == SOLAR:
        params["source_as_of"] = _parse_utc(
            TRACK_A_SOLAR_SNAPSHOTS.get(
                cell["country"], "2026-07-19T11:25:54Z"
            )
        )
    sql = (
        _solar_sql(cell["country"])
        if cell["variable"] == SOLAR
        else _synoptic_sql(cell["variable"], cell["country"])
    )
    started = time.monotonic()
    result = _client().query(
        sql,
        params,
        external_data=_external_thresholds(
            cell["country"], cell["variable"]
        ),
    )
    frame = _long_frame(
        result,
        track=cell["track"],
        country=cell["country"],
        variable=cell["variable"],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return cell, frame.height, time.monotonic() - started


def _cells(tracks: list[str]) -> list[dict]:
    cells: list[dict] = []
    if "track_a" in tracks or "track_b" in tracks:
        for track in ("track_a", "track_b"):
            if track not in tracks:
                continue
            cfg = CONFIG["tracks"][track]
            track_models = TRACK_MODELS[track]
            for country in COUNTRIES:
                for variable in SYNOPTIC_VARIABLES:
                    cells.append(
                        {
                            "track": track,
                            "country": country,
                            "variable": variable,
                            "model": "matched_models",
                            "models": track_models,
                            "start": cfg["start"],
                            "end": cfg["end"],
                            "max_lead": cfg["max_lead_hours"] * 60,
                        }
                    )
            solar_countries = (
                set(TRACK_A_SOLAR_SNAPSHOTS)
                if track == "track_a"
                else {
                    country
                    for country in COUNTRIES
                    if country not in SOLAR_EXCLUDED_COUNTRIES
                    and _solar_stations(country)
                }
            )
            solar_models = (
                TRACK_A_SOLAR_MODELS
                if track == "track_a"
                else TRACK_B_SOLAR_MODELS
            )
            for country in (
                country for country in COUNTRIES if country in solar_countries
            ):
                cells.append(
                    {
                        "track": track,
                        "country": country,
                        "variable": SOLAR,
                        "model": "matched_models",
                        "models": solar_models,
                        "start": cfg["start"],
                        "end": cfg["end"],
                        "max_lead": SOLAR_MAX_LEAD_MINUTES,
                    }
                )
    return cells


def _write_outputs(cells: list[dict]) -> None:
    paths = [
        _cell_path(
            cell["track"], cell["country"], cell["variable"], cell["model"]
        )
        for cell in cells
    ]
    frames = [
        _format_period_columns(pl.read_parquet(path))
        for path in paths
        if path.exists() and pl.read_parquet(path).height > 0
    ]
    if not frames:
        raise RuntimeError("No metric result cells were produced")
    data = pl.concat(frames)
    for definition, synoptic_out, solar_out in (
        ("climatology", SYNOPTIC_OUT, SOLAR_OUT),
        ("window", SYNOPTIC_WINDOW_OUT, SOLAR_WINDOW_OUT),
    ):
        variant = data.filter(
            pl.col("bucket_definition") == definition
        ).drop("bucket_definition")
        synoptic = variant.filter(pl.col("variable") != SOLAR)
        solar = variant.filter(pl.col("variable") == SOLAR)
        if synoptic.height:
            synoptic.write_parquet(synoptic_out)
            print(f"wrote {synoptic_out} ({synoptic.height} rows)")
        if solar.height:
            solar.write_parquet(solar_out)
            print(f"wrote {solar_out} ({solar.height} rows)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--track",
        action="append",
        choices=("track_a", "track_b"),
    )
    parser.add_argument("--country", action="append", choices=COUNTRIES)
    parser.add_argument("--model", action="append")
    args = parser.parse_args()

    if not THRESHOLDS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {THRESHOLDS_PATH}; run "
            "scripts/extract_climatology_thresholds.py first"
        )
    tracks = args.track or ["track_a", "track_b"]
    cells = _cells(tracks)
    if args.country:
        cells = [cell for cell in cells if cell["country"] in args.country]
    if args.model:
        cells = [cell for cell in cells if cell["model"] in args.model]
    print(f"{len(cells)} metric cells on {args.workers} workers")

    completed = 0
    lock = threading.Lock()
    started = time.monotonic()

    def run(cell: dict):
        nonlocal completed
        result = _run_cell(cell)
        with lock:
            completed += 1
            info, rows, elapsed = result
            print(
                f"[{completed}/{len(cells)}] {info['track']} {info['country']} "
                f"{info['variable'].split('_')[0]} {info['model']} "
                f"rows={rows} query_s={elapsed:.1f}",
                flush=True,
            )
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, cells))
    _write_outputs(cells)
    print(f"finished in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
