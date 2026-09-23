"""Shared pairwise scoring engine for externally defined event footprints.

Use ``score_official_temperature_events.py`` or
``score_official_windstorms.py``. Event dates, countries, and provenance are
defined in ``config/official_events.yaml`` and expanded to station footprints
by ``build_official_event_footprints.py``.
"""

from __future__ import annotations

import argparse
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import clickhouse_connect
import polars as pl
from clickhouse_connect.driver.external import ExternalData

from extract_climatology_metrics import (
    CANONICAL_SOURCE_SNAPSHOT,
    CONFIG,
    COUNTRIES,
    INIT_HOURS,
    TEMP,
    TRACK_MODELS,
    _bias_cte,
)
from qe_client import PROJECT_ROOT
from style import DISPLAY, MODEL_ORDER

DERIVED = PROJECT_ROOT / "data" / "derived"
CACHE = PROJECT_ROOT / "data" / "cache" / "temperature_record_scoring_v5"
CELLS_OUT = DERIVED / "temperature_record_event_metric_cells.parquet"
SKILL_OUT = DERIVED / "temperature_record_event_skill.parquet"
EPISODE_SKILL_OUT = (
    DERIVED / "temperature_record_event_skill_by_episode.parquet"
)
REPORT_OUT = PROJECT_ROOT / "reports" / "temperature_record_event_skill.md"
VARIABLE_LABEL = "Temperature"
EVENT_LABEL = "warm-record"
COLLECTION_LABEL = "spatially supported ERA5-record episodes"
DIRECT_EVENT_FOOTPRINTS: Path | None = None

REFERENCE = "ecmwf_ifs_single"
TRACK_A_MODELS = TRACK_MODELS["track_a"]
LEADS = [hour * 60 for hour in range(6, 49, 6)]
SCOPES = {
    **{f"lead_{hour}": [hour * 60] for hour in (6, 12, 24, 48)},
    "h6_48": LEADS,
}
_thread_local = threading.local()


def _client():
    client = getattr(_thread_local, "clickhouse_client", None)
    if client is not None:
        return client
    missing = [
        key
        for key in ("CH_HOST", "CH_PORT", "CH_USER", "CH_PASSWORD")
        if not os.environ.get(key)
    ]
    if missing:
        raise RuntimeError(f"Missing ClickHouse environment variables: {missing}")
    client = clickhouse_connect.get_client(
        host=os.environ["CH_HOST"],
        port=int(os.environ["CH_PORT"]),
        username=os.environ["CH_USER"],
        password=os.environ["CH_PASSWORD"],
        secure=True,
        connect_timeout=900,
        send_receive_timeout=900,
    )
    _thread_local.clickhouse_client = client
    return client


def _prepare_scoring_events() -> pl.DataFrame:
    if DIRECT_EVENT_FOOTPRINTS is None:
        raise RuntimeError(
            "DIRECT_EVENT_FOOTPRINTS must be configured by an official-event wrapper"
        )
    return (
        pl.read_parquet(DIRECT_EVENT_FOOTPRINTS)
        .select("country", "station", "time", "episode_id", "record_type")
        .unique(subset=["country", "station", "time", "record_type"])
        .sort(["country", "time", "station"])
    )


def _event_file(country: str, episode_id: str, events: pl.DataFrame) -> Path:
    safe_episode = episode_id.replace(":", "").replace("/", "-")
    path = CACHE / "events" / f"{country}_{safe_episode}.parquet"
    frame = events.filter(
        (pl.col("country") == country)
        & (pl.col("episode_id") == episode_id)
    ).select(
        "country",
        "station",
        "time",
        "episode_id",
        "record_type",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return path


def _external_events(path: Path) -> ExternalData:
    return ExternalData(
        file_path=str(path),
        file_name="record_events.parquet",
        fmt="Parquet",
        structure=(
            "country String, station String, time DateTime, episode_id String, "
            "record_type String"
        ),
    )


def _score_sql() -> str:
    bias = _bias_cte(TEMP)
    return f"""
WITH
model_points AS (
  SELECT s.model AS model_name, s.station, s.init_time,
         s.prediction_timedelta AS lead_minutes,
         e.episode_id, e.record_type,
         avg(s.{TEMP}) AS raw_error
  FROM production.synoptic_station_error_member AS s
  ANY INNER JOIN record_events AS e
    ON e.station = s.station
   AND e.time = s.init_time + toIntervalMinute(s.prediction_timedelta)
  WHERE s.model IN {{models:Array(String)}}
    AND s.station IN (SELECT station FROM record_events)
    AND s.init_time >= {{start:DateTime}}
    AND s.init_time < {{end:DateTime}}
    AND s.prediction_timedelta IN {{leads:Array(UInt32)}}
    AND toHour(s.init_time) IN {{init_hours:Array(UInt8)}}
    AND isFinite(s.{TEMP})
    AND s.{TEMP} IS NOT NULL
    AND s.inserted_at <= {{source_as_of:DateTime}}
  GROUP BY model_name, s.station, s.init_time, lead_minutes,
           e.episode_id, e.record_type
),
ref_points AS (
  SELECT station, init_time, lead_minutes, episode_id, record_type, raw_error
  FROM model_points
  WHERE model_name = '{REFERENCE}'
),
paired AS (
  SELECT p.model_name, p.init_time, p.lead_minutes,
         p.episode_id, p.record_type,
         p.raw_error, r.raw_error AS ref_raw_error
  FROM model_points AS p
  INNER JOIN ref_points AS r
    ON r.station = p.station
   AND r.init_time = p.init_time
   AND r.lead_minutes = p.lead_minutes
   AND r.episode_id = p.episode_id
   AND r.record_type = p.record_type
  WHERE p.model_name != '{REFERENCE}'
),
{bias},
scored AS (
  SELECT p.model_name,
         p.episode_id AS episode_name,
         p.record_type AS event_type,
         p.lead_minutes,
         score.1 AS debias, score.2 AS error, score.3 AS ref_error
  FROM paired AS p
  LEFT JOIN bias AS bm
    ON bm.model = p.model_name
   AND bm.applies_to_week = toMonday(
         p.init_time + toIntervalMinute(p.lead_minutes)
       )
   AND bm.init_hour = toHour(p.init_time)
   AND bm.lead = p.lead_minutes
  LEFT JOIN bias AS br
    ON br.model = '{REFERENCE}'
   AND br.applies_to_week = toMonday(
         p.init_time + toIntervalMinute(p.lead_minutes)
       )
   AND br.init_hour = toHour(p.init_time)
   AND br.lead = p.lead_minutes
  ARRAY JOIN [
    tuple(toUInt8(0), p.raw_error, p.ref_raw_error, toUInt8(1)),
    tuple(
      toUInt8(1),
      p.raw_error - bm.bias_value,
      p.ref_raw_error - br.bias_value,
      toUInt8(
        bm.bias_present = 1 AND isFinite(bm.bias_value)
        AND br.bias_present = 1 AND isFinite(br.bias_value)
      )
    )
  ] AS score
  WHERE score.4 = 1
)
SELECT model_name AS model,
       episode_name AS episode_id,
       event_type AS record_type,
       lead_minutes AS lead,
       debias,
       sqrt(avg(error * error)) AS rmse,
       avg(abs(error)) AS mae,
       avg(error) AS bias,
       sqrt(avg(ref_error * ref_error)) AS ref_rmse,
       avg(abs(ref_error)) AS ref_mae,
       avg(ref_error) AS ref_bias,
       count() AS sample_count
FROM scored
GROUP BY model_name, episode_name, event_type, lead_minutes, debias
ORDER BY episode_name, lead_minutes, debias, model_name
LIMIT 500000
SETTINGS max_execution_time = 900,
         max_rows_to_read = 1000000000,
         max_result_rows = 500000,
         timeout_before_checking_execution_speed = 0,
         join_algorithm = 'auto'
"""


def _cell_path(country: str, episode_id: str) -> Path:
    safe_episode = episode_id.replace(":", "").replace("/", "-")
    return CACHE / "metrics" / f"{country}_{safe_episode}.parquet"


def _score_cell(
    country: str, episode_id: str, event_path: Path
) -> tuple[str, str, int, float]:
    path = _cell_path(country, episode_id)
    if path.exists():
        return country, episode_id, pl.read_parquet(path).height, 0.0
    event_frame = pl.read_parquet(event_path)
    if event_frame.is_empty():
        return country, episode_id, 0, 0.0
    cfg = CONFIG["tracks"]["track_a"]
    track_start = datetime.fromisoformat(cfg["start"].replace("Z", "+00:00"))
    track_end = datetime.fromisoformat(cfg["end"].replace("Z", "+00:00"))
    event_min = event_frame["time"].min()
    event_max = event_frame["time"].max()
    if event_min.tzinfo is None:
        event_min = event_min.replace(tzinfo=timezone.utc)
        event_max = event_max.replace(tzinfo=timezone.utc)
    start = max(track_start, event_min - timedelta(hours=48))
    end = min(track_end, event_max + timedelta(hours=1))
    started = time.monotonic()
    result = _client().query(
        _score_sql(),
        {
            "models": TRACK_A_MODELS,
            "start": start,
            "end": end,
            "bias_start": start - timedelta(days=35),
            "leads": LEADS,
            "init_hours": INIT_HOURS,
            "source_as_of": datetime.fromisoformat(
                CANONICAL_SOURCE_SNAPSHOT.replace("Z", "+00:00")
            ).astimezone(timezone.utc),
        },
        external_data=_external_events(event_path),
    )
    frame = pl.DataFrame(
        result.result_rows, schema=result.column_names, orient="row"
    )
    if frame.is_empty():
        return country, episode_id, 0, time.monotonic() - started
    frame = frame.with_columns(
        pl.lit(country).alias("country"),
        pl.col("debias").cast(pl.Boolean),
        pl.col("lead").cast(pl.Int64),
        pl.col("sample_count").cast(pl.Int64),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return country, episode_id, frame.height, time.monotonic() - started


def _scope_cells(cells: pl.DataFrame) -> pl.DataFrame:
    frames = []
    for scope, leads in SCOPES.items():
        frames.append(
            cells.filter(pl.col("lead").is_in(leads)).with_columns(
                pl.lit(scope).alias("lead_scope")
            )
        )
    return pl.concat(frames)


def _pooled_components(frame: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    return frame.group_by(keys).agg(
        (pl.col("mae") * pl.col("sample_count")).sum().alias("mae_sum"),
        (pl.col("ref_mae") * pl.col("sample_count"))
        .sum()
        .alias("ref_mae_sum"),
        (pl.col("bias") * pl.col("sample_count")).sum().alias("bias_sum"),
        pl.col("sample_count").sum().alias("n"),
        pl.col("lead").n_unique().alias("n_leads"),
    )


def _skill_table(cells: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    scoped = _scope_cells(cells).filter(pl.col("debias"))
    component_keys = [
        "model",
        "record_type",
        "lead_scope",
        "episode_id",
    ]
    comp = _pooled_components(scoped, component_keys)
    per_episode = comp.with_columns(
        (
            100
            * (
                1
                - (pl.col("mae_sum") / pl.col("n"))
                / (pl.col("ref_mae_sum") / pl.col("n"))
            )
        ).alias("skill")
    ).select(
        "model",
        "record_type",
        "lead_scope",
        "episode_id",
        "skill",
        pl.col("n").alias("n_samples"),
        "n_leads",
    )

    keys = ["model", "record_type", "lead_scope"]
    packed = comp.group_by(keys).agg(
        pl.struct(
            "episode_id",
            "mae_sum",
            "n",
            "ref_mae_sum",
        ).alias("episodes"),
        pl.col("n_leads").max(),
    )

    def aggregate(episodes: list[dict]) -> dict:
        mae_sum = sum(row["mae_sum"] for row in episodes)
        n = sum(row["n"] for row in episodes)
        ref_sum = sum(row["ref_mae_sum"] for row in episodes)
        value = 100 * (1 - mae_sum / ref_sum)
        leave_one_out = []
        for row in episodes:
            nm = n - row["n"]
            if nm <= 0:
                continue
            leave_one_out.append(
                100
                * (
                    1
                    - (mae_sum - row["mae_sum"])
                    / (ref_sum - row["ref_mae_sum"])
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
            "n_samples": n,
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
        .sort(["lead_scope", "model"])
    )
    return pooled, per_episode


def _write_report(
    skill: pl.DataFrame, per_episode: pl.DataFrame, events: pl.DataFrame
) -> None:
    order = [model for model in MODEL_ORDER if model != REFERENCE]
    headline = skill.filter(
        (pl.col("lead_scope") == "h6_48")
        & (pl.col("record_type") == "high")
    )
    cells = {row["model"]: row for row in headline.iter_rows(named=True)}
    lines = [
        f"# {VARIABLE_LABEL} skill on {COLLECTION_LABEL}",
        "",
        f"Continental {EVENT_LABEL} episodes are evaluated over their "
        "affected station footprints and durations. Forecast samples are "
        "matched pairwise to IFS; ensembles are evaluated through their means "
        "and the paper's causal bias correction is applied.",
        "",
        "Coverage differs by model and event; episode counts, pairwise-matched "
        "sample counts, and leave-one-event-out uncertainty are reported "
        "without a post hoc inclusion threshold.",
        "",
        "## Pooled 6--48 h skill",
        "",
        "| model | skill (%) | episode jackknife SE | episodes | samples |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in order:
        row = cells.get(model)
        if row is None:
            continue
        se = "--" if row["skill_se"] is None else f"{row['skill_se']:.1f}"
        lines.append(
            f"| {DISPLAY.get(model, model)} | {row['value']:+.1f} | "
            f"{se} | {row['n_episodes']} | {row['n_samples']:,} |"
        )
    lines += [
        "",
        "## Skill by episode (6--48 h)",
        "",
        "| episode | "
        + " | ".join(DISPLAY.get(model, model) for model in order if model in cells)
        + " |",
        "|---" + "|---:" * sum(model in cells for model in order) + "|",
    ]
    episode_rows = per_episode.filter(
        (pl.col("lead_scope") == "h6_48")
        & (pl.col("record_type") == "high")
    )
    episodes = sorted(episode_rows["episode_id"].unique().to_list())
    for episode in episodes:
        values = {
            row["model"]: row["skill"]
            for row in episode_rows.filter(
                pl.col("episode_id") == episode
            ).iter_rows(named=True)
        }
        lines.append(
            f"| {episode} | "
            + " | ".join(
                f"{values[model]:+.1f}" if model in values else "--"
                for model in order
                if model in cells
            )
            + " |"
        )
    lines += [
        "",
        "## Event sample inventory",
        "",
        "| episode | footprint station-hours before forecast matching | stations | countries |",
        "|---|---:|---:|---:|",
    ]
    for row in (
        events.group_by("episode_id")
        .agg(
            pl.len().alias("hours"),
            pl.col("station").n_unique().alias("stations"),
            pl.col("country").n_unique().alias("countries"),
        )
        .sort("episode_id")
        .iter_rows(named=True)
    ):
        lines.append(
            f"| {row['episode_id']} | {row['hours']:,} | "
            f"{row['stations']} | {row['countries']} |"
        )
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--country", action="append", choices=COUNTRIES)
    args = parser.parse_args()

    countries = args.country or COUNTRIES
    events = _prepare_scoring_events().filter(
        pl.col("country").is_in(countries)
    )
    tasks: list[tuple[str, str, Path]] = []
    for country in countries:
        episode_ids = sorted(
            events.filter(pl.col("country") == country)["episode_id"]
            .unique()
            .to_list()
        )
        for episode_id in episode_ids:
            tasks.append(
                (
                    country,
                    episode_id,
                    _event_file(country, episode_id, events),
                )
            )
    CACHE.mkdir(parents=True, exist_ok=True)
    print(
        f"{len(tasks)} country-episode scoring cells on {args.workers} workers; "
        f"{events.height} supported station-hours"
    )
    completed = 0
    lock = threading.Lock()

    def run(task: tuple[str, str, Path]):
        nonlocal completed
        result = _score_cell(*task)
        with lock:
            completed += 1
            name, episode_id, rows, elapsed = result
            print(
                f"[{completed}/{len(tasks)}] {name} {episode_id} "
                f"rows={rows} query_s={elapsed:.1f}",
                flush=True,
            )
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, tasks))

    frames = [
        pl.read_parquet(_cell_path(country, episode_id))
        for country, episode_id, _ in tasks
        if _cell_path(country, episode_id).exists()
        and pl.read_parquet(_cell_path(country, episode_id)).height
    ]
    if not frames:
        raise RuntimeError("No metric cells produced")
    cells = (
        pl.concat(frames)
        .with_columns(pl.col("debias").cast(pl.Boolean))
        .sort(["episode_id", "country", "lead", "debias", "model"])
    )
    cells.write_parquet(CELLS_OUT)
    skill, per_episode = _skill_table(cells)
    skill.write_parquet(SKILL_OUT)
    per_episode.write_parquet(EPISODE_SKILL_OUT)
    _write_report(skill, per_episode, events)
    print(f"wrote {CELLS_OUT} ({cells.height} rows)")
    print(f"wrote {SKILL_OUT} ({skill.height} rows)")
    print(f"wrote {EPISODE_SKILL_OUT} ({per_episode.height} rows)")
    print(f"wrote {REPORT_OUT}")


if __name__ == "__main__":
    main()
