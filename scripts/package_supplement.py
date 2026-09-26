"""Create and verify the anonymised reviewer supplementary archive.

Unlike ``package_overleaf.py`` (a private working copy that still carries the
camera-ready author block), this archive may be shown to reviewers.  It holds
the Git-tracked code, configuration, compact aggregates and reports, with
identity-revealing strings redacted.  The build aborts if any forbidden
pattern survives or if an aggregate carries station-level columns.
``--smoke-test`` regenerates the score-based figures and tables offline from
the unpacked archive.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "submission" / "supplementary_material.zip"

INCLUDE_PREFIXES = ("scripts/", "config/", "data/derived/", "reports/")
INCLUDE_FILES = ("pyproject.toml", "uv.lock")
# Website export, manuscript packaging and a local endpoint probe are not
# part of the reproduction pipeline.
EXCLUDE_FILES = {
    "scripts/export_web_benchmark.py",
    "scripts/validate_web_benchmark.py",
    "scripts/package_overleaf.py",
    "scripts/package_supplement.py",
    "scripts/probe_precip_domains.py",
    "scripts/build_paper.py",
}

REDACTIONS = (
    ("# Both are provided with Jua platform access (https://jua.ai). No defaults:",
     "# Both are provided with platform access. No defaults:"),
    ('"http://localhost:12880"', '""'),
    ('"http://localhost:8080"', '""'),
    ('"localdevkey:localdevsecret"', '""'),
    ("Jua's synoptic network", "the platform's synoptic network"),
    ("JUA_API_BASE", "VERIFICATION_API_BASE"),
    ("JUA_API_KEY", "VERIFICATION_API_KEY"),
    ("Jua API access", "verification API access"),
)

FORBIDDEN = re.compile(
    r"molinaro|gabler|siegenheim|henry martin|mark frey|poulsen|seitz|"
    r"olivier lam|jua\.ai|juaai|jua_api|jua api|jua platform|research@|"
    r"github\.com|/users/|localhost|localdev",
    re.IGNORECASE,
)
FIGURE_PATTERN = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
INPUT_PATTERN = re.compile(r"\\input\{([^}]+)\}")
STATION_COLUMNS = {"station", "station_id", "latitude", "longitude", "lat", "lon"}

OFFLINE_COMMANDS = (
    ("_climatology", "scripts/make_numbers.py"),
    ("_climatology", "scripts/figures_v4.py"),
    ("_climatology", "scripts/write_paper_tables.py"),
    ("_climatology", "scripts/figures_precip.py"),
    (None, "scripts/fig_appb_country_bars.py"),
    (None, "scripts/figures_official_events.py"),
)

README = """ANONYMISED SUPPLEMENTARY MATERIAL

Code, configuration and derived aggregates for the submission
"Do AI weather models miss extremes?". Station identities, per-station series,
raw observations and raw forecast fields are not included.

Layout
  config/        experiment matrix and source-defined event catalogue
  scripts/       extraction, scoring, aggregation, table and figure code
  data/derived/  compact aggregates behind every reported number
  reports/       human-readable dumps of the aggregates

Regenerate all score-based figures and tables offline (Python >= 3.12, uv):

  uv sync --frozen
  EXTREMES_VARIANT=_climatology uv run python scripts/make_numbers.py
  EXTREMES_VARIANT=_climatology uv run python scripts/figures_v4.py
  EXTREMES_VARIANT=_climatology uv run python scripts/write_paper_tables.py
  EXTREMES_VARIANT=_climatology uv run python scripts/figures_precip.py
  uv run python scripts/fig_appb_country_bars.py
  uv run python scripts/figures_official_events.py

Figures are written to figures/, LaTeX tables to paper/tables/, and the
numbers report to reports/paper_numbers.md.

Artifact provenance
  headline_skill_track_{a,b}_climatology.parquet
      regime bar figures and headline skill tables
  solar_lead_skill_track_a_climatology.parquet, track_b_lead_skill_climatology.parquet
      lead-time curves and per-lead tables
  solar_bias_lead48_track_a_climatology.parquet
      solar panel of the conditional-bias figure
  final_aggregates_climatology.parquet
      wind/temperature/precipitation conditional bias, per-country table,
      precipitation figures and tables, reports/paper_numbers.md
  precip_categorical.parquet
      heavy-precipitation detection figure and table
  appb_country_skill_climatology.parquet
      per-country regime-profile figures
  official_*_event_skill*.parquet, official_event_catalog.parquet
      record-temperature and windstorm case-study figure and tables

Re-running extraction (scripts/extract*.py, scripts/score_official_events_api.py)
requires credentials for the forecast-verification API and the observation
database, supplied through environment variables; these are not included.
"""


def tracked_files() -> list[str]:
    listed = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True)
    return sorted(
        path
        for path in listed.splitlines()
        if (path.startswith(INCLUDE_PREFIXES) or path in INCLUDE_FILES)
        and path not in EXCLUDE_FILES
    )


def source_date_epoch() -> int:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return int(configured)
    return int(
        subprocess.check_output(
            ["git", "log", "-1", "--format=%ct"], cwd=REPO, text=True
        ).strip()
    )


def redact(text: str) -> str:
    for old, new in REDACTIONS:
        text = text.replace(old, new)
    return text


def check_parquet(relative: str, data: bytes) -> list[str]:
    with tempfile.NamedTemporaryFile(suffix=".parquet") as handle:
        handle.write(data)
        handle.flush()
        frame = pl.read_parquet(handle.name)
    problems = [
        f"{relative}: station-level column {column!r}"
        for column in frame.columns
        if column.lower() in STATION_COLUMNS
    ]
    for column, dtype in frame.schema.items():
        if dtype not in (pl.String, pl.List(pl.String)):
            continue
        values = frame[column].explode(empty_as_null=True) if dtype != pl.String else frame[column]
        if any(FORBIDDEN.search(value) for value in values.drop_nulls().unique()):
            problems.append(f"{relative}: forbidden text in column {column!r}")
    return problems


def build_contents() -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    problems: list[str] = []
    for relative in tracked_files():
        raw = (REPO / relative).read_bytes()
        if relative.endswith(".parquet"):
            problems.extend(check_parquet(relative, raw))
            contents[relative] = raw
            continue
        text = redact(raw.decode("utf-8"))
        for match in FORBIDDEN.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            problems.append(f"{relative}:{line}: {match.group(0)!r}")
        contents[relative] = text.encode("utf-8")
    contents["README.txt"] = README.encode("utf-8")
    if problems:
        raise RuntimeError("Anonymity check failed:\n  " + "\n  ".join(problems))
    return contents


def smoke_test(contents: dict[str, bytes]) -> None:
    with tempfile.TemporaryDirectory(prefix="extremes-supplement-") as tmp:
        root = Path(tmp)
        for relative, data in contents.items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (root / "figures" / "appendix").mkdir(parents=True, exist_ok=True)
        (root / "paper" / "tables").mkdir(parents=True, exist_ok=True)
        for variant, script in OFFLINE_COMMANDS:
            env = os.environ.copy()
            env.pop("EXTREMES_VARIANT", None)
            if variant:
                env["EXTREMES_VARIANT"] = variant
            result = subprocess.run(
                [sys.executable, script],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if result.returncode:
                raise RuntimeError(f"{script} failed offline:\n{result.stdout[-3000:]}")
            print(f"smoke-test ok: {script}")
        manuscript = (REPO / "paper" / "main.tex").read_text()
        expected = [
            candidates
            for name in sorted(set(FIGURE_PATTERN.findall(manuscript)))
            for candidates in [(root / "figures" / name, root / "figures/appendix" / name)]
        ] + [
            (root / "paper" / name,)
            for name in sorted(set(INPUT_PATTERN.findall(manuscript)))
        ]
        missing = [
            str(candidates[0].relative_to(root))
            for candidates in expected
            if not any(path.exists() for path in candidates)
        ]
        if missing:
            raise RuntimeError(f"Artifacts cited in main.tex not regenerated: {missing}")
        print(f"smoke-test regenerated all {len(expected)} cited figures and tables")


def zip_contents(contents: dict[str, bytes], output: Path, epoch: int) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.gmtime(max(epoch, 315532800))[:6]  # ZIP dates start in 1980.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(contents):
            info = zipfile.ZipInfo(relative, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents[relative])
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()

    contents = build_contents()
    if args.smoke_test:
        smoke_test(contents)
    digest = zip_contents(contents, args.output, source_date_epoch())
    print(f"wrote {args.output} ({len(contents)} files)")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
