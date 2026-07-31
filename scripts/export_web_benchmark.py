"""Export the published benchmark as compact, versioned website JSON.

The exporter reads only tracked, station-free aggregates.  Its output is
deterministically sorted and contains enough metadata for the public
interactive benchmark page without exposing station identities or requiring
database/API access.

Run:
    uv run python scripts/export_web_benchmark.py \
      --output ../website/public/data/benchmarks/ai-weather-extremes-v1.json
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import polars as pl

REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"

PRECIP = "precipitation_amount_sum_1h"

MODELS = [
    {
        "key": "ept2_1_helios",
        "label": "Jua EPT-2.1 Helios",
        "shortLabel": "EPT-2.1 Helios",
        "group": "Jua",
        "color": "#E69F00",
        "marker": "star",
    },
    {
        "key": "ept2_1_europa",
        "label": "Jua EPT-2.1 Europa",
        "shortLabel": "EPT-2.1 Europa",
        "group": "Jua",
        "color": "#009E73",
        "marker": "circle",
    },
    {
        "key": "ept2_hrrr",
        "label": "Jua EPT-2 HRRR",
        "shortLabel": "EPT-2 HRRR",
        "group": "Jua",
        "color": "#17BECF",
        "marker": "square",
    },
    {
        "key": "ept2_reasoning",
        "label": "Jua EPT-2 Reasoning",
        "shortLabel": "EPT-2 Reasoning",
        "group": "Jua",
        "color": "#D62728",
        "marker": "diamond",
    },
    {
        "key": "ept2_e",
        "label": "Jua EPT-2e",
        "shortLabel": "EPT-2e",
        "group": "Jua",
        "color": "#7A3EB1",
        "marker": "plus",
    },
    {
        "key": "aurora",
        "label": "Microsoft Aurora",
        "shortLabel": "Microsoft Aurora",
        "group": "External AI",
        "color": "#FF7F0E",
        "marker": "triangleDown",
    },
    {
        "key": "aifs",
        "label": "ECMWF AIFS",
        "shortLabel": "ECMWF AIFS",
        "group": "External AI",
        "color": "#1F4E9C",
        "marker": "cross",
    },
    {
        "key": "ecmwf_ens",
        "label": "ECMWF ENS (mean)",
        "shortLabel": "ECMWF ENS",
        "group": "Physical",
        "color": "#56B4E9",
        "marker": "triangleUp",
    },
    {
        "key": "noaa_gfs_single",
        "label": "NOAA GFS",
        "shortLabel": "NOAA GFS",
        "group": "Physical",
        "color": "#7F7F7F",
        "marker": "hexagon",
    },
    {
        "key": "icon_global",
        "label": "DWD ICON Global",
        "shortLabel": "DWD ICON Global",
        "group": "Physical",
        "color": "#8C510A",
        "marker": "triangleLeft",
    },
    {
        "key": "icon_eu",
        "label": "DWD ICON-EU",
        "shortLabel": "DWD ICON-EU",
        "group": "Physical",
        "color": "#BCBD22",
        "marker": "triangleRight",
    },
]

VARIABLES = [
    {
        "key": "wind_speed_at_height_level_10m",
        "label": "10 m wind speed",
        "shortLabel": "Wind",
        "unit": "m/s",
        "regimeSet": "standard",
    },
    {
        "key": "air_temperature_at_height_level_2m",
        "label": "2 m temperature",
        "shortLabel": "Temperature",
        "unit": "°C",
        "regimeSet": "standard",
    },
    {
        "key": "surface_downwelling_shortwave_flux_sum_1h",
        "label": "1 h shortwave accumulation",
        "shortLabel": "Solar",
        "unit": "Wh/m²",
        "regimeSet": "standard",
    },
    {
        "key": PRECIP,
        "label": "1 h precipitation",
        "shortLabel": "Precipitation",
        "unit": "mm",
        "regimeSet": "precipitation",
    },
]

REGIMES = {
    "standard": [
        {"key": "all", "label": "All conditions", "shortLabel": "All"},
        {"key": "lt_q5", "label": "Very low (<P5)", "shortLabel": "<P5"},
        {"key": "q5_q25", "label": "Low (P5–25)", "shortLabel": "P5–25"},
        {"key": "q25_q75", "label": "Typical (P25–75)", "shortLabel": "P25–75"},
        {"key": "q75_q95", "label": "High (P75–95)", "shortLabel": "P75–95"},
        {"key": "gt_q95", "label": "Very high (>P95)", "shortLabel": ">P95"},
    ],
    "precipitation": [
        {"key": "all", "label": "All conditions", "shortLabel": "All"},
        {"key": "dry", "label": "Dry (<0.1 mm)", "shortLabel": "Dry"},
        {"key": "wet_lt_p50", "label": "Light (wet <P50)", "shortLabel": "<P50"},
        {"key": "p50_p75", "label": "Moderate (P50–75)", "shortLabel": "P50–75"},
        {"key": "p75_p95", "label": "High (P75–95)", "shortLabel": "P75–95"},
        {"key": "gt_p95", "label": "Heavy (>P95)", "shortLabel": ">P95"},
    ],
}

COUNTRIES = [
    {"key": "DE", "label": "Germany"},
    {"key": "FR", "label": "France"},
    {"key": "GB", "label": "United Kingdom"},
    {"key": "ES", "label": "Spain"},
    {"key": "IT", "label": "Italy"},
    {"key": "PL", "label": "Poland"},
    {"key": "NL", "label": "Netherlands"},
    {"key": "BE", "label": "Belgium"},
    {"key": "CH", "label": "Switzerland"},
    {"key": "NO", "label": "Norway"},
    {"key": "AT", "label": "Austria"},
    {"key": "CZ", "label": "Czechia"},
    {"key": "DK", "label": "Denmark"},
]


def finite(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def source_commit() -> tuple[str, str]:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    committed_at = subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", "HEAD"], cwd=REPO, text=True
    ).strip()
    return commit, committed_at


def pooled_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for track in ("track_a", "track_b"):
        frame = pl.read_parquet(
            DERIVED / f"headline_skill_{track}_climatology.parquet"
        )
        for record in frame.iter_rows(named=True):
            rows.append(
                {
                    "view": "pooled",
                    "track": track,
                    "variable": record["variable"],
                    "scope": record["lead_scope"],
                    "model": record["model"],
                    "regime": record["obs_bucket"],
                    "skill": finite(record["skill"]),
                    "se": finite(record["skill_se"]),
                    "n": finite(record["n"]),
                }
            )

    precip = pl.read_parquet(DERIVED / "final_aggregates_climatology.parquet").filter(
        (pl.col("variable") == PRECIP)
        & (pl.col("kind") == "skill_pct")
        & pl.col("debias")
        & pl.col("country").is_null()
        & pl.col("lead_scope").is_in(["h1_48", "h1_12"])
    )
    for record in precip.iter_rows(named=True):
        rows.append(
            {
                "view": "pooled",
                "track": record["track"],
                "variable": record["variable"],
                "scope": record["lead_scope"],
                "model": record["model"],
                "regime": record["obs_bucket"],
                "skill": finite(record["value"]),
                "se": finite(record["skill_se"]),
                "n": finite(record["n_samples"]),
            }
        )
    return rows


def country_records() -> list[dict[str, Any]]:
    frame = pl.read_parquet(
        DERIVED / "appb_country_skill_climatology.parquet"
    )
    return [
        {
            "view": "country",
            "track": "country_profiles",
            "variable": record["variable"],
            "scope": "h1_48",
            "country": record["country"],
            "model": record["model"],
            "regime": record["obs_bucket"],
            "skill": finite(record["skill_pct"]),
            "se": None,
            "n": None,
        }
        for record in frame.iter_rows(named=True)
    ]


def build_payload() -> dict[str, Any]:
    commit, committed_at = source_commit()
    records = pooled_records() + country_records()
    records.sort(
        key=lambda row: (
            row["view"],
            row["track"],
            row["variable"],
            row["scope"],
            row.get("country") or "",
            row["regime"],
            row["model"],
        )
    )
    return {
        "schemaVersion": 1,
        "source": {
            "repository": "https://github.com/juaAI/aiweather-extremes",
            "commit": commit,
            "committedAt": committed_at,
            "metric": "MAE skill relative to ECMWF IFS (%)",
            "referenceModel": "ecmwf_ifs_single",
            "climatology": "ERA5 1991–2020",
            "debiased": True,
            "uncertainty": "±1 leave-one-month-out jackknife standard error",
        },
        "views": {
            "track_a": {
                "label": "Europe pooled",
                "period": "2025-09-01/2026-06-30",
                "description": "Primary Europe-pooled comparison.",
            },
            "track_b": {
                "label": "Regional comparison",
                "period": "2026-03-01/2026-06-30",
                "description": "Regional Jua models and DWD ICON-EU.",
            },
            "country_profiles": {
                "label": "Country profiles",
                "period": "2026-03-01/2026-06-30",
                "description": (
                    "Mixed regional/global model set on month-matched cells; "
                    "not Track A filtered to a country."
                ),
            },
        },
        "scopes": {
            "h6_48": {"label": "6–48 h", "shortLabel": "Full"},
            "h1_48": {"label": "1–48 h", "shortLabel": "Full"},
            "h1_12": {"label": "1–12 h", "shortLabel": "Short"},
        },
        "models": MODELS,
        "variables": VARIABLES,
        "regimes": REGIMES,
        "countries": COUNTRIES,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "reports" / "benchmark-web-v1.json",
    )
    args = parser.parse_args()
    payload = build_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    print(f"wrote {args.output} ({len(payload['records']):,} records)")


if __name__ == "__main__":
    main()
