"""Create an allowlisted, identity-scanned anonymous code archive."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "anonymous_code.zip"

ALLOWLIST = [
    "pyproject.toml",
    "uv.lock",
    "config/matrix.yaml",
    "scripts/aggregates.py",
    "scripts/extract_climatology_metrics.py",
    "scripts/extract_climatology_thresholds.py",
    "scripts/extract_forecast_conditioned_bias.py",
    "scripts/fig_conditional_bias.py",
    "scripts/fig_tail_penalty.py",
    "scripts/figures_v4.py",
    "scripts/make_numbers.py",
    "scripts/prepare_climatology_figure_data.py",
    "scripts/qe_client.py",
    "scripts/style.py",
    "scripts/summarize_thresholds.py",
    "scripts/write_paper_tables.py",
    "data/derived/final_aggregates_climatology.parquet",
    "data/derived/final_aggregates_climatology_status.json",
    "data/derived/final_aggregates_window_matched.parquet",
    "data/derived/final_aggregates_window_matched_status.json",
    "data/derived/forecast_conditioned_bias_climatology.parquet",
    "data/derived/headline_skill_track_a_climatology.parquet",
    "data/derived/headline_skill_track_b_climatology.parquet",
    "data/derived/precip_aggregates_compact.parquet",
    "data/derived/solar_bias_lead48_track_a_climatology.parquet",
    "data/derived/solar_lead_skill_track_a_climatology.parquet",
    "data/derived/solar_monthly_skill_track_a_climatology.parquet",
    "data/derived/solar_monthly_skill_track_b_climatology.parquet",
    "data/derived/threshold_summary.json",
    "data/derived/track_b_lead_skill_climatology.parquet",
]

ARCHIVE_README = b"""# Anonymous reproduction package

This archive reproduces the score-based tables and figures from committed
compact aggregates:

```bash
uv sync --frozen
uv run python scripts/prepare_climatology_figure_data.py
EXTREMES_VARIANT=_climatology uv run python scripts/make_numbers.py
EXTREMES_VARIANT=_climatology uv run python scripts/write_paper_tables.py
EXTREMES_VARIANT=_climatology uv run python scripts/figures_v4.py
EXTREMES_VARIANT=_climatology uv run python scripts/fig_tail_penalty.py
uv run python scripts/fig_conditional_bias.py
```

Rebuilding the aggregates requires warehouse-derived bucketed metric inputs
that are not included. Station identities, station coordinates, and the full
threshold parquet are withheld, so the static station map and station-count
table are supplied only in the separate manuscript source package.
"""

FORBIDDEN = [
    b"Marvin Vincent Gabler",
    b"Roberto Molinaro",
    b"Niall Siegenheim",
    b"Henry Martin",
    b"Mark Frey",
    b"Niels Poulsen",
    b"Philipp Seitz",
    b"Olivier Lam",
    b"research@jua.ai",
    b"github.com/juaAI/aiweather-extremes",
    b"jua.ai",
    b"JUA_API",
    b"Jua API",
    b"Jua platform",
]


def source_epoch() -> int:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return int(configured)
    return int(
        subprocess.check_output(
            ["git", "log", "-1", "--format=%ct"], cwd=REPO, text=True
        ).strip()
    )


def main() -> None:
    files = [Path(name) for name in ALLOWLIST]
    missing = [str(path) for path in files if not (REPO / path).exists()]
    if missing:
        raise FileNotFoundError(f"anonymous archive inputs missing: {missing}")
    for path in files:
        content = (REPO / path).read_bytes()
        for forbidden in FORBIDDEN:
            if forbidden.lower() in content.lower():
                raise RuntimeError(
                    f"identifying content in {path}: {forbidden.decode()}"
                )
    for forbidden in FORBIDDEN:
        if forbidden.lower() in ARCHIVE_README.lower():
            raise RuntimeError(f"identifying content in archive README: {forbidden.decode()}")

    epoch = source_epoch()
    timestamp = time.gmtime(max(epoch, 315532800))[:6]
    with zipfile.ZipFile(
        OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        readme_info = zipfile.ZipInfo("README.md", date_time=timestamp)
        readme_info.compress_type = zipfile.ZIP_DEFLATED
        readme_info.external_attr = 0o100644 << 16
        archive.writestr(readme_info, ARCHIVE_README)
        for path in sorted(files):
            info = zipfile.ZipInfo(str(path), date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (REPO / path).read_bytes())

    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    print(f"wrote {OUTPUT} ({len(files) + 1} files)")
    print("sha256", digest)


if __name__ == "__main__":
    main()
