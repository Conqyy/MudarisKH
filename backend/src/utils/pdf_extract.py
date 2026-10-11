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


def extract_pdf_pages(file_bytes: bytes, max_pages: int = 160,
                      max_characters: int = 600000) -> list:
    """Read every numbered PDF page, including blank/scanned pages.

    Unlike the legacy excerpt helper this never silently samples a collection.
    Blank text is honest: callers must read the corresponding page image.
    """
    import fitz
    pages, characters = [], 0
    try:
        with fitz.open(stream=file_bytes, filetype='pdf') as document:
            if not document.page_count or document.page_count > max_pages:
                raise ValueError(f'Past-exam PDF exceeds the {max_pages}-page limit; split the file.')
            for index, page in enumerate(document):
                text = (page.get_text('text') or '').strip()
                if not text:
                    text = ' '.join(word[4] for word in page.get_text('words') or []).strip()
                characters += len(text)
                if characters > max_characters:
                    raise ValueError('Past-exam text exceeds the analysis limit; split the file.')
                pages.append({'page': index + 1, 'text': text})
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('Could not read every past-exam PDF page. Check the file and retry.') from error
    return pages


def render_pdf_page_window(file_bytes: bytes, start_page: int, end_page: int,
                           zoom: float = 1.25, max_pages: int = 32) -> list:
    """Render a complete contiguous 1-based inclusive range, or raise."""
    import base64
    import fitz
    if (type(start_page) is not int or type(end_page) is not int
            or start_page < 1 or end_page < start_page or end_page - start_page + 1 > max_pages):
        raise ValueError('Invalid or excessive PDF page window; split the source paper.')
    try:
        with fitz.open(stream=file_bytes, filetype='pdf') as document:
            if end_page > document.page_count:
                raise ValueError('Requested PDF page window is incomplete.')
            result = []
            for number in range(start_page, end_page + 1):
                page = document[number - 1]
                # Bound dimensions as well as page count (malicious/large page boxes).
                longest = max(page.rect.width, page.rect.height)
                scale = min(zoom, 1600 / longest) if longest > 0 else zoom
                png = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')
                result.append({'page': number, 'imageUri': 'data:image/png;base64,' + base64.b64encode(png).decode()})
            return result
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('Could not render complete past-exam page coverage. Check the PDF and retry.') from error
