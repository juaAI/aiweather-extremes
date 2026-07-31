"""Solar MAE skill for Track A / Track B headline bars + monthly series.

Track A: Sep 2025–Jun 2026, no ICON-EU.
Track B: Mar 2026–Jun 2026, includes ICON-EU.

Writes:
  data/derived/solar_headline_skill.parquet
  data/derived/solar_headline_skill_track_b.parquet
  data/derived/solar_monthly_skill_track_a.parquet
  data/derived/solar_monthly_skill_track_b.parquet

Run:  uv run python scripts/fig_solar_headline.py
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
DERIVED = REPO_ROOT / "data" / "derived"
REF = "ecmwf_ifs_single"
INIT_HOURS = [0, 6, 12, 18]
MIN_SAMPLES = 100
LEADS = list(range(60, 48 * 60 + 1, 60))
F3_BUCKETS = ["all", "q5_q25", "q25_q75", "q75_q95", "gt_q95"]

TRACKS = {
    "track_a": {
        "start": "2025-09-01T00:00:00Z",
        "end": "2026-07-01T00:00:00Z",
        "months": [
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
        ],
        "models": [
            "ept2_1_helios",
            "ept2_1_europa",
            "ept2_hrrr",
            "ept2_e",
            "ept2_reasoning",
            "ecmwf_ifs_single",
            "noaa_gfs_single",
            "icon_global",
        ],
        "out": DERIVED / "solar_headline_skill.parquet",
        "out_monthly": DERIVED / "solar_monthly_skill_track_a.parquet",
    },
    "track_b": {
        "start": "2026-03-01T00:00:00Z",
        "end": "2026-07-01T00:00:00Z",
        "months": [
            ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
            ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
            ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"),
            ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ],
        # Regional showdown + Helios; IFS is the skill reference.
        "models": [
            "ept2_1_helios",
            "ept2_1_europa",
            "ept2_hrrr",
            "icon_eu",
            "ecmwf_ifs_single",
        ],
        "out": DERIVED / "solar_headline_skill_track_b.parquet",
        "out_monthly": DERIVED / "solar_monthly_skill_track_b.parquet",
    },
}


def _fetch_cell(
    client: QEClient, models: list[str], country: str, start: str, end: str
) -> pl.DataFrame | None:
    try:
        data = client.metrics(
            models=models,
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
            "prediction_timedelta": data["prediction_timedelta"],
            "obs_bucket": data["obs_bucket"],
            "avg": data["avg"],
            "sample_count": data["sample_count"],
            "country": [country] * n,
            "period_start": [start] * n,
        }
    )


def fetch_full(client: QEClient, cfg: dict) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    print(f"Full window {cfg['start'][:10]} → {cfg['end'][:10]}")
    for c in COUNTRIES:
        df = _fetch_cell(client, cfg["models"], c, cfg["start"], cfg["end"])
        if df is None:
            print(f"  full SKIP {c}")
        else:
            print(f"  full OK {c} rows={df.height}")
            frames.append(df)
    return pl.concat(frames) if frames else pl.DataFrame()


def fetch_months(client: QEClient, cfg: dict) -> pl.DataFrame:
    jobs = [(c, a, b) for a, b in cfg["months"] for c in COUNTRIES]
    frames: list[pl.DataFrame] = []
    print(f"Months: {len(cfg['months'])} × {len(COUNTRIES)} countries")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, df in enumerate(
            pool.map(
                lambda j: _fetch_cell(client, cfg["models"], j[0], j[1], j[2]), jobs
            ),
            1,
        ):
            if df is not None:
                frames.append(df)
            if i % 12 == 0 or i == len(jobs):
                print(f"  months: {i}/{len(jobs)}", flush=True)
    return pl.concat(frames) if frames else pl.DataFrame()


def _matched(df: pl.DataFrame) -> pl.DataFrame:
    df = df.filter(
        (pl.col("prediction_timedelta").is_in(LEADS))
        & (pl.col("sample_count") >= MIN_SAMPLES)
    )
    ref = df.filter(pl.col("model") == REF).select(
        "country",
        "prediction_timedelta",
        "obs_bucket",
        "period_start",
        pl.col("avg").alias("ref_avg"),
        pl.col("sample_count").alias("ref_n"),
    )
    return df.filter(pl.col("model") != REF).join(
        ref,
        on=["country", "prediction_timedelta", "obs_bucket", "period_start"],
        how="inner",
    )


# Pool sample-weighted mean errors, not error sums: a model whose matched
# cells carry fewer samples than the reference must not score that deficit as
# skill. Matches jackknife_se below and aggregates._skill_from_cells.
_MODEL_POOL = (pl.col("avg") * pl.col("sample_count")).sum() / pl.col(
    "sample_count"
).sum()
_REF_POOL = (pl.col("ref_avg") * pl.col("ref_n")).sum() / pl.col("ref_n").sum()


def skill_point(matched: pl.DataFrame) -> pl.DataFrame:
    return matched.group_by(["model", "obs_bucket"]).agg(
        (100 * (1 - _MODEL_POOL / _REF_POOL)).alias("skill"),
        pl.col("sample_count").sum().alias("n"),
    )


def skill_by_month(matched: pl.DataFrame) -> pl.DataFrame:
    """Per-month pooled skill (countries × leads within each calendar month)."""
    return matched.group_by(["model", "obs_bucket", "period_start"]).agg(
        (100 * (1 - _MODEL_POOL / _REF_POOL)).alias("skill"),
        pl.col("sample_count").sum().alias("n"),
        pl.col("country").n_unique().alias("n_countries"),
    )


def jackknife_se(month_matched: pl.DataFrame) -> pl.DataFrame:
    per = month_matched.group_by(["model", "obs_bucket", "period_start"]).agg(
        (pl.col("avg") * pl.col("sample_count")).sum().alias("s_model"),
        pl.col("sample_count").sum().alias("n_model"),
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


def build_track(client: QEClient, name: str, cfg: dict) -> None:
    print(f"\n===== {name} =====")
    full = fetch_full(client, cfg)
    months = fetch_months(client, cfg)
    if full.is_empty():
        raise SystemExit(f"{name}: no full-window data")
    if months.is_empty():
        raise SystemExit(f"{name}: no monthly data")
    print(f"full countries: {sorted(full['country'].unique().to_list())}")
    matched_full = _matched(full)
    matched_months = _matched(months)
    sk = skill_point(matched_full)
    se = jackknife_se(matched_months)
    joined = sk.join(se, on=["model", "obs_bucket"], how="left").filter(
        pl.col("obs_bucket").is_in(F3_BUCKETS)
    )
    monthly = skill_by_month(matched_months).filter(
        pl.col("obs_bucket").is_in(F3_BUCKETS + ["lt_q5"])
    )
    joined = joined.sort("obs_bucket", "model")
    monthly = monthly.sort("period_start", "obs_bucket", "model")
    cfg["out"].parent.mkdir(parents=True, exist_ok=True)
    joined.write_parquet(cfg["out"])
    monthly.write_parquet(cfg["out_monthly"])
    print(f"wrote {cfg['out']}")
    print(f"wrote {cfg['out_monthly']}")
    # quick table
    order = sorted(
        joined.filter(pl.col("obs_bucket") == "all")["model"].to_list(),
        key=lambda m: -joined.filter(
            (pl.col("model") == m) & (pl.col("obs_bucket") == "all")
        )["skill"][0],
    )
    print(f"{'model':22} " + " ".join(f"{b:>9}" for b in F3_BUCKETS))
    for m in order:
        cells = []
        for b in F3_BUCKETS:
            r = joined.filter((pl.col("model") == m) & (pl.col("obs_bucket") == b))
            if r.height:
                s = r["skill_se"][0]
                cells.append(
                    f"{r['skill'][0]:+.1f}" + (f"±{s:.1f}" if s is not None else "")
                )
            else:
                cells.append("—")
        print(f"{DISPLAY.get(m, m):22} " + " ".join(f"{c:>9}" for c in cells))
    # monthly all-conditions snapshot
    print("\nmonthly skill (all conditions):")
    months_ord = sorted(monthly["period_start"].unique().to_list())
    print(f"{'model':22} " + " ".join(f"{p[:7]:>8}" for p in months_ord))
    for m in order:
        cells = []
        for p in months_ord:
            r = monthly.filter(
                (pl.col("model") == m)
                & (pl.col("obs_bucket") == "all")
                & (pl.col("period_start") == p)
            )
            cells.append(f"{r['skill'][0]:+.1f}" if r.height else "—")
        print(f"{DISPLAY.get(m, m):22} " + " ".join(f"{c:>8}" for c in cells))


def main() -> None:
    client = QEClient()
    for name, cfg in TRACKS.items():
        build_track(client, name, cfg)


if __name__ == "__main__":
    main()
