"""Build the ONE authoritative aggregates dataset for the paper:
``data/derived/final_aggregates.parquet``.

Inputs (all long-format, identical column layout):
* ``bucketed_metrics.parquet``  — track_a + track_b, wind + temp, per-country
  local-percentile regimes (obs_bucket), family='mean' (rmse/mae/bias, all
  track models jointly sample-matched) and family='crps' (mae+crps, ensemble
  models only).
* ``solar_metrics_country.parquet`` — track_c, per-country solar
  (surface_downwelling_shortwave_flux_sum_1h), family='mean'.

Output: one row per (track, model, variable, obs_bucket, lead_scope, debias,
kind[, country]) with columns:

* ``kind``       — 'skill_pct' (MAE-based, primary) | 'skill_pct_rmse' |
                   'rmse' | 'mae' | 'bias' | 'country' (MAE-based) |
                   'month' (MAE-based monthly skill; month in the country col)
* ``value``      — the aggregate. 'country' rows carry per-country skill_pct.
* ``skill_se``   — delete-1 jackknife SE over monthly replicates (skill rows
                   only; months use month-relative percentile regimes, so the
                   SE is a replicate-based uncertainty proxy for the
                   full-window estimate, not a decomposition of it).
* ``n_months``   — number of monthly replicates behind skill_se.
* ``n_leads``    — distinct leads actually pooled; ``grid_leads`` is the size
                   of the scope's lead grid (missing leads are omitted, never
                   interpolated).
* ``n_samples``  — total pooled sample count.

Pooling rules (everywhere): cross-country and cross-lead pooling is
sample-weighted. RMSE pools quadratically sqrt(sum(n_i*rmse_i^2)/sum(n_i));
bias/mae/crps pool linearly sum(n_i*x_i)/sum(n_i). skill_pct =
100*(1 - pooled_rmse_model / pooled_rmse_ref) where model and reference are
pooled over the SAME (country, lead) cells of the SAME family='mean'
requests, so samples match; regime cells with sample_count < 100 are
excluded from pooling on both sides. family='mean' and family='crps' rows
are never mixed in one computation.

Lead scopes: 'lead_6/12/24/48' (single leads), 'h6_48' (6-hourly grid
6..48h, the AIFS/AIFS ENS/Aurora cadence bound = Track A standard),
'h6_240' (6-hourly grid to 240h, long-horizon models), 'h1_48' (all hourly
leads 1..48). A model is a member of a scope only if it natively covers
>= 50% of the scope grid (excludes e.g. six-hourly AIFS-family models from hourly
scopes and 48h-horizon regionals from h6_240); members with partial grids
(e.g. icon_global tops out at 180h) keep their rows with n_leads <
grid_leads.

Run:  python scripts/aggregates.py   (builds + self-tests)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random

import polars as pl

from qe_client import PROJECT_ROOT

DERIVED = PROJECT_ROOT / "data" / "derived"
OUT_PATH = DERIVED / "final_aggregates.parquet"

# CLI variant -> filename suffix shared by inputs and outputs.
VARIANT_SUFFIXES = {
    "window": "",
    "climatology": "_climatology",
    "window_matched": "_window_matched",
}

REFERENCE = "ecmwf_ifs_single"
PRECIP = "precipitation_amount_sum_1h"
PRESERVED_PRECIP = DERIVED / "precip_aggregates_compact.parquet"
MIN_SAMPLES = 100
BUCKETS = ["all", "lt_q5", "q5_q25", "q25_q75", "q75_q95", "gt_q95"]
# Precipitation carries its own wet-hour regimes (dry mass + climatological wet
# bands) rather than the symmetric lt_q5..gt_q95 of the unbounded variables.
PRECIP_BUCKETS = ["all", "dry", "wet_lt_p50", "p50_p75", "p75_p95", "gt_p95"]
COUNTRY_BUCKETS = ["all", "lt_q5", "q75_q95", "gt_q95", "p75_p95", "gt_p95"]
# Minimum fraction of the scope's lead grid a model must natively cover.
MIN_GRID_COVERAGE = 0.5

# lead_scope -> grid of prediction_timedelta values in minutes
SCOPES: dict[str, list[int]] = {
    "lead_6": [6 * 60],
    "lead_12": [12 * 60],
    "lead_24": [24 * 60],
    "lead_48": [48 * 60],
    "h6_48": [h * 60 for h in range(6, 49, 6)],
    "h6_240": [h * 60 for h in range(6, 241, 6)],
    "h1_48": [h * 60 for h in range(1, 49)],
    "h1_12": [h * 60 for h in range(1, 13)],
}
# Scopes applicable per track (bounded by the track's max lead).
TRACK_SCOPES = {
    "track_a": list(SCOPES),
    "track_b": [
        "lead_6",
        "lead_12",
        "lead_24",
        "lead_48",
        "h6_48",
        "h1_48",
        "h1_12",
    ],
    "track_c": [
        "lead_6",
        "lead_12",
        "lead_24",
        "lead_48",
        "h6_48",
        "h1_48",
        "h1_12",
    ],
}


_SOURCE_COLUMNS = [
    "track",
    "model",
    "variable",
    "prediction_timedelta",
    "metric",
    "obs_bucket",
    "avg",
    "sample_count",
    "period_kind",
    "period_start",
    "country",
    "debias",
    "family",
]


def _load_sources(suffix: str = "") -> pl.DataFrame:
    frames = [
        pl.scan_parquet(DERIVED / f"bucketed_metrics{suffix}.parquet")
        .filter(pl.col("model") != "ept2")
        .select(_SOURCE_COLUMNS)
        .collect()
    ]
    solar = DERIVED / f"solar_metrics_country{suffix}.parquet"
    if solar.exists():
        frames.append(
            pl.scan_parquet(solar)
            .filter(pl.col("model") != "ept2")
            .select(_SOURCE_COLUMNS)
            .collect()
        )
    # Precipitation regimes are climatological by construction (a single file,
    # not variant-suffixed), so it folds into every variant unchanged.
    precip = DERIVED / "bucketed_metrics_precip.parquet"
    if precip.exists():
        frames.append(
            pl.scan_parquet(precip)
            .filter(pl.col("model") != "ept2")
            .select(_SOURCE_COLUMNS)
            .collect()
        )
    return pl.concat(frames)


def _member_models(df: pl.DataFrame) -> pl.DataFrame:
    """(track, model, variable, debias, lead_scope) membership + native grid
    coverage, from full-window family='mean' rmse rows (pre sample filter)."""
    leads = (
        df.filter(
            (pl.col("period_kind") == "full")
            & (pl.col("family") == "mean")
            & (pl.col("metric") == "rmse")
        )
        .group_by(["track", "model", "variable", "debias"])
        .agg(pl.col("prediction_timedelta").unique().alias("leads"))
    )
    rows = []
    for r in leads.iter_rows(named=True):
        have = set(r["leads"])
        for scope in TRACK_SCOPES[r["track"]]:
            grid = SCOPES[scope]
            covered = sum(1 for lead in grid if lead in have)
            if covered / len(grid) >= MIN_GRID_COVERAGE:
                rows.append(
                    {
                        "track": r["track"],
                        "model": r["model"],
                        "variable": r["variable"],
                        "debias": r["debias"],
                        "lead_scope": scope,
                        "native_leads": covered,
                        "grid_leads": len(grid),
                    }
                )
    return pl.DataFrame(rows)


def _scope_frame(df: pl.DataFrame, members: pl.DataFrame) -> pl.DataFrame:
    """Explode source rows into (row x member lead_scope)."""
    scope_frames = []
    for scope, grid in SCOPES.items():
        sub = df.filter(pl.col("prediction_timedelta").is_in(grid)).with_columns(
            pl.lit(scope).alias("lead_scope")
        )
        scope_frames.append(sub)
    exploded = pl.concat(scope_frames)
    return exploded.join(
        members, on=["track", "model", "variable", "debias", "lead_scope"], how="inner"
    )


def _pool(frame: pl.DataFrame, keys: list[str], metric: str) -> pl.DataFrame:
    """Sample-weighted pooling: quadratic for rmse, linear otherwise."""
    sub = frame.filter(pl.col("metric") == metric)
    if metric == "rmse":
        value = (
            ((pl.col("avg") ** 2) * pl.col("sample_count")).sum()
            / pl.col("sample_count").sum()
        ).sqrt()
    else:
        value = (pl.col("avg") * pl.col("sample_count")).sum() / pl.col(
            "sample_count"
        ).sum()
    return sub.group_by(keys).agg(
        value.alias("value"),
        pl.col("prediction_timedelta").n_unique().alias("n_leads"),
        pl.col("sample_count").sum().alias("n_samples"),
        pl.col("grid_leads").first().alias("grid_leads"),
    )


def _matched_cells(frame: pl.DataFrame, metric: str = "mae") -> pl.DataFrame:
    """Join model metric cells to reference cells of the same family='mean'
    request on (country, lead), so both sides pool identical samples."""
    rmse = frame.filter((pl.col("family") == "mean") & (pl.col("metric") == metric))
    cell_keys = [
        "track",
        "lead_scope",
        "variable",
        "obs_bucket",
        "debias",
        "period_kind",
        "period_start",
        "country",
        "prediction_timedelta",
    ]
    ref = rmse.filter(pl.col("model") == REFERENCE).select(
        [
            *cell_keys,
            pl.col("avg").alias("ref_avg"),
            pl.col("sample_count").alias("ref_n"),
        ]
    )
    model = rmse.filter(pl.col("model") != REFERENCE)
    joined = model.join(ref, on=cell_keys, how="inner")
    return joined


_SKILL_KEYS = ["track", "model", "variable", "obs_bucket", "debias", "lead_scope"]


def _skill_from_cells(
    cells: pl.DataFrame, keys: list[str], metric: str = "mae"
) -> pl.DataFrame:
    if metric == "rmse":
        model_pool = (
            ((pl.col("avg") ** 2) * pl.col("sample_count")).sum()
            / pl.col("sample_count").sum()
        ).sqrt()
        ref_pool = (
            ((pl.col("ref_avg") ** 2) * pl.col("ref_n")).sum() / pl.col("ref_n").sum()
        ).sqrt()
    else:
        model_pool = (pl.col("avg") * pl.col("sample_count")).sum() / pl.col(
            "sample_count"
        ).sum()
        ref_pool = (pl.col("ref_avg") * pl.col("ref_n")).sum() / pl.col("ref_n").sum()
    return cells.group_by(keys).agg(
        (100 * (1 - model_pool / ref_pool)).alias("value"),
        pl.col("prediction_timedelta").n_unique().alias("n_leads"),
        pl.col("sample_count").sum().alias("n_samples"),
        pl.col("grid_leads").first().alias("grid_leads"),
    )


def _jackknife(
    groups: pl.DataFrame, keys: list[str], metric: str = "mae"
) -> pl.DataFrame:
    """Delete-1 jackknife SE of skill_pct over monthly replicates.

    Input: month-level matched cells. Per month we keep the pooled sums; the
    leave-one-month-out skill is recomputed from the complementary sums.
    """
    model_sum = (
        (pl.col("avg") ** 2) * pl.col("sample_count")
        if metric == "rmse"
        else pl.col("avg") * pl.col("sample_count")
    )
    ref_sum = (
        (pl.col("ref_avg") ** 2) * pl.col("ref_n")
        if metric == "rmse"
        else pl.col("ref_avg") * pl.col("ref_n")
    )
    per_month = groups.group_by([*keys, "period_start"]).agg(
        model_sum.sum().alias("s_model"),
        pl.col("sample_count").sum().alias("n_model"),
        ref_sum.sum().alias("s_ref"),
        pl.col("ref_n").sum().alias("n_ref"),
    )
    packed = per_month.group_by(keys).agg(
        pl.struct(["s_model", "n_model", "s_ref", "n_ref"]).alias("months")
    )

    def se(months: list[dict]) -> float | None:
        m = len(months)
        if m < 2:
            return None
        ts_model = sum(x["s_model"] for x in months)
        tn_model = sum(x["n_model"] for x in months)
        ts_ref = sum(x["s_ref"] for x in months)
        tn_ref = sum(x["n_ref"] for x in months)
        thetas = []
        for x in months:
            sm, nm = ts_model - x["s_model"], tn_model - x["n_model"]
            sr, nr = ts_ref - x["s_ref"], tn_ref - x["n_ref"]
            if nm <= 0 or nr <= 0:
                return None
            model_value = math.sqrt(sm / nm) if metric == "rmse" else sm / nm
            ref_value = math.sqrt(sr / nr) if metric == "rmse" else sr / nr
            thetas.append(100 * (1 - model_value / ref_value))
        mean = sum(thetas) / m
        return math.sqrt((m - 1) / m * sum((t - mean) ** 2 for t in thetas))

    return packed.with_columns(
        pl.col("months").map_elements(se, return_dtype=pl.Float64).alias("skill_se"),
        pl.col("months").list.len().cast(pl.Int64).alias("n_months"),
    ).drop("months")


def _jackknife_tail_penalty(
    groups: pl.DataFrame, keys: list[str]
) -> pl.DataFrame:
    """Delete-one-month SE for skill(>P95) minus skill(all)."""
    per_month = (
        groups.filter(pl.col("obs_bucket").is_in(["all", "gt_q95"]))
        .group_by([*keys, "period_start", "obs_bucket"])
        .agg(
            (pl.col("avg") * pl.col("sample_count")).sum().alias("s_model"),
            pl.col("sample_count").sum().alias("n_model"),
            (pl.col("ref_avg") * pl.col("ref_n")).sum().alias("s_ref"),
            pl.col("ref_n").sum().alias("n_ref"),
        )
    )
    packed = per_month.group_by(keys).agg(
        pl.struct(
            ["period_start", "obs_bucket", "s_model", "n_model", "s_ref", "n_ref"]
        ).alias("rows"),
        pl.col("period_start").n_unique().cast(pl.Int64).alias("n_months"),
    )

    def se(rows: list[dict]) -> float | None:
        by_bucket: dict[str, dict[object, dict]] = {"all": {}, "gt_q95": {}}
        for row in rows:
            by_bucket[row["obs_bucket"]][row["period_start"]] = row
        months = sorted(set(by_bucket["all"]) & set(by_bucket["gt_q95"]))
        if len(months) < 2:
            return None
        totals: dict[str, tuple[float, int, float, int]] = {}
        for bucket in ("all", "gt_q95"):
            values = [by_bucket[bucket][month] for month in months]
            totals[bucket] = (
                sum(value["s_model"] for value in values),
                sum(value["n_model"] for value in values),
                sum(value["s_ref"] for value in values),
                sum(value["n_ref"] for value in values),
            )
        thetas = []
        for month in months:
            skills = {}
            for bucket in ("all", "gt_q95"):
                sm, nm, sr, nr = totals[bucket]
                omitted = by_bucket[bucket][month]
                sm -= omitted["s_model"]
                nm -= omitted["n_model"]
                sr -= omitted["s_ref"]
                nr -= omitted["n_ref"]
                if nm <= 0 or nr <= 0:
                    return None
                skills[bucket] = 100 * (1 - (sm / nm) / (sr / nr))
            thetas.append(skills["gt_q95"] - skills["all"])
        mean = sum(thetas) / len(thetas)
        return math.sqrt(
            (len(thetas) - 1)
            / len(thetas)
            * sum((theta - mean) ** 2 for theta in thetas)
        )

    return packed.with_columns(
        pl.col("rows").map_elements(se, return_dtype=pl.Float64).alias("skill_se"),
    ).drop("rows")


def build(suffix: str = "") -> pl.DataFrame:
    df = _load_sources(suffix)
    members = _member_models(df)
    scoped = _scope_frame(df, members)
    full = scoped.filter(
        (pl.col("period_kind") == "full") & (pl.col("sample_count") >= MIN_SAMPLES)
    )
    eligibility_keys = [
        "track",
        "model",
        "variable",
        "obs_bucket",
        "debias",
        "family",
        "metric",
        "country",
        "prediction_timedelta",
        "lead_scope",
    ]
    eligible = full.select(eligibility_keys).unique()
    month = scoped.filter(pl.col("period_kind") == "month").join(
        eligible, on=eligibility_keys, how="inner"
    )

    parts: list[pl.DataFrame] = []
    base_cols = [
        "track",
        "model",
        "variable",
        "obs_bucket",
        "lead_scope",
        "debias",
        "kind",
        "country",
        "value",
        "skill_se",
        "n_months",
        "n_leads",
        "grid_leads",
        "n_samples",
    ]

    def finish(
        frame: pl.DataFrame, kind: str, *, country_col: bool = False
    ) -> pl.DataFrame:
        out = frame.with_columns(pl.lit(kind).alias("kind"))
        if not country_col:
            out = out.with_columns(pl.lit(None, dtype=pl.String).alias("country"))
        for col, dtype in (("skill_se", pl.Float64), ("n_months", pl.Int64)):
            if col not in out.columns:
                out = out.with_columns(pl.lit(None, dtype=dtype).alias(col))
        return out.select(base_cols)

    mean_full = full.filter(pl.col("family") == "mean")
    mean_month = month.filter(pl.col("family") == "mean")

    # -- pooled skill (matched vs reference). PRIMARY metric: MAE (linear
    # pooling, robust to noisy station reports); RMSE-based skill kept as a
    # separate kind for the appendix.
    cells_full = _matched_cells(mean_full, "mae")
    skill = _skill_from_cells(cells_full, _SKILL_KEYS, "mae")
    cells_month = _matched_cells(mean_month, "mae")
    jk = _jackknife(cells_month, _SKILL_KEYS)
    skill = skill.join(jk, on=_SKILL_KEYS, how="left")
    parts.append(finish(skill, "skill_pct"))

    penalty_keys = [
        "track",
        "model",
        "variable",
        "debias",
        "lead_scope",
    ]
    all_skill = skill.filter(pl.col("obs_bucket") == "all").select(
        *penalty_keys,
        pl.col("value").alias("all_value"),
    )
    tail_skill = skill.filter(pl.col("obs_bucket") == "gt_q95").select(
        *penalty_keys,
        pl.col("value").alias("tail_value"),
        "n_leads",
        "grid_leads",
        "n_samples",
    )
    penalty = (
        tail_skill.join(all_skill, on=penalty_keys, how="inner")
        .with_columns(
            (pl.col("tail_value") - pl.col("all_value")).alias("value"),
            pl.lit("gt_q95_minus_all").alias("obs_bucket"),
        )
        .drop("tail_value", "all_value")
    )
    penalty_jk = _jackknife_tail_penalty(cells_month, penalty_keys)
    penalty = penalty.join(penalty_jk, on=penalty_keys, how="left")
    parts.append(finish(penalty, "tail_penalty"))

    cells_full_rmse = _matched_cells(mean_full, "rmse")
    skill_rmse = _skill_from_cells(cells_full_rmse, _SKILL_KEYS, "rmse")
    cells_month_rmse = _matched_cells(mean_month, "rmse")
    jk_rmse = _jackknife(cells_month_rmse, _SKILL_KEYS, "rmse")
    skill_rmse = skill_rmse.join(jk_rmse, on=_SKILL_KEYS, how="left")
    parts.append(finish(skill_rmse, "skill_pct_rmse"))

    # -- raw pooled rmse and pooled bias (all models incl. reference) --------
    pool_keys = _SKILL_KEYS
    parts.append(finish(_pool(mean_full, pool_keys, "rmse"), "rmse"))
    parts.append(finish(_pool(mean_full, pool_keys, "mae"), "mae"))
    parts.append(finish(_pool(mean_full, pool_keys, "bias"), "bias"))

    # -- crps/mae ratio, family='crps' only (never mixed with 'mean') --------
    crps_full = full.filter(pl.col("family") == "crps")
    if crps_full.height:
        c = _pool(crps_full, pool_keys, "crps").rename({"value": "crps"})
        m = _pool(crps_full, pool_keys, "mae").select(
            [*pool_keys, pl.col("value").alias("mae")]
        )
        ratio = (
            c.join(m, on=pool_keys, how="inner")
            .with_columns((pl.col("crps") / pl.col("mae")).alias("value"))
            .drop("crps", "mae")
        )
        parts.append(finish(ratio, "crps_mae_ratio"))

    # -- per-country skill rows (heatmaps / positive-country counts) ---------
    country_keys = [*_SKILL_KEYS, "country"]
    cf = cells_full.filter(pl.col("obs_bucket").is_in(COUNTRY_BUCKETS))
    country_skill = _skill_from_cells(cf, country_keys)
    cm = cells_month.filter(pl.col("obs_bucket").is_in(COUNTRY_BUCKETS))
    country_jk = _jackknife(cm, country_keys)
    country_skill = country_skill.join(country_jk, on=country_keys, how="left")
    parts.append(finish(country_skill, "country", country_col=True))

    # -- monthly skill rows (kind='month'): per calendar month, pooled
    # cross-country, MAE-based; feeds the solar month-by-month analysis.
    month_keys = [*_SKILL_KEYS, "period_start"]
    month_skill = _skill_from_cells(cells_month, month_keys, "mae").rename(
        {"period_start": "country"}
    )  # reuse the country column to carry the month label
    parts.append(finish(month_skill, "month", country_col=True))

    result = pl.concat(parts).with_columns(pl.lit(REFERENCE).alias("ref_model"))
    return result.sort(
        [
            "track",
            "kind",
            "variable",
            "lead_scope",
            "obs_bucket",
            "debias",
            "model",
            "country",
        ]
    )


# --------------------------------------------------------------------------
# Independent self-test: recompute 5 random aggregate rows with plain Python
# loops straight from the source parquets (no polars aggregation), and demand
# agreement to 6 decimals.
# --------------------------------------------------------------------------


def _rows_for(
    src: pl.DataFrame,
    row: dict,
    family: str,
    metric: str,
    *,
    model: str | None = None,
    country: str | None = None,
    period_kind: str = "full",
) -> list[dict]:
    """Boolean-mask filter only; all pooling math stays in plain Python."""
    mask = (
        (pl.col("track") == row["track"])
        & (pl.col("model") == (model or row["model"]))
        & (pl.col("variable") == row["variable"])
        & (pl.col("obs_bucket") == row["obs_bucket"])
        & (pl.col("debias") == row["debias"])
        & (pl.col("family") == family)
        & (pl.col("metric") == metric)
        & (pl.col("period_kind") == period_kind)
        & pl.col("prediction_timedelta").is_in(SCOPES[row["lead_scope"]])
        & (pl.col("sample_count") >= MIN_SAMPLES)
    )
    if country is not None:
        mask = mask & (pl.col("country") == country)
    return src.filter(mask).to_dicts()


def _naive_linear(rows: list[dict]) -> float | None:
    n = sum(r["sample_count"] for r in rows)
    return None if not n else sum(r["sample_count"] * r["avg"] for r in rows) / n


def _naive_quadratic(rows: list[dict]) -> float | None:
    n = sum(r["sample_count"] for r in rows)
    if not n:
        return None
    return math.sqrt(sum(r["sample_count"] * r["avg"] ** 2 for r in rows) / n)


def _naive_skill(
    row: dict,
    src: pl.DataFrame,
    country: str | None,
    metric: str = "mae",
    period_kind: str = "full",
) -> float | None:
    """Matched-cell pooling vs reference, dictionaries and loops only."""
    model_rows = _rows_for(
        src, row, "mean", metric, country=country, period_kind=period_kind
    )
    ref_rows = _rows_for(
        src,
        row,
        "mean",
        metric,
        model=REFERENCE,
        country=country,
        period_kind=period_kind,
    )
    ref_index = {(r["country"], r["prediction_timedelta"]): r for r in ref_rows}
    matched = [
        (r, ref_index[(r["country"], r["prediction_timedelta"])])
        for r in model_rows
        if (r["country"], r["prediction_timedelta"]) in ref_index
    ]
    if not matched:
        return None
    pool = _naive_quadratic if metric == "rmse" else _naive_linear
    rm = pool([m for m, _ in matched])
    rr = pool([f for _, f in matched])
    return 100 * (1 - rm / rr)


def _naive_value(row: dict, src: pl.DataFrame, suffix: str = "") -> float | None:
    kind = row["kind"]
    if kind in ("rmse", "mae", "bias"):
        rows = _rows_for(src, row, "mean", kind)
        return _naive_quadratic(rows) if kind == "rmse" else _naive_linear(rows)
    if kind == "skill_pct_rmse":
        return _naive_skill(row, src, None, metric="rmse")
    if kind == "month":
        month_src = _load_sources(suffix).filter(
            pl.col("period_start") == row["country"]
        )
        return _naive_skill(row, month_src, None, metric="mae", period_kind="month")
    return _naive_skill(row, src, row["country"] if kind == "country" else None)


def self_test(
    result: pl.DataFrame, n: int = 5, seed: int = 20260718, suffix: str = ""
) -> bool:
    src = _load_sources(suffix).filter(pl.col("period_kind") == "full")
    rng = random.Random(seed)  # noqa: S311 -- reproducible sampling, not crypto
    candidates = result.filter(~pl.col("kind").is_in(["month", "tail_penalty"]))
    # one candidate per kind first, then fill randomly
    kinds = candidates["kind"].unique().to_list()
    picks: list[dict] = []
    for kind in rng.sample(kinds, min(len(kinds), n)):
        sub = candidates.filter(pl.col("kind") == kind)
        picks.append(sub.row(rng.randrange(sub.height), named=True))
    while len(picks) < n:
        picks.append(candidates.row(rng.randrange(candidates.height), named=True))

    ok = True
    for row in picks:
        naive = _naive_value(row, src, suffix)
        got = row["value"]
        match = naive is not None and abs(naive - got) < 1e-6
        ok &= match
        print(
            f"  [{'OK ' if match else 'BAD'}] {row['kind']:15s} {row['track']} "
            f"{row['model']} {row['variable'].split('_at_')[0]} "
            f"{row['obs_bucket']} {row['lead_scope']} debias={row['debias']} "
            f"country={row['country']}: parquet={got:.8f} naive="
            f"{naive if naive is None else f'{naive:.8f}'}"
        )
    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=sorted(VARIANT_SUFFIXES),
        default="window",
        help="Which bucket definition to aggregate. 'window' is the released "
        "in-window percentile dataset; 'climatology' uses the ERA5 1991-2020 "
        "thresholds and 'window_matched' is its sample-identical in-window "
        "counterpart (both from extract_climatology_metrics.py).",
    )
    args = parser.parse_args()
    suffix = VARIANT_SUFFIXES[args.variant]
    out_path = DERIVED / f"final_aggregates{suffix}.parquet"

    # The raw precipitation pull is intentionally not committed because it is
    # large. A fresh extraction supplies bucketed_metrics_precip.parquet. For
    # an offline rebuild from the public compact artifacts, preserve the
    # already-published precipitation slice explicitly and record its source
    # aggregate hash rather than silently dropping the variable.
    preserved_precip: pl.DataFrame | None = None
    preserved_from_sha256: str | None = None
    precip_source = DERIVED / "bucketed_metrics_precip.parquet"
    if not precip_source.exists() and PRESERVED_PRECIP.exists():
        preserved_from_sha256 = hashlib.sha256(
            PRESERVED_PRECIP.read_bytes()
        ).hexdigest()
        preserved_precip = pl.read_parquet(PRESERVED_PRECIP)
        if preserved_precip.is_empty():
            preserved_precip = None
            preserved_from_sha256 = None

    rebuilt = build(suffix)
    ok = self_test(rebuilt, suffix=suffix)
    result = rebuilt
    preserved_ok = True
    if preserved_precip is not None:
        if not rebuilt.filter(pl.col("variable") == PRECIP).is_empty():
            raise RuntimeError("cannot preserve precipitation over rebuilt rows")
        key_columns = [
            "track",
            "model",
            "variable",
            "obs_bucket",
            "lead_scope",
            "debias",
            "kind",
            "country",
        ]
        preserved_ok = (
            preserved_precip.schema == rebuilt.schema
            and not preserved_precip.select(key_columns).is_duplicated().any()
            and preserved_precip["value"].is_not_null().all()
        )
        if not preserved_ok:
            raise RuntimeError("preserved precipitation slice failed validation")
        result = pl.concat([rebuilt, preserved_precip]).sort(
            [
                "track",
                "kind",
                "variable",
                "lead_scope",
                "obs_bucket",
                "debias",
                "model",
                "country",
            ]
        )

    result.write_parquet(out_path)
    print(f"wrote {out_path} ({result.height} rows)")
    summary = result.group_by(["track", "kind"]).agg(pl.len()).sort(["track", "kind"])
    print(summary)
    status: dict[str, object] = {
        "rows": result.height,
        "self_test": "PASS" if ok and preserved_ok else "FAIL",
        "precipitation_source": (
            "raw bucketed_metrics_precip.parquet"
            if precip_source.exists()
            else "data/derived/precip_aggregates_compact.parquet"
        ),
    }
    if preserved_precip is not None:
        status.update(
            {
                "preserved_precip_rows": preserved_precip.height,
                "preserved_from_sha256": preserved_from_sha256,
                "preserved_validation": "PASS",
            }
        )
    (DERIVED / f"final_aggregates{suffix}_status.json").write_text(
        json.dumps(status, indent=2) + "\n"
    )
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
