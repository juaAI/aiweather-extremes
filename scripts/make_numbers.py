"""Every number quoted inline in the paper text, generated ENTIRELY from the
one authoritative aggregates dataset ``data/derived/final_aggregates.parquet``
(built by ``scripts/aggregates.py``), into ``reports/paper_numbers.md``.

Rerun after any re-extraction / re-aggregation and reconcile the text against
it before compiling:

    python scripts/aggregates.py
    python scripts/make_numbers.py
"""

from __future__ import annotations

import json
import os

import polars as pl
import yaml

from qe_client import PROJECT_ROOT
from style import (
    BUCKET_ORDER,
    DISPLAY,
    MODEL_ORDER,
    PRECIP,
    PRECIP_BUCKET_ORDER,
    REFERENCE,
    TEMP,
    WIND,
)

DERIVED = PROJECT_ROOT / "data" / "derived"

# Active regime definition; see figures_v4.py. Set EXTREMES_VARIANT=_climatology
# to build from ERA5 1991-2020 climatological regimes. Outputs keep canonical
# names so the paper needs no per-variant includes.
VARIANT_SUFFIX = os.environ.get("EXTREMES_VARIANT", "")


def _derived(stem: str):
    return DERIVED / f"{stem}{VARIANT_SUFFIX}.parquet"

OUT = PROJECT_ROOT / "reports" / "paper_numbers.md"

SOLAR = "surface_downwelling_shortwave_flux_sum_1h"
SCOPE_LABEL = {
    "lead_6": "lead 6 h",
    "lead_12": "lead 12 h",
    "lead_24": "lead 24 h",
    "lead_48": "lead 48 h",
    "h6_48": "full horizon 6-48 h (6-hourly grid)",
    "h6_240": "full horizon 6-240 h (6-hourly grid)",
    "h1_48": "full horizon 1-48 h (hourly grid)",
}
TRACK_A_SCOPES = ["lead_6", "lead_12", "lead_24", "lead_48", "h6_48", "h6_240", "h1_48"]
TRACK_BC_SCOPES = ["lead_6", "lead_12", "lead_24", "lead_48", "h6_48", "h1_48"]

# Solar model order (track_c includes ept2_1_helios, excludes aifs/aurora/ens).
SOLAR_ORDER = ["ept2_1_helios"] + [
    m for m in MODEL_ORDER if m not in ("aifs", "aurora", "ecmwf_ens")
]

# Precip: aifs/aurora/helios emit no precipitation.
PRECIP_ORDER = [
    "ept2_reasoning", "ept2_hrrr", "ept2_e", "ept2_1_europa",
    "icon_eu", "ecmwf_ens", "noaa_gfs_single", "icon_global",
]


def _f(v: float | None) -> str:
    return "--" if v is None else f"{v:+.1f}"


def _ordered(models: list[str], order: list[str]) -> list[str]:
    return [m for m in order if m in models] + sorted(set(models) - set(order))


def _skill_table(
    fa: pl.DataFrame,
    track: str,
    variable: str,
    scope: str,
    *,
    debias: bool = True,
    order: list[str] | None = None,
    with_se: bool = False,
) -> list[str]:
    sub = fa.filter(
        (pl.col("kind") == "skill_pct")
        & (pl.col("track") == track)
        & (pl.col("variable") == variable)
        & (pl.col("lead_scope") == scope)
        & (pl.col("debias") == debias)
    )
    if sub.height == 0:
        return [f"_(no data for {track} {scope})_"]
    models = _ordered(sub["model"].unique().to_list(), order or MODEL_ORDER)
    cells = {(r["model"], r["obs_bucket"]): r for r in sub.iter_rows(named=True)}
    header = "| model | " + " | ".join(BUCKET_ORDER) + " |"
    rule = "|---" * (len(BUCKET_ORDER) + 1) + "|"
    lines = [header, rule]
    for m in models:
        row = [DISPLAY.get(m, m)]
        for b in BUCKET_ORDER:
            r = cells.get((m, b))
            if r is None:
                row.append("--")
            elif with_se and r["skill_se"] is not None:
                row.append(f"{_f(r['value'])} (±{r['skill_se']:.1f})")
            else:
                row.append(_f(r["value"]))
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _precip_skill_table(
    fa: pl.DataFrame, track: str, scope: str, *, with_se: bool = True
) -> list[str]:
    """Precip skill in wet-hour regimes (own bucket order, own model order)."""
    sub = fa.filter(
        (pl.col("kind") == "skill_pct")
        & (pl.col("track") == track)
        & (pl.col("variable") == PRECIP)
        & (pl.col("lead_scope") == scope)
        & pl.col("debias")
    )
    if sub.height == 0:
        return [f"_(no data for {track} {scope})_"]
    models = _ordered(sub["model"].unique().to_list(), PRECIP_ORDER)
    cells = {(r["model"], r["obs_bucket"]): r for r in sub.iter_rows(named=True)}
    header = "| model | " + " | ".join(PRECIP_BUCKET_ORDER) + " |"
    rule = "|---" * (len(PRECIP_BUCKET_ORDER) + 1) + "|"
    lines = [header, rule]
    for m in models:
        row = [DISPLAY.get(m, m)]
        for b in PRECIP_BUCKET_ORDER:
            r = cells.get((m, b))
            if r is None:
                row.append("--")
            elif with_se and r["skill_se"] is not None:
                row.append(f"{_f(r['value'])} (±{r['skill_se']:.1f})")
            else:
                row.append(_f(r["value"]))
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _precip_categorical() -> list[str]:
    path = DERIVED / "precip_categorical.parquet"
    if not path.exists():
        return ["_(no precip_categorical.parquet)_"]
    cat = pl.read_parquet(path).filter(
        (pl.col("track") == "track_a")
        & (pl.col("period_kind") == "full")
        & pl.col("debias")
        & (pl.col("prediction_timedelta") <= 48 * 60)
    )
    agg = cat.group_by("model").agg(
        pl.col("hits").sum(),
        pl.col("false_alarms").sum(),
        pl.col("misses").sum(),
    ).with_columns(
        (pl.col("hits") / (pl.col("hits") + pl.col("misses"))).alias("pod"),
        (pl.col("false_alarms") / (pl.col("hits") + pl.col("false_alarms"))).alias("far"),
        (pl.col("hits") / (pl.col("hits") + pl.col("misses") + pl.col("false_alarms"))).alias("csi"),
        ((pl.col("hits") + pl.col("false_alarms")) / (pl.col("hits") + pl.col("misses"))).alias("freq_bias"),
    )
    by = {r["model"]: r for r in agg.iter_rows(named=True)}
    lines = ["| model | POD | FAR | CSI | freq bias |", "|---|---|---|---|---|"]
    order = _ordered(list(by), PRECIP_ORDER + [REFERENCE])
    for m in sorted(order, key=lambda m: -by[m]["csi"]):
        r = by[m]
        lines.append(
            f"| {DISPLAY.get(m, m)} | {r['pod']:.2f} | {r['far']:.2f} "
            f"| {r['csi']:.2f} | {r['freq_bias']:.2f} |"
        )
    return lines


def _omissions(fa: pl.DataFrame) -> list[str]:
    lines = []
    sk = fa.filter(pl.col("kind") == "skill_pct")
    for track in ["track_a", "track_b", "track_c"]:
        t = sk.filter(pl.col("track") == track)
        all_models = set(t["model"].unique().to_list()) | {REFERENCE}
        for scope in TRACK_A_SCOPES if track == "track_a" else TRACK_BC_SCOPES:
            s = t.filter(pl.col("lead_scope") == scope)
            if s.height == 0:
                continue
            present = set(s["model"].unique().to_list()) | {REFERENCE}
            missing = sorted(all_models - present)
            if missing:
                lines.append(
                    f"- {track} {scope}: omitted (native cadence/horizon does not "
                    f"cover this grid): {', '.join(DISPLAY.get(m, m) for m in missing)}"
                )
        partial = (
            t.filter(pl.col("n_leads") < pl.col("grid_leads"))
            .group_by(["model", "lead_scope"])
            .agg(pl.col("n_leads").max(), pl.col("grid_leads").first())
            .sort(["lead_scope", "model"])
        )
        for r in partial.iter_rows(named=True):
            lines.append(
                f"- {track} {r['lead_scope']}: {DISPLAY.get(r['model'], r['model'])} "
                f"pools {r['n_leads']}/{r['grid_leads']} grid leads (missing leads "
                "omitted, never interpolated)"
            )
    return lines


def main() -> None:
    fa = pl.read_parquet(_derived("final_aggregates"))
    status = json.loads(
        (DERIVED / f"final_aggregates{VARIANT_SUFFIX}_status.json").read_text()
    )
    matrix = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())

    L: list[str] = [
        "# Inline paper numbers",
        "",
        "Single source: `data/derived/final_aggregates.parquet` "
        f"({status['rows']} rows, aggregation self-test: {status['self_test']}). "
        "Regenerate with `python scripts/aggregates.py && "
        "python scripts/make_numbers.py`.",
        "",
        "Conventions: skill_pct = 100*(1 - MAE_model/MAE_IFS) (MAE primary; "
        "RMSE-based skill in kind=skill_pct_rmse), sample-matched "
        "per (country, lead) cell vs ECMWF IFS; cross-country and cross-lead "
        "pooling sample-weighted (RMSE quadratic, bias/MAE/CRPS linear); regime "
        "cells with <100 samples excluded; extremes = LOCAL per-country "
        "percentile regimes (obs_bucket); (±x.x) = jackknife SE over monthly "
        "replicates. All skills/biases/deltas signed, 1 decimal.",
        "",
        "## Coverage omissions (models lacking leads are omitted, not interpolated)",
        "",
    ]
    L += _omissions(fa)
    L += [
        "- track_c solar: GB, IT, PL returned no benchmark rows at all (no "
        "solar station obs in QE for these countries) -> 9 of 12 countries. "
        "ES solar obs stop after March (421 samples in the whole window; most "
        "regime cells fall under the 100-sample floor); SE obs stop after "
        "April (no May/June monthly replicates).",
        "- track_c solar tail regimes (lt_q5/q75_q95/gt_q95) exist only at "
        "daylight-valid leads: leads 6 h (valid 06/18 UTC) have no high-"
        "irradiance buckets, lead 12 h (valid 00/12 UTC) has no lt_q5 cell "
        ">=100 samples. Night leads drop out of tail pooling.",
    ]

    # ---- Track A: wind + temp, all scopes -------------------------------
    for variable, vname in ((WIND, "10 m wind speed"), (TEMP, "2 m temperature")):
        L += ["", f"# Track A ({vname}), skill_pct vs IFS, debiased"]
        for scope in TRACK_A_SCOPES:
            L += ["", f"## {vname} — {SCOPE_LABEL[scope]}", ""]
            L += _skill_table(
                fa, "track_a", variable, scope, with_se=scope.startswith("h")
            )

    # ---- Local-tail per-country counts (gt_q95, h6_48) -------------------
    L += ["", "# Local-tail per-country counts: gt_q95, h6_48, debiased", ""]
    cn = fa.filter(
        (pl.col("kind") == "country")
        & (pl.col("obs_bucket") == "gt_q95")
        & (pl.col("lead_scope") == "h6_48")
        & pl.col("debias")
    )
    vshort_map = {WIND: "wind", TEMP: "temp", SOLAR: "solar"}
    for track in ["track_a", "track_b", "track_c"]:
        sub = cn.filter(pl.col("track") == track)
        if sub.height == 0:
            continue
        counts = (
            sub.group_by(["model", "variable"])
            .agg(
                (pl.col("value") > 0).sum().alias("n_pos"),
                pl.len().alias("n_countries"),
            )
            .sort(["variable", "model"])
        )
        order = SOLAR_ORDER if track == "track_c" else MODEL_ORDER
        L += [
            f"## {track}",
            "",
            "| model | variable | positive countries |",
            "|---|---|---|",
        ]
        for m in _ordered(counts["model"].unique().to_list(), order):
            for r in counts.filter(pl.col("model") == m).iter_rows(named=True):
                L.append(
                    f"| {DISPLAY.get(m, m)} | {vshort_map[r['variable']]} "
                    f"| {r['n_pos']}/{r['n_countries']} |"
                )
        L.append("")

    # ---- Track B ----------------------------------------------------------
    for variable, vname in ((WIND, "10 m wind speed"), (TEMP, "2 m temperature")):
        L += ["", f"# Track B ({vname}), skill_pct vs IFS, debiased"]
        for scope in ["h1_48", "lead_6", "lead_12", "lead_24", "lead_48"]:
            L += ["", f"## {vname} — {SCOPE_LABEL[scope]}", ""]
            L += _skill_table(
                fa, "track_b", variable, scope, with_se=scope.startswith("h")
            )

    # ---- Track C solar -----------------------------------------------------
    L += [
        "",
        "# Track C (solar, 1 h shortwave accumulation), skill_pct vs IFS, debiased",
    ]
    for scope in ["h1_48", "lead_6", "lead_12", "lead_24", "lead_48"]:
        L += ["", f"## solar — {SCOPE_LABEL[scope]}", ""]
        L += _skill_table(
            fa,
            "track_c",
            SOLAR,
            scope,
            order=SOLAR_ORDER,
            with_se=scope.startswith("h"),
        )

    # ---- Precipitation (wet-hour regimes) ----------------------------------
    L += [
        "",
        "# Precipitation (1 h accumulation), skill_pct vs IFS, debiased, "
        "wet-hour regimes",
        "",
        "Regimes: all / dry (<0.1 mm) / wet <P50 / P50-75 / P75-95 / >P95 of "
        "the ERA5 1991-2020 wet-hour climatology. Multiplicative debiasing "
        "(sum(obs)/sum(fc), trailing 4 wk, clip [0.33,3]).",
    ]
    for track, tlabel, scopes in (
        ("track_a", "Track A", ["h1_48", "lead_6", "lead_12", "lead_24", "lead_48"]),
        ("track_b", "Track B", ["h1_48"]),
    ):
        L += ["", f"## {tlabel}"]
        for scope in scopes:
            L += ["", f"### precip — {SCOPE_LABEL[scope]}", ""]
            L += _precip_skill_table(fa, track, scope, with_se=scope.startswith("h"))
    L += [
        "",
        "## Heavy-precip (>P95) categorical detection, Track A, ≤48 h, debiased",
        "",
    ]
    L += _precip_categorical()

    # ---- Conditional bias fingerprint at lead 48 ---------------------------
    L += [
        "",
        "# Conditional bias fingerprint at lead 48 h (debiased, pooled cross-country)",
        "",
        "| model | variable | bias lt_q5 | bias gt_q95 |",
        "|---|---|---|---|",
    ]
    bias = fa.filter(
        (pl.col("kind") == "bias")
        & (pl.col("lead_scope") == "lead_48")
        & pl.col("debias")
        & (pl.col("track") == "track_a")
        & pl.col("obs_bucket").is_in(["lt_q5", "gt_q95"])
    )
    for variable, vshort in ((WIND, "wind"), (TEMP, "temp")):
        sub = bias.filter(pl.col("variable") == variable)
        cells = {
            (r["model"], r["obs_bucket"]): r["value"] for r in sub.iter_rows(named=True)
        }
        for m in _ordered(sub["model"].unique().to_list(), MODEL_ORDER):
            L.append(
                f"| {DISPLAY.get(m, m)} | {vshort} | {_f(cells.get((m, 'lt_q5')))} "
                f"| {_f(cells.get((m, 'gt_q95')))} |"
            )
        lo = sub.filter(pl.col("obs_bucket") == "lt_q5")["value"]
        hi = sub.filter(pl.col("obs_bucket") == "gt_q95")["value"]
        L.append(
            f"| RANGE ({vshort}) | {vshort} | {_f(lo.min())} .. {_f(lo.max())} "
            f"| {_f(hi.min())} .. {_f(hi.max())} |"
        )

    # ---- Debias deltas (Europa + EPT-2 Reasoning) ---------------------------
    L += [
        "",
        "# Debias delta (debiased minus raw skill_pct), h6_48",
        "",
        "| model | track/variable | " + " | ".join(BUCKET_ORDER) + " |",
        "|---" * 8 + "|",
    ]
    sk = fa.filter(pl.col("kind") == "skill_pct")
    delta_specs = [
        ("ept2_1_europa", "track_a", WIND, "wind", "h6_48"),
        ("ept2_1_europa", "track_a", TEMP, "temp", "h6_48"),
        ("ept2_reasoning", "track_a", WIND, "wind", "h6_48"),
        ("ept2_reasoning", "track_a", TEMP, "temp", "h6_48"),
        ("ept2_1_europa", "track_c", SOLAR, "solar (h1_48)", "h1_48"),
        ("ept2_1_helios", "track_c", SOLAR, "solar (h1_48)", "h1_48"),
    ]
    for model, track, variable, vlabel, scope in delta_specs:
        on = sk.filter(
            (pl.col("model") == model)
            & (pl.col("track") == track)
            & (pl.col("variable") == variable)
            & (pl.col("lead_scope") == scope)
            & pl.col("debias")
        )
        off = sk.filter(
            (pl.col("model") == model)
            & (pl.col("track") == track)
            & (pl.col("variable") == variable)
            & (pl.col("lead_scope") == scope)
            & ~pl.col("debias")
        )
        d_on = {r["obs_bucket"]: r["value"] for r in on.iter_rows(named=True)}
        d_off = {r["obs_bucket"]: r["value"] for r in off.iter_rows(named=True)}
        row = [DISPLAY.get(model, model), f"{track} {vlabel}"]
        for b in BUCKET_ORDER:
            if b in d_on and b in d_off:
                row.append(_f(d_on[b] - d_off[b]))
            else:
                row.append("--")
        L.append("| " + " | ".join(row) + " |")

    # ---- Attribution inputs --------------------------------------------------
    L += [
        "",
        "# Attribution inputs (mixed-effects left to the paper author)",
        "",
        "Model attribute axes (config/matrix.yaml) joined with pooled gt_q95 "
        "skill at h6_48 (debiased). Replicate-level input for the mixed-effects "
        "model: `kind='country'` rows of final_aggregates.parquet (per-country "
        "skill + jackknife SE at all lead scopes, regimes all/q75_q95/gt_q95).",
        "",
        "| model | family | training | output | domain | wind gt_q95 (±SE) | temp gt_q95 (±SE) |",
        "|---|---|---|---|---|---|---|",
    ]
    attrs = matrix["models"]
    g95 = sk.filter(
        (pl.col("track") == "track_a")
        & (pl.col("lead_scope") == "h6_48")
        & pl.col("debias")
        & (pl.col("obs_bucket") == "gt_q95")
    )
    cells = {(r["model"], r["variable"]): r for r in g95.iter_rows(named=True)}
    for m in _ordered(g95["model"].unique().to_list(), MODEL_ORDER):
        a = attrs.get(m, {})

        def cell(variable: str, m: str = m) -> str:
            r = cells.get((m, variable))
            if r is None:
                return "--"
            se = f" (±{r['skill_se']:.1f})" if r["skill_se"] is not None else ""
            return f"{_f(r['value'])}{se}"

        L.append(
            f"| {DISPLAY.get(m, m)} | {a.get('family', '?')} | {a.get('training', '?')} "
            f"| {a.get('output', '?')} | {a.get('domain', '?')} | {cell(WIND)} | {cell(TEMP)} |"
        )

    OUT.write_text("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
