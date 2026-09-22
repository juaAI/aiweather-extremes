"""Extract a forecast-conditioned reliability diagnostic at 48 h.

Observation-conditioned bins necessarily show regression toward the centre for
any imperfect forecast. This companion diagnostic instead bins the forecast
against the same fixed ERA5 1991--2020 station/day/hour thresholds. For a
conditionally unbiased point forecast, mean forecast-minus-observation error
within a forecast bin is zero.

Reads the same ClickHouse tables, date intersection, bias correction, and
external threshold files as ``extract_climatology_metrics.py``.
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import polars as pl

from extract_climatology_metrics import (
    CANONICAL_SOURCE_SNAPSHOT,
    CONFIG,
    COUNTRIES,
    DERIVED_DIR,
    INIT_HOURS,
    SYNOPTIC_VARIABLES,
    TRACK_MODELS,
    _bias_cte,
    _client,
    _climatology_day_sql,
    _external_thresholds,
    _parse_utc,
    _source_cte,
)

LEAD_MINUTES = 48 * 60
OUT = DERIVED_DIR / "forecast_conditioned_bias_climatology.parquet"


def _sql(variable: str, country: str) -> str:
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
        extra_filter=(
            "AND inserted_at <= {source_as_of:DateTime} "
            "AND prediction_timedelta = {lead:UInt32}"
        ),
    )
    bias = _bias_cte(variable)
    return f"""
WITH
obs AS (
  SELECT station, time, toFloat32({variable}) / 10.0 AS obs_value
  FROM production.synoptic_station_data FINAL
  WHERE station IN ({station_filter})
    AND time >= {{start:DateTime}}
    AND time <= {{end:DateTime}} + toIntervalMinute({{lead:UInt32}})
    AND {variable} != 65535
),
{source},
{bias},
joined AS (
  SELECT p.model AS model, p.station AS station_id,
         p.init_time, p.prediction_timedelta,
         p.raw_error, o.obs_value,
         b.bias_present, b.bias_value,
         t.station != '' AS threshold_present,
         t.q05, t.q25, t.q75, t.q95
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
debiased_common_points AS (
  SELECT station_id, init_time, prediction_timedelta
  FROM joined
  WHERE bias_present = 1 AND isFinite(bias_value)
  GROUP BY station_id, init_time, prediction_timedelta
  HAVING uniqExact(model) = {{n_models:UInt16}}
)
SELECT model, toBool(score.1) AS debias,
       multiIf(
         obs_value + score.2 < q05, 'lt_q5',
         obs_value + score.2 < q25, 'q5_q25',
         obs_value + score.2 < q75, 'q25_q75',
         obs_value + score.2 < q95, 'q75_q95',
         'gt_q95'
       ) AS forecast_bucket,
       avg(score.2) AS bias,
       avg(abs(score.2)) AS mae,
       count() AS sample_count
FROM joined
ARRAY JOIN [
  tuple(toUInt8(0), raw_error, toUInt8(1)),
  tuple(
    toUInt8(1),
    raw_error - bias_value,
    toUInt8(bias_present = 1 AND isFinite(bias_value))
  )
] AS score
WHERE score.3 = 1
  AND threshold_present
  AND (station_id, init_time, prediction_timedelta) IN (
    SELECT station_id, init_time, prediction_timedelta
    FROM debiased_common_points
  )
GROUP BY model, debias, forecast_bucket
ORDER BY model, debias, forecast_bucket
SETTINGS max_execution_time = 900,
         max_rows_to_read = 0,
         timeout_before_checking_execution_speed = 0
"""


def _cell(country: str, variable: str) -> pl.DataFrame:
    track = CONFIG["tracks"]["track_a"]
    params = {
        "models": TRACK_MODELS["track_a"],
        "n_models": len(TRACK_MODELS["track_a"]),
        "start": _parse_utc(track["start"]),
        "end": _parse_utc(track["end"]),
        "bias_start": _parse_utc(track["start"]) - timedelta(days=35),
        "max_lead": LEAD_MINUTES,
        "lead": LEAD_MINUTES,
        "init_hours": INIT_HOURS,
        "source_as_of": _parse_utc(CANONICAL_SOURCE_SNAPSHOT),
    }
    result = _client().query(
        _sql(variable, country),
        params,
        external_data=_external_thresholds(country, variable),
    )
    return pl.DataFrame(
        result.result_rows,
        schema=[
            "model",
            "debias",
            "forecast_bucket",
            "bias",
            "mae",
            "sample_count",
        ],
        orient="row",
    ).with_columns(
        pl.lit(country).alias("country"),
        pl.lit(variable).alias("variable"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    jobs = [(country, variable) for country in COUNTRIES for variable in SYNOPTIC_VARIABLES]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        frames = list(pool.map(lambda job: _cell(*job), jobs))
    country = pl.concat(frames)
    pooled = (
        country.group_by(["model", "variable", "debias", "forecast_bucket"])
        .agg(
            (pl.col("bias") * pl.col("sample_count")).sum()
            .truediv(pl.col("sample_count").sum())
            .alias("bias"),
            (pl.col("mae") * pl.col("sample_count")).sum()
            .truediv(pl.col("sample_count").sum())
            .alias("mae"),
            pl.col("sample_count").sum(),
        )
        .with_columns(pl.lit("pooled").alias("country"))
    )
    pl.concat([country, pooled], how="diagonal").write_parquet(OUT)
    print(f"wrote {OUT} ({country.height + pooled.height} rows)")
    print(f"finished in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
