"""Robust PDF text extraction.

pypdf frequently returns empty or garbled text for perfectly valid *text*
PDFs whose fonts lack a ToUnicode map (common with many LaTeX/exporter-produced
files). PyMuPDF (fitz) handles those far better, so we try it first and only
fall back to pypdf if needed.
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


def _extract_with_pypdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as e:  # pragma: no cover
        logger.warning(f"pypdf not available: {e}")
        return ""

    pages = []
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        for i, page in enumerate(reader.pages):
            txt = (page.extract_text() or "").strip()
            if txt:
                pages.append(f"[Page {i + 1}]\n{txt}")
    except Exception as e:
        logger.warning(f"pypdf extraction error: {e}")

    return "\n\n".join(pages)


def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a PDF using PyMuPDF first, pypdf as a fallback.

    Returns the richer of the two results. May return "" for scanned/
    image-only PDFs (which would require OCR to read).
    """
    primary = _extract_with_pymupdf(file_bytes)
    if len(primary.strip()) >= _MIN_MEANINGFUL:
        return primary

    logger.warning("PyMuPDF yielded little/no text; trying pypdf fallback.")
    fallback = _extract_with_pypdf(file_bytes)

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


def image_to_image_uri(file_bytes: bytes) -> str:
    """Normalize an uploaded photo/image into a PNG data-URI a vision model can
    read. Applies EXIF orientation (so sideways phone photos are upright),
    converts to RGB, and downscales very large photos to keep the payload sane.
    Rejects bytes that cannot be decoded as an image."""
    import base64
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(file_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        max_dim = 2200
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.warning('Image normalization failed: %s', type(e).__name__)
        raise ValueError('The uploaded image could not be decoded') from e


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
            count = min(max(1, max_pages), len(doc))
            indices = sorted({round(i * (len(doc) - 1) / max(1, count - 1)) for i in range(count)})
            for index in indices:
                page = doc[index]
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                png = pix.tobytes("png")
                uris.append("data:image/png;base64," + base64.b64encode(png).decode())
    except Exception as e:
        logger.warning(f"PDF->image render failed: {e}")
        return []
    return uris
