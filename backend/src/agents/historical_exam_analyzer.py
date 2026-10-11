from openai import OpenAI
import json
import logging
import math
from collections import defaultdict
from statistics import median
from src.config import settings
from src.config import prompts
from src.utils.ai_retry import chat_with_retry
from src.utils.ai_contracts import validate_analysis, response_text
from src.utils.text_normalization import as_text
from src.config.historical_prompts import HISTORICAL_BOUNDARY_SYSTEM_PROMPT
from src.utils.course_foundation import build_foundation_context

logger = logging.getLogger("MudarisHistAnalyzer")


def _allocate_counts(shares: dict, total: int) -> dict:
    """Largest remainders keep a typical paper's integer type counts consistent."""
    denominator = sum(shares.values()) or 1
    exact = {key: value / denominator * total for key, value in shares.items()}
    counts = {key: math.floor(value) for key, value in exact.items()}
    for key in sorted(exact, key=lambda key: -(exact[key] - counts[key]))[:total - sum(counts.values())]:
        counts[key] += 1
    return counts


def aggregate_papers(papers: list) -> dict:
    """Compatible single-paper statistics, giving each actual paper equal influence."""
    if not papers:
        raise ValueError('No complete past-exam papers were found.')
    types, topics, difficulty = defaultdict(float), {}, defaultdict(float)
    styles, patterns = {}, []
    for paper in papers:
        validate_analysis('historical', paper)
        for row in paper['questionTypes']:
            types[row['type']] += row['count'] / paper['totalQuestions'] / len(papers)
            if row.get('style'):
                styles.setdefault(row['type'], [])
                if row['style'] not in styles[row['type']]:
                    styles[row['type']].append(row['style'])
        weight_total = sum(row['weight'] for row in paper['topicWeights']) or 1
        for row in paper['topicWeights']:
            key = row['topic'].strip().casefold()
            if key not in topics:
                topics[key] = {'topic': row['topic'], 'weight': 0.0, 'questionCount': 0.0}
            topics[key]['weight'] += row['weight'] / weight_total / len(papers)
            topics[key]['questionCount'] += row['questionCount'] / len(papers)
        difficulty_total = sum(row['percentage'] for row in paper['difficultyDistribution']) or 100
        for row in paper['difficultyDistribution']:
            difficulty[row['level']] += row['percentage'] / difficulty_total * 100 / len(papers)
        for pattern in paper['patterns']:
            if pattern not in patterns:
                patterns.append(pattern)
    typical = max(1, math.floor(median(paper['totalQuestions'] for paper in papers) + 0.5))
    counts = _allocate_counts(types, typical)
    topic_total = sum(row['weight'] for row in topics.values()) or 1
    result = {
        'analysisVersion': 2, 'paperCount': len(papers), 'papers': papers,
        'collectionQuestionCount': sum(paper['totalQuestions'] for paper in papers),
        'totalQuestions': typical,
        'questionTypes': [{'type': key, 'count': count, 'percentage': count / typical * 100,
                           'style': '; '.join(styles.get(key, []))} for key, count in counts.items() if count],
        'topicWeights': [{**row, 'weight': row['weight'] / topic_total,
                         'questionCount': math.floor(row['questionCount'] + 0.5)} for row in topics.values()],
        'difficultyDistribution': [{'level': key, 'percentage': value} for key, value in difficulty.items()],
        'patterns': patterns,
        'gradingBlueprint': 'Each paper has equal influence. Typical length is the median paper question count; '
                            'type proportions are normalized per paper. Original mark allocations remain in papers[].',
        'skills': list(dict.fromkeys(skill for paper in papers for skill in paper.get('skills', []))),
    }
    validate_analysis('historical', result)
    return result


class HistoricalExamAnalyzer:
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

    def extract_exam_text(self, file_bytes: bytes) -> str:
        # Robust extraction: PyMuPDF first (handles font encodings pypdf fails
        # on), with pypdf as a fallback.
        from src.utils.pdf_extract import extract_pdf_text
        return extract_pdf_text(file_bytes)

    def analyze_exam(self, text: str, course_title: str, image_uris: list = None,
                     document_insights: list = None) -> dict:
        """Compatibility entry for one photo/text paper; PDFs use analyze_pdf."""
        result = self._analyze_paper(text, course_title, image_uris, document_insights)
        paper = {**result, 'paperId': 'paper_1', 'startPage': 1,
                 'endPage': max(1, len(image_uris or [])), 'examType': result.get('examType'), 'totalMarks': result.get('totalMarks'),
                 'boundaryEvidence': 'Individual photo/text input; PDF paper boundaries were not detected.',
                 'boundaryConfidence': None, 'boundaryStatus': 'individual_input'}
        combined = aggregate_papers([paper])
        self.tag_topic_scope(combined, document_insights)
        combined['_contextCoverage'] = result['_contextCoverage']
        return combined

    def analyze_pdf(self, file_bytes: bytes, course_title: str,
                    document_insights: list = None) -> dict:
        """Detect complete contiguous papers, then analyze every page of each paper."""
        from src.utils.pdf_extract import extract_pdf_pages, render_pdf_page_window
        from src.utils.json_parse import parse_with_retry
        pages = extract_pdf_pages(file_bytes)
        decisions, current_start, current_identity, previous_image = [], None, None, None
        for offset in range(0, len(pages), 8):
            batch = pages[offset:offset + 8]
            numbers = [page['page'] for page in batch]
            images = render_pdf_page_window(file_bytes, numbers[0], numbers[-1], max_pages=8)
            self._require_page_coverage(images, numbers)
            if any(len(page['text']) > 12000 for page in batch):
                raise ValueError('One past-exam page exceeds the text limit; split or simplify the file.')
            content = [{'type': 'text', 'text': f'Course: {course_title}\nRequested pages: {numbers}\n'
                f'Current paper begins at page: {current_start}\n'
                + (f'Current paper identity and boundary evidence: {json.dumps(current_identity, ensure_ascii=False)}\n'
                   if current_identity else '')
                + (f'Previous page {pages[offset - 1]["page"]}:\n{pages[offset - 1]["text"]}\n' if offset else '')}]
            if previous_image is not None:
                content.append({'type': 'text', 'text': f'CONTEXT ONLY: Previous PDF Page {previous_image["page"]}. '
                    'Use this image for continuity; do NOT return a decision for this context page.'})
                content.append({'type': 'image_url', 'image_url': {'url': previous_image['imageUri']}})
            for page, image in zip(batch, images):
                content.append({'type': 'text', 'text': f'PDF Page {page["page"]}\n{page["text"]}'})
                content.append({'type': 'image_url', 'image_url': {'url': image['imageUri']}})

            def _call(reminder):
                answer = chat_with_retry(self.client, model=self.model_id,
                    messages=[{'role': 'system', 'content': HISTORICAL_BOUNDARY_SYSTEM_PROMPT + reminder},
                              {'role': 'user', 'content': content}], temperature=0.0, max_tokens=4000)
                return response_text(answer)

            def _validate(value):
                rows = value.get('pages')
                if not isinstance(rows, list) or [row.get('page') for row in rows if isinstance(row, dict)] != numbers:
                    raise ValueError('Paper boundary decisions do not cover every requested page.')
                for row in rows:
                    if type(row.get('startsPaper')) is not bool or type(row.get('uncertain')) is not bool:
                        raise ValueError('Invalid paper boundary decision.')
                    confidence = row.get('confidence')
                    if (type(confidence) not in (int, float) or not math.isfinite(confidence)
                            or not 0 <= confidence <= 1):
                        raise ValueError('Invalid paper boundary confidence.')
                    if row['uncertain'] or confidence < 0.75:
                        raise ValueError('Ambiguous paper boundaries; split the PDF into individual papers and retry.')
                    if not isinstance(row.get('evidence'), str) or not row['evidence'].strip():
                        raise ValueError('Paper boundary evidence is missing.')
                    if row.get('examType') not in (None, 'quiz', 'midterm', 'final'):
                        raise ValueError('Invalid detected exam type; use null when unknown.')
                    marks = row.get('totalMarks')
                    if marks is not None and (type(marks) not in (int, float) or not math.isfinite(marks) or marks <= 0):
                        raise ValueError('Invalid detected total marks; use null when unknown.')
                if numbers[0] == 1 and not rows[0]['startsPaper']:
                    raise ValueError('PDF does not begin with an identifiable paper boundary; split the file.')
                return value

            try:
                detected = parse_with_retry(_call, label='paper boundaries', validator=_validate)['pages']
            except RuntimeError as error:
                raise RuntimeError('Could not identify every paper boundary confidently. '
                                   'Split this PDF into individual exams and retry.') from error
            decisions.extend(detected)
            for row in detected:
                if row['startsPaper']:
                    current_start = row['page']
                    current_identity = {'startPage': row['page'], 'examType': row.get('examType'),
                                        'totalMarks': row.get('totalMarks'), 'boundaryEvidence': row['evidence']}
            previous_image = images[-1]

        starts = [row for row in decisions if row['startsPaper']]
        papers = []
        for index, start in enumerate(starts):
            first = start['page']
            last = starts[index + 1]['page'] - 1 if index + 1 < len(starts) else len(pages)
            images = render_pdf_page_window(file_bytes, first, last)
            self._require_page_coverage(images, list(range(first, last + 1)))
            text = '\n\n'.join(f'[Page {page["page"]}]\n{page["text"]}' for page in pages[first - 1:last])
            result = self._analyze_paper(text, course_title, [image['imageUri'] for image in images], document_insights)
            papers.append({**result, 'paperId': f'paper_{index + 1}', 'startPage': first, 'endPage': last,
                           'examType': start.get('examType') or result.get('examType'),
                           'totalMarks': start.get('totalMarks') or result.get('totalMarks'),
                           'boundaryEvidence': start['evidence'], 'boundaryConfidence': start['confidence'],
                           'boundaryStatus': 'detected'})
        combined = aggregate_papers(papers)
        self.tag_topic_scope(combined, document_insights)
        combined['_contextCoverage'] = {'pagesAvailable': len(pages), 'pagesIncluded': len(pages),
            'imagesAvailable': len(pages), 'imagesIncluded': len(pages), 'excerpted': False,
            'characters': sum(len(page['text']) for page in pages),
            'includedCharacters': sum(len(page['text']) for page in pages)}
        return combined

    @staticmethod
    def _require_page_coverage(images: list, numbers: list) -> None:
        if ([row.get('page') for row in images] != numbers
                or any(not isinstance(row.get('imageUri'), str) or not row['imageUri'] for row in images)):
            raise ValueError('Incomplete PDF image page coverage. Check the source and retry.')

    def _analyze_paper(self, text: str, course_title: str, image_uris: list = None,
                       document_insights: list = None) -> dict:
        logger.info("Analyzing historical exam"
                    + (f" (+{len(image_uris)} page images)" if image_uris else ""))

        if len(text) > 80000 or len(image_uris or []) > 32:
            raise ValueError('Individual past-exam paper exceeds the analysis limit; split the source.')
        truncated = text
        reference = build_foundation_context(document_insights)
        grounding = (
            '\n\nUse the lecture document reference to interpret paper topics and academic '
            'terminology. The original exam text and images remain the primary evidence. '
            'Preserve all original question counts, question types, difficulty, and marks, '
            'including out-of-scope questions; never change the paper to fit the lectures. '
            'Describe unsupported course alignment honestly using the existing topic names '
            'and patterns. Keep the existing output schema; scope tags are applied separately.\n\n'
            + reference if reference else ''
        )

        from src.utils.json_parse import parse_with_retry

        def _user_content():
            # When page images are available, send them so the model can SEE
            # equations, diagrams, figures, and code — not just extracted text.
            if image_uris:
                parts = [{
                    "type": "text",
                    "text": (
                        f"Course: {course_title}{grounding}\n\nThe exam pages are shown as images below"
                        " (read the equations, diagrams, figures, and code in them)."
                        + (f"\n\n---EXTRACTED TEXT (for reference)---\n{truncated}" if truncated.strip() else "")
                    ),
                }]
                for uri in image_uris:
                    parts.append({"type": "image_url", "image_url": {"url": uri}})
                return parts
            return f"Course: {course_title}{grounding}\n\n---EXAM TEXT---\n{truncated}"

        def _call(reminder: str) -> str:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": prompts.HISTORICAL_EXAM_SYSTEM_PROMPT + reminder
                            + '\nThis input is ONE already-separated paper. Analyze only this paper, '
                              'count each exam question once (not again in attached answer keys), '
                              'and return its flat historical-analysis fields. Do not aggregate other papers.',
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
                "topicWeights",
                "questionTypes",
                "difficultyDistribution",
                "gradingBlueprint",
                "patterns",
                "totalQuestions",
            ),
            label="historical exam analysis",
            validator=lambda data: validate_analysis('historical', data),
        )
        # gradingBlueprint is a string, not a list — fix default if missing
        if not isinstance(result.get("gradingBlueprint"), str):
            result["gradingBlueprint"] = ""

        topics = result.get("topicWeights") or []
        qtypes = result.get("questionTypes") or []
        patterns = result.get("patterns") or []
        if not topics and not qtypes and not patterns:
            raise RuntimeError(
                "The AI returned an empty exam analysis. Try re-uploading or "
                "re-analyzing — the model may have been overloaded."
            )

        # Scope check: decide HERE (at analysis time) whether each of this past
        # exam's topics is still covered by the course's current lecture
        # documents. The result is stored on the analysis so the generator just
        # reads the flag — it never re-decides scope itself.
        self.tag_topic_scope(result, document_insights)

        result['_contextCoverage'] = {'characters': len(text), 'includedCharacters': len(truncated), 'excerpted': False,
                                      'imagesIncluded': len(image_uris or []), 'imagesAvailable': len(image_uris or [])}
        return result

    @staticmethod
    def tag_topic_scope(result: dict, document_insights: list) -> dict:
        """Annotate each topicWeight with inScope (True/False) against the course's
        current lecture documents, and add a top-level outOfCourseTopics list.
        If no documents are available, scope is left undetermined (inScope=None)."""
        from src.utils.topic_scope import course_scope_from_docs, topic_in_scope

        topics = result.get("topicWeights") or []
        _, words = course_scope_from_docs(document_insights)
        out_of_course = []
        for w in topics:
            name = as_text(w.get("topic", ""))
            if not words:                 # no documents → can't judge scope
                w["inScope"] = None
                continue
            in_scope = topic_in_scope(name, words)
            w["inScope"] = in_scope
            if not in_scope and name:
                out_of_course.append(name)
        result["outOfCourseTopics"] = out_of_course
        result["scopeChecked"] = bool(words)
        result['scopeStatus'] = 'document_scope' if words else 'no_doc_scope'
        if out_of_course:
            logger.info('Past exam: %d out-of-scope topics excluded', len(out_of_course))
        return result
