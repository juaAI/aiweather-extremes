"""Track A solar MAE skill vs lead (for fig2-style solar panel).

Writes data/derived/solar_lead_skill_track_a.parquet
  columns: model, obs_bucket, lead_h, skill, skill_se, n, n_months

Leads: 1, 6, 12, 24, 48 h. Also stores pooled h1_12 and h1_48 rows
(lead_h = -12 / -48) for the right-hand pooled markers.

Run:  uv run python scripts/fig_solar_leads.py
"""

from __future__ import annotations

import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qe_client import QEClient, QEError
from style import COUNTRIES, DISPLAY, SOLAR

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "data" / "derived" / "solar_lead_skill_track_a.parquet"

START, END = "2025-09-01T00:00:00Z", "2026-07-01T00:00:00Z"
MONTHS = [
    ("2025-09-01T00:00:00Z", "2025-10-01T00:00:00Z"),
    ("2025-10-01T00:00:00Z", "2025-11-01T00:00:00Z"),
    ("2025-11-01T00:00:00Z", "2025-12-01T00:00:00Z"),
    ("2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"),
    ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
    ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
    ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"),
    ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"),
]
MODELS = [
    "ept2_1_helios",
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_e",
    "ept2_reasoning",
    "ecmwf_ifs_single",
    "noaa_gfs_single",
    "icon_global",
]
REF = "ecmwf_ifs_single"
INIT_HOURS = [0, 6, 12, 18]
MIN_SAMPLES = 100
BUCKETS = ["all", "gt_q95", "q25_q75"]
SINGLE_LEADS_H = [1, 6, 12, 24, 48]
POOLS = {
    -12: list(range(60, 12 * 60 + 1, 60)),
    -48: list(range(60, 48 * 60 + 1, 60)),
}


def _fetch(client: QEClient, country: str, start: str, end: str) -> pl.DataFrame | None:
    try:
        data = client.metrics(
            models=MODELS,
            geo={"type": "country_key", "value": country},
            start_time=start,
            end_time=end,
            variables=[SOLAR],
            metrics=["mae"],
            max_lead_minutes=48 * 60,
            debias=True,
            obs_buckets=True,
            init_hours=INIT_HOURS,
        )
    except QEError as exc:
        print(f"  SKIP {country} {start[:10]}: {exc}")
        return None
    if not data or not data.get("model"):
        return None
    n = len(data["model"])
    return pl.DataFrame(
        {
            "model": data["model"],
            "lead": data["prediction_timedelta"],
            "obs_bucket": data["obs_bucket"],
            "avg": data["avg"],
            "n": data["sample_count"],
            "country": [country] * n,
            "period_start": [start] * n,
        }
    )


def _matched(df: pl.DataFrame, leads: list[int]) -> pl.DataFrame:
    df = df.filter(
        (pl.col("lead").is_in(leads))
        & (pl.col("n") >= MIN_SAMPLES)
        & (pl.col("obs_bucket").is_in(BUCKETS))
    )
    ref = df.filter(pl.col("model") == REF).select(
        "country",
        "lead",
        "obs_bucket",
        "period_start",
        pl.col("avg").alias("ref_avg"),
        pl.col("n").alias("ref_n"),
    )
    return df.filter(pl.col("model") != REF).join(
        ref, on=["country", "lead", "obs_bucket", "period_start"], how="inner"
    )


def skill_point(matched: pl.DataFrame) -> pl.DataFrame:
    # Pool sample-weighted mean errors, not error sums: a model whose matched
    # cells carry fewer samples than the reference must not score that deficit
    # as skill. Matches jackknife_se below and aggregates._skill_from_cells.
    model_pool = (pl.col("avg") * pl.col("n")).sum() / pl.col("n").sum()
    ref_pool = (pl.col("ref_avg") * pl.col("ref_n")).sum() / pl.col("ref_n").sum()
    return matched.group_by(["model", "obs_bucket"]).agg(
        (100 * (1 - model_pool / ref_pool)).alias("skill"),
        pl.col("n").sum().alias("n"),
    )


def jackknife_se(month_matched: pl.DataFrame) -> pl.DataFrame:
    per = month_matched.group_by(["model", "obs_bucket", "period_start"]).agg(
        (pl.col("avg") * pl.col("n")).sum().alias("s_model"),
        pl.col("n").sum().alias("n_model"),
        (pl.col("ref_avg") * pl.col("ref_n")).sum().alias("s_ref"),
        pl.col("ref_n").sum().alias("n_ref"),
    )
    rows = []
    for (model, bucket), g in per.group_by(["model", "obs_bucket"]):
        months = g.to_dicts()
        m = len(months)
        if m < 2:
            rows.append(
                {"model": model, "obs_bucket": bucket, "skill_se": None, "n_months": m}
            )
            continue
        loo = []
        for i in range(m):
            rest = [months[j] for j in range(m) if j != i]
            sm = sum(r["s_model"] for r in rest)
            nm = sum(r["n_model"] for r in rest)
            sr = sum(r["s_ref"] for r in rest)
            nr = sum(r["n_ref"] for r in rest)
            if nm <= 0 or nr <= 0 or sr == 0:
                continue
            loo.append(100 * (1 - (sm / nm) / (sr / nr)))
        if len(loo) < 2:
            se = None
        else:
            mean = sum(loo) / len(loo)
            var = sum((x - mean) ** 2 for x in loo) * (m - 1) / m
            se = math.sqrt(var)
        rows.append(
            {"model": model, "obs_bucket": bucket, "skill_se": se, "n_months": m}
        )
    return pl.DataFrame(rows)


def score(full: pl.DataFrame, months: pl.DataFrame, leads: list[int], lead_h: int) -> pl.DataFrame:
    sk = skill_point(_matched(full, leads))
    se = jackknife_se(_matched(months, leads))
    return (
        sk.join(se, on=["model", "obs_bucket"], how="left")
        .with_columns(pl.lit(lead_h).alias("lead_h"))
        .select("model", "obs_bucket", "lead_h", "skill", "skill_se", "n", "n_months")
    )


def main() -> None:
    client = QEClient()
    full_frames, month_frames = [], []
    print(f"full {START[:10]}→{END[:10]}")
    for c in COUNTRIES:
        df = _fetch(client, c, START, END)
        if df is None:
            print(f"  SKIP {c}")
        else:
            print(f"  OK {c}")
            full_frames.append(df)
    jobs = [(c, a, b) for a, b in MONTHS for c in COUNTRIES]
    print(f"months: {len(jobs)}")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, df in enumerate(
            pool.map(lambda j: _fetch(client, j[0], j[1], j[2]), jobs), 1
        ):
            if df is not None:
                month_frames.append(df)
            if i % 24 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}", flush=True)
    full = pl.concat(full_frames)
    months = pl.concat(month_frames)

    pieces = []
    for h in SINGLE_LEADS_H:
        pieces.append(score(full, months, [h * 60], h))
    for lead_h, leads in POOLS.items():
        pieces.append(score(full, months, leads, lead_h))

    out = pl.concat(pieces).sort("obs_bucket", "lead_h", "model")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(OUT)
    print(f"wrote {OUT}")

    for bucket in ("all", "gt_q95"):
        print(f"\n=== {bucket} ===")
        sub = out.filter(
            (pl.col("obs_bucket") == bucket) & (pl.col("lead_h").is_in(SINGLE_LEADS_H))
        )
        models = sorted(
            sub.filter(pl.col("lead_h") == 6)["model"].to_list(),
            key=lambda m: -sub.filter((pl.col("model") == m) & (pl.col("lead_h") == 6))[
                "skill"
            ][0],
        )
        print(f"{'model':22}" + "".join(f"{h:>8}" for h in SINGLE_LEADS_H))
        for m in models:
            cells = []
            for h in SINGLE_LEADS_H:
                r = sub.filter((pl.col("model") == m) & (pl.col("lead_h") == h))
                cells.append(f"{r['skill'][0]:+.1f}" if r.height else "—")
            print(f"{DISPLAY.get(m, m):22}" + "".join(f"{c:>8}" for c in cells))


if __name__ == "__main__":
    main()
