"""Plot change in MAE skill from all conditions to the >P95 regime."""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.patches import Patch

from style import COLORS, MODEL_ORDER, REFERENCE, TEMP, WIND, apply_style

REPO = Path(__file__).resolve().parents[1]
SUFFIX = os.environ.get("EXTREMES_VARIANT", "_climatology")
DATA = REPO / "data" / "derived" / f"final_aggregates{SUFFIX}.parquet"
OUT = REPO / "figures" / "fig_tail_penalty.png"
SHORT = {
    "ept2_1_europa": "Europa",
    "ept2_hrrr": "HRRR",
    "ept2_reasoning": "Reasoning",
    "ept2_e": "EPT-2e",
    "aurora": "Aurora",
    "aifs_ens": "AIFS ENS",
    "aifs": "AIFS",
    "ecmwf_ens": "ENS",
    "noaa_gfs_single": "GFS",
    "icon_global": "ICON",
}


def _penalties(
    data: pl.DataFrame, variable: str, debias: bool
) -> dict[str, tuple[float, float | None]]:
    frame = data.filter(
        (pl.col("track") == "track_a")
        & (pl.col("kind") == "tail_penalty")
        & (pl.col("variable") == variable)
        & (pl.col("lead_scope") == "h6_48")
        & (pl.col("debias") == debias)
        & pl.col("country").is_null()
    )
    return {
        row["model"]: (row["value"], row["skill_se"])
        for row in frame.iter_rows(named=True)
    }


def main() -> None:
    apply_style()
    data = pl.read_parquet(DATA)
    track_a_models = data.filter(
        (pl.col("track") == "track_a")
        & (pl.col("kind") == "skill_pct")
        & (pl.col("lead_scope") == "h6_48")
    )["model"].unique().to_list()
    models = [
        model
        for model in MODEL_ORDER
        if model != REFERENCE and model in track_a_models
    ]
    x = np.arange(len(models))
    width = 0.38
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 5.2), sharex=True)
    for ax, variable, title in zip(
        axes,
        (WIND, TEMP),
        ("10 m wind speed", "2 m temperature"),
        strict=True,
    ):
        raw = _penalties(data, variable, False)
        corrected = _penalties(data, variable, True)
        colors = [COLORS[model] for model in models]
        raw_values = [raw.get(model, (np.nan, None))[0] for model in models]
        raw_errors = [raw.get(model, (np.nan, np.nan))[1] or np.nan for model in models]
        corrected_values = [
            corrected.get(model, (np.nan, None))[0] for model in models
        ]
        corrected_errors = [
            corrected.get(model, (np.nan, np.nan))[1] or np.nan for model in models
        ]
        ax.bar(
            x - width / 2,
            raw_values,
            width,
            color=colors,
            alpha=0.35,
            edgecolor="0.3",
            linewidth=0.4,
            yerr=raw_errors,
            error_kw={"linewidth": 0.6, "ecolor": "0.25"},
        )
        ax.bar(
            x + width / 2,
            corrected_values,
            width,
            color=colors,
            edgecolor="0.25",
            linewidth=0.4,
            yerr=corrected_errors,
            error_kw={"linewidth": 0.6, "ecolor": "0.25"},
        )
        ax.axhline(0, color="black", linewidth=0.9)
        ax.set_ylabel("Tail $-$ all skill (points)")
        ax.set_title(title)
    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels(
        [SHORT.get(model, model) for model in models],
        rotation=35,
        ha="right",
        fontsize=8,
    )
    fig.legend(
        handles=[
            Patch(facecolor="0.4", alpha=0.35, edgecolor="0.3", label="Raw"),
            Patch(facecolor="0.4", edgecolor="0.25", label="Bias-corrected"),
        ],
        loc="upper right",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.98, 0.965),
    )
    fig.suptitle(
        "Change in MAE skill from all conditions to the >P95 regime",
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(OUT, dpi=250)
    plt.close(fig)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
