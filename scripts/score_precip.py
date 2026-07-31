"""Offline precipitation scoring in wet-hour climatological regimes.

Precipitation has no station-benchmark API path and no ClickHouse error tables,
so this reproduces the temperature/wind/solar scoring conventions
(``extract_climatology_metrics.py``) entirely offline from the pulled forecasts
and the ingested gauge panel:

  * common-date matching -- an init date is scored only if every model of the
    track produced a forecast for it (ensemble members already averaged to a
    mean at extraction time);
  * trailing-four-week additive debiasing per (model, init-hour, lead), applied
    to each valid week from the four preceding valid weeks, matching
    ``synoptic_station_bias_europe``;
  * observed-value regimes from ERA5 1991--2020 wet-hour thresholds
    (``extract_precip_thresholds.py``), plus the dry mass as its own regime;
  * per (model, lead, country, regime, period, debias) MAE/RMSE/bias, written in
    the same 19-column layout as ``bucketed_metrics.parquet`` so ``aggregates.py``
    folds precipitation in with no schema change.

A companion categorical file scores the heavy-precip exceedance event
(obs >= P95) with a 2x2 contingency per (model, lead, country, period, debias)
for POD/FAR/CSI/frequency-bias downstream.

Outputs:
  data/derived/bucketed_metrics_precip.parquet
  data/derived/precip_categorical.parquet

Run:
    uv run python scripts/score_precip.py [--track track_a] [--model ept2 ...]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import yaml

from qe_client import PROJECT_ROOT

CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "matrix.yaml").read_text())

DERIVED = PROJECT_ROOT / "data" / "derived"
FORECAST_DIR = DERIVED / "precip_forecasts"
OBS_PATH = DERIVED / "precip_obs_hourly.parquet"
THRESHOLDS_PATH = DERIVED / "station_precip_thresholds_era5_1991_2020.parquet"
JOINED_DIR = PROJECT_ROOT / "data" / "cache" / "precip_scored"
BUCKETED_OUT = DERIVED / "bucketed_metrics_precip.parquet"
CATEGORICAL_OUT = DERIVED / "precip_categorical.parquet"

VARIABLE = "precipitation_amount_sum_1h"
WET_MM = 0.1  # Dry/wet boundary, matching the ERA5 wet-hour threshold cutoff.
DEBIAS_WEEKS = 4

# Regime labels are precip-specific (dry mass + wet climatological bands) rather
# than the symmetric lt_q5..gt_q95 of the unbounded variables.
REGIME_ORDER = ["dry", "wet_lt_p50", "p50_p75", "p75_p95", "gt_p95"]

TRACK_MODELS = {
    "track_a": [
        "ecmwf_ens",
        "ecmwf_ifs_single",
        "ept2_1_europa",
        "ept2_e",
        "ept2_hrrr",
        "ept2_reasoning",
        "icon_global",
        "noaa_gfs_single",
    ],
    "track_b": [
        "ecmwf_ifs_single",
        "ept2_1_europa",
        "ept2_hrrr",
        "icon_eu",
        "ecmwf_ens",
    ],
}


def _model_dir(track: str, model: str) -> Path:
    """Forecast directory for (track, model).

    Only ICON-EU was pulled specifically for Track B; the other Track B models
    reuse their Track A pull, whose 2025-09..2026-07 span already covers the
    Track B window. Fall back to Track A when the track-specific dir is absent.
    """
    specific = FORECAST_DIR / track / model
    if specific.exists() and any(specific.glob("*.parquet")):
        return specific
    return FORECAST_DIR / "track_a" / model


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


OBS_REGIME_PATH = JOINED_DIR / "obs_regime.parquet"


def _obs_regime() -> pl.DataFrame:
    """Assign every observed hour a wet-hour climatological regime once."""
    obs = pl.read_parquet(OBS_PATH).select(
        pl.col("station_id"),
        pl.col("country"),
        pl.col("valid_time").dt.replace_time_zone(None).alias("valid_time"),
        pl.col("precip_mm"),
    )
    obs = obs.with_columns(
        pl.col("valid_time").dt.ordinal_day().alias("_doy"),
        (
            pl.col("valid_time").dt.is_leap_year()
            & (pl.col("valid_time").dt.month() > 2)
        ).alias("_leap_after_feb"),
        pl.col("valid_time").dt.hour().cast(pl.UInt8).alias("hour"),
    ).with_columns(
        (pl.col("_doy") - pl.col("_leap_after_feb").cast(pl.Int32))
        .cast(pl.UInt16)
        .alias("climatology_day")
    )

    thr = pl.read_parquet(THRESHOLDS_PATH).select(
        pl.col("station").alias("station_id"),
        "climatology_day",
        "hour",
        "q50",
        "q75",
        "q95",
    )
    joined = obs.join(
        thr, on=["station_id", "climatology_day", "hour"], how="left"
    )
    regime = (
        pl.when(pl.col("precip_mm") < WET_MM)
        .then(pl.lit("dry"))
        .when(pl.col("q50").is_null())
        .then(pl.lit("wet_unclassified"))
        .when(pl.col("precip_mm") < pl.col("q50"))
        .then(pl.lit("wet_lt_p50"))
        .when(pl.col("precip_mm") < pl.col("q75"))
        .then(pl.lit("p50_p75"))
        .when(pl.col("precip_mm") < pl.col("q95"))
        .then(pl.lit("p75_p95"))
        .otherwise(pl.lit("gt_p95"))
        .alias("regime")
    )
    return joined.select(
        "station_id",
        "valid_time",
        "country",
        pl.col("precip_mm").alias("obs_mm"),
        pl.col("q95").alias("thr_p95"),
        regime,
    )


def _common_inits(
    track: str, models: list[str], start: datetime, end: datetime
) -> set[datetime]:
    """Init timestamps within the track window that every model forecast."""
    per_model = []
    for model in models:
        stamps = {
            stamp
            for path in _model_dir(track, model).glob("*.parquet")
            if start
            <= (
                stamp := datetime.strptime(path.stem, "%Y-%m-%dT%H").replace(
                    tzinfo=timezone.utc
                )
            )
            < end
        }
        per_model.append(stamps)
    if not per_model:
        return set()
    return set.intersection(*per_model)


def _join_model(
    track: str,
    model: str,
    common: set[datetime],
) -> Path | None:
    """Stream a model's forecasts joined to observed regimes to a parquet."""
    files = sorted(_model_dir(track, model).glob("*.parquet"))
    keep = sorted(
        path
        for path in files
        if datetime.strptime(path.stem, "%Y-%m-%dT%H").replace(
            tzinfo=timezone.utc
        )
        in common
    )
    if not keep:
        return None
    obs = pl.scan_parquet(OBS_REGIME_PATH)
    fc = pl.scan_parquet(keep).select(
        "station_id",
        "lead",
        "forecast_mm",
        pl.col("init_time").dt.replace_time_zone(None).alias("init_time"),
    ).with_columns(
        (pl.col("init_time") + pl.duration(hours=pl.col("lead"))).alias(
            "valid_time"
        ),
        (pl.col("lead") * 60).cast(pl.Int64).alias("prediction_timedelta"),
        pl.col("init_time").dt.hour().cast(pl.UInt8).alias("init_hour"),
    )
    scored = fc.join(
        obs, on=["station_id", "valid_time"], how="inner"
    ).with_columns(
        (pl.col("forecast_mm") - pl.col("obs_mm")).alias("raw_error"),
        pl.col("valid_time").dt.truncate("1w").alias("valid_week"),
        pl.lit(model).alias("model"),
    ).select(
        "model",
        "country",
        "prediction_timedelta",
        "init_hour",
        "valid_time",
        "valid_week",
        "forecast_mm",
        "obs_mm",
        "thr_p95",
        "regime",
        "raw_error",
    )
    out = JOINED_DIR / f"{track}__{model}.parquet"
    scored.sink_parquet(out)
    return out


# Multiplicative factors are clipped to a physical range so a near-dry trailing
# window cannot produce a runaway scaling; a genuine systematic precip amount
# bias is well inside 0.33-3x.
FACTOR_MIN, FACTOR_MAX = 0.33, 3.0


def _debias_table(paths: list[Path]) -> pl.DataFrame:
    """Trailing-four-week *multiplicative* factor per (model, init_hour, lead).

    Precipitation is zero-bounded and right-skewed, so additive debiasing is
    inappropriate (it can push forecasts negative and inflate MAE). The standard
    correction scales the forecast by sum(obs)/sum(forecast) over a trailing
    window, applied per (model, init-hour, lead) so systematic wet/dry biases are
    removed while zeros stay zero.
    """
    # Pool over init-hour and lead: a per-(init-hour, lead) factor is estimated
    # from too few wet events and, at short leads where physics models barely
    # spin up precip, sum(forecast)->0 blows the ratio to the clip ceiling. The
    # systematic wet/dry amount bias is a model-level property, so one factor per
    # (model, trailing week) over millions of station-hours is stable.
    weekly = (
        pl.scan_parquet(paths)
        .group_by("model", "valid_week")
        .agg(
            pl.col("obs_mm").sum().alias("obs_sum"),
            pl.col("forecast_mm").sum().alias("fc_sum"),
        )
        .collect(engine="streaming")
    )
    # A valid week's factor comes from the four preceding valid weeks.
    lagged = []
    for k in range(1, DEBIAS_WEEKS + 1):
        lagged.append(
            weekly.with_columns(
                (
                    pl.col("valid_week") + pl.duration(weeks=k)
                ).alias("applies_week")
            )
        )
    contributions = pl.concat(lagged)
    weeks = (
        contributions.group_by("model", "applies_week")
        .agg(
            pl.col("obs_sum").sum().alias("obs_sum"),
            pl.col("fc_sum").sum().alias("fc_sum"),
            pl.len().alias("n_weeks"),
        )
        .with_columns(
            # Only a full trailing window gives a stable ratio; a partial window
            # (the first weeks of the record) pins to the clip and wrecks that
            # month. The other variables warm up their debias from 35 days before
            # the track start, but precip has no forecasts/obs before Sep 1, so
            # instead carry the first fully-warmed factor back over the spin-up
            # weeks (nearest reliable calibration) rather than leaving them raw.
            pl.when((pl.col("fc_sum") > 0) & (pl.col("n_weeks") == DEBIAS_WEEKS))
            .then(
                (pl.col("obs_sum") / pl.col("fc_sum")).clip(
                    FACTOR_MIN, FACTOR_MAX
                )
            )
            .otherwise(None)
            .alias("warm_factor")
        )
        .sort("model", "applies_week")
    )
    return (
        weeks.with_columns(
            pl.col("warm_factor")
            .fill_null(strategy="backward")
            .fill_null(strategy="forward")
            .over("model")
            .fill_null(1.0)
            .alias("factor")
        )
        .select("model", "applies_week", "factor")
        .rename({"applies_week": "valid_week"})
    )


def _metric_rows(
    paths: list[Path],
    bias: pl.DataFrame,
    *,
    track: str,
    start: datetime,
    track_end: datetime,
) -> pl.DataFrame:
    scored = (
        pl.scan_parquet(paths)
        .join(
            bias.lazy(),
            on=["model", "valid_week"],
            how="left",
        )
        .with_columns(
            pl.col("factor").fill_null(1.0),
            pl.col("valid_time").dt.truncate("1mo").alias("month_start"),
            pl.col("raw_error").alias("err_raw"),
            (pl.col("forecast_mm") * pl.col("factor") - pl.col("obs_mm")).alias(
                "err_deb"
            ),
        )
    )
    # Both debias variants aggregated in one pass; expand only over (full,
    # monthly) periods and (all, regime) buckets, mirroring the SQL ARRAY JOINs.
    periods = [
        ("full", pl.lit(start.replace(tzinfo=None))),
        ("month", pl.col("month_start")),
    ]
    wide_frames = []
    for period_kind, period_expr in periods:
        withp = scored.with_columns(period_expr.alias("period_start"))
        for bucket_expr in (pl.lit("all"), pl.col("regime")):
            grp = (
                withp.with_columns(bucket_expr.alias("obs_bucket"))
                .group_by(
                    "model",
                    "prediction_timedelta",
                    "obs_bucket",
                    "period_start",
                    "country",
                )
                .agg(
                    pl.col("err_raw").pow(2).mean().sqrt().alias("rmse_false"),
                    pl.col("err_raw").abs().mean().alias("mae_false"),
                    pl.col("err_raw").mean().alias("bias_false"),
                    pl.col("err_deb").pow(2).mean().sqrt().alias("rmse_true"),
                    pl.col("err_deb").abs().mean().alias("mae_true"),
                    pl.col("err_deb").mean().alias("bias_true"),
                    pl.len().alias("sample_count"),
                )
                .with_columns(pl.lit(period_kind).alias("period_kind"))
                .collect(engine="streaming")
            )
            wide_frames.append(grp)
    wide = pl.concat(wide_frames)

    # Melt the two debias variants back into rows.
    debias_frames = []
    for debias in (False, True):
        suffix = "true" if debias else "false"
        debias_frames.append(
            wide.select(
                "model",
                "prediction_timedelta",
                "obs_bucket",
                "period_start",
                "country",
                "period_kind",
                "sample_count",
                pl.col(f"rmse_{suffix}").alias("rmse"),
                pl.col(f"mae_{suffix}").alias("mae"),
                pl.col(f"bias_{suffix}").alias("bias"),
                pl.lit(debias).alias("debias"),
            )
        )
    combined = pl.concat(debias_frames)
    return _finalize(combined, track=track, track_end=track_end)


def _period_end_expr(track_end: datetime) -> pl.Expr:
    end = track_end.replace(tzinfo=None)
    return (
        pl.when(pl.col("period_kind") == "full")
        .then(pl.lit(end))
        .otherwise(pl.col("period_start").dt.offset_by("1mo"))
    )


def _finalize(
    combined: pl.DataFrame, *, track: str, track_end: datetime
) -> pl.DataFrame:
    combined = combined.with_columns(
        _period_end_expr(track_end).alias("period_end")
    )
    metric_frames = []
    for metric in ("rmse", "mae", "bias"):
        metric_frames.append(
            combined.select(
                "model",
                pl.lit(VARIABLE).alias("variable"),
                "prediction_timedelta",
                pl.lit(metric).alias("metric"),
                "obs_bucket",
                pl.col(metric).alias("avg"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_05"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_25"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_50"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_75"),
                pl.lit(None, dtype=pl.Float64).alias("quantile_95"),
                pl.col("sample_count").cast(pl.Int64),
                pl.lit(track).alias("track"),
                "period_kind",
                pl.col("period_start")
                .dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                .alias("period_start"),
                pl.col("period_end")
                .dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                .alias("period_end"),
                "country",
                pl.col("debias").cast(pl.Boolean),
                pl.lit("mean").alias("family"),
            )
        )
    return pl.concat(metric_frames)


def _categorical_rows(
    paths: list[Path],
    bias: pl.DataFrame,
    *,
    track: str,
    start: datetime,
) -> pl.DataFrame:
    """2x2 contingency for the heavy-precip exceedance event (obs >= P95)."""
    scored = (
        pl.scan_parquet(paths)
        .filter(pl.col("thr_p95").is_not_null())
        .join(
            bias.lazy(),
            on=["model", "valid_week"],
            how="left",
        )
        .with_columns(
            pl.col("factor").fill_null(1.0),
            pl.col("valid_time").dt.truncate("1mo").alias("month_start"),
            (pl.col("obs_mm") >= pl.col("thr_p95")).alias("obs_event"),
            (pl.col("forecast_mm") >= pl.col("thr_p95")).alias("fc_event_false"),
            (
                pl.col("forecast_mm") * pl.col("factor") >= pl.col("thr_p95")
            ).alias("fc_event_true"),
        )
    )
    wide_frames = []
    for period_kind, period_expr in (
        ("full", pl.lit(start.replace(tzinfo=None))),
        ("month", pl.col("month_start")),
    ):
        wide_frames.append(
            scored.with_columns(period_expr.alias("period_start"))
            .group_by("model", "prediction_timedelta", "period_start", "country")
            .agg(
                (pl.col("obs_event") & pl.col("fc_event_false")).sum().alias("hits_false"),
                (~pl.col("obs_event") & pl.col("fc_event_false")).sum().alias("fa_false"),
                (pl.col("obs_event") & ~pl.col("fc_event_false")).sum().alias("miss_false"),
                (~pl.col("obs_event") & ~pl.col("fc_event_false")).sum().alias("cn_false"),
                (pl.col("obs_event") & pl.col("fc_event_true")).sum().alias("hits_true"),
                (~pl.col("obs_event") & pl.col("fc_event_true")).sum().alias("fa_true"),
                (pl.col("obs_event") & ~pl.col("fc_event_true")).sum().alias("miss_true"),
                (~pl.col("obs_event") & ~pl.col("fc_event_true")).sum().alias("cn_true"),
            )
            .with_columns(pl.lit(period_kind).alias("period_kind"))
            .collect(engine="streaming")
        )
    wide = pl.concat(wide_frames)
    frames = []
    for debias in (False, True):
        suffix = "true" if debias else "false"
        frames.append(
            wide.select(
                "model",
                "prediction_timedelta",
                "period_start",
                "country",
                "period_kind",
                pl.col(f"hits_{suffix}").alias("hits"),
                pl.col(f"fa_{suffix}").alias("false_alarms"),
                pl.col(f"miss_{suffix}").alias("misses"),
                pl.col(f"cn_{suffix}").alias("correct_negatives"),
                pl.lit(debias).alias("debias"),
                pl.lit(track).alias("track"),
            )
        )
    return pl.concat(frames)


def _score_track(track: str, models: list[str]):
    cfg = CONFIG["tracks"][track]
    start = _parse_utc(cfg["start"])
    end = _parse_utc(cfg["end"])
    common = _common_inits(track, models, start, end)
    print(f"{track}: {len(models)} models, {len(common)} common inits")

    paths = []
    for model in models:
        path = _join_model(track, model, common)
        if path is not None:
            rows = pl.scan_parquet(path).select(pl.len()).collect().item()
            print(f"  {model:18} scored rows={rows:,}", flush=True)
            paths.append(path)
    if not paths:
        raise RuntimeError(f"No scored data for {track}")

    bias = _debias_table(paths)
    metrics = _metric_rows(paths, bias, track=track, start=start, track_end=end)
    categorical = _categorical_rows(paths, bias, track=track, start=start)
    return metrics, categorical


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", action="append", choices=("track_a", "track_b"))
    args = parser.parse_args()
    tracks = args.track or ["track_a", "track_b"]

    if not THRESHOLDS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {THRESHOLDS_PATH}; run extract_precip_thresholds.py first"
        )
    JOINED_DIR.mkdir(parents=True, exist_ok=True)
    print("building observed-hour regimes ...")
    obs_regime = _obs_regime()
    obs_regime.write_parquet(OBS_REGIME_PATH)
    print(f"  {obs_regime.height:,} observed hours classified")

    metric_frames, categorical_frames = [], []
    for track in tracks:
        metrics, categorical = _score_track(track, TRACK_MODELS[track])
        metric_frames.append(metrics)
        categorical_frames.append(categorical)

    metrics = pl.concat(metric_frames).sort(
        "track",
        "period_kind",
        "period_start",
        "country",
        "model",
        "prediction_timedelta",
        "metric",
        "obs_bucket",
        "debias",
    )
    categorical = pl.concat(categorical_frames).sort(
        "track",
        "period_kind",
        "period_start",
        "country",
        "model",
        "prediction_timedelta",
        "debias",
    )
    metrics.write_parquet(BUCKETED_OUT)
    categorical.write_parquet(CATEGORICAL_OUT)
    print(f"wrote {BUCKETED_OUT}")
    print(f"wrote {CATEGORICAL_OUT}")


if __name__ == "__main__":
    main()
