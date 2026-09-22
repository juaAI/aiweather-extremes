"""Paper appendix: per-country figure grids for every country and bucket,
per-country bucket-pair heatmaps, plus LaTeX table fragments with the full
numeric results. All skill shown is MAE-based (the paper's primary metric,
metric='mae' rows); the legacy 'ept2' model is excluded everywhere.

Inputs:  data/derived/{skill_vs_reference,europe_metrics,fingerprint}.parquet
  skill_vs_reference.parquet: track, family, model, country, variable, debias,
    lead_hours, obs_bucket, metric, skill_full (fraction vs ecmwf_ifs_single),
    sample_count, monthly stats and significance columns.
  europe_metrics.parquet: model, variable, prediction_timedelta (minutes),
    metric, obs_bucket, avg, sample_count, track, period_kind, period_start,
    period_end, country, debias, family.
  fingerprint.parquet: track, model, country, variable, debias, lead_hours,
    obs_bucket, conditional_bias, sample_count.

Outputs: figures/appendix/*.png, paper/tables/*.tex,
         reports/figures_appendix_manifest.md

Run:  python scripts/figures_appendix.py
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.colors import LogNorm

from qe_client import PROJECT_ROOT
from style import (
    BUCKET_LABELS,
    BUCKET_ORDER,
    COLORS,
    LINESTYLES,
    MARKERS,
    DISPLAY,
    MODEL_ORDER,
    REFERENCE,
    TEMP,
    VAR_SHORT,
    VAR_TITLE,
    VAR_UNIT,
    WIND,
    apply_style,
    COUNTRIES,
    model_legend_handles,
)

DERIVED_DIR = PROJECT_ROOT / "data" / "derived"
APPENDIX_DIR = PROJECT_ROOT / "figures" / "appendix"
TABLES_DIR = PROJECT_ROOT / "paper" / "tables"
REPORTS_DIR = PROJECT_ROOT / "reports"

BUCKET_SHORT = {
    "all": "all",
    "lt_q5": "<P5",
    "q5_q25": "P5-25",
    "q25_q75": "P25-75",
    "q75_q95": "P75-95",
    "gt_q95": ">P95",
}
# LaTeX-safe bucket headers (< and > need math mode in text).
BUCKET_TEX = {
    "all": "All",
    "lt_q5": "$<$P5",
    "q5_q25": "P5--25",
    "q25_q75": "P25--75",
    "q75_q95": "P75--95",
    "gt_q95": "$>$P95",
}
# EC ENS is deliberately excluded from the regional Track B comparison: it is
# a global medium-range ensemble, not a regional model.
TRACK_B_MODELS = ["ept2_1_europa", "ept2_hrrr", "icon_eu"]
# Thinned line set for the appA panel grids (print legibility): ept2_e and
# ecmwf_ens are dropped to reduce clutter.
APPA_MODELS = [
    "ept2_1_europa",
    "ept2_hrrr",
    "ept2_reasoning",
    "aifs_ens",
    "aurora",
    "aifs",
    "icon_global",
]
SAMPLE_COUNT_MODEL = (
    "ept2_reasoning"  # counts are per-bucket obs counts, model-invariant
)
NAN_GRAY = "#d4d4d4"
COUNTRY_HEATMAP_PAIRS = [
    ("all", "lt_q5"),
    ("q5_q25", "q25_q75"),
    ("q75_q95", "gt_q95"),
]

manifest: list[tuple[str, str]] = []


def _bump_fonts() -> None:
    """Print-legibility bump on top of apply_style(): appendix grids are
    <= 12 in wide, so >= 10 pt here keeps text readable at 16 cm."""
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10.5,
            "figure.titlesize": 13,
        }
    )


def _record(path, caption: str) -> None:
    manifest.append((str(path.relative_to(PROJECT_ROOT)), caption))
    print("wrote", path)


def _ordered_models(models: list[str]) -> list[str]:
    return [m for m in MODEL_ORDER if m in models]


def _shared_ylim(values: np.ndarray) -> tuple[float, float]:
    """Shared y-limits covering the full data range (no clipped lines), padded,
    zero included."""
    vals = values[np.isfinite(values)]
    lo, hi = min(vals.min(), 0.0), max(vals.max(), 0.0)
    pad = 0.05 * (hi - lo)
    return lo - pad, hi + pad


def _figure_legend(fig, models: list[str], **kwargs) -> None:
    handles = model_legend_handles(models, ncol=3)
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=min(len(models), 3),
        fontsize=10.5,
        bbox_to_anchor=(0.5, 0.0),
        handlelength=3.2,
        handletextpad=0.6,
        **kwargs,
    )


def _skill_base(df: pl.DataFrame, track: str) -> pl.DataFrame:
    """MAE-based skill rows (the paper's primary metric)."""
    return df.filter(
        (pl.col("track") == track)
        & pl.col("debias")
        & (pl.col("family") == "mean")
        & (pl.col("metric") == "mae")
    )


def _style_no_data_panel(ax) -> None:
    """A no-data country panel styled as information, not breakage: light
    hatched background and a physical explanation. Used where a regime is
    structurally empty (calm climates: P5 of observed wind is 0) or falls
    below the 100-sample floor."""
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
        0.55,
        "regime not observable",
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=9,
        color="#666666",
        fontstyle="italic",
    )
    ax.text(
        0.5,
        0.40,
        "calm share > 5% or n < 100",
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=7.5,
        color="#999999",
    )
    ax.tick_params(colors="#bbbbbb")


# ---------------------------------------------------------------- A1
def fig_a1_skill_by_country(df: pl.DataFrame, variable: str, bucket: str) -> None:
    base = _skill_base(df, "track_a").filter(
        (pl.col("variable") == variable)
        & (pl.col("obs_bucket") == bucket)
        & (pl.col("lead_hours") <= 120)
        & pl.col("model").is_in(APPA_MODELS)
    )
    models = _ordered_models(base["model"].unique().to_list())
    ylo, yhi = _shared_ylim(100 * base["skill_full"].to_numpy())

    fig, axes = plt.subplots(3, 4, figsize=(12, 9.5), sharex=True, sharey=True)
    for ax, country in zip(axes.flat, COUNTRIES, strict=True):
        sub = base.filter(pl.col("country") == country)
        if sub.height == 0:
            _style_no_data_panel(ax)
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
                markersize=2.5,
            )
        ax.axhline(0, color="k", lw=0.8, ls="--")
        ax.set_title(country)
        ax.set_xlim(0, 120)
        ax.set_ylim(ylo, yhi)
    for ax in axes[-1, :]:
        ax.set_xlabel("Lead time (h)")
    for ax in axes[:, 0]:
        ax.set_ylabel("MAE skill vs ECMWF IFS (%)")
    _figure_legend(fig, models)
    fig.suptitle(
        f"MAE skill vs ECMWF IFS per country — {VAR_TITLE[variable]}, "
        f"{BUCKET_LABELS[bucket]} (debiased, Track A)"
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    out = APPENDIX_DIR / f"appA_skill_by_country_{VAR_SHORT[variable]}_{bucket}.png"
    fig.savefig(out)
    plt.close(fig)
    _record(
        out,
        f"Per-country MAE skill relative to ECMWF IFS versus lead time for "
        f"{VAR_TITLE[variable]} in the {BUCKET_LABELS[bucket]} bucket "
        f"(debiased, Track A; regional models end at 48 h; 7-model subset — "
        f"EPT-2e and EC ENS omitted for legibility).",
    )


# ---------------------------------------------------------------- A2
def fig_a2_bucket_profile(df: pl.DataFrame, variable: str) -> None:
    base = _skill_base(df, "track_a").filter(
        (pl.col("variable") == variable) & pl.col("lead_hours").is_in([24.0, 48.0])
    )
    pooled = base.group_by(["model", "country", "obs_bucket"]).agg(
        (100 * pl.col("skill_full").median()).alias("skill_pct")
    )
    models = _ordered_models(pooled["model"].unique().to_list())
    ylo, yhi = _shared_ylim(pooled["skill_pct"].to_numpy())
    x = np.arange(len(BUCKET_ORDER))

    fig, axes = plt.subplots(3, 4, figsize=(12, 9.5), sharex=True, sharey=True)
    for ax, country in zip(axes.flat, COUNTRIES, strict=True):
        sub = pooled.filter(pl.col("country") == country)
        for model in models:
            mdf = sub.filter(pl.col("model") == model)
            lookup = dict(zip(mdf["obs_bucket"], mdf["skill_pct"], strict=True))
            ys = np.array([lookup.get(b, np.nan) for b in BUCKET_ORDER])
            if np.all(np.isnan(ys)):
                continue
            ax.plot(
                x,
                ys,
                marker=MARKERS.get(model, "o"),
                ms=3,
                lw=1.4,
                linestyle=LINESTYLES.get(model, "-"),
                color=COLORS.get(model),
            )
        ax.axhline(0, color="k", lw=0.8, ls="--")
        ax.set_title(country)
        ax.set_ylim(ylo, yhi)
        ax.set_xticks(
            x,
            [BUCKET_SHORT[b] for b in BUCKET_ORDER],
            rotation=45,
            ha="right",
            fontsize=10,
        )
    for ax in axes[-1, :]:
        ax.set_xlabel("Observed-value bucket")
    for ax in axes[:, 0]:
        ax.set_ylabel("MAE skill vs ECMWF IFS (%)")
    _figure_legend(fig, models)
    fig.suptitle(
        f"MAE skill vs ECMWF IFS across observed-value buckets per country — "
        f"{VAR_TITLE[variable]}\n(debiased, Track A, median of 24/48 h leads)"
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    out = APPENDIX_DIR / f"appB_bucket_profile_by_country_{VAR_SHORT[variable]}.png"
    fig.savefig(out)
    plt.close(fig)
    _record(
        out,
        f"Per-country skill profile across all six observed-value buckets for "
        f"{VAR_TITLE[variable]} (debiased, Track A, median over 24 and 48 h "
        f"leads); gaps mark buckets with no samples (e.g. no <P5 wind bucket "
        f"in calm-climate countries).",
    )


# ---------------------------------------------------------------- A3
def fig_a3_sample_counts(df: pl.DataFrame) -> None:
    base = _skill_base(df, "track_a").filter(
        (pl.col("model") == SAMPLE_COUNT_MODEL) & (pl.col("lead_hours") == 24.0)
    )
    # Vertical stack (one full-width heatmap per variable) for print legibility.
    fig, axes = plt.subplots(2, 1, figsize=(10, 12), constrained_layout=True)
    for ax, variable in zip(axes, (WIND, TEMP), strict=True):
        sub = base.filter(pl.col("variable") == variable)
        mat = np.full((len(COUNTRIES), len(BUCKET_ORDER)), np.nan)
        for i, country in enumerate(COUNTRIES):
            for j, bucket in enumerate(BUCKET_ORDER):
                row = sub.filter(
                    (pl.col("country") == country) & (pl.col("obs_bucket") == bucket)
                )
                if row.height:
                    mat[i, j] = row["sample_count"][0]
        im = ax.imshow(
            np.ma.masked_invalid(mat),
            cmap="viridis",
            aspect="auto",
            norm=LogNorm(vmin=max(np.nanmin(mat), 1), vmax=np.nanmax(mat)),
        )
        for i in range(len(COUNTRIES)):
            for j in range(len(BUCKET_ORDER)):
                if np.isnan(mat[i, j]):
                    ax.text(
                        j, i, "-", ha="center", va="center", fontsize=10, color="gray"
                    )
                else:
                    norm_v = im.norm(mat[i, j])
                    ax.text(
                        j,
                        i,
                        f"{int(mat[i, j]):,}",
                        ha="center",
                        va="center",
                        fontsize=10,
                        color="white" if norm_v < 0.6 else "black",
                    )
        ax.set_xticks(
            range(len(BUCKET_ORDER)),
            [BUCKET_SHORT[b] for b in BUCKET_ORDER],
        )
        ax.set_yticks(range(len(COUNTRIES)), COUNTRIES)
        ax.set_xlabel("Observed-value bucket")
        ax.set_ylabel("Country")
        ax.set_title(VAR_TITLE[variable])
        ax.grid(visible=False)
        fig.colorbar(im, ax=ax, label="Sample count (log scale)", pad=0.02)
    fig.suptitle(
        "Verification sample counts per country and observed-value bucket\n"
        "(full period, 24 h lead; counts are per-bucket station-observation pairs)"
    )
    out = APPENDIX_DIR / "appC_sample_counts.png"
    fig.savefig(out)
    plt.close(fig)
    _record(
        out,
        "Sample counts per country and observed-value bucket at 24 h lead "
        "(full period), documenting the tail sample sizes behind the "
        "per-country extreme-bucket estimates; dashes mark empty buckets.",
    )


# ---------------------------------------------------------------- A4
def fig_a4_bias_heatmap(fp: pl.DataFrame, variable: str) -> None:
    """Reviewer redesign: the per-country fingerprint LINE grids were
    unreadable. Replacement: one annotated country x regime heatmap of the
    conditional bias at 48 h lead, averaged across all models (the main-text
    envelope figure shows the cross-model spread is small, so the mean is a
    faithful summary)."""
    base = fp.filter(
        (pl.col("track") == "track_a")
        & pl.col("debias")
        & (pl.col("variable") == variable)
        & (pl.col("lead_hours") == 48.0)
        & pl.col("model").is_in(MODEL_ORDER)
    )
    mat = np.full((len(COUNTRIES), len(BUCKET_ORDER)), np.nan)
    for i, country in enumerate(COUNTRIES):
        for j, bucket in enumerate(BUCKET_ORDER):
            sub = base.filter(
                (pl.col("country") == country) & (pl.col("obs_bucket") == bucket)
            )
            if sub.height:
                mat[i, j] = sub["conditional_bias"].mean()
    vmax = np.nanmax(np.abs(mat))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad(NAN_GRAY)

    fig, ax = plt.subplots(figsize=(9, 7.5), constrained_layout=True)
    im = ax.imshow(
        np.ma.masked_invalid(mat), cmap=cmap, vmin=-vmax, vmax=vmax, aspect="auto"
    )
    ax.set_xticks(range(len(BUCKET_ORDER)))
    ax.set_xticklabels([BUCKET_SHORT[b] for b in BUCKET_ORDER])
    ax.set_yticks(range(len(COUNTRIES)))
    ax.set_yticklabels(COUNTRIES)
    ax.set_xlabel("Observed-value bucket")
    ax.set_ylabel("Country")
    ax.grid(visible=False)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if np.isnan(v):
                ax.text(j, i, "--", ha="center", va="center", fontsize=10, color="0.45")
                continue
            color = "white" if abs(v) > 0.62 * vmax else "black"
            ax.text(
                j, i, f"{v:+.1f}", ha="center", va="center", fontsize=10, color=color
            )
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label(f"Conditional bias ({VAR_UNIT[variable]}), cross-model mean")
    ax.set_title(
        f"Conditional bias per country and observed-value bucket — "
        f"{VAR_TITLE[variable]}\n"
        "(48 h lead, debiased, Track A; mean across all models incl. the "
        "ECMWF IFS reference)"
    )
    out = APPENDIX_DIR / f"appD_bias_heatmap_{VAR_SHORT[variable]}.png"
    fig.savefig(out)
    plt.close(fig)
    _record(
        out,
        f"Per-country conditional bias by observed-value bucket at 48 h lead "
        f"for {VAR_TITLE[variable]} (debiased; cross-model mean, since the "
        f"cross-model spread is small — see the main-text envelope figure): "
        f"positive in the low tail, negative in the high tail in every "
        f"country — the regression-to-the-mean fingerprint. Gray cells have "
        f"no samples.",
    )


# ---------------------------------------------------------------- E
def fig_e_country_heatmaps(df: pl.DataFrame, variable: str) -> None:
    """Per-country skill heatmaps, two vertically stacked buckets per figure
    (three figures per variable), full print width."""
    base = _skill_base(df, "track_a").filter(
        (pl.col("variable") == variable) & pl.col("lead_hours").is_in([24.0, 48.0])
    )
    med = base.group_by(["model", "country", "obs_bucket"]).agg(
        (100 * pl.col("skill_full").median()).alias("skill_pct")
    )
    models = _ordered_models(med["model"].unique().to_list())

    grids: dict[str, np.ndarray] = {}
    for bucket in BUCKET_ORDER:
        grid = np.full((len(models), len(COUNTRIES)), np.nan)
        sub = med.filter(pl.col("obs_bucket") == bucket)
        for i, model in enumerate(models):
            for j, country in enumerate(COUNTRIES):
                row = sub.filter(
                    (pl.col("model") == model) & (pl.col("country") == country)
                )
                if row.height:
                    grid[i, j] = row["skill_pct"][0]
        grids[bucket] = grid

    # One symmetric color scale across all six buckets of the variable so the
    # three figures stay comparable.
    vmax = max(np.nanmax(np.abs(g)) for g in grids.values() if not np.all(np.isnan(g)))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad(NAN_GRAY)

    for idx, (top, bottom) in enumerate(COUNTRY_HEATMAP_PAIRS, start=1):
        fig, axes = plt.subplots(2, 1, figsize=(10, 10.5), constrained_layout=True)
        for ax, bucket in zip(axes, (top, bottom), strict=True):
            grid = grids[bucket]
            im = ax.imshow(
                np.ma.masked_invalid(grid),
                cmap=cmap,
                vmin=-vmax,
                vmax=vmax,
                aspect="auto",
            )
            ax.set_xticks(range(len(COUNTRIES)))
            ax.set_xticklabels(COUNTRIES)
            ax.set_yticks(range(len(models)))
            ax.set_yticklabels([DISPLAY.get(m, m) for m in models])
            ax.set_title(BUCKET_LABELS[bucket])
            ax.set_xlabel("Country")
            ax.grid(visible=False)
            for i in range(grid.shape[0]):
                for j in range(grid.shape[1]):
                    v = grid[i, j]
                    if np.isnan(v):
                        continue
                    color = "white" if abs(v) > 0.62 * vmax else "black"
                    ax.text(
                        j,
                        i,
                        f"{v:.1f}",
                        ha="center",
                        va="center",
                        fontsize=10,
                        color=color,
                    )
        cbar = fig.colorbar(im, ax=axes, shrink=0.75, pad=0.02)
        cbar.set_label("MAE improvement vs ECMWF IFS (%)")
        fig.suptitle(
            f"{VAR_TITLE[variable]} — per-country skill vs ECMWF IFS\n"
            "(median of 24 h and 48 h leads, debiased, Track A; gray = no samples)"
        )
        out = APPENDIX_DIR / f"appE_country_heatmap_{VAR_SHORT[variable]}_{idx}.png"
        fig.savefig(out)
        plt.close(fig)
        _record(
            out,
            f"Per-country MAE skill vs ECMWF IFS (\\%) for {VAR_TITLE[variable]} in "
            f"the {BUCKET_LABELS[top]} and {BUCKET_LABELS[bottom]} buckets "
            f"(median of 24 and 48 h leads, debiased; gray cells have no "
            f"samples; shared color scale across all six buckets).",
        )


# ---------------------------------------------------------------- tables
def _fmt(v: float | None) -> str:
    return "--" if v is None or not np.isfinite(v) else f"{v:+.1f}"


def _tabular(col_spec: str, header_rows: list[str], body_rows: list[str]) -> str:
    lines = [f"\\begin{{tabular}}{{{col_spec}}}", "\\toprule"]
    lines += header_rows
    lines.append("\\midrule")
    lines += body_rows
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def table_t1_europe_pooled(em: pl.DataFrame, variable: str) -> None:
    """Europe-pooled % MAE improvement vs IFS, sample-weighted over 24+48 h."""
    base = em.filter(
        (pl.col("track") == "track_a")
        & (pl.col("period_kind") == "full")
        & (pl.col("family") == "mean")
        & pl.col("debias")
        & (pl.col("metric") == "mae")
        & (pl.col("variable") == variable)
        & ((pl.col("prediction_timedelta") / 60).is_in([24.0, 48.0]))
    )
    # MAE pools linearly (sample-weighted), unlike the quadratic RMSE pooling.
    agg = base.group_by(["model", "obs_bucket"]).agg(
        (
            (pl.col("avg") * pl.col("sample_count")).sum()
            / pl.col("sample_count").sum()
        ).alias("mae")
    )
    ref = (
        agg.filter(pl.col("model") == REFERENCE)
        .rename({"mae": "mae_ref"})
        .drop("model")
    )
    skill = (
        agg.filter(pl.col("model") != REFERENCE)
        .join(ref, on="obs_bucket")
        .with_columns((100 * (1 - pl.col("mae") / pl.col("mae_ref"))).alias("pct"))
    )
    models = _ordered_models(skill["model"].unique().to_list())
    header = ["Model & " + " & ".join(BUCKET_TEX[b] for b in BUCKET_ORDER) + r" \\"]
    body = []
    for m in models:
        sub = skill.filter(pl.col("model") == m)
        lookup = dict(zip(sub["obs_bucket"], sub["pct"], strict=True))
        cells = " & ".join(_fmt(lookup.get(b)) for b in BUCKET_ORDER)
        body.append(f"{DISPLAY.get(m, m)} & {cells} \\\\")

    # ICON-EU has no Track A coverage (benchmark rows start Feb 2026); append
    # it from its own Track B window against the same IFS-matched sample,
    # marked with a dagger so the different window is explicit.
    trackb = em.filter(
        (pl.col("track") == "track_b")
        & (pl.col("period_kind") == "full")
        & (pl.col("family") == "mean")
        & pl.col("debias")
        & (pl.col("metric") == "mae")
        & (pl.col("variable") == variable)
        & ((pl.col("prediction_timedelta") / 60).is_in([24.0, 48.0]))
    )
    agg_b = trackb.group_by(["model", "obs_bucket"]).agg(
        (
            (pl.col("avg") * pl.col("sample_count")).sum()
            / pl.col("sample_count").sum()
        ).alias("mae")
    )
    ref_b = (
        agg_b.filter(pl.col("model") == REFERENCE)
        .rename({"mae": "mae_ref"})
        .drop("model")
    )
    icon_eu = (
        agg_b.filter(pl.col("model") == "icon_eu")
        .join(ref_b, on="obs_bucket")
        .with_columns((100 * (1 - pl.col("mae") / pl.col("mae_ref"))).alias("pct"))
    )
    if icon_eu.height:
        lookup = dict(zip(icon_eu["obs_bucket"], icon_eu["pct"], strict=True))
        cells = " & ".join(_fmt(lookup.get(b)) for b in BUCKET_ORDER)
        body.append(rf"DWD ICON-EU$^{{\dagger}}$ & {cells} \\")

    out = TABLES_DIR / f"europe_pooled_skill_{VAR_SHORT[variable]}.tex"
    out.write_text(_tabular("l" + "r" * len(BUCKET_ORDER), header, body))
    _record(
        out,
        f"Europe-pooled MAE improvement vs ECMWF IFS (\\%) per observed-value "
        f"bucket for {VAR_TITLE[variable]} (debiased, Track A, sample-weighted "
        f"over 24 and 48 h leads).",
    )


def table_t2_per_country_gt95(df: pl.DataFrame, variable: str) -> None:
    """Per-country % skill at gt_q95, median over 24/48 h leads."""
    base = _skill_base(df, "track_a").filter(
        (pl.col("variable") == variable)
        & (pl.col("obs_bucket") == "gt_q95")
        & pl.col("lead_hours").is_in([24.0, 48.0])
    )
    agg = base.group_by(["model", "country"]).agg(
        (100 * pl.col("skill_full").median()).alias("pct")
    )
    models = _ordered_models(agg["model"].unique().to_list())
    header = ["Model & " + " & ".join(COUNTRIES) + r" \\"]
    body = []
    for m in models:
        sub = agg.filter(pl.col("model") == m)
        lookup = dict(zip(sub["country"], sub["pct"], strict=True))
        cells = " & ".join(_fmt(lookup.get(c)) for c in COUNTRIES)
        body.append(f"{DISPLAY.get(m, m)} & {cells} \\\\")

    # ICON-EU from its own Track B window (no Track A coverage), dagger-marked.
    icon_b = _skill_base(df, "track_b").filter(
        (pl.col("variable") == variable)
        & (pl.col("obs_bucket") == "gt_q95")
        & pl.col("lead_hours").is_in([24.0, 48.0])
        & (pl.col("model") == "icon_eu")
    )
    if icon_b.height:
        agg_b = icon_b.group_by("country").agg(
            (100 * pl.col("skill_full").median()).alias("pct")
        )
        lookup = dict(zip(agg_b["country"], agg_b["pct"], strict=True))
        cells = " & ".join(_fmt(lookup.get(c)) for c in COUNTRIES)
        body.append(rf"DWD ICON-EU$^{{\dagger}}$ & {cells} \\")

    out = TABLES_DIR / f"per_country_gt95_{VAR_SHORT[variable]}.tex"
    out.write_text(_tabular("l" + "r" * len(COUNTRIES), header, body))
    _record(
        out,
        f"Per-country MAE skill vs ECMWF IFS (\\%) in the very-high (>P95) "
        f"bucket for {VAR_TITLE[variable]} (debiased, Track A, median over "
        f"24 and 48 h leads).",
    )


def table_t3_track_b() -> None:
    """Track B: regional models x buckets x both variables, Europe-pooled
    (sample-weighted) over the MATCHED 24-48 h lead range. Pooling different
    lead ranges per model (e.g. 24-120 h for ICON-EU vs 24-48 h for the
    48 h-horizon regionals) is not a like-for-like comparison and inflated
    the regionals' standing in an earlier revision."""
    em = pl.read_parquet(DERIVED_DIR / "europe_metrics.parquet")
    base = em.filter(
        (pl.col("track") == "track_b")
        & (pl.col("period_kind") == "full")
        & (pl.col("family") == "mean")
        & pl.col("debias")
        & (pl.col("metric") == "mae")
        & ((pl.col("prediction_timedelta") / 60) >= 24.0)
        & ((pl.col("prediction_timedelta") / 60) <= 48.0)
    )
    pooled = base.group_by(["model", "variable", "obs_bucket"]).agg(
        (
            (pl.col("avg") * pl.col("sample_count")).sum()
            / pl.col("sample_count").sum()
        ).alias("mae")
    )
    ref = (
        pooled.filter(pl.col("model") == REFERENCE)
        .rename({"mae": "mae_ref"})
        .drop("model")
    )
    agg = (
        pooled.filter(pl.col("model") != REFERENCE)
        .join(ref, on=["variable", "obs_bucket"])
        .with_columns((100 * (1 - pl.col("mae") / pl.col("mae_ref"))).alias("pct"))
    )
    n = len(BUCKET_ORDER)
    header = [
        r"& \multicolumn{"
        + str(n)
        + r"}{c}{"
        + VAR_TITLE[WIND]
        + r"} & \multicolumn{"
        + str(n)
        + r"}{c}{"
        + VAR_TITLE[TEMP]
        + r"} \\",
        rf"\cmidrule(lr){{2-{n + 1}}} \cmidrule(lr){{{n + 2}-{2 * n + 1}}}",
        "Model & "
        + " & ".join(BUCKET_TEX[b] for b in BUCKET_ORDER)
        + " & "
        + " & ".join(BUCKET_TEX[b] for b in BUCKET_ORDER)
        + r" \\",
    ]
    body = []
    for m in TRACK_B_MODELS:
        cells = []
        for variable in (WIND, TEMP):
            sub = agg.filter((pl.col("model") == m) & (pl.col("variable") == variable))
            lookup = dict(zip(sub["obs_bucket"], sub["pct"], strict=True))
            cells += [_fmt(lookup.get(b)) for b in BUCKET_ORDER]
        body.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + r" \\")
    out = TABLES_DIR / "track_b_skill.tex"
    out.write_text(_tabular("l" + "r" * (2 * n), header, body))
    _record(
        out,
        "Track B (regional window, Feb--May 2026): MAE skill vs ECMWF IFS (\\%) "
        "per observed-value bucket for both variables (debiased, Europe-pooled, "
        "sample-weighted over 24--48 h leads).",
    )


def write_manifest() -> None:
    lines = [
        "# Appendix figures & tables manifest",
        "",
        "Produced by `python scripts/figures_appendix.py`. "
        "One-sentence captions for LaTeX draft use.",
        "",
    ]
    for path, caption in manifest:
        lines.append(f"- `{path}` — {caption}")
    out = REPORTS_DIR / "figures_appendix_manifest.md"
    out.write_text("\n".join(lines) + "\n")
    print("wrote", out)


def main() -> None:
    apply_style()
    _bump_fonts()
    APPENDIX_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    skill = pl.read_parquet(DERIVED_DIR / "skill_vs_reference.parquet")
    europe = pl.read_parquet(DERIVED_DIR / "europe_metrics.parquet")
    fingerprint = pl.read_parquet(DERIVED_DIR / "fingerprint.parquet")

    for variable in (WIND, TEMP):
        for bucket in BUCKET_ORDER:
            fig_a1_skill_by_country(skill, variable, bucket)
    for variable in (WIND, TEMP):
        fig_a2_bucket_profile(skill, variable)
    fig_a3_sample_counts(skill)
    for variable in (WIND, TEMP):
        fig_a4_bias_heatmap(fingerprint, variable)
    for variable in (WIND, TEMP):
        fig_e_country_heatmaps(skill, variable)

    for variable in (WIND, TEMP):
        table_t1_europe_pooled(europe, variable)
        table_t2_per_country_gt95(skill, variable)
    table_t3_track_b()

    write_manifest()


if __name__ == "__main__":
    main()
