"""Score forecasts over externally documented record-temperature events."""

from __future__ import annotations

import score_record_events as scorer

scorer.CACHE = (
    scorer.PROJECT_ROOT / "data" / "cache" / "official_temperature_scoring_v1"
)
scorer.DIRECT_EVENT_FOOTPRINTS = (
    scorer.DERIVED / "official_temperature_event_footprints.parquet"
)
scorer.CELLS_OUT = (
    scorer.DERIVED / "official_temperature_event_metric_cells.parquet"
)
scorer.SKILL_OUT = scorer.DERIVED / "official_temperature_event_skill.parquet"
scorer.EPISODE_SKILL_OUT = (
    scorer.DERIVED / "official_temperature_event_skill_by_episode.parquet"
)
scorer.REPORT_OUT = (
    scorer.PROJECT_ROOT / "reports" / "official_temperature_event_skill.md"
)
scorer.VARIABLE_LABEL = "Temperature"
scorer.EVENT_LABEL = "externally documented record-temperature"
scorer.COLLECTION_LABEL = "externally documented record-temperature events"


if __name__ == "__main__":
    scorer.main()
