"""Phase 2 extraction: country-level bucketed benchmark metrics.

All data comes directly from ``POST /v1/station-benchmarks/metrics`` with
``geo={country_key}`` and ``obs_buckets=true``. Two query families per cell:

* ``mean``: rmse + mae + bias for ALL track models in one multi-model request,
  so the server-side init-date intersection guarantees every model is scored
  on the same forecast days. ``init_hours=[0,6,12,18]`` additionally pins all
  models to the same synoptic samples (regional models init far more often).
* ``crps``: mae + crps for the ensemble-output models only (CRPS needs the
  per-member distribution and is much heavier; deterministic CRPS==MAE adds
  nothing). MAE is re-requested so the CRPS/MAE ratio is internally
  consistent within this family's own date intersection.

Cells: track x country x variable x debias x period, where periods are the
track's calendar months (month-relative extremes + uncertainty replicates)
plus the full track window (period-absolute extremes). Cells run on a thread
pool (I/O-bound; ClickHouse does the work server-side). Responses are cached
content-addressed by the client, so the script is fully resumable; the
derived long-format parquet is rebuilt from all cell frames at the end.

Run:  python scripts/extract.py [--workers N]
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import polars as pl
import yaml

from qe_client import PROJECT_ROOT, QEClient, QEError

DERIVED_DIR = PROJECT_ROOT / "data" / "derived"
CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())

# Parallel in-flight requests. ClickHouse fans these out server-side; keep it
# well below the cluster's concurrency limits since this hits prod.
DEFAULT_WORKERS = 6

INIT_HOURS = [0, 6, 12, 18]
MEAN_METRICS = ["rmse", "mae", "bias"]
CRPS_METRICS = ["mae", "crps"]

RESPONSE_COLUMNS = [
    "model",
    "variable",
    "prediction_timedelta",
    "metric",
    "obs_bucket",
    "avg",
    "quantile_05",
    "quantile_25",
    "quantile_50",
    "quantile_75",
    "quantile_95",
    "sample_count",
]


def _iso(d: str) -> str:
    return d if "T" in d else f"{d}T00:00:00Z"


def _periods(track: dict) -> list[tuple[str, str, str]]:
    """(kind, start, end) periods for a track: its months, then full window."""
    t_start, t_end = track["start"], track["end"]
    periods: list[tuple[str, str, str]] = []
    for m_start, m_end in CONFIG["months"]:
        m_start, m_end = _iso(m_start), _iso(m_end)
        if m_end <= t_start or m_start >= t_end:
            continue
        periods.append(("month", max(m_start, t_start), min(m_end, t_end)))
    periods.append(("full", t_start, t_end))
    return periods


def _cells() -> list[dict]:
    cells: list[dict] = []
    model_attrs = CONFIG["models"]
    for track_name, track in CONFIG["tracks"].items():
        ensemble_models = [
            m for m in track["models"] if model_attrs[m]["output"] == "ensemble"
        ]
        for kind, start, end in _periods(track):
            for country in CONFIG["countries"]:
                for variable in CONFIG["variables"]:
                    for debias in CONFIG["debias"]:
                        base = {
                            "track": track_name,
                            "period_kind": kind,
                            "start": start,
                            "end": end,
                            "country": country,
                            "variable": variable,
                            "debias": debias,
                            "max_lead_minutes": track["max_lead_hours"] * 60,
                        }
                        cells.append(
                            {**base, "family": "mean", "models": track["models"]}
                        )
    # Months first (cheaper, and they already unlock the analysis); full-window
    # scans last.
    cells.sort(key=lambda c: (c["period_kind"] == "full", c["track"], c["country"]))
    return cells


def _fetch_cell(client: QEClient, cell: dict) -> dict | None:
    metrics = MEAN_METRICS if cell["family"] == "mean" else CRPS_METRICS
    try:
        return client.metrics(
            models=cell["models"],
            geo={"type": "country_key", "value": cell["country"]},
            start_time=cell["start"],
            end_time=cell["end"],
            variables=[cell["variable"]],
            metrics=metrics,
            max_lead_minutes=cell["max_lead_minutes"],
            debias=cell["debias"],
            obs_buckets=True,
            init_hours=INIT_HOURS,
        )
    except QEError as exc:
        print(f"  SKIP ({exc.status}): {exc}")
        return None
    except RuntimeError as exc:
        print(f"  FAIL after retries: {exc}")
        return None


def _cell_frame(cell: dict, data: dict) -> pl.DataFrame | None:
    if not data or not data.get("model"):
        return None
    n = len(data["model"])
    columns = {c: data.get(c, [None] * n) for c in RESPONSE_COLUMNS}
    df = pl.DataFrame(columns)
    return df.with_columns(
        pl.lit(cell["track"]).alias("track"),
        pl.lit(cell["period_kind"]).alias("period_kind"),
        pl.lit(cell["start"]).alias("period_start"),
        pl.lit(cell["end"]).alias("period_end"),
        pl.lit(cell["country"]).alias("country"),
        pl.lit(cell["debias"]).alias("debias"),
        pl.lit(cell["family"]).alias("family"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--track",
        action="append",
        choices=sorted(CONFIG["tracks"]),
        help="Restrict extraction to one or more tracks (repeatable). "
        "When set, merges into existing bucketed_metrics.parquet for other tracks.",
    )
    args = parser.parse_args()

    client = QEClient()
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    cells = _cells()
    if args.track:
        want = set(args.track)
        cells = [c for c in cells if c["track"] in want]
    print(f"{len(cells)} cells to extract on {args.workers} workers")

    started = time.monotonic()
    done_count = 0
    progress_lock = threading.Lock()

    def run_cell(indexed: tuple[int, dict]) -> pl.DataFrame | None:
        nonlocal done_count
        i, cell = indexed
        data = _fetch_cell(client, cell)
        frame = _cell_frame(cell, data) if data is not None else None
        with progress_lock:
            done_count += 1
            rate = done_count / (time.monotonic() - started)
            print(
                f"[{done_count}/{len(cells)}] {cell['track']} {cell['country']} "
                f"{cell['variable'].split('_at_')[0]} debias={cell['debias']} "
                f"{cell['family']} {cell['period_kind']} {cell['start'][:10]} "
                f"rows={frame.height if frame is not None else 0} "
                f"({rate:.2f} cells/s)",
                flush=True,
            )
        return frame

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_cell, enumerate(cells)))
    frames = [f for f in results if f is not None]

    if frames:
        result = pl.concat(frames)
        out = DERIVED_DIR / "bucketed_metrics.parquet"
        if args.track and out.exists():
            keep = pl.read_parquet(out).filter(~pl.col("track").is_in(args.track))
            result = pl.concat([keep, result])
            print(
                f"merged with existing parquet "
                f"(kept {keep.height} rows from other tracks)"
            )
        result.write_parquet(out)
        status = {
            "rows": result.height,
            "cells_total": len(cells),
            "cells_with_data": len(frames),
            "tracks": args.track or sorted(CONFIG["tracks"]),
            "elapsed_s": round(time.monotonic() - started, 1),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        (DERIVED_DIR / "extract_status.json").write_text(json.dumps(status, indent=2))
        print(f"\nwrote {out} ({result.height} rows from {len(frames)} new cells)")
    else:
        print("no data extracted")


if __name__ == "__main__":
    main()
