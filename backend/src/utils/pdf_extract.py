"""Robust PDF text extraction.

PyPDF2 frequently returns empty or garbled text for perfectly valid *text*
PDFs whose fonts lack a ToUnicode map (common with many LaTeX/exporter-produced
files). PyMuPDF (fitz) handles those far better, so we try it first and only
fall back to PyPDF2 if needed.
"""
import io
import logging

logger = logging.getLogger("MudarisPDFExtract")

# Below this many characters we treat the extraction as "failed" (likely a
# scanned/image-only PDF, or an encoding the extractor couldn't decode).
_MIN_MEANINGFUL = 20


def _extract_with_pymupdf(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover
        logger.warning(f"PyMuPDF not available: {e}")
        return ""

    pages = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for i, page in enumerate(doc):
                txt = (page.get_text("text") or "").strip()
                if not txt:
                    # Fallback: reconstruct text from positioned word tokens.
                    words = page.get_text("words") or []
                    if words:
                        txt = " ".join(w[4] for w in words).strip()
                if txt:
                    pages.append(f"[Page {i + 1}]\n{txt}")
    except Exception as e:
        logger.warning(f"PyMuPDF extraction error: {e}")

    return "\n\n".join(pages)


def _extract_with_pypdf2(file_bytes: bytes) -> str:
    try:
        from PyPDF2 import PdfReader
    except Exception as e:  # pragma: no cover
        logger.warning(f"PyPDF2 not available: {e}")
        return ""

    pages = []
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        for i, page in enumerate(reader.pages):
            txt = (page.extract_text() or "").strip()
            if txt:
                pages.append(f"[Page {i + 1}]\n{txt}")
    except Exception as e:
        logger.warning(f"PyPDF2 extraction error: {e}")

    return "\n\n".join(pages)


def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF using PyMuPDF first, PyPDF2 as a fallback.

    Returns the richer of the two results. May return "" for scanned/
    image-only PDFs (which would require OCR to read).
    """
    primary = _extract_with_pymupdf(file_bytes)
    if len(primary.strip()) >= _MIN_MEANINGFUL:
        return primary

    logger.warning("PyMuPDF yielded little/no text; trying PyPDF2 fallback.")
    fallback = _extract_with_pypdf2(file_bytes)

    best = primary if len(primary.strip()) >= len(fallback.strip()) else fallback
    if not best.strip():
        logger.error(
            "PDF text extraction failed entirely — the file is likely a "
            "scanned/image-only PDF that needs OCR."
        )
    return best


def is_meaningful_text(text: str) -> bool:
    """True if the extracted text has enough content to be worth analyzing."""
    return bool(text) and len(text.strip()) >= _MIN_MEANINGFUL


def pdf_to_image_uris(file_bytes: bytes, max_pages: int = 8, zoom: float = 2.0) -> list:
    """Render PDF pages to PNG data-URIs so a vision model can SEE the page —
    including equations, diagrams, figures, and code that plain text extraction
    misses. Returns [] if PyMuPDF is unavailable or rendering fails."""
    try:
        import base64
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover
        logger.warning(f"PyMuPDF not available for rendering: {e}")
        return []

    uris = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc[:max_pages]:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                png = pix.tobytes("png")
                uris.append("data:image/png;base64," + base64.b64encode(png).decode())
    except Exception as e:
        logger.warning(f"PDF->image render failed: {e}")
        return []
    return uris
