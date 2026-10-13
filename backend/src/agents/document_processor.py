from src.services.source_evidence import evidence_content, SOURCE_POLICY
from openai import OpenAI
import json
import io
import re
import logging
from src.config import settings
from src.config import prompts
from src.utils.ai_retry import chat_with_retry
from src.utils.ai_contracts import validate_analysis, response_text
from src.utils.text_normalization import excerpt
from src.utils.course_foundation import build_foundation_context
from src.utils.source_contracts import (
    validate_manifest, validate_guide, validate_source_visual_result, source_coverage,
)

logger = logging.getLogger("MudarisDocProcessor")
SOURCE_REQUEST_CHARACTERS = 30_000
SOURCE_REQUEST_IMAGES = 8


def _evidence_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _image_uris(value):
    if (not isinstance(value, list) or not value
            or any(not isinstance(uri, str) or not uri.startswith('data:image/') for uri in value)):
        raise ValueError('Original visual images are unavailable; render the source or convert it to PDF.')
    return value


def _validate_guide_batch(data, allowed):
    """Provider references can only point at evidence in this successful request."""
    fields = {'sections': ('label', 'purpose'), 'concepts': ('name',), 'visualReferences': ('kind', 'label')}
    if not isinstance(data, dict) or set(data) != set(fields) | {'warnings'}:
        raise ValueError('Invalid source guide batch fields')
    result = {key: [] for key in fields}
    for key, names in fields.items():
        if not isinstance(data[key], list):
            raise ValueError('Invalid source guide rows')
        for row in data[key]:
            if not isinstance(row, dict) or set(row) != set(names) | {'unitIds'}:
                raise ValueError('Invalid source guide row fields')
            normalized = {}
            for name in names:
                if not isinstance(row[name], str) or not row[name].strip():
                    raise ValueError('Empty source guide label')
                normalized[name] = ' '.join(row[name].split())
            refs = row['unitIds']
            if (not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs)
                    or len(set(refs)) != len(refs) or not set(refs) <= allowed):
                raise ValueError('Guide references were not supplied in this batch')
            normalized['unitIds'] = refs[:]
            result[key].append(normalized)
    if not isinstance(data['warnings'], list) or any(not isinstance(w, str) or not w.strip() for w in data['warnings']):
        raise ValueError('Invalid source guide warnings')
    result['warnings'] = list(dict.fromkeys(data['warnings']))
    return result


class DocumentProcessorAgent:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://mudaris-app.com",
                "X-Title": "Mudaris AI Engine"
            }, timeout=90.0, max_retries=0,
        )
        self.model_id = settings.OPENROUTER_MODEL

    def _source_request(self, policy, evidence, images, validator, label):
        from src.utils.json_parse import parse_with_retry

        serialized = _evidence_json(evidence)
        if len(serialized) > SOURCE_REQUEST_CHARACTERS or len(images) > SOURCE_REQUEST_IMAGES:
            raise ValueError('Split source evidence: request metadata/text exceeds processing bounds.')
        content = serialized
        if images:
            content = [{'type': 'text', 'text': serialized}] + [
                {'type': 'image_url', 'image_url': {'url': uri}} for uri in images]

        def call(reminder):
            try:
                response = chat_with_retry(
                    self.client, model=self.model_id,
                    messages=[{'role': 'system', 'content': policy + reminder},
                              {'role': 'user', 'content': content}],
                    temperature=0.1, max_tokens=settings.OPENROUTER_MAX_TOKENS)
            except Exception as exc:
                if images and getattr(exc, 'status_code', None) in (400, 415, 422):
                    raise RuntimeError('Configured provider could not read original images; use an image-capable model and retry preparation.') from exc
                raise
            return response_text(response)

        return parse_with_retry(call, label=label, validator=validator)

    def read_source_visual(self, unit: dict, image_uris: list[str]) -> dict:
        """Extract every supplied original asset; never interpret it as policy."""
        images = _image_uris(image_uris)
        if not isinstance(unit, dict) or unit.get('needsVisualRead') is not True:
            raise ValueError('Visual extraction requires a visual source unit')
        for key in ('unitId', 'kind', 'label'):
            if not isinstance(unit.get(key), str) or not unit[key].strip():
                raise ValueError('Invalid source visual metadata')
        if type(unit.get('position')) is not int or unit['position'] < 1:
            raise ValueError('Invalid source visual position')
        results = []
        # Native text is preserved by apply_source_visual_result, not rewritten by OCR.
        for start in range(0, len(images), SOURCE_REQUEST_IMAGES):
            batch = images[start:start + SOURCE_REQUEST_IMAGES]
            evidence = {'sourceUnit': {key: unit[key] for key in ('unitId', 'kind', 'position', 'label')},
                        'imageStart': start, 'imageEnd': start + len(batch), 'imageCount': len(images)}
            results.append(self._source_request(prompts.SOURCE_VISUAL_SYSTEM_PROMPT, evidence, batch,
                                                validate_source_visual_result, 'source visual extraction'))
        # A warned blank read is unresolved even when another asset is readable.
        readability = ('uncertain' if any(r['readability'] == 'uncertain'
                                         or (r['readability'] == 'blank' and r['warnings']) for r in results)
                       else 'blank' if all(r['readability'] == 'blank' for r in results) else 'readable')
        merged = {'text': '\n\n'.join(r['text'] for r in results if r['text'].strip()),
                  'visualDescription': '\n\n'.join(r['visualDescription'] for r in results if r['visualDescription'].strip()),
                  'readability': readability,
                  'warnings': list(dict.fromkeys(w for r in results for w in r['warnings']))}
        return validate_source_visual_result(merged)

    def analyze_source_guide(self, manifest: dict, course_title: str, render_unit) -> dict:
        """Guide a published, prepared source without changing its canonical revision."""
        manifest = validate_manifest(manifest)
        if not manifest['coverage']['complete'] or not manifest['coverage']['readableUnitIds']:
            raise ValueError('Source is blank or has unresolved preparation coverage; retry preparation.')
        if not isinstance(course_title, str):
            raise ValueError('Invalid course title')
        batches = self._guide_batches(manifest, course_title, render_unit)
        merged = {'version': 1, 'sourceRevision': manifest['sourceRevision'],
                  'sections': [], 'concepts': [], 'visualReferences': [], 'warnings': manifest['warnings'][:]}
        submitted = []
        for evidence, images in batches:
            allowed = {record['reference']['unitId'] for record in evidence['sourceEvidence']}
            result = self._source_request(prompts.SOURCE_GUIDE_SYSTEM_PROMPT, evidence, images,
                                          lambda data: _validate_guide_batch(data, allowed), 'source guide')
            # A parsed, validated successful batch is the only source of submitted accounting.
            submitted.extend(evidence['sourceEvidence'])
            for key in ('sections', 'concepts', 'visualReferences'):
                self._merge_guide_rows(merged[key], result[key], key)
            merged['warnings'] = list(dict.fromkeys(merged['warnings'] + result['warnings']))
        merged['unitCoverage'] = self._submitted_coverage(manifest, submitted)
        order = {unit['unitId']: index for index, unit in enumerate(manifest['units'])}
        for key in ('sections', 'concepts', 'visualReferences'):
            for row in merged[key]:
                row['unitIds'].sort(key=order.__getitem__)
        return validate_guide(merged, manifest)

    @staticmethod
    def _guide_batches(manifest, course_title, render_unit):
        """Pack complete Unicode ranges using their actual serialized request size."""
        records, images = [], []

        def envelope(items):
            return {'courseTitle': course_title, 'sourceEvidence': items}

        def fits(items):
            return len(_evidence_json(envelope(items))) <= SOURCE_REQUEST_CHARACTERS

        def flush():
            nonlocal records, images
            batch = (envelope(records), images)
            records, images = [], []
            return batch

        if not fits([]):
            raise ValueError('Split source metadata: course title exceeds request bounds.')
        for unit in manifest['units']:
            if unit['blank']:
                continue
            base = {'reference': {key: manifest[key] for key in ('documentId', 'sourceRevision')},
                    'label': unit['label'], 'kind': unit['kind'], 'position': unit['position']}
            base['reference']['unitId'] = unit['unitId']
            for field in ('text', 'visualText'):
                text = unit.get(field, '')
                start = 0
                while start < len(text):
                    def record(end):
                        return {**base, 'textField': field, 'start': start, 'end': end, 'text': text[start:end]}
                    # Fit at least one character, otherwise start a fresh request.
                    if not fits(records + [record(start + 1)]):
                        if records:
                            yield flush()
                        if not fits([record(start + 1)]):
                            raise ValueError('Split source metadata: unit label/identity exceeds request bounds.')
                    low, high = start + 1, len(text)
                    while low < high:
                        middle = (low + high + 1) // 2
                        if fits(records + [record(middle)]):
                            low = middle
                        else:
                            high = middle - 1
                    records.append(record(low))
                    start = low
                    if start < len(text):
                        yield flush()
            if unit['visualAssets']:
                uris = _image_uris(render_unit(unit))
                if len(uris) != len(unit['visualAssets']):
                    raise ValueError('Original visual rendering omitted or changed source assets; retry preparation.')
                for index, uri in enumerate(uris):
                    record = {**base, 'imageStart': index, 'imageEnd': index + 1, 'imageCount': len(uris)}
                    if len(images) == SOURCE_REQUEST_IMAGES or not fits(records + [record]):
                        if records:
                            yield flush()
                    if not fits([record]):
                        raise ValueError('Split source metadata: visual label/identity exceeds request bounds.')
                    records.append(record)
                    images.append(uri)
        if records:
            yield flush()

    @staticmethod
    def _submitted_coverage(manifest, submitted):
        accounted = []
        for unit in manifest['units']:
            records = [r for r in submitted if r['reference']['unitId'] == unit['unitId']]
            if not unit['blank']:
                if not records:
                    raise ValueError('Guide did not successfully process every nonblank unit')
                for field in ('text', 'visualText'):
                    end = 0
                    for record in (r for r in records if r.get('textField') == field):
                        if record['start'] != end or record['text'] != unit.get(field, '')[end:record['end']]:
                            raise ValueError('Guide has missing or contradictory submitted source ranges')
                        end = record['end']
                    if end != len(unit.get(field, '')):
                        raise ValueError('Guide did not successfully process complete source text')
                actual = [r['imageStart'] for r in records if 'imageStart' in r]
                if actual != list(range(len(unit['visualAssets']))):
                    raise ValueError('Guide did not successfully process every original visual asset')
            accounted.append(unit)
        return source_coverage(accounted)

    @staticmethod
    def _merge_guide_rows(target, rows, category):
        keys = {'sections': ('label',), 'concepts': ('name',), 'visualReferences': ('kind', 'label')}[category]
        for row in rows:
            identity = tuple(row[key].casefold() for key in keys)
            existing = next((old for old in target if tuple(old[key].casefold() for key in keys) == identity), None)
            if existing is None:
                target.append(row)
            else:
                existing['unitIds'] = list(dict.fromkeys(existing['unitIds'] + row['unitIds']))
                if category == 'sections' and row['purpose'] not in existing['purpose'].split('; '):
                    existing['purpose'] += '; ' + row['purpose']

    def extract_text(self, file_bytes: bytes, file_type: str) -> str:
        if file_type == "pdf":
            return self._extract_pdf(file_bytes)
        elif file_type == "pptx":
            return self._extract_pptx(file_bytes)
        elif file_type == "docx":
            return self._extract_docx(file_bytes)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    def _extract_pdf(self, file_bytes: bytes) -> str:
        # Robust extraction: PyMuPDF first (handles tricky font encodings that
        # pypdf returns empty for), with pypdf as a fallback.
        from src.utils.pdf_extract import extract_pdf_text
        return extract_pdf_text(file_bytes)

    def _extract_pptx(self, file_bytes: bytes) -> str:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(file_bytes))
        slides = []
        for i, slide in enumerate(prs.slides):
            texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        line = para.text.strip()
                        if line:
                            texts.append(line)
                if shape.has_table:
                    for row in shape.table.rows:
                        line = ' | '.join(cell.text.strip() for cell in row.cells)
                        if line.strip(): texts.append(line)
            if slide.has_notes_slide:
                frame = slide.notes_slide.notes_text_frame
                if frame is not None and frame.text.strip():
                    texts.append('[Speaker notes]\n' + frame.text.strip())
            if texts:
                slides.append(f"[Slide {i+1}]\n" + "\n".join(texts))
        return "\n\n".join(slides)

    def _extract_docx(self, file_bytes: bytes) -> str:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        for index, table in enumerate(doc.tables):
            cells = [' | '.join(cell.text.strip() for cell in row.cells) for row in table.rows]
            if any(cells):
                paragraphs.append(f'[Table {index + 1}]\n' + '\n'.join(cells))
        for section in doc.sections:
            for area in (section.header, section.footer):
                for paragraph in area.paragraphs:
                    if paragraph.text.strip() and paragraph.text.strip() not in paragraphs:
                        paragraphs.append(paragraph.text.strip())
        return "\n\n".join(paragraphs)

    def analyze_document(self, text: str, course_title: str, image_uris: list = None) -> dict:
        """Run AI analysis on document text. Retries once on malformed JSON,
        and RAISES on persistent failure (so the upload handler can mark the
        document 'failed' instead of silently storing an empty analysis).
        When page images are supplied, the (vision) model also reads equations,
        diagrams, figures, and code that plain text extraction misses.
        """
        from src.utils.json_parse import parse_with_retry

        logger.info("Analyzing lecture document"
                    + (f" (+{len(image_uris)} page images)" if image_uris else ""))
        truncated = excerpt(text, 30000)

        def _user_content():
            if image_uris:
                parts = [{
                    "type": "text",
                    "text": (
                        f"Course: {course_title}\n\nThe lecture pages are shown as images below"
                        " (read the equations, diagrams, figures, and code in them)."
                        + (f"\n\n---EXTRACTED TEXT (for reference)---\n{truncated}" if truncated.strip() else "")
                    ),
                }]
                for uri in image_uris[:8]:
                    parts.append({"type": "image_url", "image_url": {"url": uri}})
                return parts
            return f"Course: {course_title}\n\n---DOCUMENT TEXT---\n{truncated}"

        def _call(reminder: str) -> str:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": prompts.DOCUMENT_PROCESSOR_SYSTEM_PROMPT + reminder,
                    },
                    {"role": "user", "content": _user_content()},
                ],
                temperature=0.1,
                max_tokens=settings.OPENROUTER_MAX_TOKENS,
            )
            return response_text(response)

        result = parse_with_retry(
            _call,
            required_keys=(
                "topics",
                "definitions",
                "formulas",
                "chapterMapping",
                "keyConceptCount",
            ),
            label="document analysis",
            validator=lambda data: validate_analysis('document', data),
        )

        # Sanity check: if every output field is empty, the analysis was
        # effectively useless — fail loudly so the user can retry.
        topics = result.get("topics") or []
        defs = result.get("definitions") or []
        formulas = result.get("formulas") or []
        chapters = result.get("chapterMapping") or []
        if not topics and not defs and not formulas and not chapters:
            raise RuntimeError(
                "The AI returned an empty analysis (no topics, definitions, "
                "formulas, or chapters). Try re-analyzing — the model may "
                "have been overloaded or had trouble with this content."
            )

        result['_contextCoverage'] = {'characters': len(text), 'includedCharacters': len(truncated), 'excerpted': len(text) > 30000,
                                      'imagesIncluded': min(len(image_uris or []), 8), 'imagesAvailable': len(image_uris or [])}
        return result

    def analyze_tutorial(self, text: str, course_title: str, image_uris: list = None,
                         document_insights: list = None, *, lecture_evidence: dict | None = None) -> dict:
        """Analyze a TUTORIAL / practice-problem sheet. Unlike a lecture document,
        a tutorial is a set of QUESTIONS the student solves — so we capture each
        problem (what it asks, the given data/tables, the concept, and the method)
        precisely enough that an exam can regenerate a variant with new numbers.
        Page images let the model read tables, equations, diagrams, and code."""
        from src.utils.json_parse import parse_with_retry

        logger.info("Analyzing tutorial"
                    + (f" (+{len(image_uris)} page images)" if image_uris else ""))
        truncated = excerpt(text, 30000)
        reference = build_foundation_context(document_insights)
        grounding = (
            '\n\nUse the lecture document reference for course topic and method alignment. '
            'The tutorial text and page images remain the primary evidence: preserve every '
            'original problem, given data, requested task, and problem count. Do not replace '
            'the exercises with lecture examples or solve them. Describe unsupported course '
            'alignment honestly in the existing concept/method fields. Keep the existing '
            'output schema.\n\n' + reference if reference else ''
        )

        def _user_content():
            if image_uris:
                parts = [{
                    "type": "text",
                    "text": (
                        f"Course: {course_title}{grounding}\n\nThe tutorial pages are shown as images below"
                        " (read the problems, tables, equations, diagrams, and code in them)."
                        + (f"\n\n---EXTRACTED TEXT (for reference)---\n{truncated}" if truncated.strip() else "")
                    ),
                }]
                for uri in image_uris[:8]:
                    parts.append({"type": "image_url", "image_url": {"url": uri}})
                return parts
            return f"Course: {course_title}{grounding}\n\n---TUTORIAL TEXT---\n{truncated}"

        def _call(reminder: str) -> str:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": prompts.TUTORIAL_SYSTEM_PROMPT + reminder + (SOURCE_POLICY if lecture_evidence is not None else ""),
                    },
                    {"role": "user", "content": evidence_content(_user_content(), lecture_evidence)},
                ],
                temperature=0.1,
                # Tutorials can have many problems + code; give the JSON room so
                # it isn't truncated mid-output.
                max_tokens=max(settings.OPENROUTER_MAX_TOKENS, 8000),
            )
            return response_text(response)

        result = parse_with_retry(
            _call,
            required_keys=("topics", "problems", "formulas", "skills", "problemCount"),
            label="tutorial analysis",
            validator=lambda data: validate_analysis('tutorial', data),
        )

        problems = result.get("problems") or []
        topics = result.get("topics") or []
        if not problems and not topics:
            raise RuntimeError(
                "The AI returned an empty tutorial analysis (no problems or "
                "topics). Try re-analyzing — the model may have been overloaded."
            )

        result['_contextCoverage'] = {'characters': len(text), 'includedCharacters': len(truncated), 'excerpted': len(text) > 30000,
                                      'imagesIncluded': min(len(image_uris or []), 8), 'imagesAvailable': len(image_uris or [])}
        return result
