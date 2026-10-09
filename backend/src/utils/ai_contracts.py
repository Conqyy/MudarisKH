"""Validate provider output before it can be marked successful or persisted."""
from collections import Counter
import math
import re
from src.utils.text_normalization import normalize_insights, text_list

QUESTION_TYPES = frozenset({'mcq', 'written', 'true_false', 'fill_blank', 'matching',
                            'equation', 'proof', 'calculation', 'diagram', 'code', 'problem_solving', 'essay'})


def response_text(response) -> str:
    choices = getattr(response, 'choices', None)
    if not choices or getattr(choices[0], 'finish_reason', None) == 'length':
        raise ValueError('AI response is missing or truncated')
    content = getattr(getattr(choices[0], 'message', None), 'content', None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError('AI response is empty')
    return content.strip()


def _text(row, key, nonempty=True):
    value = row.get(key)
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError(f'Invalid AI text field: {key}')
    return value


def _number(row, key, lower=0, upper=None, integer=False):
    value = row.get(key)
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or (integer and type(value) is not int) or value < lower or (upper is not None and value > upper)):
        raise ValueError(f'Invalid AI numeric field: {key}')
    return value


def _list(row, key, nonempty=False):
    value = row.get(key)
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f'Invalid AI array field: {key}')
    return value


def _objects(row, key, text_fields=(), nonempty=False):
    values = _list(row, key, nonempty)
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f'Invalid AI object in: {key}')
        for field in text_fields:
            _text(value, field)
    return values


def _strings(row, key):
    values = _list(row, key)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f'Invalid AI text array: {key}')
    return values


def validate_analysis(kind: str, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('Analysis must be an object')
    # Tolerate known legacy topic/formula object shapes while rejecting unknown
    # nontext items rather than quietly dropping them from newly generated data.
    for key in ('topics', 'formulas', 'skills', 'patterns'):
        if key in data:
            original = _list(data, key)
            normalized = text_list(original)
            if len(normalized) != len(original):
                raise ValueError(f'Unrecognizable analysis text in {key}')
            data = {**data, key: normalized}
    if kind == 'document':
        for key in ('topics', 'formulas'): _strings(data, key)
        _objects(data, 'definitions', ('term', 'definition'))
        _objects(data, 'chapterMapping', ('chapter', 'content'))
        _number(data, 'keyConceptCount', integer=True)
        if not any(data[key] for key in ('topics', 'formulas', 'definitions', 'chapterMapping')):
            raise ValueError('Empty document analysis')
    elif kind == 'tutorial':
        for key in ('topics', 'formulas', 'skills'): _strings(data, key)
        problems = _objects(data, 'problems', ('label', 'statement'))
        for problem in problems:
            for key in ('concept', 'method', 'type'):
                if key in problem: _text(problem, key, False)
            if 'asks' in problem: _strings(problem, 'asks')
        if _number(data, 'problemCount', integer=True) != len(problems):
            raise ValueError('Tutorial problem count does not match complete problems')
        if not problems and not data['topics']: raise ValueError('Empty tutorial analysis')
    elif kind == 'audio':
        _text(data, 'summary', False)
        chapters = _objects(data, 'chapterMapping', ('chapter',))
        for chapter in chapters: _strings(chapter, 'segments')
        for hint in _objects(data, 'examHints', ('hint', 'source')): _number(hint, 'confidence', upper=1)
        for emphasis in _objects(data, 'keyEmphasis', ('topic', 'quote')):
            if emphasis.get('emphasisLevel') not in ('high', 'medium', 'low'): raise ValueError('Invalid emphasis level')
        if not any(data[key] for key in ('chapterMapping', 'examHints', 'keyEmphasis', 'summary')):
            raise ValueError('Empty audio analysis')
    elif kind == 'historical':
        total = _number(data, 'totalQuestions', lower=1, integer=True)
        types = _objects(data, 'questionTypes', ('type',), True)
        for item in types:
            if item['type'] not in QUESTION_TYPES: raise ValueError('Unknown historical question type')
            _number(item, 'count', lower=1, integer=True)
            _number(item, 'percentage', upper=100)
        if sum(item['count'] for item in types) != total: raise ValueError('Historical question counts disagree')
        weights = _objects(data, 'topicWeights', ('topic',))
        for item in weights:
            _number(item, 'weight', upper=1)
            _number(item, 'questionCount', integer=True)
        for item in _objects(data, 'difficultyDistribution', ('level',)):
            if item['level'] not in ('easy', 'medium', 'hard'): raise ValueError('Invalid difficulty level')
            _number(item, 'percentage', upper=100)
        _text(data, 'gradingBlueprint')
        _strings(data, 'patterns')
    else:
        raise ValueError('Unknown analysis contract')
    return data


def validate_summary(data: dict) -> dict:
    _text(data, 'title')
    _text(data, 'overview')
    for section in _objects(data, 'sections', ('heading', 'content'), True):
        _strings(section, 'keyPoints')
        if section.get('examLikelihood') not in ('high', 'medium', 'low'): raise ValueError('Invalid exam likelihood')
        _number(section, 'examWeight', upper=100)
    _objects(data, 'keyTerms', ('term', 'definition'))
    _strings(data, 'examFocus')
    return data


def validate_flashcards(data: dict, count: int) -> dict:
    cards = _objects(data, 'cards', ('front', 'back', 'topic'), True)
    if len(cards) != count: raise ValueError('Generated card count differs from requested count')
    seen = set()
    for card in cards:
        if card.get('examLikelihood') not in ('high', 'medium', 'low'): raise ValueError('Invalid card likelihood')
        front = card['front'].strip().casefold()
        if front in seen: raise ValueError('Duplicate flashcard front')
        seen.add(front)
    return data


def validate_answers(data: dict, expected_count: int = None) -> dict:
    items = _objects(data, 'items', ('question', 'answer'), True)
    if expected_count is not None and len(items) != expected_count: raise ValueError('Answer key is incomplete')
    for item in items:
        if 'explanation' in item: _text(item, 'explanation', False)
    return data


def exam_question_numbers(tex: str) -> list:
    clean = re.sub(r'<secret-rubrics>.*?</secret-rubrics>', '', tex, flags=re.DOTALL)
    return [int(number) for number in re.findall(r'\\(?:textbf|section\*|subsection\*)\{\s*Question\s+(\d+)\b', clean, flags=re.IGNORECASE)]


def align_printed_marks(tex: str, rubrics: dict) -> str:
    """Apply validated normalized rubric marks to the corresponding display."""
    validate_exam_contract(tex, rubrics)
    questions = rubrics.get('questions', {})
    scores = [_number(questions[f'q{i + 1}'], 'max_score', lower=0.000001) for i in range(len(questions))]
    pattern = r'\[\s*(\d+(?:\.\d+)?)\s*(marks?)\s*\]'
    if not scores or len(re.findall(pattern, tex, re.IGNORECASE)) != len(scores):
        raise ValueError('Cannot align marks: printed question marks are missing or ambiguous')
    values = iter(scores)
    return re.sub(pattern, lambda match: f'[{next(values):g} {match.group(2)}]', tex, flags=re.IGNORECASE)


def validate_rubrics(rubrics: dict) -> dict:
    questions = rubrics.get('questions') if isinstance(rubrics, dict) else None
    if not isinstance(questions, dict) or not questions:
        raise ValueError('Exam grading rubric is missing or incomplete')
    expected_ids = {f'q{i}' for i in range(1, len(questions) + 1)}
    if set(questions) != expected_ids: raise ValueError('Exam question IDs are missing or duplicated')
    for row in questions.values():
        if not isinstance(row, dict) or row.get('question_type') not in QUESTION_TYPES:
            raise ValueError('Invalid rubric question type')
        _number(row, 'max_score', lower=0.000001)
        if row['question_type'] in ('mcq', 'true_false'): _text(row, 'correct_answer')
        else: _text(row, 'criteria')
    return rubrics


def validate_exam_contract(tex: str, rubrics: dict, historical: list = None, total_marks=None) -> dict:
    if not isinstance(tex, str) or '\\begin{document}' not in tex or '\\end{document}' not in tex:
        raise ValueError('Exam LaTeX is incomplete')
    validate_rubrics(rubrics)
    questions = rubrics['questions']
    printed = exam_question_numbers(tex)
    if printed != list(range(1, len(questions) + 1)):
        raise ValueError('Printed exam questions do not match rubric question IDs')
    if historical:
        reference = historical[0]
        expected = Counter({item['type']: item['count'] for item in reference.get('questionTypes', [])})
        actual = Counter(row['question_type'] for row in questions.values())
        if expected and actual != expected: raise ValueError('Exam question mix differs from the selected reference exam')
        if reference.get('totalQuestions') and len(questions) != reference['totalQuestions']:
            raise ValueError('Exam question count differs from the selected reference exam')
    if total_marks is not None:
        if abs(sum(row['max_score'] for row in questions.values()) - total_marks) > 0.001:
            raise ValueError('Exam rubric marks differ from requested total')
        displayed = [float(score) for score in re.findall(r'\[\s*(\d+(?:\.\d+)?)\s*marks?\s*\]', tex, flags=re.IGNORECASE)]
        if len(displayed) != len(questions) or any(abs(score - questions[f'q{i + 1}']['max_score']) > 0.001 for i, score in enumerate(displayed)):
            raise ValueError('Printed exam marks differ from the grading rubric')
    return rubrics
