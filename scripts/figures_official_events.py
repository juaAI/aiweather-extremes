"""Generate the event comparison figure and appendix tables."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from qe_client import PROJECT_ROOT
from style import COLORS, DISPLAY, MARKERS, MODEL_ORDER, SAVE_DPI, apply_style

DERIVED = PROJECT_ROOT / "data" / "derived"
MAIN_FIGURES = PROJECT_ROOT / "figures"
TABLES = PROJECT_ROOT / "paper" / "tables"

TEMP_SKILL = DERIVED / "official_temperature_event_skill.parquet"
WIND_SKILL = DERIVED / "official_wind_event_skill.parquet"
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


def combined_main_figure() -> None:
    temp = _headline(TEMP_SKILL)
    wind = _headline(WIND_SKILL)
    temp_lookup = {row["model"]: row for row in temp.iter_rows(named=True)}
    wind_lookup = {row["model"]: row for row in wind.iter_rows(named=True)}
    models = _models(temp, wind)
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 4.8), sharey=True)
    for ax, lookup, title in (
        (axes[0], temp_lookup, "Temperature records"),
        (axes[1], wind_lookup, "Windstorms"),
    ):
        bounds = [
            bound
            for row in lookup.values()
            for bound in (
                row["value"] - row["skill_se"],
                row["value"] + row["skill_se"],
            )
        ]
        lower, upper = min(-5.0, min(bounds)), max(5.0, max(bounds))
        pad = 0.07 * (upper - lower)
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
                markeredgewidth=0.7,
                markersize=5.5,
                capsize=3,
                linewidth=1.4,
                zorder=3,
            )
        for index in range(0, len(models), 2):
            ax.axhspan(index - 0.5, index + 0.5, color="0.96", zorder=0)
        ax.axvline(0, color="black", linewidth=0.8, linestyle=":")
        ax.set_xlim(lower - pad, upper + pad)
        ax.set_ylim(len(models) - 0.5, -0.5)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("MAE skill vs IFS (%)", fontsize=8.5)
        ax.grid(axis="x", alpha=0.22)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="x", labelsize=7.5)
    axes[0].set_yticks(np.arange(len(models)))
    axes[0].set_yticklabels(
        [DISPLAY.get(model, model) for model in models], fontsize=8
    )
    axes[1].tick_params(axis="y", labelleft=False)
    fig.subplots_adjust(left=0.29, right=0.99, top=0.92, bottom=0.15, wspace=0.12)
    path = MAIN_FIGURES / "fig7_official_events.png"
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
    TABLES.mkdir(parents=True, exist_ok=True)
    combined_main_figure()
    skill_table()
    catalog_table()


if __name__ == "__main__":
    main()
