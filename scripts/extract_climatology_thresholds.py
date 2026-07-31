"""Build station-level ERA5 1991--2020 percentile thresholds.

ERA5 is first bilinearly interpolated to each verification station. P5/P25/
P75/P95 are then estimated independently for every station, calendar day, and
UTC hour from a cyclic +/-15-day calendar window over 1991--2020. Country
pooling is deferred until after observations have been assigned to local
regimes.

The script reads ClickHouse credentials from CH_HOST, CH_PORT, CH_USER, and
CH_PASSWORD. Cell results are cached, so interrupted runs are resumable.

Run:
    uv run python scripts/extract_climatology_thresholds.py [--workers N]
"""

from __future__ import annotations

import argparse
import calendar
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import clickhouse_connect
import polars as pl
import yaml

from qe_client import PROJECT_ROOT

CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())
COUNTRIES = [str(country) for country in CONFIG["countries"]]

DERIVED_DIR = PROJECT_ROOT / "data" / "derived"
CACHE_DIR = (
    PROJECT_ROOT / "data" / "cache" / "station_climatology_thresholds"
)
OUT_PATH = (
    DERIVED_DIR / "station_climatology_thresholds_era5_1991_2020.parquet"
)

ERA5_RESOLUTION = "720x1440_WNP"
REFERENCE_YEAR = 2001  # Non-leap calendar used for stable month/day alignment.
SMOOTHING_DAYS = 15
DEFAULT_WORKERS = 6

TEMP = "air_temperature_at_height_level_2m"
WIND = "wind_speed_at_height_level_10m"
SOLAR = "surface_downwelling_shortwave_flux_sum_1h"

_thread_local = threading.local()


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
    )
    _thread_local.clickhouse_client = client
    return client


def _month_days(month: int) -> tuple[int, int]:
    start = date(REFERENCE_YEAR, month, 1)
    end = date(
        REFERENCE_YEAR,
        month,
        calendar.monthrange(REFERENCE_YEAR, month)[1],
    )
    return start.timetuple().tm_yday, end.timetuple().tm_yday


def _source_months(month: int) -> list[int]:
    start = date(REFERENCE_YEAR, month, 1) - timedelta(days=SMOOTHING_DAYS)
    end = date(
        REFERENCE_YEAR,
        month,
        calendar.monthrange(REFERENCE_YEAR, month)[1],
    ) + timedelta(days=SMOOTHING_DAYS)
    months: set[int] = set()
    current = start
    while current <= end:
        months.add(current.month)
        current += timedelta(days=1)
    return sorted(months)


def _common_ctes(
    *,
    country: str,
    weights_table: str,
    mapping_sql: str,
    variables_sql: str,
    source_months: list[int],
) -> str:
    months = ", ".join(str(month) for month in source_months)
    return f"""
WITH station_weights AS (
  SELECT m.country_key, w.station,
         z.1 AS id1, z.2 AS id2, z.3 AS id3, z.4 AS weight
  FROM (
    SELECT station, neighbor_level_1_ids, neighbor_level_2_ids,
           neighbor_level_3_ids, neighbor_weights
    FROM production.{weights_table}
    WHERE resolution = '{ERA5_RESOLUTION}'
  ) AS w
  ANY INNER JOIN (
    {mapping_sql}
  ) AS m ON m.station = w.station
  ARRAY JOIN arrayZip(
    w.neighbor_level_1_ids, w.neighbor_level_2_ids,
    w.neighbor_level_3_ids, w.neighbor_weights
  ) AS z
),
station_values AS (
  SELECT sw.country_key, sw.station, a.time,
         toDayOfYear(a.time)
           - if(
               (
                 (toYear(a.time) % 4 = 0 AND toYear(a.time) % 100 != 0)
                 OR toYear(a.time) % 400 = 0
               )
               AND toMonth(a.time) > 2,
               1,
               0
             )
             AS source_day,
         {variables_sql}
  FROM production.arco_era5 AS a
  INNER JOIN station_weights AS sw
    ON sw.id1 = a.id_level_1
   AND sw.id2 = a.id_level_2
   AND sw.id3 = a.id_level_3
  WHERE (a.id_level_1, a.id_level_2, a.id_level_3) IN (
          SELECT (id1, id2, id3) FROM station_weights
        )
    AND a.time >= '1991-01-01'
    AND a.time < '2021-01-01'
    AND toMonth(a.time) IN ({months})
    AND NOT (toMonth(a.time) = 2 AND toDayOfMonth(a.time) = 29)
  GROUP BY sw.country_key, sw.station, a.time
)"""


def _synoptic_sql(country: str, month: int) -> str:
    first_day, last_day = _month_days(month)
    variables = f"""
         sumIf(toFloat64(a.{TEMP}) * sw.weight, a.{TEMP} != 65535)
           / sumIf(sw.weight, a.{TEMP} != 65535) / 10.0 AS t2m,
         sumIf(toFloat64(a.{WIND}) * sw.weight, a.{WIND} != 65535)
           / sumIf(sw.weight, a.{WIND} != 65535) / 10.0 AS ws10"""
    mapping = f"""
    SELECT station, country_key
    FROM production.synoptic_geo_mapping
    WHERE country_key = '{country}'
    LIMIT 10000"""
    ctes = _common_ctes(
        country=country,
        weights_table="synoptic_station_interp_weights",
        mapping_sql=mapping,
        variables_sql=variables,
        source_months=_source_months(month),
    )
    return f"""
{ctes}
SELECT country_key AS country, station,
       target_day AS climatology_day, toHour(time) AS hour,
       quantilesTDigest(0.05, 0.25, 0.75, 0.95)(t2m) AS t2m_qs,
       quantilesTDigest(0.05, 0.25, 0.75, 0.95)(ws10) AS ws10_qs,
       count() AS sample_count
FROM station_values
ARRAY JOIN range({first_day}, {last_day + 1}) AS target_day
WHERE least(
        abs(toInt32(source_day) - toInt32(target_day)),
        365 - abs(toInt32(source_day) - toInt32(target_day))
      ) <= {SMOOTHING_DAYS}
GROUP BY country, station, climatology_day, hour
ORDER BY country, station, climatology_day, hour
LIMIT 1000000
SETTINGS max_execution_time = 120,
         max_rows_to_read = 500000000,
         max_result_rows = 1000000,
         timeout_before_checking_execution_speed = 0,
         join_algorithm = 'auto'
"""


def _solar_sql(country: str, month: int) -> str:
    first_day, last_day = _month_days(month)
    variables = f"""
         sumIf(toFloat64(a.{SOLAR}) * sw.weight, a.{SOLAR} != 65535)
           / sumIf(sw.weight, a.{SOLAR} != 65535) * 1000.0 AS ssrd"""
    mapping = f"""
    SELECT concat('solar:', station_id) AS station, country AS country_key
    FROM production.solar_station_meta
    WHERE country = '{country}' AND is_clean = 1
    LIMIT 10000"""
    ctes = _common_ctes(
        country=country,
        weights_table="solar_station_interp_weights",
        mapping_sql=mapping,
        variables_sql=variables,
        source_months=_source_months(month),
    )
    return f"""
{ctes}
SELECT country_key AS country, station,
       target_day AS climatology_day, toHour(time) AS hour,
       quantilesTDigestIf(0.05, 0.25, 0.75, 0.95)(ssrd, ssrd > 0) AS ssrd_qs,
       countIf(ssrd > 0) AS sample_count
FROM station_values
ARRAY JOIN range({first_day}, {last_day + 1}) AS target_day
WHERE least(
        abs(toInt32(source_day) - toInt32(target_day)),
        365 - abs(toInt32(source_day) - toInt32(target_day))
      ) <= {SMOOTHING_DAYS}
GROUP BY country, station, climatology_day, hour
HAVING sample_count > 0
ORDER BY country, station, climatology_day, hour
LIMIT 1000000
SETTINGS max_execution_time = 120,
         max_rows_to_read = 500000000,
         max_result_rows = 1000000,
         timeout_before_checking_execution_speed = 0,
         join_algorithm = 'auto'
"""


def _expand_quantiles(df: pl.DataFrame, *, network: str) -> pl.DataFrame:
    if df.is_empty():
        return pl.DataFrame(
            schema={
                "country": pl.String,
                "station": pl.String,
                "climatology_day": pl.UInt16,
                "hour": pl.UInt8,
                "variable": pl.String,
                "q05": pl.Float64,
                "q25": pl.Float64,
                "q75": pl.Float64,
                "q95": pl.Float64,
                "sample_count": pl.UInt64,
            }
        )
    if network == "synoptic":
        return pl.concat(
            [
                df.select(
                    "country",
                    "station",
                    "climatology_day",
                    "hour",
                    pl.lit(variable).alias("variable"),
                    pl.col(qs).list.get(0).alias("q05"),
                    pl.col(qs).list.get(1).alias("q25"),
                    pl.col(qs).list.get(2).alias("q75"),
                    pl.col(qs).list.get(3).alias("q95"),
                    "sample_count",
                )
                for variable, qs in ((TEMP, "t2m_qs"), (WIND, "ws10_qs"))
            ]
        )
    return df.select(
        "country",
        "station",
        "climatology_day",
        "hour",
        pl.lit(SOLAR).alias("variable"),
        pl.col("ssrd_qs").list.get(0).alias("q05"),
        pl.col("ssrd_qs").list.get(1).alias("q25"),
        pl.col("ssrd_qs").list.get(2).alias("q75"),
        pl.col("ssrd_qs").list.get(3).alias("q95"),
        "sample_count",
    )


def _normalise_schema(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        pl.col("country").cast(pl.String),
        pl.col("station").cast(pl.String),
        pl.col("climatology_day").cast(pl.UInt16),
        pl.col("hour").cast(pl.UInt8),
        pl.col("variable").cast(pl.String),
        pl.col("q05").cast(pl.Float64),
        pl.col("q25").cast(pl.Float64),
        pl.col("q75").cast(pl.Float64),
        pl.col("q95").cast(pl.Float64),
        pl.col("sample_count").cast(pl.UInt64),
    )


def _cell_path(network: str, country: str, month: int) -> Path:
    cache_network = "solar_positive_only_v2" if network == "solar" else network
    return CACHE_DIR / f"{cache_network}_{country}_{month:02d}.parquet"


def _run_cell(cell: tuple[str, str, int]) -> tuple[tuple[str, str, int], int, float]:
    network, country, month = cell
    path = _cell_path(network, country, month)
    if path.exists():
        return cell, pl.read_parquet(path).height, 0.0
    sql = (
        _synoptic_sql(country, month)
        if network == "synoptic"
        else _solar_sql(country, month)
    )
    started = time.monotonic()
    result = _client().query(sql)
    df = pl.DataFrame(result.result_rows, schema=result.column_names, orient="row")
    expanded = _normalise_schema(_expand_quantiles(df, network=network))
    path.parent.mkdir(parents=True, exist_ok=True)
    expanded.write_parquet(path)
    return cell, expanded.height, time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--network",
        action="append",
        choices=("synoptic", "solar"),
        help="Restrict to one network; repeat to select both.",
    )
    parser.add_argument("--country", action="append", choices=COUNTRIES)
    parser.add_argument("--month", action="append", type=int, choices=range(1, 13))
    args = parser.parse_args()

    networks = args.network or ["synoptic", "solar"]
    countries = args.country or COUNTRIES
    months = args.month or list(range(1, 13))
    cells = [
        (network, country, month)
        for network in networks
        for country in countries
        for month in months
    ]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{len(cells)} climatology cells on {args.workers} workers")

    completed = 0
    lock = threading.Lock()
    started = time.monotonic()

    def run(cell: tuple[str, str, int]):
        nonlocal completed
        result = _run_cell(cell)
        with lock:
            completed += 1
            (network, country, month), rows, elapsed = result
            print(
                f"[{completed}/{len(cells)}] {network} {country} {month:02d} "
                f"rows={rows} query_s={elapsed:.1f}",
                flush=True,
            )
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, cells))

    expected = [
        _cell_path(network, country, month)
        for network in networks
        for country in countries
        for month in months
    ]
    scans = [pl.scan_parquet(path) for path in expected if path.exists()]
    pl.concat(scans).sink_parquet(OUT_PATH)
    row_count = (
        pl.scan_parquet(OUT_PATH).select(pl.len().alias("n")).collect().item()
    )
    print(
        f"wrote {OUT_PATH} ({row_count} rows, "
        f"{time.monotonic() - started:.1f}s)"
    )


if __name__ == "__main__":
    main()
