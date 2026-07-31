"""Build station-level ERA5 1991--2020 *wet-hour* precipitation thresholds.

Precipitation cannot reuse ``extract_climatology_thresholds.py``: the national
gauges of the precipitation panel are not in ``synoptic_station_interp_weights``
(that table only covers Jua's synoptic network), and precipitation is
zero-inflated so plain P5/P25/P75/P95 degenerate to zero at most stations.

This script instead:

  * interpolates ERA5 to each gauge with bilinear weights computed offline from
    the ERA5 grid coordinates (``precip_station_era5_weights.parquet``), passed
    to ClickHouse as an external table so no write access is needed; and
  * estimates percentiles over *wet* hours only (ERA5 >= 0.1 mm), matching the
    ``wet_clim`` regime definition. Dryness itself is a separate regime handled
    downstream, so the thresholds only need to cut the wet part of the
    distribution.

ERA5 ``precipitation_amount_sum_1h`` is stored as hundredths of a millimetre
(raw / 100 = mm; verified against Germany's ~800 mm/yr climatology), unlike the
tenths used for temperature and wind. The wet cutoff is therefore raw > 10.

Thresholds are estimated per station, calendar day and UTC hour from a cyclic
+/-15-day window over 1991--2020, identical in spirit to the temperature/wind
thresholds. Cells are cached per (country, month) so runs are resumable.

Reads ClickHouse credentials from CH_HOST, CH_PORT, CH_USER, CH_PASSWORD.

Run:
    uv run python scripts/extract_precip_thresholds.py [--workers N]
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
from clickhouse_connect.driver.external import ExternalData

from qe_client import PROJECT_ROOT

DERIVED_DIR = PROJECT_ROOT / "data" / "derived"
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "station_precip_thresholds"
WEIGHTS_PATH = DERIVED_DIR / "precip_station_era5_weights.parquet"
STATIONS_PATH = DERIVED_DIR / "precip_obs_stations.parquet"
OUT_PATH = DERIVED_DIR / "station_precip_thresholds_era5_1991_2020.parquet"

REFERENCE_YEAR = 2001  # Non-leap calendar for stable month/day alignment.
SMOOTHING_DAYS = 15
WET_RAW = 10  # 0.1 mm in ERA5 raw hundredths-of-mm units.
MM_SCALE = 100.0
DEFAULT_WORKERS = 6
# The +/-15-day window ARRAY JOIN expands rows ~31x before aggregation, so the
# per-query memory scales with station count. ~1350 stations (DE) fit ClickHouse's
# 137 GiB limit; 1774 (FR) does not. Chunk stations -- percentiles are strictly
# per-station, so chunking is exact -- to stay well under the ceiling.
STATION_CHUNK = 700

# Continental-Europe box: drops the 19 overseas/Arctic gauges (Canaries,
# Svalbard, Dutch Caribbean) that would distort a European climatology.
LAT_MIN, LAT_MAX = 34.0, 72.0
LON_MIN, LON_MAX = -11.0, 32.0

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
    last = calendar.monthrange(REFERENCE_YEAR, month)[1]
    end = date(REFERENCE_YEAR, month, last)
    return start.timetuple().tm_yday, end.timetuple().tm_yday


def _source_months(month: int) -> list[int]:
    start = date(REFERENCE_YEAR, month, 1) - timedelta(days=SMOOTHING_DAYS)
    last = calendar.monthrange(REFERENCE_YEAR, month)[1]
    end = date(REFERENCE_YEAR, month, last) + timedelta(days=SMOOTHING_DAYS)
    months: set[int] = set()
    current = start
    while current <= end:
        months.add(current.month)
        current += timedelta(days=1)
    return sorted(months)


def _load_station_countries() -> pl.DataFrame:
    stations = pl.read_parquet(STATIONS_PATH).filter(
        pl.col("lat").is_between(LAT_MIN, LAT_MAX)
        & pl.col("lon").is_between(LON_MIN, LON_MAX)
    )
    return stations.select("station_id", "country")


def _weights_for(country_stations: list[str]) -> pl.DataFrame:
    weights = pl.read_parquet(WEIGHTS_PATH)
    return weights.filter(pl.col("station").is_in(country_stations)).select(
        "station", "id1", "id2", "id3", "weight"
    )


def _external(weights: pl.DataFrame) -> ExternalData:
    return ExternalData(
        file_name="sw",
        fmt="CSV",
        data=weights.write_csv(include_header=False).encode(),
        structure=[
            "station String",
            "id1 UInt8",
            "id2 UInt16",
            "id3 UInt32",
            "weight Float64",
        ],
    )


def _sql(month: int) -> str:
    first_day, last_day = _month_days(month)
    months = ", ".join(str(m) for m in _source_months(month))
    return f"""
WITH sv AS (
  SELECT sw.station, a.time,
         toDayOfYear(a.time)
           - if(
               (
                 (toYear(a.time) % 4 = 0 AND toYear(a.time) % 100 != 0)
                 OR toYear(a.time) % 400 = 0
               ) AND toMonth(a.time) > 2,
               1, 0
             ) AS source_day,
         sumIf(toFloat64(a.precipitation_amount_sum_1h) * sw.weight,
               a.precipitation_amount_sum_1h != 65535)
           / sumIf(sw.weight, a.precipitation_amount_sum_1h != 65535) AS praw
  FROM production.arco_era5 AS a
  INNER JOIN sw
    ON sw.id1 = a.id_level_1 AND sw.id2 = a.id_level_2 AND sw.id3 = a.id_level_3
  WHERE (a.id_level_1, a.id_level_2, a.id_level_3) IN (SELECT id1, id2, id3 FROM sw)
    AND a.time >= '1991-01-01' AND a.time < '2021-01-01'
    AND toMonth(a.time) IN ({months})
    AND NOT (toMonth(a.time) = 2 AND toDayOfMonth(a.time) = 29)
  GROUP BY sw.station, a.time
)
SELECT station,
       target_day AS climatology_day,
       toHour(time) AS hour,
       quantilesTDigestIf(0.50, 0.75, 0.90, 0.95)(praw / {MM_SCALE}, praw > {WET_RAW})
         AS wet_qs,
       countIf(praw > {WET_RAW}) AS wet_count,
       count() AS total_count
FROM sv
ARRAY JOIN range({first_day}, {last_day + 1}) AS target_day
WHERE least(
        abs(toInt32(source_day) - toInt32(target_day)),
        365 - abs(toInt32(source_day) - toInt32(target_day))
      ) <= {SMOOTHING_DAYS}
GROUP BY station, climatology_day, hour
HAVING wet_count > 0
ORDER BY station, climatology_day, hour
LIMIT 5000000
SETTINGS max_execution_time = 300,
         max_rows_to_read = 0,
         max_result_rows = 5000000,
         timeout_before_checking_execution_speed = 0,
         join_algorithm = 'auto'
"""


def _expand(df: pl.DataFrame, country: str) -> pl.DataFrame:
    if df.is_empty():
        return pl.DataFrame(
            schema={
                "country": pl.String,
                "station": pl.String,
                "climatology_day": pl.UInt16,
                "hour": pl.UInt8,
                "q50": pl.Float64,
                "q75": pl.Float64,
                "q90": pl.Float64,
                "q95": pl.Float64,
                "wet_count": pl.UInt64,
                "total_count": pl.UInt64,
            }
        )
    return df.select(
        pl.lit(country).alias("country"),
        pl.col("station").cast(pl.String),
        pl.col("climatology_day").cast(pl.UInt16),
        pl.col("hour").cast(pl.UInt8),
        pl.col("wet_qs").list.get(0).cast(pl.Float64).alias("q50"),
        pl.col("wet_qs").list.get(1).cast(pl.Float64).alias("q75"),
        pl.col("wet_qs").list.get(2).cast(pl.Float64).alias("q90"),
        pl.col("wet_qs").list.get(3).cast(pl.Float64).alias("q95"),
        pl.col("wet_count").cast(pl.UInt64),
        pl.col("total_count").cast(pl.UInt64),
    )


def _cell_path(country: str, month: int) -> Path:
    return CACHE_DIR / f"{country}_{month:02d}.parquet"


def _run_cell(
    cell: tuple[str, int], station_index: dict[str, list[str]]
) -> tuple[tuple[str, int], int, float]:
    country, month = cell
    path = _cell_path(country, month)
    if path.exists():
        return cell, pl.read_parquet(path).height, 0.0
    stations = station_index[country]
    if not stations:
        expanded = _expand(pl.DataFrame(), country)
        path.parent.mkdir(parents=True, exist_ok=True)
        expanded.write_parquet(path)
        return cell, 0, 0.0
    started = time.monotonic()
    parts = []
    for offset in range(0, len(stations), STATION_CHUNK):
        chunk = stations[offset : offset + STATION_CHUNK]
        weights = _weights_for(chunk)
        result = _client().query(_sql(month), external_data=_external(weights))
        parts.append(
            pl.DataFrame(
                result.result_rows, schema=result.column_names, orient="row"
            )
        )
    df = pl.concat(parts) if parts else pl.DataFrame()
    expanded = _expand(df, country)
    path.parent.mkdir(parents=True, exist_ok=True)
    expanded.write_parquet(path)
    return cell, expanded.height, time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--country", action="append")
    parser.add_argument("--month", action="append", type=int, choices=range(1, 13))
    args = parser.parse_args()

    stations = _load_station_countries()
    station_index = {
        key[0]: grp["station_id"].to_list()
        for key, grp in stations.group_by(["country"])
    }
    countries = args.country or sorted(station_index)
    months = args.month or list(range(1, 13))
    cells = [(country, month) for country in countries for month in months]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"{len(cells)} precip-threshold cells "
        f"({len(countries)} countries x {len(months)} months) on {args.workers} workers"
    )

    completed = 0
    lock = threading.Lock()
    started = time.monotonic()

    def run(cell: tuple[str, int]):
        nonlocal completed
        result = _run_cell(cell, station_index)
        with lock:
            completed += 1
            (country, month), rows, elapsed = result
            print(
                f"[{completed}/{len(cells)}] {country} {month:02d} "
                f"rows={rows} query_s={elapsed:.1f}",
                flush=True,
            )
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, cells))

    paths = [_cell_path(country, month) for country, month in cells]
    scans = [pl.scan_parquet(p) for p in paths if p.exists()]
    pl.concat(scans).sink_parquet(OUT_PATH)
    total = pl.scan_parquet(OUT_PATH).select(pl.len().alias("n")).collect().item()
    print(f"wrote {OUT_PATH} ({total:,} rows, {time.monotonic() - started:.1f}s)")


if __name__ == "__main__":
    main()
