"""Validate desk-rejection-sensitive properties of the ICLR review PDF."""

from __future__ import annotations

import re
from pathlib import Path

import fitz

from qe_client import PROJECT_ROOT

PAPER = PROJECT_ROOT / "paper"
MAIN = PAPER / "main.tex"
PDF = PAPER / "main.pdf"

FORBIDDEN_REVIEW_TEXT = (
    "Marvin Vincent Gabler",
    "Roberto Molinaro",
    "Niall Siegenheim",
    "Henry Martin",
    "Mark Frey",
    "Niels Poulsen",
    "Philipp Seitz",
    "Olivier Lam",
    "research@jua.ai",
    "github.com/juaAI/aiweather-extremes",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def heading_page(document: fitz.Document, heading: str) -> int:
    target = heading.casefold()
    for index, page in enumerate(document):
        lines = [line.strip().casefold() for line in page.get_text().splitlines()]
        if target in lines:
            return index + 1
    raise RuntimeError(f"PDF heading not found: {heading}")


def main() -> None:
    source = MAIN.read_text()
    review_source = source + (PAPER / "supplement.tex").read_text()

    require(r"\usepackage{iclr2027_conference" in source, "ICLR style is not loaded")
    require(
        not re.search(r"^[^%]*\\iclrfinalcopy", source, flags=re.MULTILINE),
        r"\iclrfinalcopy must remain disabled for review",
    )
    require(r"\author{Anonymous Authors}" in source, "review author block is not anonymous")
    require(r"\subsection*{AI use statement}" in source, "AI use statement is missing")
    require(
        source.index(r"\bibliography{references}") < source.index(r"\appendix"),
        "references must precede appendices",
    )
    for value in FORBIDDEN_REVIEW_TEXT:
        require(value not in review_source, f"identifying review text remains: {value}")

    require(PDF.exists(), "paper/main.pdf has not been built")
    document = fitz.open(PDF)
    references_page = heading_page(document, "References")
    require(
        references_page <= 10,
        f"main text exceeds nine pages: references start on page {references_page}",
    )
    require(
        heading_page(document, "AI use statement") <= 10,
        "AI statement is misplaced",
    )

    metadata = " ".join(str(value or "") for value in document.metadata.values())
    for value in FORBIDDEN_REVIEW_TEXT:
        require(value not in metadata, f"identifying PDF metadata remains: {value}")
    latin_modern = [
        font[3]
        for page in document
        for font in page.get_fonts()
        if "LMRoman" in font[3]
    ]
    require(
        not latin_modern,
        f"ICLR review PDF uses Latin Modern instead of Times: {sorted(set(latin_modern))}",
    )

    print(
        f"PASS: anonymous ICLR review PDF; references begin on page "
        f"{references_page}; total pages={len(document)}"
    )


if __name__ == "__main__":
    main()
