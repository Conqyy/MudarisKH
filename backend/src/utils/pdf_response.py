"""Own temporary PDF directories through compilation and response streaming."""
import logging
import re
import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from src.utils.compile_pdf import compile_tex_to_pdf, validate_tex_source

logger = logging.getLogger("MudarisCompiler")
_OWNED_DIRECTORIES: dict[Path, Path] = {}
_OWNERSHIP_LOCK = threading.Lock()


def unicode_font_preamble() -> list[str]:
    """XeLaTeX language setup with bounded, installed Arabic-font fallbacks.

    Latin text keeps XeLaTeX's default font. Missing Arabic fonts produce a
    compilation error rather than silently rendering unsupported characters.
    """
    return [
        r"\usepackage{fontspec}",
        r"\usepackage{polyglossia}",
        r"\setmainlanguage{english}",
        r"\setotherlanguage{arabic}",
        r"\IfFontExistsTF{Arial}{\newfontfamily\arabicfont[Script=Arabic]{Arial}}{",
        r"\IfFontExistsTF{Amiri}{\newfontfamily\arabicfont[Script=Arabic]{Amiri}}{",
        r"\IfFontExistsTF{Noto Naskh Arabic}{\newfontfamily\arabicfont[Script=Arabic]{Noto Naskh Arabic}}{",
        r"\IfFontExistsTF{DejaVu Sans}{\newfontfamily\arabicfont[Script=Arabic]{DejaVu Sans}}{",
        r"\PackageError{Mudaris}{No supported Arabic font is installed}{Install Arial, Amiri, Noto Naskh Arabic, or DejaVu Sans.}",
        r"}}}}",
    ]


class _TemporaryPDFResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A client disconnect can prevent Starlette's background callback.
            cleanup_temp_pdf(self.path)


def _safe_basename(name: str) -> str:
    basename = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    basename = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)[:60].strip("._") or "document"
    if basename.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        basename = "document_" + basename
    return basename


def _cleanup_owned_directory(directory: Path) -> None:
    with _OWNERSHIP_LOCK:
        parent = _OWNED_DIRECTORIES.get(directory)
        if parent is None:
            return
    # Verify the exact registered absolute target immediately before deletion.
    if directory.parent != parent or directory.resolve() != directory or directory.is_symlink():
        logger.warning("Refused cleanup of a replaced temporary PDF directory")
        return
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Temporary PDF cleanup failed")
        return
    with _OWNERSHIP_LOCK:
        _OWNED_DIRECTORIES.pop(directory, None)


def compile_temp_pdf(tex: str, name: str, engine: str = "pdflatex") -> str | None:
    """Return an owned temporary PDF; invalid source raises ValueError."""
    validate_tex_source(tex)
    directory = Path(tempfile.mkdtemp(prefix="mudaris-pdf-")).resolve()
    with _OWNERSHIP_LOCK:
        _OWNED_DIRECTORIES[directory] = directory.parent
    keep = False
    try:
        tex_file = directory / f"{_safe_basename(name)}.tex"
        tex_file.write_text(tex, encoding="utf-8")
        result = compile_tex_to_pdf(str(tex_file), engine=engine)
        expected = tex_file.with_suffix(".pdf")
        if not result or Path(result).resolve() != expected or not expected.is_file() or expected.is_symlink():
            return None
        with expected.open("rb") as document:
            if document.read(5) != b"%PDF-":
                return None
        keep = True
        return str(expected)
    except OSError:
        logger.warning("Temporary PDF creation failed")
        return None
    finally:
        if not keep:
            _cleanup_owned_directory(directory)


def cleanup_temp_pdf(path: str) -> None:
    """Remove only a directory allocated and registered by this module."""
    directory = Path(path).absolute().parent
    _cleanup_owned_directory(directory)


def pdf_file_response(path: str, name: str) -> FileResponse:
    """Stream a PDF and release its owned directory after streaming."""
    try:
        return _TemporaryPDFResponse(path, media_type="application/pdf", filename=f"{_safe_basename(name)}.pdf",
                            content_disposition_type="inline", background=BackgroundTask(cleanup_temp_pdf, path))
    except Exception:
        cleanup_temp_pdf(path)
        raise


def compile_pdf_response(tex: str, name: str, engine: str = "pdflatex") -> FileResponse:
    try:
        path = compile_temp_pdf(tex, name, engine=engine)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The document contains unsupported or unsafe TeX") from exc
    except Exception as exc:
        logger.warning("Temporary PDF compilation failed")
        raise HTTPException(status_code=503, detail="PDF compilation is unavailable or failed") from exc
    if not path:
        raise HTTPException(status_code=503, detail="PDF compilation is unavailable or failed")
    return pdf_file_response(path, name)


def check_tex_compiles(tex: str, name: str = "document", engine: str = "pdflatex") -> bool:
    """Check compilation without retaining the PDF or auxiliary files."""
    path = None
    try:
        path = compile_temp_pdf(tex, name, engine=engine)
        return path is not None
    except (ValueError, OSError):
        return False
    finally:
        if path:
            cleanup_temp_pdf(path)
