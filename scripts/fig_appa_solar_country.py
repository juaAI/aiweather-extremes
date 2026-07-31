"""Appendix A-style: per-country solar MAE skill vs lead, by obs bucket.

Uses data/derived/solar_metrics_country.parquet (Track C / Helios window,
Mar 20–Jun 15 2026, hourly leads to 48 h).

Writes figures/appendix/appA_skill_by_country_solar_{bucket}.png

Run:  uv run python scripts/fig_appa_solar_country.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (
    BUCKET_LABELS,
    BUCKET_ORDER,
    COLORS,
    LINESTYLES,
    MARKERS,
    REFERENCE,
    SOLAR,
    VAR_TITLE,
    apply_style,
    COUNTRIES,
    model_legend_handles,
)

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "data" / "derived" / "solar_metrics_country.parquet"
OUT_DIR = REPO / "figures" / "appendix"

MIN_N = 100
# Parallel to wind/temp App A: thinned set for print legibility.
APPA_SOLAR_MODELS = [
    "ept2_1_helios",
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_reasoning",
    "icon_global",
    "noaa_gfs_single",
]


def _style_no_data(ax, reason: str = "no solar station obs") -> None:
    ax.set_facecolor("#f4f4f4")
    ax.fill_between(
        [0, 1],
        0,
        1,
        transform=ax.transAxes,
        facecolor="none",
        edgecolor="#d0d0d0",
        hatch="///",
        linewidth=0,
        zorder=0,
    )
    ax.text(
        0.5,
        0.5,
        reason,
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=9,
        color="#666666",
        fontstyle="italic",
    )
    ax.tick_params(colors="#bbbbbb")


def _skill_table(raw: pl.DataFrame) -> pl.DataFrame:
    """Per country × lead × bucket × model skill vs IFS (fraction)."""
    base = raw.filter(
        (pl.col("period_kind") == "full")
        & pl.col("debias")
        & (pl.col("metric") == "mae")
        & (pl.col("sample_count") >= MIN_N)
        & pl.col("obs_bucket").is_in(BUCKET_ORDER)
    ).with_columns((pl.col("prediction_timedelta") / 60.0).alias("lead_hours"))

    ref = base.filter(pl.col("model") == REFERENCE).select(
        "country",
        "lead_hours",
        "obs_bucket",
        pl.col("avg").alias("ref_avg"),
        pl.col("sample_count").alias("ref_n"),
    )
    matched = base.filter(
        (pl.col("model") != REFERENCE) & pl.col("model").is_in(APPA_SOLAR_MODELS)
    ).join(ref, on=["country", "lead_hours", "obs_bucket"], how="inner")

    return matched.with_columns(
        (1.0 - pl.col("avg") / pl.col("ref_avg")).alias("skill_full")
    ).select("model", "country", "lead_hours", "obs_bucket", "skill_full", "sample_count")


def fig_bucket(skill: pl.DataFrame, bucket: str) -> None:
    base = skill.filter(pl.col("obs_bucket") == bucket)
    models = [m for m in APPA_SOLAR_MODELS if m in base["model"].unique().to_list()]
    vals = 100 * base["skill_full"].to_numpy()
    if len(vals) and np.isfinite(vals).any():
        finite = vals[np.isfinite(vals)]
        lo, hi = min(finite.min(), 0.0), max(finite.max(), 0.0)
        pad = 0.05 * (hi - lo) if hi > lo else 5.0
        ylo, yhi = lo - pad, hi + pad
    else:
        ylo, yhi = -20.0, 20.0

    fig, axes = plt.subplots(3, 4, figsize=(12, 9.5), sharex=True, sharey=True)
    for ax, country in zip(axes.flat, COUNTRIES, strict=True):
        sub = base.filter(pl.col("country") == country)
        if sub.height == 0:
            # GB/IT/PL: no solar obs; others: bucket empty at this window.
            reason = (
                "no solar station obs"
                if country in ("GB", "IT", "PL")
                else "regime n < 100"
            )
            _style_no_data(ax, reason)
        for model in models:
            mdf = sub.filter(pl.col("model") == model).sort("lead_hours")
            if mdf.height == 0:
                continue
            ax.plot(
                mdf["lead_hours"],
                100 * mdf["skill_full"],
                linestyle=LINESTYLES.get(model, "-"),
                color=COLORS.get(model),
                lw=1.5,
                marker=MARKERS.get(model, "o"),
                markersize=2.0,
            )
        ax.axhline(0, color="k", lw=0.8, ls="--")
        ax.set_title(country)
        ax.set_xlim(0, 48)
        ax.set_ylim(ylo, yhi)
    for ax in axes[-1, :]:
        ax.set_xlabel("Lead time (h)")
    for ax in axes[:, 0]:
        ax.set_ylabel("MAE skill vs ECMWF IFS (%)")

    handles = model_legend_handles(models, ncol=3)
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=3,
        fontsize=10,
        bbox_to_anchor=(0.5, 0.0),
        handlelength=3.2,
        handletextpad=0.6,
    )
    fig.suptitle(
        f"MAE skill vs ECMWF IFS per country — {VAR_TITLE[SOLAR]}, "
        f"{BUCKET_LABELS[bucket]}\n"
        f"(debiased, Mar 20\u2013Jun 15 2026; hourly leads to 48 h)"
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.96))
    out = OUT_DIR / f"appA_skill_by_country_solar_{bucket}.png"
    fig.savefig(out)
    plt.close(fig)
    print("wrote", out)


def main() -> None:
    apply_style()
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.titlesize": 12,
        }
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = pl.read_parquet(SRC)
    skill = _skill_table(raw)
    print(
        "countries with data:",
        sorted(skill["country"].unique().to_list()),
        "rows",
        skill.height,
    )
    for bucket in BUCKET_ORDER:
        fig_bucket(skill, bucket)


if __name__ == "__main__":
    main()
