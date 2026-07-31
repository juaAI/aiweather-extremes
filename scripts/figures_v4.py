"""Final main-paper figure and table set (v4).

Single data source: ``data/derived/final_aggregates.parquet`` (schema and
pooling rules in ``scripts/aggregates.py``). Everything shown is
debiased and uses LOCAL per-country percentile regimes pooled across
countries — the paper's only extremes definition.

Primary metric everywhere: MAE-based skill vs ECMWF IFS (kind='skill_pct');
RMSE-based skill (kind='skill_pct_rmse') only feeds the appendix table t6.

Schema limits handled here (documented, not bugs):
* Per-lead skill rows exist only at the single leads 6/12/24/48 h (solar
  also 1 h). F2/F8 plot single leads as marker-lines in a 1×2 layout
  (all conditions | tail or typical); no pooled-horizon panel.
* Track A dual-horizon bars (fig3 / fig3_short): 
  ``data/derived/headline_skill_track_a.parquet`` from
  ``scripts/fig_horizon_headlines.py`` (6–48 h and 1–12 h).
* Track B bars: ``wt_headline_skill_track_b.parquet`` +
  ``solar_headline_skill_track_b.parquet``.

Run:  python scripts/figures_v4.py
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.patches import Patch

from qe_client import PROJECT_ROOT
from style import (
    BUCKET_LABELS,
    BUCKET_ORDER,
    COLORS,
    LINESTYLES,
    MARKERS,
    DISPLAY,
    MODEL_ORDER,
    PRECIP,
    PRECIP_BUCKET_ORDER,
    PRECIP_BUCKET_SHORT,
    REFERENCE,
    SAVE_DPI,
    SOLAR,
    TEMP,
    VAR_TITLE,
    VAR_UNIT,
    VAR_SHORT,
    WIND,
    apply_style,
    COUNTRIES,
    model_legend_handles,
)

# Repo root (qe_client.PROJECT_ROOT is parents[2] — one level above the repo).
REPO_ROOT = Path(__file__).resolve().parents[1]
FIGURES = REPO_ROOT / "figures"

# Active regime definition. Empty means the in-window percentiles shipped with
# the aggregates; "_climatology" selects the ERA5 1991-2020 threshold variant
# built by extract_climatology_metrics.py. Figures are always written to their
# canonical names so the paper does not need per-variant includes.
VARIANT_SUFFIX = os.environ.get("EXTREMES_VARIANT", "")


def _derived(stem: str) -> Path:
    return REPO_ROOT / "data" / "derived" / f"{stem}{VARIANT_SUFFIX}.parquet"
TABLES = REPO_ROOT / "paper" / "tables"
SKILL_LABEL = "MAE skill vs ECMWF IFS (%)"


def _save(fig, path: Path, **kwargs) -> None:
    """savefig with fixed DPI so helpers stay sharp even without apply_style()."""
    fig.savefig(path, dpi=SAVE_DPI, **kwargs)
# MODEL_ORDER lacks the solar-only ept2_1_helios; track_c needs it first.
# (The raw track_c extraction still carries legacy 'ept2' rows; keeping the
# ordering here restricted to SOLAR_ORDER excludes them from every output.)
SOLAR_ORDER = ["ept2_1_helios", *MODEL_ORDER]
# Track C coverage: GB/IT/PL have no solar station obs.
SOLAR_COUNTRIES = [c for c in COUNTRIES if c not in ("GB", "IT", "PL")]
SOLAR_WINDOW = "20 Mar\u201315 Jun"
SINGLE_LEADS = [6, 12, 24, 48]
TRACK_B_MODELS = ["ept2_1_europa", "ept2_hrrr", "icon_eu"]
DAGGER = "$^{\\dagger}$"

# Compact one-line regime labels (rotated tick labels on narrow panels).
BUCKET_SHORT = {
    "all": "all",
    "lt_q5": "<P5",
    "q5_q25": "P5\u201325",
    "q25_q75": "P25\u201375",
    "q75_q95": "P75\u201395",
    "gt_q95": ">P95",
}
# Two-line regime labels for categorical axes ("All conditions" -> two lines).
BUCKET_2L = {
    b: BUCKET_LABELS[b].replace(" (", "\n(")
    if "(" in BUCKET_LABELS[b]
    else "All\nconditions"
    for b in BUCKET_ORDER
}
# LaTeX column heads for regimes.
BUCKET_TEX = {
    "all": "All",
    "lt_q5": "$<$P5",
    "q5_q25": "P5--25",
    "q25_q75": "P25--75",
    "q75_q95": "P75--95",
    "gt_q95": "$>$P95",
}


@functools.cache
def _data() -> pl.DataFrame:
    return pl.read_parquet(
        _derived("final_aggregates")
    ).filter(pl.col("debias"))


def _sel(
    track: str,
    kind: str,
    variable: str,
    scope: str | None = None,
    bucket: str | None = None,
    model: str | None = None,
    country: str | None = None,
) -> pl.DataFrame:
    f = _data().filter(
        (pl.col("track") == track)
        & (pl.col("kind") == kind)
        & (pl.col("variable") == variable)
    )
    if scope is not None:
        f = f.filter(pl.col("lead_scope") == scope)
    if bucket is not None:
        f = f.filter(pl.col("obs_bucket") == bucket)
    if model is not None:
        f = f.filter(pl.col("model") == model)
    if country is not None:
        f = f.filter(pl.col("country") == country)
    return f


def _val(
    track: str,
    kind: str,
    variable: str,
    scope: str,
    bucket: str,
    model: str,
    country: str | None = None,
) -> tuple[float | None, float | None]:
    """(value, skill_se) or (None, None) when the cell is absent."""
    f = _sel(track, kind, variable, scope, bucket, model, country)
    if f.height == 0:
        return None, None
    r = f.row(0, named=True)
    return r["value"], r["skill_se"]


def _models(
    track: str,
    variable: str,
    scope: str,
    kind: str = "skill_pct",
    bucket: str = "all",
    order: list[str] | None = None,
) -> list[str]:
    avail = set(_sel(track, kind, variable, scope, bucket)["model"].to_list())
    return [m for m in (order or MODEL_ORDER) if m in avail]


def _lead_series(
    track: str, variable: str, bucket: str, model: str
) -> tuple[list[float | None], list[float | None]]:
    vals, ses = [], []
    for h in SINGLE_LEADS:
        v, s = _val(track, "skill_pct", variable, f"lead_{h}", bucket, model)
        vals.append(v)
        ses.append(s)
    return vals, ses


def _band(ax, x, vals, ses, model, marker=None, ms=3.2, lw=1.8):
    xs = [xi for xi, v in zip(x, vals, strict=False) if v is not None]
    ys = [v for v in vals if v is not None]
    if not ys:
        return
    ax.plot(
        xs,
        ys,
        marker=marker or MARKERS.get(model, "o"),
        ms=ms,
        lw=lw,
        linestyle=LINESTYLES.get(model, "-"),
        color=COLORS.get(model, "gray"),
        label=DISPLAY.get(model, model),
    )
    band = [
        (v, s)
        for v, s in zip(vals, ses, strict=False)
        if v is not None and s is not None
    ]
    if len(band) == len(ys):
        lo = [v - s for v, s in band]
        hi = [v + s for v, s in band]
        ax.fill_between(xs, lo, hi, color=COLORS.get(model, "gray"), alpha=0.13, lw=0)


# ---------------------------------------------------------------------------
# F2 — skill vs lead, 2x2 per variable
# ---------------------------------------------------------------------------


def fig2(variable: str) -> None:
    """Track A wind/temp skill vs lead — Track B layout: all | >P95 side by side.

    Single leads only (6/12/24/48 h); no long-horizon pooled panel.
    """
    models = _models("track_a", variable, "h6_48")
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.4), sharey=True)
    for j, bucket in enumerate(["all", "gt_q95"]):
        ax = axes[j]
        for m in models:
            vals, ses = _lead_series("track_a", variable, bucket, m)
            _band(ax, SINGLE_LEADS, vals, ses, m)
        ax.axhline(0, color="k", lw=0.9, ls="--")
        ax.set_xticks(SINGLE_LEADS)
        ax.set_title(BUCKET_LABELS[bucket], fontsize=9)
        ax.set_xlabel("Lead time (h)")
        if j == 0:
            ax.set_ylabel(SKILL_LABEL)
    handles = model_legend_handles(models, ncol=3)
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
        f"{VAR_TITLE[variable]}: MAE skill vs ECMWF IFS by lead (debiased)",
        fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0.18, 1, 0.97))
    _save(fig, FIGURES / f"fig2_skill_vs_lead_{VAR_SHORT[variable]}.png")
    plt.close(fig)
    print("wrote", FIGURES / f"fig2_skill_vs_lead_{VAR_SHORT[variable]}.png")


SOLAR_LEADS = _derived("solar_lead_skill_track_a")
SOLAR_LEAD_H = [1, 6, 12, 24, 48]


def fig2_solar() -> None:
    """Track A solar skill vs lead — Track B layout: all | typical side by side.

    Single leads only (1/6/12/24/48 h); no pooled-horizon panel.
    Rebuild data: scripts/fig_solar_leads.py
    """
    if not SOLAR_LEADS.exists():
        raise FileNotFoundError(
            f"Missing {SOLAR_LEADS}; run scripts/fig_solar_leads.py"
        )
    df = pl.read_parquet(SOLAR_LEADS)
    models = sorted(
        df.filter((pl.col("obs_bucket") == "all") & (pl.col("lead_h") == 6))[
            "model"
        ].to_list(),
        key=lambda m: -(
            df.filter(
                (pl.col("model") == m)
                & (pl.col("obs_bucket") == "all")
                & (pl.col("lead_h") == 6)
            )["skill"][0]
        ),
    )

    def _series(model: str, bucket: str, leads: list[int]):
        vals, ses = [], []
        for h in leads:
            r = df.filter(
                (pl.col("model") == model)
                & (pl.col("obs_bucket") == bucket)
                & (pl.col("lead_h") == h)
            )
            if r.height:
                vals.append(r["skill"][0])
                ses.append(r["skill_se"][0])
            else:
                vals.append(None)
                ses.append(None)
        return vals, ses

    # Right panel: the overcast tail (P5-25), where Helios's specialisation is
    # strongly positive at every lead. The typical band (P25-75) -- Helios's one
    # weak solar regime -- is reported in the regime tables, not this headline.
    panel = {"all": "All conditions", "q5_q25": "Overcast (P5\u201325)"}
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.4), sharey=True)
    for j, bucket in enumerate(["all", "q5_q25"]):
        ax = axes[j]
        for m in models:
            vals, ses = _series(m, bucket, SOLAR_LEAD_H)
            _band(ax, SOLAR_LEAD_H, vals, ses, m)
        ax.axhline(0, color="k", lw=0.9, ls="--")
        ax.set_xticks(SOLAR_LEAD_H)
        ax.set_title(panel[bucket], fontsize=9)
        ax.set_xlabel("Lead time (h)")
        if j == 0:
            ax.set_ylabel(SKILL_LABEL)

    handles = model_legend_handles(models, ncol=3)
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
        f"{VAR_TITLE[SOLAR]}: MAE skill vs ECMWF IFS by lead (debiased)",
        fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0.18, 1, 0.97))
    out = FIGURES / "fig2_skill_vs_lead_solar.png"
    _save(fig, out)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------
# F3 — headline bars, h6_48
# ---------------------------------------------------------------------------

F3_BUCKETS = ["all", "lt_q5", "q5_q25", "q25_q75", "q75_q95", "gt_q95"]
F3_ALPHAS = {
    "all": 0.30,
    "lt_q5": 0.44,
    "q5_q25": 0.57,
    "q25_q75": 0.70,
    "q75_q95": 0.85,
    "gt_q95": 1.0,
}
# Headline skill parquets from scripts/fig_horizon_headlines.py
HEADLINE_A = _derived("headline_skill_track_a")
HEADLINE_B = _derived("headline_skill_track_b")
# Legacy fallbacks.
SOLAR_HEADLINE_B = _derived("solar_headline_skill_track_b")
WT_HEADLINE_B = _derived("wt_headline_skill_track_b")
SOLAR_HEADLINE = _derived("solar_headline_skill")
WT_HEADLINE = _derived("wt_headline_skill_track_a")


def _fig3_panel(
    ax,
    order: list[str],
    values: dict[tuple[str, str], tuple[float | None, float | None]],
    title: str,
) -> None:
    """Shared bar panel: values[(model, bucket)] -> (skill, se)."""
    x = np.arange(len(order))
    n_b = len(F3_BUCKETS)
    width = 0.9 / n_b
    lo_all, hi_all = 0.0, 0.0
    for k, bucket in enumerate(F3_BUCKETS):
        for j, m in enumerate(order):
            v, se = values.get((m, bucket), (None, None))
            if v is None:
                continue
            se = se or 0.0
            xpos = j + (k - (n_b - 1) / 2) * width
            ax.bar(
                xpos,
                v,
                width,
                color=COLORS.get(m, "gray"),
                alpha=F3_ALPHAS[bucket],
                yerr=se,
                capsize=1.2,
                error_kw={"lw": 0.6, "ecolor": "0.25"},
                edgecolor="white",
                linewidth=0.3,
            )
            # Value label tight on the whisker (original fig3 style — no flying offsets).
            pad = 0.35
            ytxt = v + se + pad if v >= 0 else v - se - pad
            ax.text(
                xpos,
                ytxt,
                f"{v:+.1f}",
                ha="center",
                va="bottom" if v >= 0 else "top",
                fontsize=5,
                rotation=90,
                color="0.2",
                clip_on=False,
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
            Patch(facecolor="gray", alpha=F3_ALPHAS[b], label=BUCKET_LABELS[b])
            for b in F3_BUCKETS
        ],
        fontsize=6,
        loc="upper right",
        ncol=3,
        handlelength=1.2,
        columnspacing=0.8,
        borderaxespad=0.3,
    )


def _values_from_df(
    df: pl.DataFrame, model_order: list[str] | None = None
) -> tuple[list[str], dict[tuple[str, str], tuple]]:
    all_sk = {
        r["model"]: r["skill"]
        for r in df.filter(pl.col("obs_bucket") == "all").iter_rows(named=True)
    }
    if model_order:
        order = [m for m in model_order if m in all_sk]
        order += sorted(
            (m for m in all_sk if m not in order), key=lambda m: -all_sk[m]
        )
    else:
        order = sorted(all_sk, key=lambda m: -all_sk[m])
    values = {
        (r["model"], r["obs_bucket"]): (r["skill"], r["skill_se"])
        for r in df.iter_rows(named=True)
    }
    return order, values


def _solar_headline_values(
    path: Path,
) -> tuple[list[str], dict[tuple[str, str], tuple]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    return _values_from_df(pl.read_parquet(path))


def _wt_headline_values(
    path: Path, variable: str, model_order: list[str] | None = None
) -> tuple[list[str], dict[tuple[str, str], tuple]]:
    return _values_from_df(
        pl.read_parquet(path).filter(pl.col("variable") == variable), model_order
    )


def _headline_track_values(
    path: Path,
    lead_scope: str,
    variable: str,
    *,
    model_order: list[str] | None = None,
) -> tuple[list[str], dict[tuple[str, str], tuple]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}; run scripts/fig_horizon_headlines.py"
        )
    df = pl.read_parquet(path).filter(
        (pl.col("lead_scope") == lead_scope) & (pl.col("variable") == variable)
    )
    if df.is_empty():
        raise FileNotFoundError(f"No rows for {lead_scope}/{variable} in {path}")
    return _values_from_df(df, model_order)


def _headline_a_values(
    lead_scope: str, variable: str
) -> tuple[list[str], dict[tuple[str, str], tuple]]:
    if HEADLINE_A.exists():
        try:
            return _headline_track_values(HEADLINE_A, lead_scope, variable)
        except FileNotFoundError:
            pass
    if variable == SOLAR:
        return _solar_headline_values(SOLAR_HEADLINE)
    if WT_HEADLINE.exists():
        return _wt_headline_values(WT_HEADLINE, variable)
    raise FileNotFoundError(
        f"No Track A headline data for {lead_scope}/{variable}; "
        "run scripts/fig_horizon_headlines.py"
    )


def _headline_bars_from_values(
    out_name: str,
    panels: list[tuple[str, list[str], dict, str]],
) -> None:
    """panels: (title, order, values, panel_title)."""
    fig, axes = plt.subplots(len(panels), 1, figsize=(6.6, 3.4 * len(panels)))
    if len(panels) == 1:
        axes = [axes]
    for ax, (_key, order, values, title) in zip(axes, panels, strict=True):
        _fig3_panel(ax, order, values, title)
    fig.tight_layout()
    FIGURES.mkdir(exist_ok=True)
    out = FIGURES / out_name
    _save(fig, out)
    plt.close(fig)
    print("wrote", out)


def _headline_bars(
    out_name: str,
    wind_temp_track: str,
    wind_temp_scope: str,
    wind_temp_models: list[str] | None,
    wt_path: Path | None,
    solar_path: Path,
    solar_span: str = "1\u201348 h",
) -> None:
    """Shared 3-panel headline bars (wind, temp, solar) from separate paths."""
    span = {
        "h6_48": "6\u201348 h",
        "h1_48": "1\u201348 h",
        "h1_12": "1\u201312 h",
    }.get(wind_temp_scope, wind_temp_scope)
    panels = []
    for variable in (WIND, TEMP):
        if wt_path is not None and wt_path.exists():
            order, values = _wt_headline_values(wt_path, variable, wind_temp_models)
        else:
            models = _models(
                wind_temp_track,
                variable,
                wind_temp_scope,
                order=wind_temp_models or MODEL_ORDER,
            )
            order = sorted(
                models,
                key=lambda m: -(
                    _val(
                        wind_temp_track,
                        "skill_pct",
                        variable,
                        wind_temp_scope,
                        "all",
                        m,
                    )[0]
                    or -999
                ),
            )
            values = {
                (m, b): _val(
                    wind_temp_track, "skill_pct", variable, wind_temp_scope, b, m
                )
                for m in order
                for b in F3_BUCKETS
            }
        panels.append(
            (
                variable,
                order,
                values,
                f"{VAR_TITLE[variable]}: full horizon {span}",
            )
        )
    solar_order, solar_values = _solar_headline_values(solar_path)
    panels.append(
        (
            SOLAR,
            solar_order,
            solar_values,
            f"{VAR_TITLE[SOLAR]}: full horizon {solar_span}",
        )
    )
    _headline_bars_from_values(out_name, panels)


def fig3() -> None:
    """Track A: wind/temp 6–48 h (all models); solar 1–48 h hourly."""
    panels = []
    for variable, scope, span in (
        (WIND, "h6_48", "6\u201348 h"),
        (TEMP, "h6_48", "6\u201348 h"),
        (SOLAR, "h1_48", "1\u201348 h"),
    ):
        order, values = _headline_a_values(scope, variable)
        panels.append(
            (variable, order, values, f"{VAR_TITLE[variable]}: {span}")
        )
    _headline_bars_from_values("fig3_headline_bars.png", panels)


def fig3_short() -> None:
    """Track A, 1–12 h — wind, temp, solar (AIFS/Aurora omitted)."""
    panels = []
    for variable in (WIND, TEMP, SOLAR):
        order, values = _headline_a_values("h1_12", variable)
        panels.append(
            (
                variable,
                order,
                values,
                f"{VAR_TITLE[variable]}: 1\u201312 h",
            )
        )
    _headline_bars_from_values("fig3b_headline_bars_1_12.png", panels)


def _fig_track_b(lead_scope: str, out_name: str, span_label: str) -> None:
    """Track B regional bars at a given lead pool."""
    panels = []
    for variable in (WIND, TEMP, SOLAR):
        if HEADLINE_B.exists():
            order, values = _headline_track_values(
                HEADLINE_B,
                lead_scope,
                variable,
                model_order=(
                    None if variable == SOLAR else TRACK_B_MODELS
                ),
            )
        elif variable == SOLAR and SOLAR_HEADLINE_B.exists():
            order, values = _solar_headline_values(SOLAR_HEADLINE_B)
        elif WT_HEADLINE_B.exists():
            order, values = _wt_headline_values(
                WT_HEADLINE_B, variable, TRACK_B_MODELS
            )
        else:
            raise FileNotFoundError(
                f"Missing Track B data; run "
                f"scripts/fig_horizon_headlines.py --track track_b"
            )
        panels.append(
            (
                variable,
                order,
                values,
                f"{VAR_TITLE[variable]}: {span_label}",
            )
        )
    _headline_bars_from_values(out_name, panels)


def fig3b() -> None:
    """Track B regional showdown — 1–48 h and 1–12 h."""
    _fig_track_b("h1_48", "fig8b_track_b_bars.png", "1\u201348 h")
    _fig_track_b("h1_12", "fig8c_track_b_bars_1_12.png", "1\u201312 h")


# ---------------------------------------------------------------------------
# Heatmap helper (F4, F5)
# ---------------------------------------------------------------------------


def _heatmap(ax, mat, row_labels, col_labels, vmax, annot_fs=7.5):
    im = ax.imshow(mat, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, fontsize=8)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=8)
    ax.grid(visible=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for r in range(mat.shape[0]):
        for c in range(mat.shape[1]):
            v = mat[r, c]
            if np.isnan(v):
                ax.text(
                    c,
                    r,
                    "--",
                    ha="center",
                    va="center",
                    fontsize=annot_fs,
                    color="0.45",
                )
            else:
                color = "white" if abs(v) > 0.55 * vmax else "0.15"
                ax.text(
                    c,
                    r,
                    f"{v:+.1f}",
                    ha="center",
                    va="center",
                    fontsize=annot_fs,
                    color=color,
                )
    return im


def fig4() -> None:
    """Three stacked model×regime heatmaps matching fig3 pools."""
    mats, model_lists, spans = {}, {}, {}
    for variable, scope, span in (
        (WIND, "h6_48", "6\u201348 h"),
        (TEMP, "h6_48", "6\u201348 h"),
        (SOLAR, "h1_48", "1\u201348 h"),
    ):
        order, values = _headline_a_values(scope, variable)
        mat = np.full((len(order), len(BUCKET_ORDER)), np.nan)
        for r, m in enumerate(order):
            for c, b in enumerate(BUCKET_ORDER):
                v, _ = values.get((m, b), (None, None))
                if v is not None:
                    mat[r, c] = v
        mats[variable] = mat
        model_lists[variable] = order
        spans[variable] = span

    order_vars = (WIND, TEMP, SOLAR)
    vmax = max(np.nanmax(np.abs(mats[v])) for v in order_vars)
    heights = [len(model_lists[v]) for v in order_vars]
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(6.6, 10.6),
        gridspec_kw={"hspace": 0.34, "height_ratios": heights},
    )
    for ax, variable in zip(axes, order_vars, strict=True):
        im = _heatmap(
            ax,
            mats[variable],
            [DISPLAY.get(m, m) for m in model_lists[variable]],
            [BUCKET_2L[b] for b in BUCKET_ORDER],
            vmax,
        )
        short = VAR_SHORT[variable]
        ax.set_title(
            f"{VAR_TITLE[variable]} ({short}, {spans[variable]})", fontsize=10
        )
    fig.suptitle(
        "Track A MAE skill vs ECMWF IFS (%) by regime (debiased)", fontsize=10.5
    )
    cbar = fig.colorbar(im, ax=axes, fraction=0.035, pad=0.02)
    cbar.set_label(SKILL_LABEL, fontsize=8.5)
    cbar.ax.tick_params(labelsize=8)
    _save(fig, FIGURES / "fig4_regime_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def fig5(variable: str) -> None:
    models = _models("track_a", variable, "h6_48")
    rows = [("track_a", m, DISPLAY.get(m, m)) for m in models]
    if _sel("track_b", "country", variable, "h6_48", "gt_q95", "icon_eu").height:
        rows.append(("track_b", "icon_eu", DISPLAY["icon_eu"] + DAGGER))
    mat = np.full((len(rows), len(COUNTRIES)), np.nan)
    for r, (track, m, _) in enumerate(rows):
        for c, country in enumerate(COUNTRIES):
            v, _se = _val(track, "country", variable, "h6_48", "gt_q95", m, country)
            if v is not None:
                mat[r, c] = v
    vmax = np.nanmax(np.abs(mat))
    fig, ax = plt.subplots(figsize=(6.6, 0.42 * len(rows) + 1.5))
    im = _heatmap(ax, mat, [lbl for _, _, lbl in rows], COUNTRIES, vmax, annot_fs=7)
    ax.set_title(
        f"{VAR_TITLE[variable]}: per-country MAE skill vs ECMWF IFS (%), "
        "very high (>P95), 6\u201348 h",
        fontsize=10,
    )
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("MAE skill (%)", fontsize=8.5)
    cbar.ax.tick_params(labelsize=8)
    _save(fig, 
        FIGURES / f"fig5_tail_heatmap_{VAR_SHORT[variable]}.png", bbox_inches="tight"
    )
    plt.close(fig)


def fig5_solar() -> None:
    """Per-country typical (P25–75) MAE skill for solar.

    For solar, typical irradiance is the energy-dominant / “extrema”
    counterpart to wind/temp >P95 — not clear-sky (>P95). Built from
    ``solar_metrics_country.parquet`` (aggregates lack q25_q75 country
    cells). Helios window, pooled 1–48 h.
    """
    src = _derived("solar_metrics_country")
    if not src.exists():
        # Local/API extract only — not shipped in the public aggregates set.
        print(f"skip fig5_solar: missing {src.name}")
        return
    raw = pl.read_parquet(src).filter(
        (pl.col("period_kind") == "full")
        & pl.col("debias")
        & (pl.col("metric") == "mae")
        & (pl.col("obs_bucket") == "q25_q75")
        & (pl.col("sample_count") >= 100)
    )
    ref = raw.filter(pl.col("model") == REFERENCE).select(
        "country",
        "prediction_timedelta",
        pl.col("avg").alias("ref_avg"),
        pl.col("sample_count").alias("ref_n"),
    )
    matched = raw.filter(pl.col("model") != REFERENCE).join(
        ref, on=["country", "prediction_timedelta"], how="inner"
    )
    # Pool sample-weighted mean errors, not error sums, so a model with fewer
    # matched samples than the reference does not score that deficit as skill.
    model_pool = (pl.col("avg") * pl.col("sample_count")).sum() / pl.col(
        "sample_count"
    ).sum()
    ref_pool = (pl.col("ref_avg") * pl.col("ref_n")).sum() / pl.col("ref_n").sum()
    skill = matched.group_by(["model", "country"]).agg(
        (100 * (1 - model_pool / ref_pool)).alias("skill")
    )
    avail = set(skill["model"].to_list())
    models = [m for m in SOLAR_ORDER if m in avail]
    mat = np.full((len(models), len(COUNTRIES)), np.nan)
    for r, m in enumerate(models):
        for c, country in enumerate(COUNTRIES):
            row = skill.filter(
                (pl.col("model") == m) & (pl.col("country") == country)
            )
            if row.height:
                mat[r, c] = row["skill"][0]
    vmax = float(np.nanmax(np.abs(mat))) if np.isfinite(mat).any() else 30.0
    fig, ax = plt.subplots(figsize=(6.6, 0.42 * len(models) + 1.5))
    im = _heatmap(
        ax, mat, [DISPLAY.get(m, m) for m in models], COUNTRIES, vmax, annot_fs=7
    )
    ax.set_title(
        f"{VAR_TITLE[SOLAR]}: per-country MAE skill vs ECMWF IFS (%), "
        f"typical (P25\u201375), 1\u201348 h",
        fontsize=10,
    )
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("MAE skill (%)", fontsize=8.5)
    cbar.ax.tick_params(labelsize=8)
    _save(fig, FIGURES / "fig5_tail_heatmap_solar.png", bbox_inches="tight")
    plt.close(fig)
    print("wrote", FIGURES / "fig5_tail_heatmap_solar.png")


# ---------------------------------------------------------------------------
# F6 — conditional bias fingerprint at lead 48 h (envelope redesign)
# ---------------------------------------------------------------------------

# Two highlighted models on top of the all-model envelope: one generative
# ensemble (solid green) and one regression AI (dash-dot deep blue).
F6_HIGHLIGHT = ["ept2_1_europa", "aifs"]
# aifs has no solar rows; helios is the natural second highlight there.
F6_HIGHLIGHT_SOLAR = ["ept2_1_europa", "ept2_1_helios"]
F6_HIGHLIGHT_PRECIP = ["ept2_1_europa", "ept2_reasoning"]
F6_PRECIP_ORDER = [
    "ept2_reasoning",
    "ept2_hrrr",
    "ept2_e",
    "ept2_1_europa",
    "ecmwf_ens",
    "noaa_gfs_single",
    "icon_global",
    REFERENCE,
]


SOLAR_BIAS_A = _derived("solar_bias_lead48_track_a")


def fig6() -> None:
    """Conditional-bias fingerprint at 48 h: gray envelope + IFS + highlights.

    Wind/temp/precipitation from track_a aggregates; solar from Track A
    Sep–Jun extract (``solar_bias_lead48_track_a.parquet``).
    """
    panels = [
        (WIND, "track_a", MODEL_ORDER, F6_HIGHLIGHT, 1.0, BUCKET_ORDER, BUCKET_SHORT),
        (TEMP, "track_a", MODEL_ORDER, F6_HIGHLIGHT, 1.0, BUCKET_ORDER, BUCKET_SHORT),
        (
            SOLAR,
            "solar_a",
            SOLAR_ORDER,
            F6_HIGHLIGHT_SOLAR,
            1 / 3600.0,
            BUCKET_ORDER,
            BUCKET_SHORT,
        ),
        (
            PRECIP,
            "track_a",
            F6_PRECIP_ORDER,
            F6_HIGHLIGHT_PRECIP,
            1.0,
            PRECIP_BUCKET_ORDER,
            PRECIP_BUCKET_SHORT,
        ),
    ]
    solar_bias = (
        pl.read_parquet(SOLAR_BIAS_A) if SOLAR_BIAS_A.exists() else pl.DataFrame()
    )

    fig, axes = plt.subplots(2, 2, figsize=(7.0, 6.1))
    for ax, (
        variable,
        track,
        order,
        highlight,
        unit_scale,
        buckets,
        bucket_short,
    ) in zip(
        axes.flat, panels, strict=True
    ):
        x = np.arange(len(buckets))
        if track == "solar_a" and not solar_bias.is_empty():
            avail = set(solar_bias["model"].to_list())
            models = [m for m in order if m in avail and m != REFERENCE]

            def series(m: str, _s=unit_scale) -> np.ndarray:
                vals = []
                for b in buckets:
                    r = solar_bias.filter(
                        (pl.col("model") == m) & (pl.col("obs_bucket") == b)
                    )
                    vals.append(
                        None if r.is_empty() else r["bias"][0] * _s
                    )
                return np.array(
                    [np.nan if v is None else v for v in vals], dtype=float
                )
        else:
            avail = set(_sel(track, "bias", variable, "lead_48")["model"].to_list())
            models = [m for m in order if m in avail and m != REFERENCE]

            def series(m: str, _t=track, _v=variable, _s=unit_scale) -> np.ndarray:
                vals = [_val(_t, "bias", _v, "lead_48", b, m)[0] for b in buckets]
                return np.array(
                    [np.nan if v is None else v * _s for v in vals], dtype=float
                )

        envelope_models = [m for m in order if m in avail]
        all_curves = np.vstack([series(m) for m in envelope_models])
        lo = np.nanmin(all_curves, axis=0)
        hi = np.nanmax(all_curves, axis=0)
        ax.vlines(x[0], lo[0], hi[0], color="0.72", lw=4, zorder=1)
        ax.fill_between(x[1:], lo[1:], hi[1:], color="0.82", lw=0, zorder=1)
        reference_values = series(REFERENCE)
        ax.plot(
            x[1:],
            reference_values[1:],
            color="k",
            lw=2.2,
            marker=MARKERS[REFERENCE],
            ms=3.4,
            zorder=3,
            label=DISPLAY[REFERENCE],
        )
        ax.plot(
            x[0],
            reference_values[0],
            color="k",
            marker=MARKERS[REFERENCE],
            ms=3.4,
            linestyle="none",
            zorder=3,
        )
        for m in highlight:
            if m not in avail and m != REFERENCE:
                continue
            values = series(m)
            ax.plot(
                x[1:],
                values[1:],
                lw=1.6,
                marker=MARKERS.get(m, "o"),
                ms=2.8,
                linestyle=LINESTYLES.get(m, "-"),
                color=COLORS.get(m, "gray"),
                zorder=4,
                label=DISPLAY.get(m, m),
            )
            ax.plot(
                x[0],
                values[0],
                marker=MARKERS.get(m, "o"),
                ms=2.8,
                linestyle="none",
                color=COLORS.get(m, "gray"),
                zorder=4,
            )
        ax.axhline(0, color="k", lw=0.8, ls=":")
        ax.set_xticks(x)
        ax.set_xticklabels(
            [bucket_short[b] for b in buckets],
            fontsize=7.5,
            rotation=45,
            ha="right",
        )
        ax.set_ylabel(f"Conditional bias ({VAR_UNIT[variable]})", fontsize=8.5)
        ax.set_title(VAR_TITLE[variable], fontsize=9)

    fig.suptitle(
        "Conditional bias by observed-value regime at 48 h (debiased)",
        fontsize=10.5,
    )
    legend_models = [
        REFERENCE,
        *F6_HIGHLIGHT,
        *F6_HIGHLIGHT_SOLAR,
        *F6_HIGHLIGHT_PRECIP,
    ]
    handles = model_legend_handles(legend_models, ncol=3)
    if handles:
        fig.legend(
            handles=handles,
            loc="lower center",
            ncol=3,
            fontsize=7.5,
            frameon=False,
            bbox_to_anchor=(0.5, 0.0),
            handlelength=3.2,
            handletextpad=0.6,
        )
    fig.tight_layout(rect=(0, 0.08, 1, 0.96))
    _save(fig, FIGURES / "fig6_fingerprint.png")
    plt.close(fig)


# ---------------------------------------------------------------------------
# F8 — track B regional models, per-lead skill
# ---------------------------------------------------------------------------


TRACK_B_LEADS = _derived("track_b_lead_skill")


def fig8() -> None:
    """Track B skill vs lead (Mar–Jun): wind, temp, solar (+Helios).

    Prefers ``track_b_lead_skill.parquet``; wind/temp fall back to aggregates.
    All regional systems have matched values at [6, 12, 24, 48] h. Solar
    second column: overcast (P5–25); wind/temp: >P95.
    """
    use_parquet = TRACK_B_LEADS.exists()
    tb = pl.read_parquet(TRACK_B_LEADS) if use_parquet else None
    solar_models = ["ept2_1_helios", *TRACK_B_MODELS]
    panels = [
        (WIND, TRACK_B_MODELS, "all", "gt_q95", SINGLE_LEADS),
        (TEMP, TRACK_B_MODELS, "all", "gt_q95", SINGLE_LEADS),
        (SOLAR, solar_models, "all", "q5_q25", SINGLE_LEADS),
    ]
    # Keep axes independent so each row can evolve its lead selection safely.
    fig, axes = plt.subplots(3, 2, figsize=(6.6, 7.8), sharex=False)
    for i, (variable, models, b0, b1, leads) in enumerate(panels):
        for j, bucket in enumerate((b0, b1)):
            ax = axes[i, j]
            for m in models:
                if use_parquet and tb is not None:
                    vals, ses = [], []
                    for h in leads:
                        r = tb.filter(
                            (pl.col("variable") == variable)
                            & (pl.col("model") == m)
                            & (pl.col("obs_bucket") == bucket)
                            & (pl.col("lead_h") == h)
                        )
                        vals.append(r["skill"][0] if r.height else None)
                        ses.append(None)
                    _band(ax, leads, vals, ses, m, ms=3.4, lw=1.6)
                elif variable != SOLAR:
                    vals, ses = _lead_series("track_b", variable, bucket, m)
                    _band(ax, leads, vals, ses, m, ms=3.4, lw=1.6)
            ax.axhline(0, color="k", lw=0.9, ls="--")
            ax.set_xticks(leads)
            bucket_label = (
                "Overcast (P5–25)"
                if variable == SOLAR and bucket == "q5_q25"
                else BUCKET_LABELS[bucket]
            )
            ax.set_title(
                f"{VAR_TITLE[variable]}\n{bucket_label}", fontsize=9
            )
            if j == 0:
                ax.set_ylabel(SKILL_LABEL, fontsize=8)
            if i == 2:
                ax.set_xlabel("Lead time (h)")
    # Canonical ordering and styling across all line figures.
    handles = model_legend_handles(solar_models, ncol=3)
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=3,
        fontsize=7.5,
        bbox_to_anchor=(0.5, 0.005),
        handlelength=3.2,
        handletextpad=0.6,
    )
    fig.suptitle(
        "Track B (Mar\u2013Jun 2026): regional models vs ECMWF IFS by lead\n"
        "(debiased; solar includes EPT-2.1 Helios; leads 6–48 h)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.11, 1, 0.94))
    _save(fig, FIGURES / "fig8_track_b.png")
    plt.close(fig)
    print("wrote", FIGURES / "fig8_track_b.png")


# ---------------------------------------------------------------------------
# F9 — solar month-by-month MAE skill (Track A + Track B)
# ---------------------------------------------------------------------------

SOLAR_MONTHLY_A = _derived("solar_monthly_skill_track_a")
SOLAR_MONTHLY_B = _derived("solar_monthly_skill_track_b")
_MONTH_LABEL = {
    "2025-09": "Sep",
    "2025-10": "Oct",
    "2025-11": "Nov",
    "2025-12": "Dec",
    "2026-01": "Jan",
    "2026-02": "Feb",
    "2026-03": "Mar",
    "2026-04": "Apr",
    "2026-05": "May",
    "2026-06": "Jun",
}


def _solar_monthly_panel(
    ax,
    path: Path,
    bucket: str,
    title: str,
    *,
    ylabel: bool = False,
) -> list:
    """Plot monthly skill lines; return legend handles from this axes."""
    if not path.exists():
        ax.set_title(f"{title} (missing data)", fontsize=9)
        ax.text(0.5, 0.5, "run fig_solar_headline.py", ha="center", va="center")
        return []
    df = pl.read_parquet(path).filter(pl.col("obs_bucket") == bucket)
    periods = sorted(df["period_start"].unique().to_list())
    labels = [_MONTH_LABEL.get(p[:7], p[:7]) for p in periods]
    x = np.arange(len(periods))
    # Rank models by mean skill across months (stable ordering).
    means = {
        m: df.filter(pl.col("model") == m)["skill"].mean()
        for m in df["model"].unique().to_list()
    }
    models = sorted(means, key=lambda m: -(means[m] if means[m] is not None else -999))
    for m in models:
        vals = []
        for p in periods:
            r = df.filter((pl.col("model") == m) & (pl.col("period_start") == p))
            vals.append(r["skill"][0] if r.height else None)
        xs = [xi for xi, v in zip(x, vals, strict=True) if v is not None]
        ys = [v for v in vals if v is not None]
        if not ys:
            continue
        ax.plot(
            xs,
            ys,
            marker=MARKERS.get(m, "o"),
            ms=3.0,
            lw=1.5,
            linestyle=LINESTYLES.get(m, "-"),
            color=COLORS.get(m, "gray"),
            label=DISPLAY.get(m, m),
        )
    ax.axhline(0, color="k", lw=0.9, ls="--")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_title(title, fontsize=9)
    if ylabel:
        ax.set_ylabel(SKILL_LABEL, fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    return model_legend_handles(models)


def fig9() -> None:
    """Month-by-month solar MAE skill for Track A (top) and Track B (bottom).

    Columns: all conditions | typical irradiance (P25–75).
    Data from ``scripts/fig_solar_headline.py`` monthly parquets.
    """
    fig, axes = plt.subplots(2, 2, figsize=(6.8, 6.2), sharey="row")
    panels = [
        (axes[0, 0], SOLAR_MONTHLY_A, "all", "Track A: all conditions", True),
        (
            axes[0, 1],
            SOLAR_MONTHLY_A,
            "q25_q75",
            "Track A: typical (P25\u201375)",
            False,
        ),
        (axes[1, 0], SOLAR_MONTHLY_B, "all", "Track B: all conditions", True),
        (
            axes[1, 1],
            SOLAR_MONTHLY_B,
            "q25_q75",
            "Track B: typical (P25\u201375)",
            False,
        ),
    ]
    handles_a, handles_b = [], []
    for i, (ax, path, bucket, title, ylab) in enumerate(panels):
        h = _solar_monthly_panel(ax, path, bucket, title, ylabel=ylab)
        if i == 0:
            handles_a = h
        if i == 2:
            handles_b = h
    axes[1, 0].set_xlabel("Month", fontsize=8)
    axes[1, 1].set_xlabel("Month", fontsize=8)
    if handles_a:
        axes[0, 1].legend(
            handles=handles_a,
            fontsize=6,
            loc="best",
            framealpha=0.9,
            handlelength=3.0,
        )
    if handles_b:
        axes[1, 1].legend(
            handles=handles_b,
            fontsize=6.5,
            loc="best",
            framealpha=0.9,
            handlelength=3.0,
        )
    fig.suptitle(
        "Solar MAE skill vs ECMWF IFS by month (debiased)",
        fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0.0, 1, 0.96))
    _save(fig, FIGURES / "fig9_solar_monthly.png")
    plt.close(fig)
    print("wrote", FIGURES / "fig9_solar_monthly.png")


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
    (TABLES / name).write_text("\n".join(lines) + "\n")
    print(f"--- {name} ---")
    print("\n".join(lines))
    print()


# NOTE: the regime skill tables (t1_skill_*, t2_perlead_*, t3_track_b_*) are
# owned by scripts/write_paper_tables.py, which is the single writer the paper
# \input's and which runs last in the reproduction pipeline. Earlier this module
# also emitted t1/t2/t3 with a different SE format and an extra ICON-EU row, so
# the committed tables depended on run order. Those generators were removed to
# make write_paper_tables.py the sole author. This module still owns the tables
# that only it produces: t4_solar, t5_per_country_gt95_* and t6_skill_rmse_*.


def t4() -> None:
    """Track C solar, h1_48, 6 regimes; sorted by all-conditions skill."""
    models = _models("track_c", SOLAR, "h1_48", order=SOLAR_ORDER)
    models = sorted(
        models,
        key=lambda m: (
            -(_val("track_c", "skill_pct", SOLAR, "h1_48", "all", m)[0] or -999)
        ),
    )
    lines = [
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        "Model & " + " & ".join(BUCKET_TEX[b] for b in BUCKET_ORDER) + " \\\\",
        "\\midrule",
    ]
    for m in models:
        cells = [
            _fmt(_val("track_c", "skill_pct", SOLAR, "h1_48", b, m)[0])
            for b in BUCKET_ORDER
        ]
        lines.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table("t4_solar.tex", lines)


def t5(variable: str) -> None:
    """Per-country gt_q95 skill at h6_48; icon_eu dagger row from track_b."""
    lines = [
        "\\begin{tabular}{l" + "r" * len(COUNTRIES) + "}",
        "\\toprule",
        "Model & " + " & ".join(COUNTRIES) + " \\\\",
        "\\midrule",
    ]
    rows = [
        ("track_a", m, DISPLAY.get(m, m)) for m in _models("track_a", variable, "h6_48")
    ]
    if _sel("track_b", "country", variable, "h6_48", "gt_q95", "icon_eu").height:
        rows.append(("track_b", "icon_eu", DISPLAY["icon_eu"] + DAGGER))
    for track, m, label in rows:
        cells = [
            _fmt(_val(track, "country", variable, "h6_48", "gt_q95", m, c)[0])
            for c in COUNTRIES
        ]
        lines.append(f"{label} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table(f"t5_per_country_gt95_{VAR_SHORT[variable]}.tex", lines)


def t6(variable: str) -> None:
    """Appendix: RMSE-based skill (kind='skill_pct_rmse') at h6_48 for
    cross-checking the MAE-primary headline numbers."""
    lines = [
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        "Model & " + " & ".join(BUCKET_TEX[b] for b in BUCKET_ORDER) + " \\\\",
        "\\midrule",
    ]
    for m in _models("track_a", variable, "h6_48", kind="skill_pct_rmse"):
        cells = [
            _fmt(_val("track_a", "skill_pct_rmse", variable, "h6_48", b, m)[0])
            for b in BUCKET_ORDER
        ]
        lines.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write_table(f"t6_skill_rmse_{VAR_SHORT[variable]}.tex", lines)


def main() -> None:
    apply_style()
    FIGURES.mkdir(exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    fig2(WIND)
    fig2(TEMP)
    fig2_solar()
    fig3()
    fig3_short()
    fig3b()
    fig5(WIND)
    fig5(TEMP)
    fig6()
    fig8()
    # t1/t2/t3 regime tables are written by write_paper_tables.py (sole owner).
    t4()
    t5(WIND)
    t5(TEMP)
    t6(WIND)
    t6(TEMP)
    print("wrote figures to", FIGURES)
    print("wrote tables to", TABLES)


if __name__ == "__main__":
    main()
