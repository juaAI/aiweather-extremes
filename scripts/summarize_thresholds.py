"""Write compact provenance for threshold and regime-occupancy claims."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from style import SOLAR, TEMP, WIND

REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"
THRESHOLDS = DERIVED / "station_climatology_thresholds_era5_1991_2020.parquet"
AGGREGATES = DERIVED / "final_aggregates_climatology.parquet"
OUT = DERIVED / "threshold_summary.json"


def main() -> None:
    thresholds = pl.scan_parquet(THRESHOLDS)
    medians: dict[str, dict[str, float]] = {}
    for variable in (WIND, TEMP):
        row = (
            thresholds.filter(pl.col("variable") == variable)
            .select(
                pl.col("q05").median().alias("p05"),
                pl.col("q95").median().alias("p95"),
            )
            .collect()
            .row(0, named=True)
        )
        medians[variable] = {key: float(value) for key, value in row.items()}

    countries = (
        thresholds.filter(pl.col("variable").is_in([WIND, TEMP]))
        .select("country", "station")
        .unique()
        .group_by("country")
        .agg(pl.col("station").n_unique().alias("stations"))
        .sort("country")
        .collect()
    )

    aggregates = pl.read_parquet(AGGREGATES)
    occupancy: dict[str, float] = {}
    for variable in (WIND, TEMP):
        rows = aggregates.filter(
            (pl.col("track") == "track_a")
            & (pl.col("model") == "ecmwf_ifs_single")
            & (pl.col("variable") == variable)
            & (pl.col("kind") == "bias")
            & (pl.col("lead_scope") == "h6_48")
            & pl.col("debias")
            & pl.col("country").is_null()
            & pl.col("obs_bucket").is_in(["all", "gt_q95"])
        )
        counts = dict(rows.select("obs_bucket", "n_samples").iter_rows())
        occupancy[variable] = counts["gt_q95"] / counts["all"]

    output = {
        "threshold_source": "ERA5 1991-2020; station/day-of-year/UTC-hour",
        "median_thresholds": medians,
        "scored_station_count": int(countries["stations"].sum()),
        "stations_by_country": dict(countries.iter_rows()),
        "upper_tail_fraction_of_matched_ifs_pairs": occupancy,
    }
    solar_countries = (
        thresholds.filter(pl.col("variable") == SOLAR)
        .select("country", "station")
        .unique()
        .group_by("country")
        .agg(pl.col("station").n_unique().alias("stations"))
        .sort("country")
        .collect()
    )
    output["solar_threshold_stations_by_country"] = dict(
        solar_countries.iter_rows()
    )
    output["solar_regime_station_count_excluding_at"] = int(
        solar_countries.filter(pl.col("country") != "AT")["stations"].sum()
    )
    OUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
