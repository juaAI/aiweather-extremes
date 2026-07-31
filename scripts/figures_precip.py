"""Precipitation figure and table set (parity with figures_v4.py).

Precipitation carries wet-hour climatological regimes (dry mass + ERA5
1991-2020 wet-hour percentile bands) rather than the symmetric lt_q5..gt_q95 of
the unbounded variables, so it gets its own module instead of being forced
through the shared bucket order. All continuous skill comes from
``final_aggregates{variant}.parquet`` (kind='skill_pct', MAE-based, debiased);
categorical exceedance scores come from ``precip_categorical.parquet``.

Outputs (figures/ and paper/tables/):
* figp1_precip_bars.png       Track A regime skill bars, 1-48 h
* figp1b_precip_bars_1_12.png Track A regime skill bars, 1-12 h
* figp2_precip_lead.png       Track A skill vs lead (all | heavy >P95)
* figp5_precip_categorical.png >P95 detection: CSI and frequency bias
* figp6_precip_track_b.png    Track B regional regime skill bars
* figp7_precip_track_b_lead.png Track B skill vs lead (all | heavy >P95)
* tp1_precip_skill.tex        Track A regime skill table (with SE)
* tp1b_precip_skill_1_12.tex  Track A 1-12 h regime skill table
* tp2_precip_track_b.tex      Track B regime skill table
* tp3_precip_categorical.tex  >P95 POD/FAR/CSI/freq-bias table
* tp4_precip_track_b_lead.tex Track B per-lead skill table

Run:  python scripts/figures_precip.py
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.patches import Patch

from style import (
    COLORS,
    DISPLAY,
    LINESTYLES,
    MARKERS,
    PRECIP,
    PRECIP_BUCKET_LABELS,
    PRECIP_BUCKET_ORDER,
    PRECIP_BUCKET_TEX,
    REFERENCE,
    SAVE_DPI,
    VAR_TITLE,
    apply_style,
    model_legend_handles,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIGURES = REPO_ROOT / "figures"
TABLES = REPO_ROOT / "paper" / "tables"
DERIVED = REPO_ROOT / "data" / "derived"
VARIANT_SUFFIX = os.environ.get("EXTREMES_VARIANT", "")
SKILL_LABEL = "MAE skill vs ECMWF IFS (%)"

# Precip model order (excludes aifs/aurora, which emit no precipitation).
# Reference last.
PRECIP_MODELS = [
    "ept2_reasoning",
    "ept2_hrrr",
    "ept2_e",
    "ept2_1_europa",
    "ecmwf_ens",
    "noaa_gfs_single",
    "icon_global",
    "ecmwf_ifs_single",
]
TRACK_B_MODELS = ["ept2_1_europa", "ept2_hrrr", "icon_eu"]
SINGLE_LEADS = [6, 12, 24, 48]

# Regimes shown in the headline bars/heatmap (dry mass omitted -- its skill is a
# ratio of ~0.05 mm errors and not the story; it is in the table instead).
WET_BARS = ["all", "wet_lt_p50", "p50_p75", "p75_p95", "gt_p95"]
BAR_ALPHAS = {
    "all": 0.30,
    "wet_lt_p50": 0.48,
    "p50_p75": 0.64,
    "p75_p95": 0.82,
    "gt_p95": 1.0,
}


def _derived(stem: str) -> Path:
    return DERIVED / f"{stem}{VARIANT_SUFFIX}.parquet"


_DATA: pl.DataFrame | None = None


def _data() -> pl.DataFrame:
    global _DATA
    if _DATA is None:
        _DATA = pl.read_parquet(_derived("final_aggregates")).filter(
            (pl.col("variable") == PRECIP) & pl.col("debias")
        )
    return _DATA


def _val(
    track: str, kind: str, scope: str, bucket: str, model: str,
    country: str | None = None,
) -> tuple[float | None, float | None]:
    f = _data().filter(
        (pl.col("track") == track)
        & (pl.col("kind") == kind)
        & (pl.col("lead_scope") == scope)
        & (pl.col("obs_bucket") == bucket)
        & (pl.col("model") == model)
    )
    if country is not None:
        f = f.filter(pl.col("country") == country)
    if f.height == 0:
        return None, None
    r = f.row(0, named=True)
    return r["value"], r.get("skill_se")


def _models(track: str, scope: str, order: list[str]) -> list[str]:
    avail = set(
        _data()
        .filter(
            (pl.col("track") == track)
            & (pl.col("kind") == "skill_pct")
            & (pl.col("lead_scope") == scope)
            & (pl.col("obs_bucket") == "all")
        )["model"]
        .to_list()
    )
    return [m for m in order if m in avail and m != REFERENCE]


def _save(fig, path: Path, **kwargs) -> None:
    FIGURES.mkdir(exist_ok=True)
    fig.savefig(path, dpi=SAVE_DPI, **kwargs)
    plt.close(fig)
    print("wrote", path)


# ---------------------------------------------------------------------------
# Categorical (>P95 exceedance) skill from the 2x2 contingency table.
# ---------------------------------------------------------------------------


def _categorical(track: str, max_lead_h: int = 48, debias: bool = True) -> pl.DataFrame:
    cat = pl.read_parquet(DERIVED / "precip_categorical.parquet")
    c = cat.filter(
        (pl.col("track") == track)
        & (pl.col("period_kind") == "full")
        & (pl.col("debias") == debias)
        & (pl.col("prediction_timedelta") <= max_lead_h * 60)
    )
    agg = c.group_by("model").agg(
        pl.col("hits").sum(),
        pl.col("false_alarms").sum(),
        pl.col("misses").sum(),
        pl.col("correct_negatives").sum(),
    )
    return agg.with_columns(
        (pl.col("hits") / (pl.col("hits") + pl.col("misses"))).alias("pod"),
        (pl.col("false_alarms") / (pl.col("hits") + pl.col("false_alarms"))).alias(
            "far"
        ),
        (
            pl.col("hits")
            / (pl.col("hits") + pl.col("misses") + pl.col("false_alarms"))
        ).alias("csi"),
        (
            (pl.col("hits") + pl.col("false_alarms"))
            / (pl.col("hits") + pl.col("misses"))
        ).alias("freq_bias"),
    )


# ---------------------------------------------------------------------------
# FIGP1 — Track A regime skill bars
# ---------------------------------------------------------------------------


def _bar_panel(ax, order, values, title) -> None:
    x = np.arange(len(order))
    n_b = len(WET_BARS)
    width = 0.16
    lo_all = hi_all = 0.0
    for k, bucket in enumerate(WET_BARS):
        for j, m in enumerate(order):
            v, se = values.get((m, bucket), (None, None))
            if v is None:
                continue
            se = se or 0.0
            xpos = j + (k - (n_b - 1) / 2) * width
            ax.bar(
                xpos, v, width, color=COLORS.get(m, "gray"),
                alpha=BAR_ALPHAS[bucket], yerr=se, capsize=1.2,
                error_kw={"lw": 0.6, "ecolor": "0.25"},
                edgecolor="white", linewidth=0.3,
            )
            ytxt = v + se + 0.3 if v >= 0 else v - se - 0.3
            ax.text(
                xpos, ytxt, f"{v:+.1f}", ha="center",
                va="bottom" if v >= 0 else "top", fontsize=5, rotation=90,
                color="0.2", clip_on=False,
            )
            lo_all = min(lo_all, ytxt if v < 0 else v - se)
            hi_all = max(hi_all, ytxt if v >= 0 else v + se)
    ax.axhline(0, color="k", lw=1)
    ax.set_ylim(lo_all - 4.5, hi_all + 4.5)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [DISPLAY.get(m, m) for m in order], rotation=28, ha="right", fontsize=6.5
    )
    ax.tick_params(axis="y", labelsize=5.5)
    ax.set_ylabel(SKILL_LABEL, fontsize=8)
    ax.set_title(title, fontsize=9)
    ax.legend(
        handles=[
            Patch(facecolor="gray", alpha=BAR_ALPHAS[b], label=PRECIP_BUCKET_LABELS[b])
            for b in WET_BARS
        ],
        fontsize=6, loc="upper right", ncol=3, handlelength=1.2,
        columnspacing=0.8, borderaxespad=0.3,
    )


def _bar_values(track, scope, order):
    all_sk = {m: _val(track, "skill_pct", scope, "all", m)[0] for m in order}
    all_sk = {m: v for m, v in all_sk.items() if v is not None}
    ordered = sorted(all_sk, key=lambda m: -all_sk[m])
    values = {
        (m, b): _val(track, "skill_pct", scope, b, m)
        for m in ordered
        for b in WET_BARS
    }
    return ordered, values


def figp1() -> None:
    order = _models("track_a", "h1_48", PRECIP_MODELS)
    ordered, values = _bar_values("track_a", "h1_48", order)
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    _bar_panel(
        ax, ordered, values,
        f"{VAR_TITLE[PRECIP]}: Track A MAE skill by wet-hour regime, 1\u201348 h",
    )
    fig.tight_layout()
    _save(fig, FIGURES / "figp1_precip_bars.png")


def figp1b() -> None:
    """Track A short-range companion to figp1, pooled over 1--12 h."""
    order = _models("track_a", "h1_12", PRECIP_MODELS)
    ordered, values = _bar_values("track_a", "h1_12", order)
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    _bar_panel(
        ax,
        ordered,
        values,
        f"{VAR_TITLE[PRECIP]}: Track A MAE skill by wet-hour regime, 1–12 h",
    )
    fig.tight_layout()
    _save(fig, FIGURES / "figp1b_precip_bars_1_12.png")


# ---------------------------------------------------------------------------
# FIGP2 — skill vs lead
# ---------------------------------------------------------------------------


def _band(ax, x, vals, ses, model):
    xs = [xi for xi, v in zip(x, vals, strict=False) if v is not None]
    ys = [v for v in vals if v is not None]
    if not ys:
        return
    ax.plot(
        xs, ys, marker=MARKERS.get(model, "o"), ms=3.4, lw=1.8,
        linestyle=LINESTYLES.get(model, "-"), color=COLORS.get(model, "gray"),
        label=DISPLAY.get(model, model),
    )
    band = [(v, s) for v, s in zip(vals, ses, strict=False) if v is not None and s is not None]
    if len(band) == len(ys):
        ax.fill_between(
            xs, [v - s for v, s in band], [v + s for v, s in band],
            color=COLORS.get(model, "gray"), alpha=0.13, lw=0,
        )


def figp2() -> None:
    order = _models("track_a", "h1_48", PRECIP_MODELS)
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.4), sharey=True)
    for j, bucket in enumerate(["all", "gt_p95"]):
        ax = axes[j]
        for m in order:
            vals, ses = [], []
            for h in SINGLE_LEADS:
                v, s = _val("track_a", "skill_pct", f"lead_{h}", bucket, m)
                vals.append(v)
                ses.append(s)
            _band(ax, SINGLE_LEADS, vals, ses, m)
        ax.axhline(0, color="k", lw=0.9, ls="--")
        ax.set_xticks(SINGLE_LEADS)
        ax.set_title(PRECIP_BUCKET_LABELS[bucket], fontsize=9)
        ax.set_xlabel("Lead time (h)")
        if j == 0:
            ax.set_ylabel(SKILL_LABEL)
    handles = model_legend_handles(order, ncol=3)
    fig.legend(
        handles=handles, loc="lower center", ncol=3, fontsize=7,
        bbox_to_anchor=(0.5, 0.01), columnspacing=1.1, handlelength=3.2,
        handletextpad=0.6,
    )
    fig.suptitle(
        f"{VAR_TITLE[PRECIP]}: MAE skill vs ECMWF IFS by lead (debiased)",
        fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0.18, 1, 0.97))
    _save(fig, FIGURES / "figp2_precip_lead.png")


# ---------------------------------------------------------------------------
# FIGP5 — >P95 detection: CSI and frequency bias
# ---------------------------------------------------------------------------


def figp5() -> None:
    cat = _categorical("track_a").to_dict(as_series=False)
    by_model = {
        cat["model"][i]: (cat["csi"][i], cat["freq_bias"][i], cat["pod"][i], cat["far"][i])
        for i in range(len(cat["model"]))
    }
    order = [m for m in PRECIP_MODELS if m in by_model]
    order = sorted(order, key=lambda m: -by_model[m][0])
    x = np.arange(len(order))
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 3.6))
    # CSI
    ax = axes[0]
    ax.bar(x, [by_model[m][0] for m in order], color=[COLORS.get(m, "gray") for m in order])
    ax.axhline(by_model.get(REFERENCE, (None,))[0], color="k", lw=1, ls="--", label="ECMWF IFS")
    ax.set_xticks(x)
    ax.set_xticklabels([DISPLAY.get(m, m) for m in order], rotation=35, ha="right", fontsize=6.5)
    ax.set_ylabel("Critical success index", fontsize=8.5)
    ax.set_title("Heavy-precip (>P95) detection skill", fontsize=9)
    ax.legend(fontsize=7)
    # frequency bias
    ax = axes[1]
    ax.bar(x, [by_model[m][1] for m in order], color=[COLORS.get(m, "gray") for m in order])
    ax.axhline(1.0, color="k", lw=1, ls="--", label="perfect (1.0)")
    ax.set_xticks(x)
    ax.set_xticklabels([DISPLAY.get(m, m) for m in order], rotation=35, ha="right", fontsize=6.5)
    ax.set_ylabel("Frequency bias (events fc / obs)", fontsize=8.5)
    ax.set_title("Heavy-precip (>P95) frequency bias", fontsize=9)
    ax.legend(fontsize=7)
    fig.suptitle(
        f"{VAR_TITLE[PRECIP]}: heavy-precip exceedance, Track A 1\u201348 h (debiased)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _save(fig, FIGURES / "figp5_precip_categorical.png")


# ---------------------------------------------------------------------------
# FIGP6 — Track B regional regime bars
# ---------------------------------------------------------------------------


def figp6() -> None:
    order = _models("track_b", "h1_48", ["ept2_1_europa", "ept2_hrrr", "icon_eu"])
    if not order:
        print("skip figp6: no Track B precip rows")
        return
    ordered, values = _bar_values("track_b", "h1_48", order)
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    _bar_panel(
        ax, ordered, values,
        f"{VAR_TITLE[PRECIP]}: Track B (Mar\u2013Jun) regional skill by regime, 1\u201348 h",
    )
    fig.tight_layout()
    _save(fig, FIGURES / "figp6_precip_track_b.png")


# ---------------------------------------------------------------------------
# FIGP7 — Track B regional skill vs lead
# ---------------------------------------------------------------------------


def figp7() -> None:
    order = _models("track_b", "h1_48", TRACK_B_MODELS)
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.4), sharey=True)
    for j, bucket in enumerate(["all", "gt_p95"]):
        ax = axes[j]
        for m in order:
            vals, ses = [], []
            for h in SINGLE_LEADS:
                v, s = _val("track_b", "skill_pct", f"lead_{h}", bucket, m)
                vals.append(v)
                ses.append(s)
            _band(ax, SINGLE_LEADS, vals, ses, m)
        ax.axhline(0, color="k", lw=0.9, ls="--")
        ax.set_xticks(SINGLE_LEADS)
        ax.set_title(PRECIP_BUCKET_LABELS[bucket], fontsize=9)
        ax.set_xlabel("Lead time (h)")
        if j == 0:
            ax.set_ylabel(SKILL_LABEL)
    handles = model_legend_handles(order, ncol=3)
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=3,
        fontsize=7,
        bbox_to_anchor=(0.5, 0.01),
        columnspacing=1.1,
        handlelength=3.2,
        handletextpad=0.6,
    )
    fig.suptitle(
        f"{VAR_TITLE[PRECIP]}: Track B regional skill vs lead (debiased)",
        fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0.18, 1, 0.97))
    _save(fig, FIGURES / "figp7_precip_track_b_lead.png")


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _fmt(v: float | None, se: float | None = None) -> str:
    if v is None:
        return "--"
    s = f"{v:+.1f}"
    if se is not None:
        s += f" ($\\pm${se:.1f})"
    return s


def _write_table(name: str, lines: list[str]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / name).write_text("\n".join(lines) + "\n")
    print(f"wrote table {name}")


def tp1() -> None:
    """Track A 1--48 h regime skill with SE."""
    order = _models("track_a", "h1_48", PRECIP_MODELS)
    lines = [
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        "Model & " + " & ".join(PRECIP_BUCKET_TEX[b] for b in PRECIP_BUCKET_ORDER) + " \\\\",
        "\\midrule",
    ]
    for m in order:
        cells = [_fmt(*_val("track_a", "skill_pct", "h1_48", b, m)) for b in PRECIP_BUCKET_ORDER]
        lines.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table("tp1_precip_skill.tex", lines)


def tp1b() -> None:
    """Track A 1--12 h regime skill with SE."""
    order = _models("track_a", "h1_12", PRECIP_MODELS)
    lines = [
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        "Model & " + " & ".join(PRECIP_BUCKET_TEX[b] for b in PRECIP_BUCKET_ORDER) + " \\\\",
        "\\midrule",
    ]
    for m in order:
        cells = [
            _fmt(*_val("track_a", "skill_pct", "h1_12", b, m))
            for b in PRECIP_BUCKET_ORDER
        ]
        lines.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table("tp1b_precip_skill_1_12.tex", lines)


def tp2() -> None:
    """Track B regime skill."""
    order = _models("track_b", "h1_48", ["ept2_1_europa", "ept2_hrrr", "icon_eu"])
    lines = [
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        "Model & " + " & ".join(PRECIP_BUCKET_TEX[b] for b in PRECIP_BUCKET_ORDER) + " \\\\",
        "\\midrule",
    ]
    for m in order:
        cells = [_fmt(*_val("track_b", "skill_pct", "h1_48", b, m)) for b in PRECIP_BUCKET_ORDER]
        lines.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table("tp2_precip_track_b.tex", lines)


def tp3() -> None:
    """Track A >P95 detection: POD/FAR/CSI/frequency bias."""
    cat = _categorical("track_a")
    by = {r["model"]: r for r in cat.iter_rows(named=True)}
    order = [m for m in PRECIP_MODELS if m in by]
    order = sorted(order, key=lambda m: -by[m]["csi"])
    lines = [
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Model & POD & FAR & CSI & Freq.\\ bias \\\\",
        "\\midrule",
    ]
    for m in order:
        r = by[m]
        lines.append(
            f"{DISPLAY.get(m, m)} & {r['pod']:.2f} & {r['far']:.2f} & "
            f"{r['csi']:.2f} & {r['freq_bias']:.2f} \\\\"
        )
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table("tp3_precip_categorical.tex", lines)


def tp4() -> None:
    """Track B per-lead all-conditions and heavy-tail skill."""
    order = _models("track_b", "h1_48", TRACK_B_MODELS)
    lines = [
        "\\begin{tabular}{@{}l*{8}{r}@{}}",
        "\\toprule",
        "& "
        + " & ".join(
            f"\\multicolumn{{2}}{{c}}{{{h}\\,h}}" for h in SINGLE_LEADS
        )
        + " \\\\",
        " ".join(
            f"\\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}"
            for i in range(len(SINGLE_LEADS))
        ),
        "Model & " + " & ".join(["All & $>$P95"] * len(SINGLE_LEADS)) + " \\\\",
        "\\midrule",
    ]
    for m in order:
        cells = []
        for h in SINGLE_LEADS:
            for bucket in ("all", "gt_p95"):
                value, _ = _val(
                    "track_b", "skill_pct", f"lead_{h}", bucket, m
                )
                cells.append(_fmt(value))
        lines.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table("tp4_precip_track_b_lead.tex", lines)


def main() -> None:
    apply_style()
    FIGURES.mkdir(exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    figp1()
    figp1b()
    figp2()
    figp5()
    figp6()
    figp7()
    tp1()
    tp1b()
    tp2()
    tp3()
    tp4()
    print("precip figures ->", FIGURES)
    print("precip tables ->", TABLES)


if __name__ == "__main__":
    main()
