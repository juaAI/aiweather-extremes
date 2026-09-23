"""Score forecasts over externally documented European windstorms."""

from __future__ import annotations

import score_record_events as scorer
from extract_climatology_thresholds import WIND

scorer.TEMP = WIND
scorer.CACHE = scorer.PROJECT_ROOT / "data" / "cache" / "official_wind_scoring_v1"
scorer.DIRECT_EVENT_FOOTPRINTS = (
    scorer.DERIVED / "official_wind_event_footprints.parquet"
)
scorer.CELLS_OUT = scorer.DERIVED / "official_wind_event_metric_cells.parquet"
scorer.SKILL_OUT = scorer.DERIVED / "official_wind_event_skill.parquet"
scorer.EPISODE_SKILL_OUT = (
    scorer.DERIVED / "official_wind_event_skill_by_episode.parquet"
)
scorer.REPORT_OUT = (
    scorer.PROJECT_ROOT / "reports" / "official_wind_event_skill.md"
)
scorer.VARIABLE_LABEL = "10 m wind"
scorer.EVENT_LABEL = "externally documented windstorm"
scorer.COLLECTION_LABEL = "externally documented European windstorms"


if __name__ == "__main__":
    scorer.main()
