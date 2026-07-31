"""Appendix B: per-country regime skill as grouped bars (fig3 style).

Window: 1 March – 30 June 2026.
Horizon: pooled 1–48 h (hourly), same as Track B / solar headlines.
Regimes: ERA5 1991-2020 climatological percentiles (all, <P5, P5-25, P25-75,
P75-95, >P95) -- the SAME definition as everywhere else in the paper, scored
OFFLINE from the climatological metric tables rather than fetched from the API
(the API only returns in-window percentiles).

Clean-clone input:
  data/derived/appb_country_skill_climatology.parquet

Preparation sources (only needed with --prepare):
  data/derived/bucketed_metrics_climatology.parquet          (wind, temp)
  data/derived/solar_metrics_country_climatology.parquet     (solar)
  data/derived/bucketed_metrics_precip.parquet                (precipitation)

Mar-Jun is reconstructed from the monthly rows: the global models and the
generative regionals come from Track A months Mar-Jun; DWD ICON-EU (regional,
Track B only) comes from Track B months. Each model is scored against the
same-track IFS on month-matched (country, lead, regime) cells, then pooled
sample-weighted over the four months and 1-48 h.

Writes figures/appendix/appB_bucket_profile_by_country_{wind,temp,solar,precip}.png

Run offline:  uv run python scripts/fig_appb_country_bars.py
Rebuild input: uv run python scripts/fig_appb_country_bars.py --prepare
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (
    BUCKET_LABELS,
    COLORS,
    COUNTRIES,
    DISPLAY,
    PRECIP,
    PRECIP_BUCKET_LABELS,
    PRECIP_BUCKET_ORDER,
    REFERENCE,
    SOLAR,
    TEMP,
    VAR_SHORT,
    VAR_TITLE,
    WIND,
    apply_style,
)

REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"
OUT_DIR = REPO / "figures" / "appendix"
WT_SOURCE = DERIVED / "bucketed_metrics_climatology.parquet"
SOLAR_SOURCE = DERIVED / "solar_metrics_country_climatology.parquet"
PRECIP_SOURCE = DERIVED / "bucketed_metrics_precip.parquet"
PROFILE_SOURCE = DERIVED / "appb_country_skill_climatology.parquet"

MIN_N = 100
LEADS_MIN = [h * 60 for h in range(1, 49)]  # 1-48 h hourly
MARJUN = [
    "2026-03-01T00:00:00Z",
    "2026-04-01T00:00:00Z",
    "2026-05-01T00:00:00Z",
    "2026-06-01T00:00:00Z",
]
# Climatological regimes, now including the very-low (<P5) tail.
BUCKETS = ["all", "lt_q5", "q5_q25", "q25_q75", "q75_q95", "gt_q95"]

# ICON-EU only runs in Track B; every other model is pooled from Track A months
# (both windows are Mar-Jun, so the comparison is like-for-like).
MODEL_TRACK = {"icon_eu": "track_b"}

WT_MODELS = [
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_reasoning",
    "icon_eu",
    "icon_global",
    "noaa_gfs_single",
]
SOLAR_MODELS = [
    "ept2_1_helios",
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_reasoning",
    "icon_eu",
    "icon_global",
    "noaa_gfs_single",
]
PRECIP_MODELS = [
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_e",
    "ept2_reasoning",
    "icon_eu",
    "icon_global",
    "noaa_gfs_single",
]

BUCKET_ALPHAS = {
    "all": 0.30,
    "lt_q5": 0.44,
    "q5_q25": 0.57,
    "q25_q75": 0.70,
    "q75_q95": 0.85,
    "gt_q95": 1.0,
    "dry": 0.40,
    "wet_lt_p50": 0.55,
    "p50_p75": 0.70,
    "p75_p95": 0.85,
    "gt_p95": 1.0,
}

# Soft y-floor so one −80% cell does not crush the panel; bars still drawn.
Y_FLOOR = -25.0


def _short_model(m: str) -> str:
    if m == "ept2_reasoning":
        return "EPT-2 Reasoning"
    if m == "ept2_1_europa":
        return "EPT-2.1 Europa"
    if m == "ept2_1_helios":
        return "EPT-2.1 Helios"
    if m == "ept2_hrrr":
        return "EPT-2 HRRR"
    return (
        DISPLAY.get(m, m)
        .replace("Jua ", "")
        .replace("EPT-2.1 ", "E2.1 ")
        .replace("EPT-2 ", "E2 ")
        .replace("Microsoft ", "")
        .replace("ECMWF ", "")
        .replace("DWD ", "")
        .replace("NOAA ", "")
    )


def _skill_offline(
    source: pl.DataFrame,
    variable: str,
    models: list[str],
    buckets: list[str],
) -> pl.DataFrame:
    """Mar-Jun climatological-regime skill per (model, country, regime).

    Pooled sample-weighted over the four months and 1-48 h leads; each model
    scored against the same-track IFS on month-matched cells. The <100-sample
    floor is applied on the pooled (model, country, regime) count so a sparse
    single month does not silently drop a whole regime.
    """
    base = source.filter(
        (pl.col("variable") == variable)
        & (pl.col("metric") == "mae")
        & pl.col("debias")
        & (pl.col("period_kind") == "month")
        & pl.col("period_start").is_in(MARJUN)
        & pl.col("prediction_timedelta").is_in(LEADS_MIN)
        & pl.col("obs_bucket").is_in(buckets)
    )
    join_keys = ["country", "prediction_timedelta", "obs_bucket", "period_start"]
    out: list[pl.DataFrame] = []
    for track in ["track_a", "track_b"]:
        tdf = base.filter(pl.col("track") == track)
        if tdf.is_empty():
            continue
        ref = tdf.filter(pl.col("model") == REFERENCE).select(
            *join_keys,
            pl.col("avg").alias("ref_avg"),
            pl.col("sample_count").alias("ref_n"),
        )
        tmodels = [m for m in models if MODEL_TRACK.get(m, "track_a") == track]
        if not tmodels:
            continue
        matched = tdf.filter(pl.col("model").is_in(tmodels)).join(
            ref, on=join_keys, how="inner"
        )
        model_pool = (pl.col("avg") * pl.col("sample_count")).sum() / pl.col(
            "sample_count"
        ).sum()
        ref_pool = (pl.col("ref_avg") * pl.col("ref_n")).sum() / pl.col("ref_n").sum()
        sk = matched.group_by(["model", "country", "obs_bucket"]).agg(
            (100 * (1 - model_pool / ref_pool)).alias("skill_pct"),
            pl.col("sample_count").sum().alias("n"),
        )
        out.append(sk.filter(pl.col("n") >= MIN_N).drop("n"))
    if not out:
        return pl.DataFrame()
    return pl.concat(out)


def _grid_shape(n: int) -> tuple[int, int]:
    """Compact grid for n panels (skip empty countries)."""
    if n <= 4:
        return 1, n
    if n <= 8:
        return 2, 4
    if n <= 9:
        return 3, 3
    return 3, 4


def _draw(
    skill: pl.DataFrame,
    variable: str,
    models: list[str],
    buckets: list[str],
    bucket_labels: dict[str, str],
) -> None:
    models = [m for m in models if m in skill["model"].unique().to_list()]
    # Only countries with data — no empty GB/ES/IT/PL panels.
    countries = [c for c in COUNTRIES if skill.filter(pl.col("country") == c).height]
    if not countries:
        print(f"  no countries with data for {variable}")
        return

    vals = skill["skill_pct"].to_numpy()
    vals = vals[np.isfinite(vals)]
    yhi = float(max(vals.max() * 1.08, 5.0)) if len(vals) else 20.0
    ylo = Y_FLOOR
    n_m, n_b = len(models), len(buckets)
    width = 0.85 / n_b
    x = np.arange(n_m)

    nrows, ncols = _grid_shape(len(countries))
    fig_w = min(3.6 * ncols, 14.5)
    fig_h = min(3.6 * nrows + 1.8, 11.5)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(fig_w, fig_h), sharex=True, sharey=True, squeeze=False
    )
    flat = list(axes.flat)
    for i, ax in enumerate(flat):
        if i >= len(countries):
            ax.set_visible(False)
            continue
        country = countries[i]
        sub = skill.filter(pl.col("country") == country)
        for k, bucket in enumerate(buckets):
            heights = []
            for m in models:
                r = sub.filter(
                    (pl.col("model") == m) & (pl.col("obs_bucket") == bucket)
                )
                heights.append(r["skill_pct"][0] if r.height else np.nan)
            xpos = x + (k - (n_b - 1) / 2) * width
            ax.bar(
                xpos,
                heights,
                width * 0.92,
                color=[COLORS.get(m, "gray") for m in models],
                alpha=BUCKET_ALPHAS[bucket],
                edgecolor="white",
                linewidth=0.25,
                clip_on=True,
            )
        ax.axhline(0, color="k", lw=0.9)
        ax.set_title(country, fontsize=12)
        ax.set_ylim(ylo, yhi)
        ax.set_xticks(x)
        ax.set_xticklabels(
            [_short_model(m) for m in models], rotation=40, ha="right", fontsize=8
        )
        ax.tick_params(axis="y", labelsize=9)
    for ax in axes[:, 0]:
        ax.set_ylabel("MAE skill vs ECMWF IFS (%)", fontsize=10)

    model_handles = [
        Line2D([], [], color=COLORS.get(m, "gray"), lw=8, label=DISPLAY.get(m, m))
        for m in models
    ]
    bucket_handles = [
        Patch(facecolor="0.45", alpha=BUCKET_ALPHAS[b], label=bucket_labels[b])
        for b in buckets
    ]
    fig.legend(
        handles=model_handles + bucket_handles,
        loc="lower center",
        ncol=4,
        fontsize=9,
        bbox_to_anchor=(0.5, 0.0),
        frameon=False,
    )
    fig.suptitle(
        f"MAE skill vs ECMWF IFS across regimes per country: "
        f"{VAR_TITLE[variable]}",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0.09, 1, 0.97))
    out = OUT_DIR / f"appB_bucket_profile_by_country_{VAR_SHORT[variable]}.png"
    fig.savefig(out)
    plt.close(fig)
    print("wrote", out, "countries", countries)


PROFILE_SPECS = (
    (WIND, WT_MODELS, BUCKETS, BUCKET_LABELS, "wind"),
    (TEMP, WT_MODELS, BUCKETS, BUCKET_LABELS, "temp"),
    (SOLAR, SOLAR_MODELS, BUCKETS, BUCKET_LABELS, "solar"),
    (
        PRECIP,
        PRECIP_MODELS,
        PRECIP_BUCKET_ORDER,
        PRECIP_BUCKET_LABELS,
        "precip",
    ),
)


def prepare_profiles() -> pl.DataFrame:
    """Build the compact, tracked Appendix-B input from raw metric tables."""
    wt = pl.read_parquet(WT_SOURCE)
    solar = pl.read_parquet(SOLAR_SOURCE)
    precip = pl.read_parquet(PRECIP_SOURCE)
    sources = {WIND: wt, TEMP: wt, SOLAR: solar, PRECIP: precip}
    frames = []
    for variable, models, buckets, _bucket_labels, name in PROFILE_SPECS:
        print(f"prepare {name} Mar–Jun 1–48 h (climatological regimes) …")
        skill = _skill_offline(sources[variable], variable, models, buckets)
        if skill.is_empty():
            raise RuntimeError(f"no Appendix-B profile data for {name}")
        frames.append(skill.with_columns(pl.lit(variable).alias("variable")))
    profiles = pl.concat(frames).select(
        "variable", "model", "country", "obs_bucket", "skill_pct"
    ).sort("variable", "country", "obs_bucket", "model")
    profiles.write_parquet(PROFILE_SOURCE)
    print("wrote", PROFILE_SOURCE, profiles.height)
    return profiles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="rebuild the compact tracked profile parquet from raw metric tables",
    )
    args = parser.parse_args()
    apply_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        profiles = prepare_profiles()
    else:
        if not PROFILE_SOURCE.exists():
            raise FileNotFoundError(
                f"Missing {PROFILE_SOURCE}; run this script once with --prepare "
                "where the raw metric tables are available"
            )
        profiles = pl.read_parquet(PROFILE_SOURCE)

    for variable, models, buckets, bucket_labels, name in PROFILE_SPECS:
        print(f"draw {name} Mar–Jun 1–48 h (climatological regimes) …")
        skill = profiles.filter(pl.col("variable") == variable).drop("variable")
        if skill.is_empty():
            print(f"  no data for {name}")
            continue
        print(
            f"  countries {sorted(skill['country'].unique().to_list())} "
            f"rows {skill.height}"
        )
        _draw(skill, variable, models, buckets, bucket_labels)


if __name__ == "__main__":
    main()
