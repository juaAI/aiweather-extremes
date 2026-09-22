"""Create and verify a self-contained Overleaf upload archive.

The archive contains only files referenced by ``paper/main.tex`` plus a short
upload note.  Paths are rewritten so ``main.tex`` sits at the project root.
The package is compiled in an isolated temporary directory before the
deterministic zip is written.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAPER = REPO / "paper"
FIGURES = REPO / "figures"
DEFAULT_OUTPUT = REPO / "overleaf_package.zip"
STYLE_FILES = (
    "iclr2027_conference.sty",
    "iclr2027_conference.bst",
    "math_commands.tex",
)

FIGURE_PATTERN = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
INPUT_PATTERN = re.compile(r"\\input\{([^}]+)\}")


def source_date_epoch() -> int:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return int(configured)
    return int(
        subprocess.check_output(
            ["git", "log", "-1", "--format=%ct"],
            cwd=REPO,
            text=True,
        ).strip()
    )


def tectonic_binary() -> str:
    configured = os.environ.get("TECTONIC_BIN")
    if configured:
        return configured
    discovered = shutil.which("tectonic")
    if discovered:
        return discovered
    local = Path.home() / ".local" / "bin" / "tectonic"
    if local.exists():
        return str(local)
    raise RuntimeError("Tectonic 0.16.9 is required to verify the package")


def resolve_figure(name: str) -> tuple[Path, Path]:
    for relative in (Path("figures") / name, Path("figures/appendix") / name):
        source = REPO / relative
        if source.exists():
            return source, relative
    raise FileNotFoundError(f"Missing referenced figure: {name}")


def prepare_tree(root: Path) -> list[Path]:
    source_tex = (PAPER / "main.tex").read_text()
    packaged_tex = source_tex.replace(
        r"\graphicspath{{../figures/}{../figures/appendix/}}",
        r"\graphicspath{{figures/}{figures/appendix/}}",
    )
    if packaged_tex == source_tex:
        raise RuntimeError("Expected graphicspath declaration was not found")

    files: list[Path] = []

    def write(relative: Path, content: str) -> None:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        files.append(relative)

    def copy(source: Path, relative: Path) -> None:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        files.append(relative)

    write(Path("main.tex"), packaged_tex)
    copy(PAPER / "references.bib", Path("references.bib"))
    for name in STYLE_FILES:
        copy(PAPER / name, Path(name))

    copied_inputs: set[Path] = set()

    def copy_dependencies(content: str) -> None:
        for name in sorted(set(FIGURE_PATTERN.findall(content))):
            source, relative = resolve_figure(name)
            if relative not in files:
                copy(source, relative)

        for name in sorted(set(INPUT_PATTERN.findall(content))):
            relative = Path(name)
            if relative.suffix == "":
                relative = relative.with_suffix(".tex")
            if relative in copied_inputs:
                continue
            source = PAPER / relative
            if not source.exists():
                raise FileNotFoundError(f"Missing referenced input: {name}")
            copied_inputs.add(relative)
            input_content = source.read_text()
            write(relative, input_content)
            copy_dependencies(input_content)

    copy_dependencies(source_tex)

    readme = """OVERLEAF UPLOAD PACKAGE

1. Upload this zip as a new Overleaf project.
2. Set main.tex as the Main document if Overleaf does not detect it.
3. Compiler: pdfLaTeX (Overleaf default). The repository's local verification
   build uses the pinned Tectonic 0.16.9 engine.
4. Bibliography: references.bib; BibTeX runs automatically.

The figures and table fragments are generated artifacts included in this
anonymous supplementary package.
"""
    write(Path("README.txt"), readme)
    return sorted(files)


def compile_tree(root: Path, epoch: int) -> Path:
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(
        [tectonic_binary(), "--keep-logs", "main.tex"],
        cwd=root,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    pdf = root / "main.pdf"
    if not pdf.exists():
        raise RuntimeError("Tectonic did not produce main.pdf")
    log = (root / "main.log").read_text()
    forbidden = (
        "Undefined control sequence",
        "Overfull \\hbox",
        "There were undefined references",
        "There were undefined citations",
    )
    errors = [needle for needle in forbidden if needle in log]
    if errors:
        raise RuntimeError(f"Packaged build log contains: {errors}")
    return pdf


def zip_tree(root: Path, files: list[Path], output: Path, epoch: int) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.gmtime(max(epoch, 315532800))[:6]  # ZIP dates start in 1980.
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative in files:
            info = zipfile.ZipInfo(str(relative), date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (root / relative).read_bytes())
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--verification-pdf",
        type=Path,
        help="optional path to keep the independently compiled package PDF",
    )
    args = parser.parse_args()

    epoch = source_date_epoch()
    with tempfile.TemporaryDirectory(prefix="extremes-overleaf-") as tmp:
        root = Path(tmp)
        files = prepare_tree(root)
        pdf = compile_tree(root, epoch)
        if args.verification_pdf:
            args.verification_pdf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pdf, args.verification_pdf)
        digest = zip_tree(root, files, args.output, epoch)

    print(f"wrote {args.output} ({len(files)} files)")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
