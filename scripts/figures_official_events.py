"""Generate appendix figures and tables for source-defined event case studies."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.colors import TwoSlopeNorm

from qe_client import PROJECT_ROOT
from style import COLORS, DISPLAY, MARKERS, MODEL_ORDER, SAVE_DPI, apply_style

DERIVED = PROJECT_ROOT / "data" / "derived"
FIGURES = PROJECT_ROOT / "figures" / "appendix"
TABLES = PROJECT_ROOT / "paper" / "tables"

TEMP_SKILL = DERIVED / "official_temperature_event_skill.parquet"
WIND_SKILL = DERIVED / "official_wind_event_skill.parquet"
TEMP_EPISODE = DERIVED / "official_temperature_event_skill_by_episode.parquet"
WIND_EPISODE = DERIVED / "official_wind_event_skill_by_episode.parquet"
CATALOG = DERIVED / "official_event_catalog.parquet"

REFERENCE = "ecmwf_ifs_single"
SCOPE = "h6_48"


def _models(*frames: pl.DataFrame) -> list[str]:
    available: set[str] = set()
    for frame in frames:
        available.update(frame["model"].unique().to_list())
    return [
        model
        for model in MODEL_ORDER
        if model != REFERENCE and model in available
    ]


def _headline(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path).filter(
        (pl.col("lead_scope") == SCOPE) & (pl.col("record_type") == "high")
    )


def _forest_figure(frame: pl.DataFrame, filename: str) -> None:
    lookup = {row["model"]: row for row in frame.iter_rows(named=True)}
    event_counts = frame["n_episodes"].unique().to_list()
    sample_counts = frame["n_samples"].unique().to_list()
    if len(event_counts) != 1 or len(sample_counts) != 1:
        raise RuntimeError("Expected identical event/sample coverage across models")
    models = [
        model
        for model in _models(frame)
        if lookup.get(model, {}).get("n_episodes", 0) >= 2
    ]
    finite_bounds = [
        bound
        for row in lookup.values()
        if row["n_episodes"] >= 2 and row["skill_se"] is not None
        for bound in (
            row["value"] - row["skill_se"],
            row["value"] + row["skill_se"],
        )
    ]
    lower = min(-5.0, min(finite_bounds))
    upper = max(5.0, max(finite_bounds))
    padding = 0.08 * (upper - lower)
    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    y = np.arange(len(models))
    for index, model in enumerate(models):
        row = lookup[model]
        ax.errorbar(
            row["value"],
            index,
            xerr=row["skill_se"],
            fmt=MARKERS.get(model, "o"),
            color=COLORS.get(model, "0.35"),
            markerfacecolor=COLORS.get(model, "0.35"),
            markeredgecolor="white",
            markeredgewidth=0.8,
            markersize=7,
            capsize=4,
            linewidth=1.7,
            zorder=3,
        )
    for band in np.arange(-0.5, len(models), 2):
        ax.axhspan(band, band + 1, color="0.96", zorder=0)
    ax.axvline(0, color="black", linewidth=0.9, linestyle=":")
    ax.set_xlim(lower - padding, upper + padding)
    ax.set_xlabel("MAE skill relative to ECMWF IFS (%)")
    ax.set_yticks(y)
    ax.set_yticklabels([DISPLAY.get(model, model) for model in models])
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    ax.grid(axis="y", visible=False)
    fig.subplots_adjust(left=0.34, right=0.98, top=0.98, bottom=0.16)
    path = FIGURES / filename
    fig.savefig(path, dpi=SAVE_DPI, bbox_inches="tight")
    plt.close(fig)
    print("wrote", path)


def pooled_figures() -> None:
    _forest_figure(
        _headline(TEMP_SKILL),
        "appF_official_temperature_event_skill.png",
    )
    _forest_figure(
        _headline(WIND_SKILL),
        "appF_official_wind_event_skill.png",
    )


def _episode_matrix(
    frame: pl.DataFrame, models: list[str]
) -> tuple[np.ndarray, list[str]]:
    sub = frame.filter(
        (pl.col("lead_scope") == SCOPE) & (pl.col("record_type") == "high")
    )
    episodes = sorted(sub["episode_id"].unique().to_list())
    values = {
        (row["model"], row["episode_id"]): row["skill"]
        for row in sub.iter_rows(named=True)
    }
    matrix = np.full((len(models), len(episodes)), np.nan)
    for row, model in enumerate(models):
        for col, episode in enumerate(episodes):
            value = values.get((model, episode))
            if value is not None:
                matrix[row, col] = value
    return matrix, episodes


def _event_labels(catalog: pl.DataFrame, variable: str) -> dict[str, str]:
    short = {
        "temp_dec2025": "Dec warmth",
        "temp_feb2026": "Feb warmth",
        "temp_apr2026": "Apr warm spell",
        "temp_may2026": "May heatwave",
        "temp_jun2026": "Jun heatwave",
        "wind_sep2025": "North Sea",
        "wind_amy2025": "Amy",
        "wind_benjamin2025": "Benjamin",
        "wind_goretti2026": "Goretti",
        "wind_nils2026": "Nils",
        "wind_marlis2026": "Marlis",
        "wind_deborah2026": "Deborah",
    }
    return {
        row["episode_id"]: short.get(row["episode_id"], row["event_name"])
        for row in catalog.filter(
            pl.col("variable") == variable
        ).iter_rows(named=True)
    }


def episode_heatmap() -> None:
    temp = pl.read_parquet(TEMP_EPISODE)
    wind = pl.read_parquet(WIND_EPISODE)
    models = _models(temp, wind)
    catalog = pl.read_parquet(CATALOG)
    fig, axes = plt.subplots(2, 1, figsize=(8.4, 8.0))
    norm = TwoSlopeNorm(vmin=-50, vcenter=0, vmax=50)
    image = None
    for ax, frame, variable, title in (
        (axes[0], temp, "temperature", "Record-temperature events"),
        (axes[1], wind, "wind", "European windstorms"),
    ):
        matrix, episodes = _episode_matrix(frame, models)
        labels = _event_labels(catalog, variable)
        image = ax.imshow(matrix, cmap="RdBu", norm=norm, aspect="auto")
        ax.set_yticks(np.arange(len(models)))
        ax.set_yticklabels([DISPLAY.get(model, model) for model in models])
        ax.set_xticks(np.arange(len(episodes)))
        ax.set_xticklabels(
            [labels.get(episode, episode) for episode in episodes],
            rotation=20,
            ha="right",
            fontsize=8,
        )
        ax.set_title(title)
        for row in range(matrix.shape[0]):
            for col in range(matrix.shape[1]):
                value = matrix[row, col]
                if np.isfinite(value):
                    color = "white" if abs(value) >= 28 else "black"
                    ax.text(
                        col,
                        row,
                        f"{value:+.1f}",
                        ha="center",
                        va="center",
                        fontsize=6.3,
                        color=color,
                    )
    assert image is not None
    colorbar = fig.colorbar(
        image, ax=axes, orientation="horizontal", fraction=0.035, pad=0.09
    )
    colorbar.set_label(
        "MAE skill vs ECMWF IFS (%) \u2014 colours clipped at \u00b150%"
    )
    fig.suptitle("Model skill by source-defined event (6\u201348 h, debiased)")
    fig.subplots_adjust(left=0.25, right=0.98, top=0.94, bottom=0.13, hspace=0.62)
    path = FIGURES / "appF_official_event_heatmap.png"
    fig.savefig(path, dpi=SAVE_DPI, bbox_inches="tight")
    plt.close(fig)
    print("wrote", path)


def _fmt(value: float | None, se: float | None) -> str:
    if value is None:
        return "--"
    if se is None:
        return f"{value:+.1f}"
    return f"{value:+.1f}\\,({se:.1f})"


def skill_table() -> None:
    temp = _headline(TEMP_SKILL)
    wind = _headline(WIND_SKILL)
    models = _models(temp, wind)
    temp_rows = {row["model"]: row for row in temp.iter_rows(named=True)}
    wind_rows = {row["model"]: row for row in wind.iter_rows(named=True)}
    if (
        len(temp["n_episodes"].unique()) != 1
        or len(temp["n_samples"].unique()) != 1
        or len(wind["n_episodes"].unique()) != 1
        or len(wind["n_samples"].unique()) != 1
    ):
        raise RuntimeError("Expected common coverage for compact event table")
    lines = [
        r"\begin{tabular}{@{}lrr@{}}",
        r"\toprule",
        r"Model & Temperature events & Windstorms \\",
        r"\midrule",
    ]
    for index, model in enumerate(models):
        t = temp_rows.get(model)
        w = wind_rows.get(model)
        t_cell = (
            "--"
            if t is None
            else _fmt(t["value"], t["skill_se"])
        )
        w_cell = (
            "--"
            if w is None
            else _fmt(w["value"], w["skill_se"])
        )
        row = (
            f"{DISPLAY.get(model, model)} & "
            + f"{t_cell} & {w_cell}"
            + r" \\"
        )
        if index < len(models) - 1:
            row += r"\addlinespace[0.25em]"
        lines.append(row)
    lines += [r"\bottomrule", r"\end{tabular}"]
    path = TABLES / "t_official_event_skill.tex"
    path.write_text("\n".join(lines) + "\n")
    print("wrote", path)


def _escape(text: str) -> str:
    return (
        text.replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
    )


def catalog_table() -> None:
    catalog = pl.read_parquet(CATALOG).sort(["variable", "start_date"])
    lines = [
        r"\begin{tabular}{@{}lllp{5.2cm}@{}}",
        r"\toprule",
        r"Variable & Event & Dates & Affected countries \\",
        r"\midrule",
    ]
    rows = list(catalog.iter_rows(named=True))
    for index, row in enumerate(rows):
        dates = (
            f"{row['start_date']}"
            if row["start_date"] == row["end_date"]
            else f"{row['start_date']}--{row['end_date']}"
        )
        line = (
            f"{row['variable'].title()} & {_escape(row['event_name'])} & "
            f"{dates} & {_escape(', '.join(row['countries']))} "
            + r"\\"
        )
        if index < len(rows) - 1:
            line += r"\addlinespace[0.2em]"
        lines.append(line)
    lines += [r"\bottomrule", r"\end{tabular}"]
    path = TABLES / "t_official_event_catalog.tex"
    path.write_text("\n".join(lines) + "\n")
    print("wrote", path)


def main() -> None:
    apply_style()
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    pooled_figures()
    skill_table()
    catalog_table()


if __name__ == "__main__":
    main()
