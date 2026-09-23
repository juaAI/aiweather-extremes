"""Score source-defined events with server-side full-cohort sample matching."""

from __future__ import annotations

import argparse
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import yaml

from extract_climatology_metrics import INIT_HOURS, TEMP, TRACK_MODELS, WIND
from qe_client import PROJECT_ROOT, QEClient
from style import DISPLAY, MODEL_ORDER

CONFIG_PATH = PROJECT_ROOT / "config" / "official_events.yaml"
DERIVED = PROJECT_ROOT / "data" / "derived"
CACHE = PROJECT_ROOT / "data" / "cache" / "official_event_metrics_api_v1"
REFERENCE = "ecmwf_ifs_single"
MODELS = TRACK_MODELS["track_a"]
LEADS = [hour * 60 for hour in range(6, 49, 6)]
VARIABLES = {"temperature": TEMP, "wind": WIND}


def _iso_start(value: str) -> str:
    return f"{value}T00:00:00Z"


def _iso_end(value: str) -> str:
    return (
        datetime.fromisoformat(value) + timedelta(days=1)
    ).strftime("%Y-%m-%dT00:00:00Z")


def _task_frame(client: QEClient, variable: str, event: dict, country: str) -> pl.DataFrame:
    response = client.metrics(
        models=MODELS,
        geo={"type": "country_key", "value": country},
        start_time=_iso_start(event["start"]),
        end_time=_iso_end(event["end"]),
        variables=[VARIABLES[variable]],
        metrics=["mae", "bias", "rmse"],
        max_lead_minutes=48 * 60,
        debias=True,
        init_hours=INIT_HOURS,
    )
    columns = [
        "model",
        "variable",
        "prediction_timedelta",
        "metric",
        "avg",
        "sample_count",
    ]
    frame = pl.DataFrame(
        {column: response.get(column, []) for column in columns}
    ).filter(pl.col("prediction_timedelta").is_in(LEADS))
    if frame.is_empty():
        return frame
    return frame.with_columns(
        pl.lit(variable).alias("event_variable"),
        pl.lit(event["id"]).alias("episode_id"),
        pl.lit(event["name"]).alias("event_name"),
        pl.lit(country).alias("country"),
    )


def _validate_common_samples(frame: pl.DataFrame) -> None:
    expected = len(MODELS)
    check = (
        frame.group_by(
            "event_variable",
            "episode_id",
            "country",
            "prediction_timedelta",
            "metric",
        )
        .agg(
            pl.col("model").n_unique().alias("n_models"),
            pl.col("sample_count").n_unique().alias("n_sample_counts"),
        )
        .filter(
            (pl.col("n_models") != expected)
            | (pl.col("n_sample_counts") != 1)
        )
    )
    if check.height:
        raise RuntimeError(
            "Server-side event samples are not common across all models:\n"
            f"{check}"
        )


def _event_components(cells: pl.DataFrame) -> pl.DataFrame:
    mae = cells.filter(pl.col("metric") == "mae")
    return mae.group_by(
        "event_variable", "episode_id", "model"
    ).agg(
        (pl.col("avg") * pl.col("sample_count")).sum().alias("mae_sum"),
        pl.col("sample_count").sum().alias("n"),
        pl.col("prediction_timedelta").n_unique().alias("n_leads"),
    )


def _skill_tables(
    cells: pl.DataFrame, variable: str
) -> tuple[pl.DataFrame, pl.DataFrame]:
    comp = _event_components(cells).filter(
        pl.col("event_variable") == variable
    )
    ref = comp.filter(pl.col("model") == REFERENCE).select(
        "episode_id",
        pl.col("mae_sum").alias("ref_mae_sum"),
        pl.col("n").alias("ref_n"),
    )
    joined = comp.filter(pl.col("model") != REFERENCE).join(
        ref, on="episode_id", how="inner"
    )
    per_episode = (
        joined.with_columns(
            (
                100
                * (
                    1
                    - (pl.col("mae_sum") / pl.col("n"))
                    / (pl.col("ref_mae_sum") / pl.col("ref_n"))
                )
            ).alias("skill"),
            pl.lit("high").alias("record_type"),
            pl.lit("h6_48").alias("lead_scope"),
        )
        .select(
            "model",
            "record_type",
            "lead_scope",
            "episode_id",
            "skill",
            pl.col("n").alias("n_samples"),
            "n_leads",
        )
        .sort(["episode_id", "model"])
    )
    packed = joined.group_by("model").agg(
        pl.struct(
            "episode_id", "mae_sum", "n", "ref_mae_sum", "ref_n"
        ).alias("episodes"),
        pl.col("n_leads").max(),
    )

    def aggregate(episodes: list[dict]) -> dict:
        model_sum = sum(row["mae_sum"] for row in episodes)
        model_n = sum(row["n"] for row in episodes)
        ref_sum = sum(row["ref_mae_sum"] for row in episodes)
        ref_n = sum(row["ref_n"] for row in episodes)
        value = 100 * (1 - (model_sum / model_n) / (ref_sum / ref_n))
        leave_one_out = []
        for row in episodes:
            n_model = model_n - row["n"]
            n_ref = ref_n - row["ref_n"]
            if n_model <= 0 or n_ref <= 0:
                continue
            leave_one_out.append(
                100
                * (
                    1
                    - ((model_sum - row["mae_sum"]) / n_model)
                    / ((ref_sum - row["ref_mae_sum"]) / n_ref)
                )
            )
        if len(leave_one_out) >= 2:
            mean = sum(leave_one_out) / len(leave_one_out)
            se = math.sqrt(
                (len(leave_one_out) - 1)
                / len(leave_one_out)
                * sum((value_i - mean) ** 2 for value_i in leave_one_out)
            )
        else:
            se = None
        return {
            "value": value,
            "skill_se": se,
            "n_episodes": len(episodes),
            "n_samples": model_n,
        }

    pooled = (
        packed.with_columns(
            pl.col("episodes")
            .map_elements(
                aggregate,
                return_dtype=pl.Struct(
                    {
                        "value": pl.Float64,
                        "skill_se": pl.Float64,
                        "n_episodes": pl.Int64,
                        "n_samples": pl.Int64,
                    }
                ),
            )
            .alias("summary")
        )
        .unnest("summary")
        .drop("episodes")
        .with_columns(
            pl.lit("high").alias("record_type"),
            pl.lit("h6_48").alias("lead_scope"),
        )
        .select(
            "model",
            "record_type",
            "lead_scope",
            "value",
            "skill_se",
            "n_episodes",
            "n_samples",
            "n_leads",
        )
        .sort("model")
    )
    return pooled, per_episode


def _write_report(
    variable: str, pooled: pl.DataFrame, per_episode: pl.DataFrame
) -> None:
    catalog = yaml.safe_load(CONFIG_PATH.read_text())[variable]
    names = {event["id"]: event["name"] for event in catalog}
    lookup = {row["model"]: row for row in pooled.iter_rows(named=True)}
    lines = [
        f"# {variable.title()} skill on full-cohort common event samples",
        "",
        "All models and IFS are evaluated on identical station, valid-time, "
        "initialisation, and lead samples. Leads are 6--48 h at 6-hourly "
        "intervals; forecasts use the paper's causal bias correction.",
        "",
        "| model | skill (%) | event jackknife SE | events | samples |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in MODEL_ORDER:
        if model == REFERENCE or model not in lookup:
            continue
        row = lookup[model]
        se = "--" if row["skill_se"] is None else f"{row['skill_se']:.1f}"
        lines.append(
            f"| {DISPLAY.get(model, model)} | {row['value']:+.1f} | {se} | "
            f"{row['n_episodes']} | {row['n_samples']:,} |"
        )
    lines += [
        "",
        "## Skill by event",
        "",
        "| event | "
        + " | ".join(
            DISPLAY.get(model, model)
            for model in MODEL_ORDER
            if model != REFERENCE and model in lookup
        )
        + " |",
        "|---"
        + "|---:" * sum(
            model != REFERENCE and model in lookup for model in MODEL_ORDER
        )
        + "|",
    ]
    for episode_id in sorted(per_episode["episode_id"].unique().to_list()):
        values = {
            row["model"]: row["skill"]
            for row in per_episode.filter(
                pl.col("episode_id") == episode_id
            ).iter_rows(named=True)
        }
        lines.append(
            f"| {names.get(episode_id, episode_id)} | "
            + " | ".join(
                f"{values[model]:+.1f}"
                for model in MODEL_ORDER
                if model != REFERENCE and model in lookup
            )
            + " |"
        )
    path = PROJECT_ROOT / "reports" / f"official_{variable}_event_skill.md"
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--api-key", default="localdevkey:localdevsecret")
    args = parser.parse_args()

    config = yaml.safe_load(CONFIG_PATH.read_text())
    tasks = [
        (variable, event, country)
        for variable in ("temperature", "wind")
        for event in config[variable]
        for country in event["countries"]
    ]
    client = QEClient(
        base_url=args.base_url,
        api_key=args.api_key,
        cache_dir=CACHE,
    )
    frames: list[pl.DataFrame] = []
    lock = threading.Lock()
    completed = 0

    def run(task: tuple[str, dict, str]) -> pl.DataFrame:
        nonlocal completed
        frame = _task_frame(client, *task)
        with lock:
            completed += 1
            print(
                f"[{completed}/{len(tasks)}] {task[0]} {task[1]['id']} "
                f"{task[2]} rows={frame.height}",
                flush=True,
            )
        return frame

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        frames = list(pool.map(run, tasks))
    cells = pl.concat([frame for frame in frames if not frame.is_empty()])
    _validate_common_samples(cells)
    for variable in ("temperature", "wind"):
        variable_cells = cells.filter(pl.col("event_variable") == variable)
        cells_path = DERIVED / f"official_{variable}_event_metric_cells.parquet"
        skill_path = DERIVED / f"official_{variable}_event_skill.parquet"
        episode_path = (
            DERIVED / f"official_{variable}_event_skill_by_episode.parquet"
        )
        variable_cells.write_parquet(cells_path)
        pooled, per_episode = _skill_tables(cells, variable)
        pooled.write_parquet(skill_path)
        per_episode.write_parquet(episode_path)
        _write_report(variable, pooled, per_episode)
        print(f"wrote {cells_path} ({variable_cells.height} rows)")
        print(f"wrote {skill_path} ({pooled.height} rows)")
        print(f"wrote {episode_path} ({per_episode.height} rows)")


if __name__ == "__main__":
    main()
