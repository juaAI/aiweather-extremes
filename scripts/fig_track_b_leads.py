"""Track B MAE skill vs lead (Mar–Jun 2026) for fig8.

Writes data/derived/track_b_lead_skill.parquet
  columns: model, lead_h, obs_bucket, skill, skill_se, variable

Wind/temp leads: 6, 12, 24, 48 h.
Solar leads: 1, 6, 12, 24, 48 h (hourly markers, same as Track A solar).

Run:  uv run python scripts/fig_track_b_leads.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qe_client import QEClient, QEError
from style import COUNTRIES, SOLAR, TEMP, WIND

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "data" / "derived" / "track_b_lead_skill.parquet"

REF = "ecmwf_ifs_single"
INIT = [0, 6, 12, 18]
MIN_N = 100
START, END = "2026-03-01T00:00:00Z", "2026-07-01T00:00:00Z"
BUCKETS = ["all", "gt_q95", "q25_q75"]

WT_LEADS = [6, 12, 24, 48]
SOLAR_LEADS = [1, 6, 12, 24, 48]
WT_MODELS = ["ept2_1_europa", "ept2_hrrr", "icon_eu", REF]
SOLAR_MODELS = ["ept2_1_helios", "ept2_1_europa", "ept2_hrrr", "icon_eu", REF]


def _fetch(
    client: QEClient,
    country: str,
    variable: str,
    models: list[str],
) -> pl.DataFrame | None:
    try:
        d = client.metrics(
            models=models,
            geo={"type": "country_key", "value": country},
            start_time=START,
            end_time=END,
            variables=[variable],
            metrics=["mae"],
            max_lead_minutes=48 * 60,
            debias=True,
            obs_buckets=True,
            init_hours=INIT,
        )
    except QEError as exc:
        print(f"  SKIP {country} {variable}: {exc}")
        return None
    if not d or not d.get("model"):
        return None
    n = len(d["model"])
    return pl.DataFrame(
        {
            "model": d["model"],
            "lead": d["prediction_timedelta"],
            "obs_bucket": d["obs_bucket"],
            "avg": d["avg"],
            "n": d["sample_count"],
            "country": [country] * n,
            "variable": [variable] * n,
        }
    )


def _score(df: pl.DataFrame, leads: list[int], variable: str) -> pl.DataFrame:
    rows: list[dict] = []
    for h in leads:
        for bucket in BUCKETS:
            sub = df.filter(
                (pl.col("lead") == h * 60)
                & (pl.col("obs_bucket") == bucket)
                & (pl.col("n") >= MIN_N)
            )
            ref = sub.filter(pl.col("model") == REF).select(
                "country", pl.col("avg").alias("ra"), pl.col("n").alias("rn")
            )
            matched = sub.filter(pl.col("model") != REF).join(ref, on="country")
            if matched.height == 0:
                continue
            # Pool sample-weighted mean errors, not error sums, so a model with
            # fewer matched samples than the reference does not score that
            # deficit as skill.
            model_pool = (pl.col("avg") * pl.col("n")).sum() / pl.col("n").sum()
            ref_pool = (pl.col("ra") * pl.col("rn")).sum() / pl.col("rn").sum()
            sk = matched.group_by("model").agg(
                (100 * (1 - model_pool / ref_pool)).alias("skill")
            )
            for r in sk.iter_rows(named=True):
                rows.append(
                    {
                        "model": r["model"],
                        "lead_h": h,
                        "obs_bucket": bucket,
                        "skill": r["skill"],
                        "skill_se": None,
                        "variable": variable,
                    }
                )
    return pl.DataFrame(rows)


def main() -> None:
    client = QEClient()
    pieces: list[pl.DataFrame] = []

    for variable, models, leads in (
        (WIND, WT_MODELS, WT_LEADS),
        (TEMP, WT_MODELS, WT_LEADS),
        (SOLAR, SOLAR_MODELS, SOLAR_LEADS),
    ):
        print(f"{variable} leads={leads}")
        frames: list[pl.DataFrame] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for df in pool.map(
                lambda c: _fetch(client, c, variable, models), COUNTRIES
            ):
                if df is not None:
                    frames.append(df)
        if not frames:
            print(f"  no data for {variable}")
            continue
        raw = pl.concat(frames)
        print("  countries", sorted(raw["country"].unique().to_list()))
        pieces.append(_score(raw, leads, variable))

    out = pl.concat(pieces).sort("variable", "obs_bucket", "lead_h", "model")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(OUT)
    print(f"wrote {OUT} rows={out.height}")


if __name__ == "__main__":
    main()
