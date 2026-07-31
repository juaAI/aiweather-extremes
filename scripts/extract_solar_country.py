"""Track C: per-country solar extraction (surface downwelling shortwave,
1h accumulation). Replaces the retired Europe-bbox pooled design of
``extract_solar.py`` with one cell per country, matching the layout of
``bucketed_metrics.parquet`` so the aggregation module can treat all three
tracks uniformly.

12 countries x 5 periods (full window + 4 monthly sub-periods) x 2 debias
= 120 requests. The QE client caches content-addressed and is thread-safe,
so the script is resumable and re-runs are free.

Solar observed-value buckets can be empty in dark/short windows; empty
frames are skipped and logged.

Run:  python scripts/extract_solar_country.py
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from extract import _cell_frame
from qe_client import PROJECT_ROOT, QEClient, QEError
from style import COUNTRIES

DERIVED_DIR = PROJECT_ROOT / "data" / "derived"

SOLAR_VAR = "surface_downwelling_shortwave_flux_sum_1h"
MODELS = [
    "ept2_1_helios",
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_e",
    "ept2_reasoning",
    "ecmwf_ifs_single",
    "noaa_gfs_single",
    "icon_eu",
    "icon_global",
]
# Helios benchmark coverage starts 2026-03-19; horizon 48 h.
PERIODS = [
    ("full", "2026-03-20T00:00:00Z", "2026-06-15T00:00:00Z"),
    ("month", "2026-03-20T00:00:00Z", "2026-04-01T00:00:00Z"),
    ("month", "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
    ("month", "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"),
    ("month", "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z"),
]
MAX_LEAD_MINUTES = 48 * 60
WORKERS = 6


def _cells() -> list[dict]:
    cells = []
    for country in COUNTRIES:
        for kind, start, end in PERIODS:
            for debias in (True, False):
                cells.append(
                    {
                        "track": "track_c",
                        "period_kind": kind,
                        "start": start,
                        "end": end,
                        "country": country,
                        "variable": SOLAR_VAR,
                        "debias": debias,
                        "family": "mean",
                    }
                )
    return cells


def main() -> None:
    client = QEClient()
    cells = _cells()
    print(f"{len(cells)} solar country cells on {WORKERS} workers")

    started = time.monotonic()
    done = 0
    lock = threading.Lock()

    def run_cell(cell: dict) -> pl.DataFrame | None:
        nonlocal done
        frame = None
        note = ""
        try:
            data = client.metrics(
                models=MODELS,
                geo={"type": "country_key", "value": cell["country"]},
                start_time=cell["start"],
                end_time=cell["end"],
                variables=[SOLAR_VAR],
                metrics=["rmse", "mae", "bias"],
                max_lead_minutes=MAX_LEAD_MINUTES,
                debias=cell["debias"],
                obs_buckets=True,
                init_hours=[0, 6, 12, 18],
            )
            frame = _cell_frame(cell, data)
            if frame is None:
                note = "EMPTY (no rows; dark/short window?)"
        except (QEError, RuntimeError) as exc:
            note = f"FAIL: {exc}"
        with lock:
            done += 1
            rate = done / (time.monotonic() - started)
            print(
                f"[{done}/{len(cells)}] {cell['country']} {cell['period_kind']} "
                f"{cell['start'][:10]} debias={cell['debias']} "
                f"rows={frame.height if frame is not None else 0} "
                f"({rate:.2f} cells/s) {note}",
                flush=True,
            )
        return frame

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(run_cell, cells))
    frames = [f for f in results if f is not None]

    if not frames:
        print("no data extracted")
        return
    result = pl.concat(frames)
    out = DERIVED_DIR / "solar_metrics_country.parquet"
    result.write_parquet(out)
    print(f"wrote {out} ({result.height} rows from {len(frames)}/{len(cells)} cells)")


if __name__ == "__main__":
    main()
