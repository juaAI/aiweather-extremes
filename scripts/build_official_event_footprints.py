"""Build externally defined temperature and wind event footprints.

Event dates and affected countries come from ``config/official_events.yaml``;
no station-count or percentile heuristic is used. Each event footprint contains
all benchmark stations in the documented countries at 00/06/12/18 UTC over the
source-reported event window.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import yaml

from qe_client import PROJECT_ROOT

CONFIG_PATH = PROJECT_ROOT / "config" / "official_events.yaml"
STATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "derived"
    / "station_climatology_thresholds_era5_1991_2020.parquet"
)
DERIVED = PROJECT_ROOT / "data" / "derived"
REPORT = PROJECT_ROOT / "reports" / "official_event_catalog.md"


def _times(start: str, end: str) -> pl.DataFrame:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = (
        datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
        + timedelta(hours=18)
    )
    return pl.DataFrame(
        {
            "time": pl.datetime_range(
                start_dt,
                end_dt,
                interval="6h",
                eager=True,
                time_zone="UTC",
            )
        }
    )


def _build_variable(
    variable: str,
    events: list[dict],
    stations: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    footprints = []
    catalog_rows = []
    for event in events:
        event_stations = stations.filter(
            pl.col("country").is_in(event["countries"])
        )
        footprint = (
            event_stations.join(_times(event["start"], event["end"]), how="cross")
            .with_columns(
                pl.lit(event["id"]).alias("episode_id"),
                pl.lit("high").alias("record_type"),
                pl.lit(event["name"]).alias("event_name"),
                pl.lit(variable).alias("variable"),
            )
            .select(
                "country",
                "station",
                "time",
                "episode_id",
                "record_type",
                "event_name",
                "variable",
            )
        )
        footprints.append(footprint)
        catalog_rows.append(
            {
                "variable": variable,
                "episode_id": event["id"],
                "event_name": event["name"],
                "start_date": datetime.fromisoformat(event["start"]).date(),
                "end_date": datetime.fromisoformat(event["end"]).date(),
                "countries": event["countries"],
                "basis": event["basis"],
                "sources_json": json.dumps(event["sources"]),
                "n_stations": event_stations.height,
                "n_footprint_station_hours": footprint.height,
            }
        )
    return pl.concat(footprints), pl.DataFrame(catalog_rows)


def main() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    stations = (
        pl.scan_parquet(STATIONS_PATH)
        .select("country", "station")
        .unique()
        .collect()
    )
    catalog_frames = []
    lines = [
        "# Authoritative event catalogue",
        "",
        "Event windows and affected countries come from the cited external "
        "sources. No station-count or country-fraction selection heuristic is "
        "used. Forecast evaluation covers all benchmark stations in each "
        "documented country footprint.",
        "",
    ]
    for variable in ("temperature", "wind"):
        footprints, catalog = _build_variable(
            variable, config[variable], stations
        )
        footprint_path = DERIVED / f"official_{variable}_event_footprints.parquet"
        footprints.write_parquet(footprint_path)
        catalog_frames.append(catalog)
        lines += [
            f"## {variable.title()} events",
            "",
            "| event | dates | countries | stations | provenance |",
            "|---|---|---|---:|---|",
        ]
        for event in config[variable]:
            row = catalog.filter(
                pl.col("episode_id") == event["id"]
            ).row(0, named=True)
            sources = ", ".join(
                f"[source {index + 1}]({url})"
                for index, url in enumerate(event["sources"])
            )
            lines.append(
                f"| {event['name']} | {event['start']}--{event['end']} | "
                f"{', '.join(event['countries'])} | {row['n_stations']} | "
                f"{sources} |"
            )
        lines.append("")
        print(f"wrote {footprint_path} ({footprints.height} rows)")
    catalog = pl.concat(catalog_frames).sort(["variable", "start_date"])
    catalog_path = DERIVED / "official_event_catalog.parquet"
    catalog.write_parquet(catalog_path)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines).rstrip() + "\n")
    print(f"wrote {catalog_path} ({catalog.height} rows)")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
