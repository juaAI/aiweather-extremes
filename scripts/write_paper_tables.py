"""Write appendix LaTeX tables that match the main-text figures.

Sources:
  headline_skill_track_a.parquet  → fig3 / fig3b regime bars
  headline_skill_track_b.parquet  → fig8b / fig8c
  solar_lead_skill_track_a.parquet → fig2 solar
  track_b_lead_skill.parquet      → fig8 lead curves
  final_aggregates.parquet        → fig2 wind/temp per-lead

Run:  uv run python scripts/write_paper_tables.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import DISPLAY, MODEL_ORDER, REFERENCE, SOLAR, TEMP, WIND

REPO = Path(__file__).resolve().parents[1]
TABLES = REPO / "paper" / "tables"
DERIVED = REPO / "data" / "derived"

# Active regime definition; see figures_v4.py. Set EXTREMES_VARIANT=_climatology
# to build from ERA5 1991-2020 climatological regimes. Outputs keep canonical
# names so the paper needs no per-variant includes.
VARIANT_SUFFIX = os.environ.get("EXTREMES_VARIANT", "")


def _derived(stem: str):
    return DERIVED / f"{stem}{VARIANT_SUFFIX}.parquet"


BUCKET_TEX = {
    "all": "All",
    "lt_q5": "$<$P5",
    "q5_q25": "P5--25",
    "q25_q75": "P25--75",
    "q75_q95": "P75--95",
    "gt_q95": "$>$P95",
}
BUCKETS = ["all", "lt_q5", "q5_q25", "q25_q75", "q75_q95", "gt_q95"]
SOLAR_ORDER = ["ept2_1_helios", *MODEL_ORDER]
TRACK_B_MODELS = ["ept2_1_europa", "ept2_hrrr", "icon_eu"]
SOLAR_B_MODELS = ["ept2_1_helios", "ept2_1_europa", "ept2_hrrr", "icon_eu"]


# Shorter row labels for dense lead tables.
SHORT = {
    "ept2_1_helios": "EPT-2.1 Helios",
    "ept2_1_europa": "EPT-2.1 Europa",
    "ept2_hrrr": "EPT-2 HRRR",
    "ept2_reasoning": "EPT-2 Reasoning",
    "ept2_e": "EPT-2e",
    "aurora": "Aurora",
    "aifs": "AIFS",
    "aifs_ens": "AIFS ENS",
    "ecmwf_ens": "ENS",
    "noaa_gfs_single": "GFS",
    "icon_global": "ICON Global",
    "icon_eu": "ICON-EU",
}


def _fmt(v: float | None, se: float | None = None) -> str:
    """Cell: +8.5 or +8.5 (0.5) — SE in parentheses, no subscript clutter."""
    if v is None:
        return "--"
    if se is not None and se == se:
        return f"{v:+.1f}\\,({se:.1f})"
    return f"{v:+.1f}"


def _model_label(m: str, *, short: bool = False) -> str:
    if short:
        return SHORT.get(m, DISPLAY.get(m, m))
    return DISPLAY.get(m, m)


def _write(name: str, lines: list[str]) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / name).write_text("\n".join(lines) + "\n")
    print("wrote", name)


def _order_models(df: pl.DataFrame, preferred: list[str]) -> list[str]:
    all_sk = {
        r["model"]: r["skill"]
        for r in df.filter(pl.col("obs_bucket") == "all").iter_rows(named=True)
    }
    order = [m for m in preferred if m in all_sk]
    order += sorted((m for m in all_sk if m not in order), key=lambda m: -all_sk[m])
    return order


def _regime_table(
    df: pl.DataFrame,
    variable: str,
    scope: str,
    out: str,
    models: list[str] | None = None,
) -> None:
    sub = df.filter(
        (pl.col("variable") == variable) & (pl.col("lead_scope") == scope)
    )
    preferred = models or (SOLAR_ORDER if variable == SOLAR else MODEL_ORDER)
    order = _order_models(sub, preferred)
    lines = [
        "\\begin{tabular}{@{}l" + "r" * len(BUCKETS) + "@{}}",
        "\\toprule",
        "Model & " + " & ".join(BUCKET_TEX[b] for b in BUCKETS) + " \\\\",
        "\\midrule",
    ]
    for i, m in enumerate(order):
        cells = []
        for b in BUCKETS:
            r = sub.filter((pl.col("model") == m) & (pl.col("obs_bucket") == b))
            cells.append(
                _fmt(r["skill"][0], r["skill_se"][0]) if r.height else "--"
            )
        row = f"{_model_label(m)} & " + " & ".join(cells) + " \\\\"
        if i < len(order) - 1:
            row += "\\addlinespace[0.35em]"
        lines.append(row)
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write(out, lines)


def _lead_table(
    df: pl.DataFrame,
    *,
    leads: list[int],
    b1: str,
    b1_label: str,
    models: list[str],
    out: str,
) -> None:
    """Per-lead skill only (no SE) — keeps wide tables readable."""
    avail = set(df["model"].to_list())
    models = [m for m in models if m in avail]
    ncols = len(leads) * 2
    lines = [
        "\\begin{tabular}{@{}l" + "*{" + str(ncols) + "}{r}" + "@{}}",
        "\\toprule",
        "& "
        + " & ".join(f"\\multicolumn{{2}}{{c}}{{{h}\\,h}}" for h in leads)
        + " \\\\",
        " ".join(f"\\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}" for i in range(len(leads))),
        "Model & " + " & ".join([f"All & {b1_label}"] * len(leads)) + " \\\\",
        "\\midrule",
    ]
    for i, m in enumerate(models):
        cells = []
        for h in leads:
            for b in ("all", b1):
                r = df.filter(
                    (pl.col("model") == m)
                    & (pl.col("lead_h") == h)
                    & (pl.col("obs_bucket") == b)
                )
                cells.append(_fmt(r["skill"][0]) if r.height else "--")
        row = f"{_model_label(m, short=True)} & " + " & ".join(cells) + " \\\\"
        if i < len(models) - 1:
            row += "\\addlinespace[0.3em]"
        lines.append(row)
    lines += ["\\bottomrule", "\\end{tabular}"]
    _write(out, lines)


def table_solar_leads() -> None:
    df = pl.read_parquet(_derived("solar_lead_skill_track_a"))
    at6 = df.filter((pl.col("obs_bucket") == "all") & (pl.col("lead_h") == 6))
    order = sorted(
        at6["model"].unique().to_list(),
        key=lambda m: -(
            at6.filter(pl.col("model") == m)["skill"][0]
            if at6.filter(pl.col("model") == m).height
            else -999
        ),
    )
    _lead_table(
        df,
        leads=[1, 6, 12, 24, 48],
        b1="q5_q25",
        b1_label="Ovc.",
        models=order,
        out="t2_perlead_solar.tex",
    )


def table_wt_leads() -> None:
    """Track A wind/temp per-lead from final_aggregates."""
    agg = _derived("final_aggregates")
    if not agg.exists():
        print("skip t2 wind/temp (no aggregates)")
        return
    fa = pl.read_parquet(agg)
    scope_map = {6: "lead_6", 12: "lead_12", 24: "lead_24", 48: "lead_48"}
    for variable, tag in ((WIND, "wind"), (TEMP, "temp")):
        rows = []
        for h, scope in scope_map.items():
            sub = fa.filter(
                (pl.col("track") == "track_a")
                & (pl.col("variable") == variable)
                & (pl.col("kind") == "skill_pct")
                & pl.col("debias")
                & (pl.col("lead_scope") == scope)
                & pl.col("obs_bucket").is_in(["all", "gt_q95"])
                & pl.col("country").is_null()
            )
            for r in sub.iter_rows(named=True):
                rows.append(
                    {
                        "model": r["model"],
                        "lead_h": h,
                        "obs_bucket": r["obs_bucket"],
                        "skill": r["value"],
                        "skill_se": r.get("skill_se"),
                    }
                )
        if not rows:
            print("skip t2", tag, "(no rows)")
            continue
        df = pl.DataFrame(rows)
        models = [m for m in MODEL_ORDER if m != REFERENCE and m in df["model"].to_list()]
        _lead_table(
            df,
            leads=[6, 12, 24, 48],
            b1="gt_q95",
            b1_label="$>$P95",
            models=models,
            out=f"t2_perlead_{tag}.tex",
        )


def table_track_b_leads() -> None:
    df = pl.read_parquet(_derived("track_b_lead_skill"))
    for variable, leads, b1, label, models, tag in (
        (WIND, [6, 12, 24, 48], "gt_q95", "$>$P95", TRACK_B_MODELS, "wind"),
        (TEMP, [6, 12, 24, 48], "gt_q95", "$>$P95", TRACK_B_MODELS, "temp"),
        (SOLAR, [6, 12, 24, 48], "q5_q25", "Ovc.", SOLAR_B_MODELS, "solar"),
    ):
        _lead_table(
            df.filter(pl.col("variable") == variable),
            leads=leads,
            b1=b1,
            b1_label=label,
            models=models,
            out=f"t2b_perlead_{tag}.tex",
        )


def table_track_b_bars() -> None:
    df = pl.read_parquet(_derived("headline_skill_track_b"))
    for scope, tag in (("h1_48", "148"), ("h1_12", "112")):
        for variable, vtag, models in (
            (WIND, "wind", TRACK_B_MODELS),
            (TEMP, "temp", TRACK_B_MODELS),
            (SOLAR, "solar", SOLAR_B_MODELS),
        ):
            _regime_table(
                df, variable, scope, f"t3_track_b_{vtag}_{tag}.tex", models=models
            )
    shutil.copy(TABLES / "t3_track_b_wind_148.tex", TABLES / "t3_track_b.tex")


def main() -> None:
    a = pl.read_parquet(_derived("headline_skill_track_a"))
    # Track A: wind/temp 6–48 h (all models); solar 1–48 h hourly.
    for variable, tag, scope in (
        (WIND, "wind", "h6_48"),
        (TEMP, "temp", "h6_48"),
        (SOLAR, "solar", "h1_48"),
    ):
        _regime_table(a, variable, scope, f"t1_skill_{tag}.tex")
        _regime_table(a, variable, "h1_12", f"t1_skill_{tag}_1_12.tex")
    table_solar_leads()
    table_wt_leads()
    table_track_b_bars()
    table_track_b_leads()
    print("done")


if __name__ == "__main__":
    main()
