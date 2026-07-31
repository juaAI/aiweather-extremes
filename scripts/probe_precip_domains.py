"""Determine which stations each model actually covers.

``/v1/forecast/meta`` reports the global storage grid for every model, including
the regional ones, so it cannot be used to tell whether a station is inside a
model's real footprint. The data endpoint instead rejects the *entire* request
with HTTP 400 when any single requested point is outside the model's domain,
which makes coverage discoverable by bisection: request a batch, and on failure
split it and recurse. Cost is O(k log n) in the number of uncovered stations,
so fully covered models resolve in a single request.

Writes data/derived/precip_model_station_coverage.parquet with one row per
(model, station_id, covered).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import polars as pl
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DERIVED = PROJECT_ROOT / "data" / "derived"
STATIONS_PATH = DERIVED / "precip_obs_stations.parquet"
OUT_PATH = DERIVED / "precip_model_station_coverage.parquet"
CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_precip_forecasts import (  # noqa: E402
    API_KEY,
    BASE_URL,
    ENSEMBLE_MODELS,
    NO_PRECIP,
    VARIABLE,
)


def covered(model: str, rows: list[dict], probe_init: str, max_lead: int = 6) -> bool:
    """True if the model returns data for every point in ``rows``.

    The lead window must span at least one step of the coarsest model:
    ecmwf_ens is 3-hourly, so a lead-1-only probe comes back empty for it and
    would be misread as "not covered".
    """
    payload = {
        "models": [model],
        "geo": {
            "type": "point",
            "value": [[r["lat"], r["lon"]] for r in rows],
            "method": "nearest",
        },
        "init_time": probe_init,
        "prediction_timedelta": {"start": 1, "end": max_lead},
        "timedelta_unit": "h",
        "variables": [VARIABLE],
    }
    if model in ENSEMBLE_MODELS:
        payload["include_ensemble_members"] = True
    req = urllib.request.Request(
        f"{BASE_URL}/v1/forecast/data",
        json.dumps(payload).encode(),
        {"X-API-Key": API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        return bool(data.get(VARIABLE))
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            return False
        raise


def resolve(model: str, rows: list[dict], probe_init: str, stats: dict) -> set[str]:
    """Bisect ``rows`` into the subset the model covers."""
    if not rows:
        return set()
    stats["requests"] += 1
    if covered(model, rows, probe_init):
        return {r["station_id"] for r in rows}
    if len(rows) == 1:
        return set()
    mid = len(rows) // 2
    return resolve(model, rows[:mid], probe_init, stats) | resolve(
        model, rows[mid:], probe_init, stats
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-init", default="2026-06-01T00:00:00Z")
    parser.add_argument("--batch", type=int, default=400)
    parser.add_argument("--model", action="append", help="restrict to these models")
    args = parser.parse_args()

    stations = (
        pl.read_parquet(STATIONS_PATH)
        .select("station_id", "country", "lat", "lon")
        .sort("station_id")
    )
    rows = stations.to_dicts()

    all_models = sorted(
        {
            m
            for track in CONFIG["tracks"].values()
            for m in track["models"]
            if m not in NO_PRECIP
        }
    )
    models = args.model or all_models

    # Re-probing a subset keeps previously resolved models from the last run.
    frames = []
    if args.model and OUT_PATH.exists():
        frames.append(
            pl.read_parquet(OUT_PATH).filter(~pl.col("model").is_in(models))
        )
    print(f"probing {len(models)} models over {len(rows)} stations\n")
    print(f"{'model':20}{'covered':>9}{'missing':>9}{'requests':>10}  countries dropped")
    for model in models:
        stats = {"requests": 0}
        keep: set[str] = set()
        for start in range(0, len(rows), args.batch):
            keep |= resolve(model, rows[start : start + args.batch], args.probe_init, stats)
        frame = stations.select("station_id", "country").with_columns(
            pl.lit(model).alias("model"),
            pl.col("station_id").is_in(list(keep)).alias("covered"),
        )
        frames.append(frame)
        miss = frame.filter(~pl.col("covered"))
        dropped = (
            miss.group_by("country")
            .len()
            .sort("len", descending=True)
            .select(pl.format("{}:{}", "country", "len"))
            .to_series()
            .to_list()
        )
        print(
            f"{model:20}{len(keep):>9,}{miss.height:>9,}{stats['requests']:>10}  "
            f"{', '.join(dropped) if dropped else '-'}"
        )

    out = pl.concat(frames)
    out.write_parquet(OUT_PATH)
    print(f"\nwrote {OUT_PATH} ({out.height:,} rows)")

    # Common station set: the like-for-like basis for cross-model comparison.
    n_models = out["model"].n_unique()
    per_model = out.filter(pl.col("covered")).group_by("station_id").len()
    common = per_model.filter(pl.col("len") == n_models)
    print(f"stations covered by all {n_models} models: {common.height:,}")


if __name__ == "__main__":
    sys.exit(main())
