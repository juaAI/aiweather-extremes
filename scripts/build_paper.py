"""Build paper/main.pdf with deterministic PDF metadata.

``xdvipdfmx`` embeds a creation timestamp by default, making otherwise
identical builds differ byte-for-byte.  ``SOURCE_DATE_EPOCH`` removes that
clock dependency.  Callers may set it explicitly; otherwise the current Git
commit timestamp is used, which is stable across clones of the same commit.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAPER = REPO / "paper"
EXPECTED_TECTONIC_VERSION = "Tectonic 0.16.9"


def source_date_epoch() -> str:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return configured
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%ct"],
        cwd=REPO,
        text=True,
    ).strip()


def main() -> None:
    actual_version = subprocess.check_output(
        ["tectonic", "--version"], text=True
    ).strip()
    if actual_version != EXPECTED_TECTONIC_VERSION:
        raise RuntimeError(
            f"Expected {EXPECTED_TECTONIC_VERSION}, got {actual_version}. "
            "Use the pinned engine version for a reproducible PDF."
        )
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = source_date_epoch()
    print("SOURCE_DATE_EPOCH=", env["SOURCE_DATE_EPOCH"])
    subprocess.run(["tectonic", "main.tex"], cwd=PAPER, env=env, check=True)


if __name__ == "__main__":
    main()
