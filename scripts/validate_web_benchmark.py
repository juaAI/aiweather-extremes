"""Deterministic contract checks for the exported website benchmark JSON.

Fails loudly on duplicates, unreachable or malformed records, scopes that
ship regime rows without an all-conditions counterpart, unexplained model
holes, and the specific ECMWF ENS regressions that motivated the checks.

Run:
    uv run python scripts/validate_web_benchmark.py \
      ../website/public/data/benchmarks/ai-weather-extremes-v1.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

WIND = "wind_speed_at_height_level_10m"
TEMP = "air_temperature_at_height_level_2m"
SOLAR = "surface_downwelling_shortwave_flux_sum_1h"
PRECIP = "precipitation_amount_sum_1h"

STANDARD_REGIMES = {"all", "lt_q5", "q5_q25", "q25_q75", "q75_q95", "gt_q95"}
PRECIP_REGIMES = {"all", "dry", "wet_lt_p50", "p50_p75", "p75_p95", "gt_p95"}

ERRORS: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        ERRORS.append(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path)
    args = parser.parse_args()
    data = json.loads(args.payload.read_text())

    check(data.get("schemaVersion") == 1, "schemaVersion must be 1")

    model_keys = {m["key"] for m in data["models"]}
    regime_sets = {
        v["key"]: (
            STANDARD_REGIMES if v["regimeSet"] == "standard" else PRECIP_REGIMES
        )
        for v in data["variables"]
    }
    scope_keys = set(data["scopes"])
    country_keys = {c["key"] for c in data["countries"]}
    view_keys = set(data["views"])
    records = data["records"]
    omissions = data.get("omissions", [])

    check(len(records) > 0, "no records exported")
    check(
        all(v.get("role") in ("primary", "secondary") for v in data["views"].values()),
        "every view needs a primary/secondary role",
    )

    # --- record-level shape ---------------------------------------------
    seen: set[tuple] = set()
    presence: dict[tuple, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for row in records:
        key = (
            row["view"],
            row["track"],
            row["variable"],
            row["scope"],
            row.get("country"),
            row["regime"],
            row["model"],
        )
        check(key not in seen, f"duplicate record {key}")
        seen.add(key)

        check(row["model"] in model_keys, f"unknown model {row['model']}")
        check(row["scope"] in scope_keys, f"unknown scope {row['scope']}")
        check(row["track"] in view_keys, f"unknown track {row['track']}")
        check(
            row["regime"] in regime_sets[row["variable"]],
            f"unreachable regime {row['regime']} for {row['variable']}",
        )
        check(
            isinstance(row["skill"], (int, float)),
            f"non-numeric skill in {key}",
        )
        if row["view"] == "country":
            check(
                row.get("country") in country_keys,
                f"unknown country {row.get('country')}",
            )
        else:
            check(
                row.get("se") is not None and row.get("n") is not None,
                f"pooled record without uncertainty/samples: {key}",
            )
            n_leads, grid_leads = row.get("nLeads"), row.get("gridLeads")
            check(
                isinstance(n_leads, int)
                and isinstance(grid_leads, int)
                and 0 < n_leads <= grid_leads,
                f"malformed lead coverage {n_leads}/{grid_leads} in {key}",
            )
        presence[(row["track"], row["variable"], row["scope"])][
            row["model"]
        ].add(row["regime"])

    # --- scope coverage: regime rows require an all-conditions row -------
    omitted = {
        (o["track"], o["variable"], o["scope"], o["model"]): o
        for o in omissions
    }
    for (track, variable, scope), models in presence.items():
        combo_regimes = set().union(*models.values())
        for model, regimes in models.items():
            check(
                "all" in regimes,
                f"{track}/{variable}/{scope}/{model} has regime rows "
                "without an all-conditions row",
            )
            if regimes == {"all"} and len(combo_regimes) > 1:
                entry = omitted.get((track, variable, scope, model))
                check(
                    entry is not None and entry.get("regimes") == "tails",
                    f"{track}/{variable}/{scope}/{model} ships all-only "
                    "coverage without a documented partial omission",
                )
        # every model hole is documented
        for model in model_keys:
            if model not in models:
                check(
                    (track, variable, scope, model) in omitted,
                    f"undocumented omission {track}/{variable}/{scope}/{model}",
                )

    # omissions must not contradict the records
    for o in omissions:
        combo = presence.get((o["track"], o["variable"], o["scope"]))
        check(
            combo is not None,
            f"omission references unknown combo {o}",
        )
        if combo is None:
            continue
        if o.get("regimes") == "tails":
            check(
                combo.get(o["model"]) == {"all"},
                f"partial omission contradicts records: {o}",
            )
        else:
            check(
                o["model"] not in combo,
                f"omission for a model that has records: {o}",
            )
        check(bool(o.get("reason")), f"omission without reason: {o}")

    # --- the specific ENS regressions this suite guards against ----------
    for variable in (WIND, TEMP):
        check(
            presence[("track_a", variable, "h6_48")].get("ecmwf_ens")
            == STANDARD_REGIMES,
            f"ENS must ship full h6_48 coverage for {variable}",
        )
        check(
            presence[("track_a", variable, "h1_12")].get("ecmwf_ens") is None,
            f"ENS must not appear on the hourly 1–12 h grid for {variable}",
        )
        check(
            presence[("track_a", variable, "h1_48")].get("ecmwf_ens") is None,
            f"ENS must not appear on the hourly 1–48 h grid for {variable}",
        )
    check(
        presence[("track_a", PRECIP, "h6_48")].get("ecmwf_ens")
        == PRECIP_REGIMES,
        "ENS precipitation must ship full 6–48 h coverage in Track A",
    )
    check(
        not any(r["track"] == "track_b" and r["model"] == "ecmwf_ens" for r in records),
        "ENS must not appear in the Track B regional cohort",
    )
    for variable in (WIND, TEMP):
        check(
            presence[("track_a", variable, "h6_48")].get("aifs_ens")
            == STANDARD_REGIMES,
            f"AIFS ENS must ship full h6_48 coverage for {variable}",
        )
        for scope in ("h1_12", "h1_48"):
            check(
                presence[("track_a", variable, scope)].get("aifs_ens") is None,
                f"AIFS ENS must not appear on the {scope} hourly grid for {variable}",
            )
    check(
        not any(
            r["model"] == "aifs_ens" and r["variable"] in (SOLAR, PRECIP)
            for r in records
        ),
        "AIFS ENS coarse accumulations must not be exported as hourly values",
    )
    check(
        not any(r["track"] == "track_b" and r["model"] == "aifs_ens" for r in records),
        "AIFS ENS must not appear in the Track B regional cohort",
    )
    check(
        not any(r["regime"] == "unclassified" for r in records),
        "unclassified regimes must not be exported",
    )

    # --- source commit must resolve in this repository -------------------
    commit = data["source"]["commit"]
    resolvable = (
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPO,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    check(resolvable, f"source commit {commit} does not resolve in {REPO}")

    if ERRORS:
        for message in ERRORS:
            print(f"FAIL: {message}", file=sys.stderr)
        raise SystemExit(f"{len(ERRORS)} validation error(s)")
    print(
        f"OK: {len(records):,} records, {len(omissions)} documented omissions, "
        f"commit {commit[:12]} resolvable"
    )


if __name__ == "__main__":
    main()
