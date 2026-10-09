"""Safe legacy analysis text and explicit, balanced context budgets."""
import json


def as_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ('topic', 'title', 'name', 'term', 'formula', 'equation', 'statement',
                    'text', 'description', 'concept', 'skill', 'problem', 'example'):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
    return ''


def text_list(value) -> list:
    if not isinstance(value, list):
        value = [value] if isinstance(value, (str, dict)) else []
    return [text for text in (as_text(item) for item in value) if text]


def excerpt(text: str, limit: int) -> str:
    """Sample beginning/middle/end instead of omitting a source's tail entirely."""
    if len(text) <= limit:
        return text
    marker = '\n[excerpt gap]\n'
    piece = max(1, (limit - 2 * len(marker)) // 3)
    middle = len(text) // 2
    return text[:piece] + marker + text[middle:middle + piece] + marker + text[-piece:]


def budget_sources(sources: list, budget: int = 18000) -> tuple:
    """Include every selected source with length/coverage metadata.

    Reject an excessive source count rather than silently omit sources. A
    character budget is conservative and explicit, not a model token guarantee.
    """
    if not sources:
        return '', []
    if len(sources) > 200 or budget // len(sources) < 120:
        raise ValueError('Too many selected sources for the context budget; select fewer sources')
    allowance = max(60, budget // len(sources) - 120)
    blocks, coverage = [], []
    for index, source in enumerate(sources):
        label, value = source
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        selected = excerpt(text, allowance)
        metadata = {'source': str(label)[:60], 'characters': len(text), 'includedCharacters': len(selected), 'excerpted': len(text) > allowance}
        coverage.append(metadata)
        blocks.append(f'[{index + 1}: {str(label)[:60]}; chars={len(text)}; excerpted={str(metadata["excerpted"]).lower()}]\n{selected}')
    return '\n\n'.join(blocks), coverage


def source_texts(texts, budget: int = 12000) -> str:
    return budget_sources([(f'source {i + 1}', as_text(text)) for i, text in enumerate(texts or [])], budget)[0]


def context_coverage(intelligence: dict) -> dict:
    """Persistable coverage policy for the selected generation bundle."""
    text_sources = {}
    for key in ('document_texts', 'historical_texts', 'tutorial_texts'):
        texts = intelligence.get(key) or []
        _, metadata = budget_sources([(f'{key} {i + 1}', as_text(text)) for i, text in enumerate(texts)], 12000)
        text_sources[key] = metadata
    return {'policy': 'all_selected_sources_with_balanced_excerpts', 'budgetUnit': 'characters',
            'perSourceGroupBudget': 12000, 'sourceCounts': dict(intelligence.get('counts') or {}),
            'textSources': text_sources}


def normalize_insights(items) -> list:
    """Normalize only known legacy text arrays; preserve numeric contract fields."""
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            raise ValueError('Invalid stored analysis object; re-analyze this source')
        row = dict(item)
        for key in ('topics', 'formulas', 'skills', 'workedExamples', 'patterns'):
            if key in row:
                row[key] = text_list(row[key])
        for key in ('definitions', 'diagrams', 'codeSnippets', 'problems', 'examHints',
                    'keyEmphasis', 'topicWeights', 'questionTypes', 'difficultyDistribution', 'chapterMapping'):
            if key in row and not isinstance(row[key], list):
                raise ValueError('Invalid stored analysis array; re-analyze this source')
            if key in row:
                row[key] = [dict(value) for value in row[key] if isinstance(value, dict)]
        result.append(row)
    return result
