"""Bounded LaTeX compilation; these checks are defense in depth, not an OS sandbox."""
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("MudarisCompiler")
MAX_TEX_SOURCE_BYTES = 1024 * 1024
COMPILE_TIMEOUT_SECONDS = 30
_ENGINES = {"pdflatex", "xelatex"}
_MIKTEX_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
    Path("C:/Program Files/MiKTeX/miktex/bin/x64"),
    Path("C:/Program Files (x86)/MiKTeX/miktex/bin/x64"),
    Path("C:/MiKTeX/miktex/bin/x64"),
]
_CLASSES = {"article", "report", "book", "extarticle", "exam", "standalone"}
# Packages are executable TeX: only installed, trusted packages supporting the
# generated documents should be made available on the compilation host.
_PACKAGES = {
    "geometry", "amsmath", "amssymb", "amsfonts", "amsthm", "mathtools",
    "fontenc", "inputenc", "fontspec", "polyglossia", "babel", "lmodern",
    "textcomp", "underscore", "enumitem", "parskip", "eso-pic", "xcolor",
    "color", "tikz", "pgf", "pgfplots", "verbatim", "listings", "fancyvrb",
    "booktabs", "array", "tabularx", "longtable", "multirow", "multicol",
    "fancyhdr", "titlesec", "titling", "setspace", "microtype", "hyperref",
    "url", "graphicx", "float", "caption", "subcaption", "siunitx",
    "physics", "cancel", "bm", "upgreek", "ulem", "ragged2e", "adjustbox",
    "tcolorbox", "framed", "needspace", "etoolbox", "iftex", "changepage",
}
_BLOCKED_COMMANDS = {
    "input", "include", "includeonly", "openin", "openout", "closein", "closeout",
    "read", "readline", "write", "newread", "newwrite", "inputiffileexists",
    "iffileexists", "fileinput", "verbatiminput", "bverbatiminput", "lverbatiminput",
    "lstinputlisting", "includegraphics", "includepdf", "bibliography", "addbibresource",
    "loadclass", "loadclasswithoptions", "requirepackagewithoptions", "documentstyle",
    "csname", "endcsname", "catcode", "scantokens", "explsyntaxon", "makeatletter",
    "directlua", "latelua", "luadirect", "special", "pdfobj", "pdfximage", "pdfxform",
    "pdfextension", "pdfprimitive", "pdfmdfivesum", "pdffiledump", "pdffilesize",
    "pdffilemoddate", "pdfstrcmp", "primitive", "font", "xetexfont", "xetexpicfile",
    "xetexpdffile", "shellescape", "writeeighteen", "usemintedstyle", "inputminted",
    "tikzexternalize", "pgfplotstableread", "pgfplotstabletypeset", "endlinechar",
    "escapechar", "everyjob", "csuse", "csdef", "csgdef", "csedef", "csxdef",
    "cslet", "csletcs", "csundef", "csappto", "cspreto", "csnumdef", "csdimdef",
}


def _without_comments(source: str) -> str:
    lines = []
    for line in source.splitlines(keepends=True):
        for index, char in enumerate(line):
            if char != "%":
                continue
            backslashes = 0
            previous = index - 1
            while previous >= 0 and line[previous] == "\\":
                backslashes += 1
                previous -= 1
            if backslashes % 2 == 0:
                line = line[:index]
                break
        lines.append(line)
    return "".join(lines)


def validate_tex_source(tex: str) -> None:
    """Raise ValueError for file/shell IO, obfuscation or unreviewed package loading.

    Article layouts, math, inline TikZ, code blocks and system font names remain
    supported. This policy cannot sandbox an arbitrary TeX engine.
    """
    if not isinstance(tex, str) or not tex.strip():
        raise ValueError("A nonempty TeX document is required")
    if len(tex.encode("utf-8")) > MAX_TEX_SOURCE_BYTES:
        raise ValueError("TeX source exceeds the size limit")
    if "^^" in tex or "\x00" in tex:
        raise ValueError("TeX character obfuscation is not allowed")
    source = _without_comments(tex)
    for match in re.finditer(r"\\([A-Za-z]+|[@:_]+)", source):
        command = match.group(1).lower()
        if command in _BLOCKED_COMMANDS or "@" in command or ":" in command:
            raise ValueError("TeX file access, shell execution or token manipulation is not allowed")
    if re.search(r"\\begin\s*\{\s*(?:filecontents\*?|minted)\s*\}", source, re.I):
        raise ValueError("External file and shell environments are not allowed")
    for match in re.finditer(r"\\(documentclass|usepackage|RequirePackage)\b", source, re.I):
        declaration = re.match(r"\s*(?:\[([^\[\]{}]*)\]\s*)?\{([^{}]+)\}", source[match.end():])
        if not declaration:
            raise ValueError("Class and package names must be literal names")
        allowed = _CLASSES if match.group(1).lower() == "documentclass" else _PACKAGES
        if any(name.strip() not in allowed for name in declaration.group(2).split(",")):
            raise ValueError("Unsupported TeX class or package")
    for match in re.finditer(r"\\(?:usetikzlibrary|usepgflibrary|usepgfplotslibrary|tcbuselibrary)\b", source, re.I):
        declaration = re.match(r"\s*\{([^{}]+)\}", source[match.end():])
        if not declaration or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", name.strip()) or ".." in name for name in declaration.group(1).split(",")):
            raise ValueError("TeX libraries must be literal installed library names")
    if re.search(r"\b(?:Path|ExternalLocation|Extension|UprightFont|ItalicFont|BoldFont)\s*=\s*[^,\]\n]*(?:[/\\]|\.\.)", source, re.I):
        raise ValueError("External font paths are not allowed")
    for match in re.finditer(r"\\(?:setmainfont|setsansfont|setmonofont|fontspec|newfontfamily|newfontface)\b(?:\s*(?:\\[A-Za-z]+|\{\\[A-Za-z]+\}))?\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}", source, re.I):
        if re.search(r"[/\\:]|\.(?:otf|ttf|tfm|pfb)\b", match.group(1), re.I):
            raise ValueError("Only system font names are allowed")


def _find_engine(engine: str = "pdflatex") -> str | None:
    if engine not in _ENGINES:
        return None
    found = shutil.which(engine)
    if found:
        return found
    for candidate in _MIKTEX_CANDIDATES:
        executable = candidate / f"{engine}.exe"
        if executable.is_file():
            return str(executable)
    return None


def compile_tex_to_pdf(tex_path: str, output_dir: str | None = None,
                       clean_aux: bool = True, engine: str = "pdflatex") -> str | None:
    """Compile policy-checked TeX twice within one time budget, or return None."""
    if engine not in _ENGINES:
        logger.warning("Unsupported TeX engine requested")
        return None
    pdf_path = None
    work_dir = None
    tex_file = None
    try:
        tex_file = Path(tex_path).resolve(strict=True)
        if not tex_file.is_file() or tex_file.stat().st_size > MAX_TEX_SOURCE_BYTES:
            raise ValueError("Invalid TeX source file")
        validate_tex_source(tex_file.read_text(encoding="utf-8"))
        latex_exe = _find_engine(engine)
        if not latex_exe:
            logger.warning("Requested TeX compiler is unavailable")
            return None
        work_dir = Path(output_dir).resolve() if output_dir else tex_file.parent
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / tex_file.with_suffix(".pdf").name
        pdf_path.unlink(missing_ok=True)
        cmd = [latex_exe, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error"]
        if "miktex" in str(latex_exe).lower():
            cmd.extend(["--disable-write18", "--disable-installer", "--dont-parse-first-line"])
        else:
            cmd.append("-no-parse-first-line")
        cmd.extend([f"-output-directory={work_dir}", str(tex_file)])
        env = os.environ.copy()
        env.update(openin_any="p", openout_any="p", shell_escape="0",
                   TEXMFOUTPUT=str(work_dir), TEXMF_OUTPUT_DIRECTORY=str(work_dir))
        deadline = time.monotonic() + COMPILE_TIMEOUT_SECONDS
        for _ in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(engine, COMPILE_TIMEOUT_SECONDS)
            result = subprocess.run(cmd, cwd=str(work_dir), env=env, shell=False,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=remaining)
            if result.returncode != 0:
                logger.warning("TeX compilation failed")
                pdf_path.unlink(missing_ok=True)
                return None
        if not pdf_path.is_file() or pdf_path.is_symlink():
            return None
        with pdf_path.open("rb") as document:
            if document.read(5) != b"%PDF-":
                pdf_path.unlink(missing_ok=True)
                return None
        return str(pdf_path)
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
        logger.warning("TeX compilation rejected, timed out or failed")
        if pdf_path is not None:
            try:
                pdf_path.unlink(missing_ok=True)
            except OSError:
                pass
        return None
    finally:
        if clean_aux and work_dir is not None and tex_file is not None:
            for ext in (".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk", ".synctex.gz"):
                try:
                    (work_dir / tex_file.with_suffix(ext).name).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove a TeX auxiliary file")
