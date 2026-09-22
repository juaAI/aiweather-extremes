"""Headline skill at matched lead pools for Track A and Track B.

Track A wind/temp: 6–48 h 6-hourly (all models; AIFS/AIFS ENS/Aurora cadence).
Track A solar: 1–48 h hourly (no AIFS/AIFS ENS/Aurora/ENS).
Track A companion: 1–12 h hourly for models with hourly output.
Track B: 1–48 h hourly and 1–12 h hourly (all models hourly; +ICON-EU).

Writes:
  data/derived/headline_skill_track_a.parquet
  data/derived/headline_skill_track_b.parquet

Run:  uv run python scripts/fig_horizon_headlines.py
      uv run python scripts/fig_horizon_headlines.py --track track_b
"""

from __future__ import annotations

import argparse
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qe_client import QEClient, QEError
from style import COUNTRIES, DISPLAY, SOLAR, TEMP, WIND

REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVED = REPO_ROOT / "data" / "derived"
REF = "ecmwf_ifs_single"
INIT_HOURS = [0, 6, 12, 18]
MIN_SAMPLES = 100
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
        "wt_models": [
            "ept2_1_europa",
            "ept2_hrrr",
            "ept2_e",
            "ept2_reasoning",
            "aifs_ens",
            "aifs",
            "aurora",
            "ecmwf_ifs_single",
            "noaa_gfs_single",
            "icon_global",
            "ecmwf_ens",
        ],
        "solar_models": [
            "ept2_1_helios",
            "ept2_1_europa",
            "ept2_hrrr",
            "ept2_e",
            "ept2_reasoning",
            "ecmwf_ifs_single",
            "noaa_gfs_single",
            "icon_global",
        ],
        "scopes": {
            # Wind/temp primary pool (6-hourly cadence of AIFS/AIFS ENS/Aurora).
            "h6_48": [h * 60 for h in range(6, 49, 6)],
            # Solar primary pool — hourly from 1 h (Helios's short-range edge).
            "h1_48": list(range(60, 48 * 60 + 1, 60)),
            "h1_12": list(range(60, 12 * 60 + 1, 60)),
        },
        # AIFS/AIFS ENS/Aurora only on 6-hourly scopes.
        "wt_models_by_scope": {
            "h6_48": None,  # all wt_models
            "h1_48": [
                "ept2_1_europa",
                "ept2_hrrr",
                "ept2_e",
                "ept2_reasoning",
                "ecmwf_ifs_single",
                "noaa_gfs_single",
                "icon_global",
                "ecmwf_ens",
            ],
            "h1_12": [
                "ept2_1_europa",
                "ept2_hrrr",
                "ept2_e",
                "ept2_reasoning",
                "ecmwf_ifs_single",
                "noaa_gfs_single",
                "icon_global",
                "ecmwf_ens",
            ],
        },
        # Wind/temp headlines: 6–48 h; 1–12 h companion (no six-hourly AI).
        "wt_scopes": ["h6_48", "h1_12"],
        # Solar: hourly pools only.
        "solar_scopes": ["h1_48", "h1_12"],
        "out": DERIVED / "headline_skill_track_a.parquet",
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
        "wt_models": [
            "ept2_1_europa",
            "ept2_hrrr",
            "icon_eu",
            "ecmwf_ifs_single",
        ],
        "solar_models": [
            "ept2_1_helios",
            "ept2_1_europa",
            "ept2_hrrr",
            "icon_eu",
            "ecmwf_ifs_single",
        ],
        "scopes": {
            "h1_48": list(range(60, 48 * 60 + 1, 60)),
            "h1_12": list(range(60, 12 * 60 + 1, 60)),
        },
        "wt_models_by_scope": {},
        "out": DERIVED / "headline_skill_track_b.parquet",
    },
}


def _fetch(
    client: QEClient,
    models: list[str],
    variable: str,
    country: str,
    start: str,
    end: str,
) -> pl.DataFrame | None:
    try:
        data = client.metrics(
            models=models,
            geo={"type": "country_key", "value": country},
            start_time=start,
            end_time=end,
            variables=[variable],
            metrics=["mae"],
            max_lead_minutes=48 * 60,
            debias=True,
            obs_buckets=True,
            init_hours=INIT_HOURS,
        )
    except QEError as exc:
        print(f"  SKIP {variable.split('_')[0]} {country} {start[:10]}: {exc}")
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
            "variable": [variable] * n,
        }
    )


def fetch_variable(
    client: QEClient, cfg: dict, models: list[str], variable: str
) -> tuple[pl.DataFrame, pl.DataFrame]:
    print(f"\n{variable}  {cfg['start'][:10]}→{cfg['end'][:10]}")
    full_frames, month_frames = [], []
    for c in COUNTRIES:
        df = _fetch(client, models, variable, c, cfg["start"], cfg["end"])
        if df is None:
            print(f"  full SKIP {c}")
        else:
            print(f"  full OK {c}")
            full_frames.append(df)
    jobs = [(c, a, b) for a, b in cfg["months"] for c in COUNTRIES]
    print(f"  months: {len(jobs)} cells")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, df in enumerate(
            pool.map(
                lambda j: _fetch(client, models, variable, j[0], j[1], j[2]), jobs
            ),
            1,
        ):
            if df is not None:
                month_frames.append(df)
            if i % 24 == 0 or i == len(jobs):
                print(f"    {i}/{len(jobs)}", flush=True)
    return (
        pl.concat(full_frames) if full_frames else pl.DataFrame(),
        pl.concat(month_frames) if month_frames else pl.DataFrame(),
    )


def _matched(df: pl.DataFrame, leads: list[int], models: list[str]) -> pl.DataFrame:
    keep = set(models) | {REF}
    df = df.filter(
        (pl.col("prediction_timedelta").is_in(leads))
        & (pl.col("sample_count") >= MIN_SAMPLES)
        & (pl.col("model").is_in(list(keep)))
        & (pl.col("obs_bucket").is_in(F3_BUCKETS))
    )
    ref = df.filter(pl.col("model") == REF).select(
        "country",
        "prediction_timedelta",
        "obs_bucket",
        "period_start",
        "variable",
        pl.col("avg").alias("ref_avg"),
        pl.col("sample_count").alias("ref_n"),
    )
    return df.filter(pl.col("model") != REF).join(
        ref,
        on=["country", "prediction_timedelta", "obs_bucket", "period_start", "variable"],
        how="inner",
    )


def skill_point(matched: pl.DataFrame) -> pl.DataFrame:
    # Pool sample-weighted mean errors, not error sums: a model whose matched
    # cells carry fewer samples than the reference must not score that deficit
    # as skill. Matches jackknife_se below and aggregates._skill_from_cells.
    model_pool = (pl.col("avg") * pl.col("sample_count")).sum() / pl.col(
        "sample_count"
    ).sum()
    ref_pool = (pl.col("ref_avg") * pl.col("ref_n")).sum() / pl.col("ref_n").sum()
    return matched.group_by(["variable", "model", "obs_bucket"]).agg(
        (100 * (1 - model_pool / ref_pool)).alias("skill"),
        pl.col("sample_count").sum().alias("n"),
    )


def jackknife_se(month_matched: pl.DataFrame) -> pl.DataFrame:
    per = month_matched.group_by(
        ["variable", "model", "obs_bucket", "period_start"]
    ).agg(
        (pl.col("avg") * pl.col("sample_count")).sum().alias("s_model"),
        pl.col("sample_count").sum().alias("n_model"),
        (pl.col("ref_avg") * pl.col("ref_n")).sum().alias("s_ref"),
        pl.col("ref_n").sum().alias("n_ref"),
    )
    rows = []
    for (variable, model, bucket), g in per.group_by(
        ["variable", "model", "obs_bucket"]
    ):
        months = g.to_dicts()
        m = len(months)
        if m < 2:
            rows.append(
                {
                    "variable": variable,
                    "model": model,
                    "obs_bucket": bucket,
                    "skill_se": None,
                    "n_months": m,
                }
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
            {
                "variable": variable,
                "model": model,
                "obs_bucket": bucket,
                "skill_se": se,
                "n_months": m,
            }
        )
    return pl.DataFrame(rows)


def score_scope(
    full: pl.DataFrame,
    months: pl.DataFrame,
    scope: str,
    leads: list[int],
    models: list[str],
) -> pl.DataFrame:
    sk = skill_point(_matched(full, leads, models))
    se = jackknife_se(_matched(months, leads, models))
    return (
        sk.join(se, on=["variable", "model", "obs_bucket"], how="left")
        .with_columns(pl.lit(scope).alias("lead_scope"))
        .select(
            "variable",
            "model",
            "obs_bucket",
            "lead_scope",
            "skill",
            "skill_se",
            "n",
            "n_months",
        )
    )


def _print_table(out: pl.DataFrame, scopes: dict) -> None:
    for scope in scopes:
        print(f"\n===== {scope} =====")
        for variable in (WIND, TEMP, SOLAR):
            sub = out.filter(
                (pl.col("lead_scope") == scope) & (pl.col("variable") == variable)
            )
            if sub.is_empty():
                continue
            order = sorted(
                sub.filter(pl.col("obs_bucket") == "all")["model"].to_list(),
                key=lambda m: -sub.filter(
                    (pl.col("model") == m) & (pl.col("obs_bucket") == "all")
                )["skill"][0],
            )
            short = variable.split("_at_")[0] if "_at_" in variable else "solar"
            print(f"\n{short}")
            print(f"{'model':22} " + " ".join(f"{b:>9}" for b in F3_BUCKETS))
            for m in order:
                cells = []
                for b in F3_BUCKETS:
                    r = sub.filter((pl.col("model") == m) & (pl.col("obs_bucket") == b))
                    if r.height:
                        s = r["skill_se"][0]
                        cells.append(
                            f"{r['skill'][0]:+.1f}"
                            + (f"±{s:.1f}" if s is not None else "")
                        )
                    else:
                        cells.append("—")
                print(f"{DISPLAY.get(m, m):22} " + " ".join(f"{c:>9}" for c in cells))


def build_track(client: QEClient, name: str, cfg: dict) -> None:
    print(f"\n######## {name} ########")
    pieces: list[pl.DataFrame] = []
    wt_full, wt_months = fetch_variable(client, cfg, cfg["wt_models"], WIND)
    t_full, t_months = fetch_variable(client, cfg, cfg["wt_models"], TEMP)
    s_full, s_months = fetch_variable(client, cfg, cfg["solar_models"], SOLAR)
    wt_full = pl.concat([wt_full, t_full])
    wt_months = pl.concat([wt_months, t_months])

    solar_scopes = set(cfg.get("solar_scopes") or cfg["scopes"])
    wt_scopes = set(cfg.get("wt_scopes") or cfg["scopes"])
    for scope, leads in cfg["scopes"].items():
        if scope in wt_scopes:
            wt_models = cfg["wt_models_by_scope"].get(scope) or cfg["wt_models"]
            print(f"\nscoring wind/temp {scope} …")
            pieces.append(score_scope(wt_full, wt_months, scope, leads, wt_models))
        if scope in solar_scopes:
            print(f"scoring solar {scope} …")
            pieces.append(
                score_scope(s_full, s_months, scope, leads, cfg["solar_models"])
            )

    out = pl.concat(pieces).sort("variable", "lead_scope", "obs_bucket", "model")
    cfg["out"].parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(cfg["out"])
    print(f"\nwrote {cfg['out']} ({out.height} rows)")
    _print_table(out, cfg["scopes"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--track",
        action="append",
        choices=sorted(TRACKS),
        help="Restrict to one or more tracks (default: both).",
    )
    args = parser.parse_args()
    names = args.track or list(TRACKS)
    client = QEClient()
    for name in names:
        build_track(client, name, TRACKS[name])


if __name__ == "__main__":
    main()
