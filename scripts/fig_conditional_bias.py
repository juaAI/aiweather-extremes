"""Compare observation- and forecast-conditioned bias at 48 h."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.patches import Patch

from style import COLORS, DISPLAY, LINESTYLES, MARKERS, MODEL_ORDER, REFERENCE, TEMP, WIND, apply_style

REPO = Path(__file__).resolve().parents[1]
AGG = REPO / "data" / "derived" / "final_aggregates_climatology.parquet"
FORECAST = REPO / "data" / "derived" / "forecast_conditioned_bias_climatology.parquet"
OUT = REPO / "figures" / "fig_conditional_bias_comparison.png"
BUCKETS = ["lt_q5", "q5_q25", "q25_q75", "q75_q95", "gt_q95"]
LABELS = ["<P5", "P5–25", "P25–75", "P75–95", ">P95"]
HIGHLIGHTS = [REFERENCE, "aifs", "aifs_ens", "ept2_1_europa"]


def _observation_frame(data: pl.DataFrame, variable: str) -> pl.DataFrame:
    return data.filter(
        (pl.col("track") == "track_a")
        & (pl.col("variable") == variable)
        & (pl.col("kind") == "bias")
        & (pl.col("lead_scope") == "lead_48")
        & pl.col("debias")
        & pl.col("country").is_null()
        & pl.col("obs_bucket").is_in(BUCKETS)
    ).select("model", pl.col("obs_bucket").alias("bucket"), "value")


def _forecast_frame(data: pl.DataFrame, variable: str) -> pl.DataFrame:
    return data.filter(
        (pl.col("country") == "pooled")
        & (pl.col("variable") == variable)
        & pl.col("debias")
        & pl.col("forecast_bucket").is_in(BUCKETS)
    ).select("model", pl.col("forecast_bucket").alias("bucket"), pl.col("bias").alias("value"))


def _series(frame: pl.DataFrame, model: str) -> np.ndarray:
    values = []
    for bucket in BUCKETS:
        row = frame.filter((pl.col("model") == model) & (pl.col("bucket") == bucket))
        values.append(np.nan if row.is_empty() else row["value"][0])
    return np.asarray(values, dtype=float)


def main() -> None:
    apply_style()
    observed = pl.read_parquet(AGG)
    forecast = pl.read_parquet(FORECAST)
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.4), sharex=True)
    for row_index, (variable, label, unit) in enumerate(
        ((WIND, "10 m wind speed", "m/s"), (TEMP, "2 m temperature", "°C"))
    ):
        frames = (
            _observation_frame(observed, variable),
            _forecast_frame(forecast, variable),
        )
        for column_index, (frame, title) in enumerate(
            zip(frames, ("Conditioned on observation", "Conditioned on forecast"), strict=True)
        ):
            ax = axes[row_index, column_index]
            available = [model for model in MODEL_ORDER if model in frame["model"].unique()]
            curves = np.vstack([_series(frame, model) for model in available])
            x = np.arange(len(BUCKETS))
            ax.fill_between(
                x,
                np.nanmin(curves, axis=0),
                np.nanmax(curves, axis=0),
                color="0.84",
                label="All-model range",
            )
            for model in HIGHLIGHTS:
                if model not in available:
                    continue
                ax.plot(
                    x,
                    _series(frame, model),
                    color=COLORS[model],
                    linestyle=LINESTYLES[model],
                    marker=MARKERS[model],
                    linewidth=1.7,
                    markersize=3.5,
                    label=DISPLAY[model],
                )
            ax.axhline(0, color="black", linestyle=":", linewidth=0.8)
            if row_index == 0:
                ax.set_title(title)
            if column_index == 0:
                ax.set_ylabel(f"{label}\nbias ({unit})")
            ax.set_xticks(x)
            ax.set_xticklabels(LABELS, rotation=35, ha="right", fontsize=7.5)
    handles = [
        Patch(facecolor="0.84", label="All-model range"),
        *[
            plt.Line2D(
                [0],
                [0],
                color=COLORS[model],
                linestyle=LINESTYLES[model],
                marker=MARKERS[model],
                label=DISPLAY[model],
            )
            for model in HIGHLIGHTS
        ],
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=7.5)
    fig.suptitle("Conditional bias at 48 h after domain-mean bias correction")
    fig.tight_layout(rect=(0, 0.1, 1, 0.95))
    fig.savefig(OUT, dpi=250)
    plt.close(fig)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
