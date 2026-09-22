"""Appendix A: per-country MAE skill vs lead, by obs bucket — bar style.

Fig.~3 layout: model on the x-axis, lead encoded by bar opacity.
Wind/temp: Track A Sep 2025–Jun 2026, leads 6/12/24/48 h (QE fetch/cache).
Solar: Helios window from solar_metrics_country.parquet, leads 1/6/12/24/48 h.

Writes figures/appendix/appA_skill_by_country_{wind,temp,solar}_{bucket}.png

Run:  uv run python scripts/fig_appa_country_bars.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qe_client import QEClient, QEError
from style import (
    BUCKET_LABELS,
    BUCKET_ORDER,
    COLORS,
    DISPLAY,
    REFERENCE,
    SOLAR,
    TEMP,
    VAR_SHORT,
    VAR_TITLE,
    WIND,
    apply_style,
    COUNTRIES,
)

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "figures" / "appendix"
SOLAR_METRICS = REPO / "data" / "derived" / "solar_metrics_country.parquet"

MIN_N = 100
START, END = "2025-09-01T00:00:00Z", "2026-07-01T00:00:00Z"

WT_LEADS = [6, 12, 24, 48]
SOLAR_LEADS = [1, 6, 12, 24, 48]

WT_MODELS = [
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_reasoning",
    "aifs_ens",
    "aurora",
    "aifs",
    "icon_global",
    "noaa_gfs_single",
]
SOLAR_MODELS = [
    "ept2_1_helios",
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_reasoning",
    "icon_global",
    "noaa_gfs_single",
]

LEAD_ALPHAS = {1: 0.35, 6: 0.45, 12: 0.60, 24: 0.80, 48: 1.0}


def _short_model(m: str) -> str:
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


def _shared_ylim(values: np.ndarray) -> tuple[float, float]:
    vals = values[np.isfinite(values)]
    if len(vals) == 0:
        return -20.0, 20.0
    lo, hi = min(vals.min(), 0.0), max(vals.max(), 0.0)
    pad = 0.08 * (hi - lo) if hi > lo else 5.0
    return lo - pad, hi + pad


def _style_empty(ax, reason: str) -> None:
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
        fontsize=8,
        color="#666666",
        fontstyle="italic",
    )
    ax.tick_params(colors="#bbbbbb")


def _skill_table(raw: pl.DataFrame, models: list[str], leads: list[int]) -> pl.DataFrame:
    """raw: model, lead (minutes), obs_bucket, avg, n, country → skill %."""
    base = raw.filter(
        pl.col("lead").is_in([h * 60 for h in leads])
        & (pl.col("n") >= MIN_N)
        & pl.col("obs_bucket").is_in(BUCKET_ORDER)
    )
    ref = base.filter(pl.col("model") == REFERENCE).select(
        "country",
        "lead",
        "obs_bucket",
        pl.col("avg").alias("ref_avg"),
        pl.col("n").alias("ref_n"),
    )
    matched = base.filter(
        (pl.col("model") != REFERENCE) & pl.col("model").is_in(models)
    ).join(ref, on=["country", "lead", "obs_bucket"], how="inner")
    # Pool sample-weighted mean errors, not error sums, so a model with fewer
    # matched samples than the reference does not score that deficit as skill.
    model_pool = (pl.col("avg") * pl.col("n")).sum() / pl.col("n").sum()
    ref_pool = (pl.col("ref_avg") * pl.col("ref_n")).sum() / pl.col("ref_n").sum()
    return matched.group_by(["model", "country", "obs_bucket", "lead"]).agg(
        (100 * (1 - model_pool / ref_pool)).alias("skill")
    ).with_columns((pl.col("lead") / 60).cast(pl.Int64).alias("lead_h")).drop("lead")


def _fetch_wt(client: QEClient, variable: str) -> pl.DataFrame:
    models = [*WT_MODELS, REFERENCE]

    def one(country: str) -> pl.DataFrame | None:
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
                init_hours=[0, 6, 12, 18],
            )
        except QEError as exc:
            print(f"  SKIP {country}: {exc}")
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
            }
        )

    frames: list[pl.DataFrame] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for df in pool.map(one, COUNTRIES):
            if df is not None:
                frames.append(df)
    if not frames:
        return pl.DataFrame()
    return _skill_table(pl.concat(frames), WT_MODELS, WT_LEADS)


def _solar_skill() -> pl.DataFrame:
    raw = (
        pl.read_parquet(SOLAR_METRICS)
        .filter(
            (pl.col("period_kind") == "full")
            & pl.col("debias")
            & (pl.col("metric") == "mae")
        )
        .select(
            "model",
            pl.col("prediction_timedelta").alias("lead"),
            "obs_bucket",
            "avg",
            pl.col("sample_count").alias("n"),
            "country",
        )
    )
    return _skill_table(raw, SOLAR_MODELS, SOLAR_LEADS)


def _draw_bucket(
    skill: pl.DataFrame,
    variable: str,
    bucket: str,
    models: list[str],
    leads: list[int],
    footnote: str,
) -> None:
    base = skill.filter(pl.col("obs_bucket") == bucket)
    models = [m for m in models if m in base["model"].unique().to_list()]
    ylo, yhi = _shared_ylim(base["skill"].to_numpy())
    n_m, n_l = len(models), len(leads)
    width = 0.85 / max(n_l, 1)
    x = np.arange(n_m)

    fig, axes = plt.subplots(3, 4, figsize=(12, 9.5), sharex=True, sharey=True)
    for ax, country in zip(axes.flat, COUNTRIES, strict=True):
        sub = base.filter(pl.col("country") == country)
        if sub.height == 0:
            reason = (
                "no solar station obs"
                if variable == SOLAR and country in ("GB", "IT", "PL")
                else "regime n < 100"
            )
            _style_empty(ax, reason)
            ax.set_title(country)
            ax.set_ylim(ylo, yhi)
            continue
        for k, h in enumerate(leads):
            heights = []
            for m in models:
                r = sub.filter((pl.col("model") == m) & (pl.col("lead_h") == h))
                heights.append(r["skill"][0] if r.height else np.nan)
            xpos = x + (k - (n_l - 1) / 2) * width
            ax.bar(
                xpos,
                heights,
                width * 0.95,
                color=[COLORS.get(m, "gray") for m in models],
                alpha=LEAD_ALPHAS.get(h, 0.7),
                edgecolor="white",
                linewidth=0.2,
            )
        ax.axhline(0, color="k", lw=0.8, ls="--")
        ax.set_title(country)
        ax.set_ylim(ylo, yhi)
        ax.set_xticks(x)
        ax.set_xticklabels(
            [_short_model(m) for m in models], rotation=55, ha="right", fontsize=6.5
        )
    for ax in axes[:, 0]:
        ax.set_ylabel("MAE skill vs ECMWF IFS (%)", fontsize=9)

    model_handles = [
        Line2D([], [], color=COLORS.get(m, "gray"), lw=6, label=DISPLAY.get(m, m))
        for m in models
    ]
    lead_handles = [
        Patch(facecolor="0.45", alpha=LEAD_ALPHAS[h], label=f"{h} h") for h in leads
    ]
    fig.legend(
        handles=model_handles + lead_handles,
        loc="lower center",
        ncol=4,
        fontsize=8,
        bbox_to_anchor=(0.5, 0.0),
        frameon=False,
    )
    fig.suptitle(
        f"MAE skill vs ECMWF IFS per country — {VAR_TITLE[variable]}, "
        f"{BUCKET_LABELS[bucket]}\n{footnote}",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0.10, 1, 0.96))
    out = OUT_DIR / f"appA_skill_by_country_{VAR_SHORT[variable]}_{bucket}.png"
    fig.savefig(out)
    plt.close(fig)
    print("wrote", out)


def main() -> None:
    apply_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, pl.DataFrame, list[str], list[int], str]] = []

    print("solar from parquet")
    solar = _solar_skill()
    jobs.append(
        (
            SOLAR,
            solar,
            SOLAR_MODELS,
            SOLAR_LEADS,
            "(debiased, Mar 20\u2013Jun 15 2026; leads 1/6/12/24/48 h)",
        )
    )

    client = QEClient()
    for variable, name in ((WIND, "wind"), (TEMP, "temp")):
        print(f"fetch {name} Track A …")
        skill = _fetch_wt(client, variable)
        if skill.is_empty():
            print(f"  no data for {name}")
            continue
        print(
            f"  countries {sorted(skill['country'].unique().to_list())} "
            f"rows {skill.height}"
        )
        jobs.append(
            (
                variable,
                skill,
                WT_MODELS,
                WT_LEADS,
                "(debiased, Track A Sep 2025\u2013Jun 2026; leads 6/12/24/48 h)",
            )
        )

    for variable, skill, models, leads, note in jobs:
        for bucket in BUCKET_ORDER:
            _draw_bucket(skill, variable, bucket, models, leads, note)


if __name__ == "__main__":
    main()
