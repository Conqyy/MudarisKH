"""
LaTeX → PDF compiler utility for Mudaris.

Discovers pdflatex on the system and compiles .tex files to .pdf automatically.
Handles MiKTeX auto-install of missing packages.
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("MudarisCompiler")

# Common MiKTeX install paths on Windows
_MIKTEX_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
    Path("C:/Program Files/MiKTeX/miktex/bin/x64"),
    Path("C:/Program Files (x86)/MiKTeX/miktex/bin/x64"),
    Path("C:/MiKTeX/miktex/bin/x64"),
]


def _find_engine(engine: str = "pdflatex") -> str | None:
    """Return the full path to a LaTeX engine (pdflatex/xelatex/lualatex), or None."""
    # 1. Check PATH first
    found = shutil.which(engine)
    if found:
        return found

    # 2. Probe common MiKTeX install locations (Windows)
    for candidate in _MIKTEX_CANDIDATES:
        exe = candidate / f"{engine}.exe"
        if exe.exists():
            return str(exe)

    return None


def compile_tex_to_pdf(
    tex_path: str,
    output_dir: str | None = None,
    clean_aux: bool = True,
    engine: str = "pdflatex",
) -> str | None:
    """
    Compile a .tex file to .pdf.

    Args:
        tex_path:   Path to the .tex file.
        output_dir: Directory for the output PDF (defaults to same dir as .tex).
        clean_aux:  Remove auxiliary files (.aux, .log, .out, .toc) after compilation.
        engine:     LaTeX engine to use ("pdflatex" default, or "xelatex" for
                    Unicode/RTL content such as Arabic).

    Returns:
        Path to the generated .pdf, or None if compilation failed.
    """
    latex_exe = _find_engine(engine)
    if not latex_exe:
        logger.error(
            f"❌ {engine} not found! Install MiKTeX: https://miktex.org/download\n"
            "   Or run:  winget install MiKTeX.MiKTeX"
        )
        return None
    pdflatex = latex_exe

    tex_file = Path(tex_path).resolve()
    if not tex_file.exists():
        logger.error(f"❌ TeX file not found: {tex_file}")
        return None

    work_dir = Path(output_dir).resolve() if output_dir else tex_file.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        pdflatex,
        "-interaction=nonstopmode",   # Don't stop on errors, keep going
        "-halt-on-error",             # But do set a non-zero exit code
        f"-output-directory={work_dir}",
        str(tex_file),
    ]

    logger.info(f"📄 Compiling {tex_file.name} → PDF ...")

    # Run pdflatex TWICE (standard practice — resolves cross-references)
    for pass_num in (1, 2):
        result = subprocess.run(
            cmd,
            cwd=str(tex_file.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 and pass_num == 2:
            logger.error(f"❌ pdflatex failed (pass {pass_num}).")
            # Extract the actual error from the log
            for line in result.stdout.splitlines():
                if line.startswith("!"):
                    logger.error(f"   {line}")
            log_file = work_dir / tex_file.with_suffix(".log").name
            if log_file.exists():
                logger.error(f"   Full log: {log_file}")
            return None

    pdf_path = work_dir / tex_file.with_suffix(".pdf").name

    if not pdf_path.exists():
        logger.error("❌ PDF file was not created despite no reported errors.")
        return None

    # Clean up auxiliary files
    if clean_aux:
        for ext in (".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk", ".synctex.gz"):
            aux_file = work_dir / tex_file.with_suffix(ext).name
            if aux_file.exists():
                aux_file.unlink()

    logger.info(f"✅ PDF generated: {pdf_path}")
    return str(pdf_path)
