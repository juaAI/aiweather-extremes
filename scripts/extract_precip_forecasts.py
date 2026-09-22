"""Pull station-point precipitation forecasts from the query engine.

Precipitation has no path through ``synoptic_station_error_member`` (the error
table carries only t2m, ws10 and ssrd) and no observations in ClickHouse
(ENG-2258 leaves ``precipitation_amount_sum_1h`` entirely sentinel-valued), so
precipitation cannot reuse the extraction path of ``extract.py`` or
``extract_climatology_metrics.py``. This script fetches raw forecasts at the
station points of ``precip_obs_hourly.parquet`` instead; scoring against those
observations happens offline in ``score_precip.py``.

Ensemble members are averaged as they arrive and only the mean is written: at
full grid the member-level response is ~10^10 values, which is not worth
persisting for a mean-only comparison.

Output layout, one file per (track, model, init date) so runs are resumable:
    data/derived/precip_forecasts/<track>/<model>/<YYYY-MM-DD>.parquet
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DERIVED = PROJECT_ROOT / "data" / "derived"
OUT_ROOT = DERIVED / "precip_forecasts"
STATIONS_PATH = DERIVED / "precip_obs_stations.parquet"
COVERAGE_PATH = DERIVED / "precip_model_station_coverage.parquet"
CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())

VARIABLE = "precipitation_amount_sum_1h"
INIT_HOURS = [0, 6, 12, 18]

# Deterministic AIFS and Aurora do not expose precipitation. AIFS ENS does,
# but its accumulation follows the six-hour model step and is not an isolated
# hourly value, so it is excluded from this hourly gauge comparison.
NO_PRECIP = {"aifs", "aifs_ens", "aurora"}
ENSEMBLE_MODELS = {"ept2_1_europa", "ept2_hrrr", "ept2_e", "ecmwf_ens"}

BASE_URL = os.environ.get("JUA_API_BASE", "http://localhost:12880").rstrip("/")
API_KEY = os.environ.get("JUA_API_KEY", "localdevkey:localdevsecret")
TIMEOUT_S = 600.0

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


# Statuses worth retrying. Because stations are pre-filtered to each model's
# covered set, the out-of-domain 400 ("No data is available for requested
# region") no longer occurs, so a 400 seen here is the query engine shedding
# load under concurrency and is transient. 422 (model does not produce the
# variable) and auth/not-found stay fatal.
RETRYABLE_STATUS = {400, 408, 425, 429, 500, 502, 503, 504}


def post(payload: dict, max_retries: int = 6) -> dict:
    body = json.dumps(payload).encode()
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    last: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{BASE_URL}/v1/forecast/data", body, headers
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS:
                raise
            last = exc
        except Exception as exc:  # noqa: BLE001 - transport errors are retried
            last = exc
        # Capped exponential backoff so a transient QE overload has time to
        # recover instead of being hammered by every worker at once.
        time.sleep(min(2.0 * (2**attempt), 30.0))
    raise RuntimeError(f"request failed after {max_retries} retries: {last}")


def fetch_chunk(
    model: str, init: datetime, stations: pl.DataFrame, max_lead: int
) -> pl.DataFrame:
    """One request: all leads for one model, init and station chunk.

    Returns a frame of station_id / lead / forecast_mm. Ensemble members are
    collapsed to their mean here so callers never see member-level data.
    """
    payload = {
        "models": [model],
        "geo": {
            "type": "point",
            "value": [[r["lat"], r["lon"]] for r in stations.iter_rows(named=True)],
            "method": "nearest",
        },
        "init_time": init.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prediction_timedelta": {"start": 1, "end": max_lead},
        "timedelta_unit": "h",
        "variables": [VARIABLE],
    }
    if model in ENSEMBLE_MODELS:
        payload["include_ensemble_members"] = True

    data = post(payload)
    values = data.get(VARIABLE) or []
    if not values:
        return pl.DataFrame(
            schema={"station_id": pl.String, "lead": pl.Int32, "forecast_mm": pl.Float64}
        )

    frame = pl.DataFrame(
        {
            "point": data["point"],
            "lead": data["prediction_timedelta"],
            "forecast_mm": values,
        }
    ).with_columns(
        pl.col("point").cast(pl.Int32),
        pl.col("lead").cast(pl.Int32),
        pl.col("forecast_mm").cast(pl.Float64),
    )
    # Ensemble mean over members; a no-op grouping for deterministic models.
    frame = (
        frame.group_by("point", "lead")
        .agg(pl.col("forecast_mm").mean())
        .sort("point", "lead")
    )
    ids = stations.select("station_id").with_row_index("point").with_columns(
        pl.col("point").cast(pl.Int32)
    )
    return frame.join(ids, on="point", how="inner").select(
        "station_id", "lead", "forecast_mm"
    )


def fetch_init(
    model: str,
    init: datetime,
    stations: pl.DataFrame,
    max_lead: int,
    chunk_size: int,
    out_path: Path,
) -> tuple[str, int]:
    parts: list[pl.DataFrame] = []
    for start in range(0, stations.height, chunk_size):
        chunk = stations.slice(start, chunk_size)
        parts.append(fetch_chunk(model, init, chunk, max_lead))
    frame = pl.concat(parts) if parts else pl.DataFrame()
    if frame.is_empty():
        return (out_path.name, 0)
    frame = frame.with_columns(
        pl.lit(model).alias("model"),
        pl.lit(init.replace(tzinfo=None)).cast(pl.Datetime("us")).alias("init_time"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
    frame.write_parquet(tmp)
    tmp.rename(out_path)
    return (out_path.name, frame.height)


def track_models(track: str) -> list[str]:
    return [m for m in CONFIG["tracks"][track]["models"] if m not in NO_PRECIP]


def init_times(track: str, init_hours: list[int]) -> list[datetime]:
    spec = CONFIG["tracks"][track]
    start = datetime.fromisoformat(spec["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(spec["end"].replace("Z", "+00:00"))
    out: list[datetime] = []
    day = start
    while day < end:
        for hour in init_hours:
            stamp = day.replace(hour=hour)
            if start <= stamp < end:
                out.append(stamp)
        day += timedelta(days=1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", default="track_a", choices=sorted(CONFIG["tracks"]))
    parser.add_argument("--model", action="append", help="restrict to these models")
    parser.add_argument(
        "--max-lead",
        type=int,
        default=48,
        help="max lead hours; 48 covers the headline h1_48 scope",
    )
    parser.add_argument(
        "--init-hours",
        default="0,12",
        help="comma-separated init hours (full convention is 0,6,12,18)",
    )
    # The data endpoint rejects requests above ~1030 points; 1000 keeps a
    # margin and is ~3x faster per station than smaller chunks.
    parser.add_argument("--chunk-size", type=int, default=1000)
    # Each worker holds one request in flight; 32 saturates the query
    # engine (17.7 req/s measured), 48 regresses.
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--limit-stations", type=int, default=0)
    parser.add_argument("--limit-inits", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stations = pl.read_parquet(STATIONS_PATH).select("station_id", "lat", "lon").sort(
        "station_id"
    )
    # The regional models (europa, hrrr, icon_eu) reject the entire request if
    # any point falls outside their footprint, so restrict every model to the
    # stations all of them cover. That also keeps the comparison like-for-like,
    # mirroring the common-date matching used for the other variables.
    if COVERAGE_PATH.exists():
        coverage = pl.read_parquet(COVERAGE_PATH)
        n_models = coverage["model"].n_unique()
        common = (
            coverage.filter(pl.col("covered"))
            .group_by("station_id")
            .len()
            .filter(pl.col("len") == n_models)
            .select("station_id")
        )
        before = stations.height
        stations = stations.join(common, on="station_id", how="inner").sort("station_id")
        log(
            f"station set: {stations.height:,} of {before:,} covered by all "
            f"{n_models} models"
        )
    if args.limit_stations:
        stations = stations.head(args.limit_stations)

    models = args.model or track_models(args.track)
    hours = [int(h) for h in args.init_hours.split(",") if h != ""]
    inits = init_times(args.track, hours)
    if args.limit_inits:
        inits = inits[: args.limit_inits]

    jobs: list[tuple[str, datetime, Path]] = []
    for model in models:
        for init in inits:
            out = (
                OUT_ROOT
                / args.track
                / model
                / f"{init.strftime('%Y-%m-%dT%H')}.parquet"
            )
            if not out.exists():
                jobs.append((model, init, out))

    chunks_per_init = -(-stations.height // args.chunk_size)
    log(
        f"track={args.track} models={len(models)} inits={len(inits)} "
        f"stations={stations.height} leads=1..{args.max_lead}h"
    )
    log(
        f"pending jobs={len(jobs)} ({len(jobs) * chunks_per_init:,} requests) "
        f"workers={args.workers}"
    )
    if args.dry_run or not jobs:
        return

    done = 0
    rows = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                fetch_init,
                model,
                init,
                stations,
                args.max_lead,
                args.chunk_size,
                out,
            ): (model, init)
            for model, init, out in jobs
        }
        for future in as_completed(futures):
            model, init = futures[future]
            try:
                _, n = future.result()
            except Exception as exc:  # noqa: BLE001 - report and continue
                log(f"  FAIL {model} {init:%Y-%m-%dT%H} {type(exc).__name__}: {exc}")
                continue
            done += 1
            rows += n
            if done % 25 == 0 or done == len(jobs):
                rate = done / max(time.time() - started, 1e-9)
                eta = (len(jobs) - done) / rate / 3600 if rate else float("nan")
                log(
                    f"  {done}/{len(jobs)} inits  {rows:,} rows  "
                    f"{rate * 3600:,.0f} inits/h  eta {eta:.1f} h"
                )
    log(f"done: {done}/{len(jobs)} inits, {rows:,} rows in {(time.time()-started)/60:.1f} min")


if __name__ == "__main__":
    sys.exit(main())
