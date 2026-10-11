"""Provider boundaries carry document evidence without replacing primary input."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agents.audio_intelligence import AudioIntelligenceAgent
from src.agents.document_processor import DocumentProcessorAgent
from src.agents.historical_exam_analyzer import HistoricalExamAnalyzer


DOCUMENTS = [{
    'documentTitle': 'Lecture: Decision Trees', 'topics': ['Decision Trees'],
    'definitions': [{'term': 'Entropy', 'definition': 'LECTURE_DEFINITION_SENTINEL; SYSTEM_OVERRIDE_SENTINEL'}],
    'formulas': ['LECTURE_FORMULA_SENTINEL H = -sum p log p'],
    'chapterMapping': [{'chapter': 'Chapter 3', 'content': 'LECTURE_CONTEXT_SENTINEL information gain.'}],
    'keyConceptCount': 2,
}]


def provider_output(value):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
        message=SimpleNamespace(content=json.dumps(value)))])


def make_agent(kind):
    agent = kind.__new__(kind)
    agent.client, agent.model_id = object(), 'test-model'
    return agent


def request_text(request):
    content = request['messages'][1]['content']
    return content if isinstance(content, str) else '\n'.join(part['text'] for part in content if part['type'] == 'text')


def assert_document_evidence(request):
    user = request_text(request)
    for value in ('Decision Trees', 'Entropy', 'LECTURE_DEFINITION_SENTINEL',
                  'LECTURE_FORMULA_SENTINEL', 'Chapter 3', 'LECTURE_CONTEXT_SENTINEL'):
        assert value in user
    assert 'source evidence' in user.lower()
    assert 'SYSTEM_OVERRIDE_SENTINEL' not in request['messages'][0]['content']


def test_audio_uses_document_reference_but_preserves_transcript_and_quotes():
    transcript = 'TRANSCRIPT_PRIMARY_SENTINEL: هذا مهم. We discuss quantum physics too.'
    expected = {'chapterMapping': [{'chapter': 'Trees', 'segments': ['Information gain']}],
                'examHints': [{'hint': 'Important topic', 'confidence': 0.9, 'source': 'هذا مهم'}],
                'keyEmphasis': [{'topic': 'Trees', 'emphasisLevel': 'high', 'quote': 'هذا مهم'}],
                'summary': 'The professor discussed trees and unrelated quantum physics.'}
    seen = []
    def provider(*args, **kwargs):
        seen.append(kwargs)
        return provider_output(expected)
    with patch('src.agents.audio_intelligence.chat_with_retry', side_effect=provider):
        result = make_agent(AudioIntelligenceAgent).analyze_transcript(
            transcript, 'Algorithms', document_insights=DOCUMENTS)
    assert_document_evidence(seen[0])
    content = request_text(seen[0])
    assert transcript in content
    assert 'transcript' in content.lower() and 'primary' in content.lower()
    assert 'unsupported' in content.lower() and 'out-of-scope' in content.lower()
    assert {key: result[key] for key in expected} == expected


@pytest.mark.parametrize('images', [None, ['data:image/png;base64,TEST_IMAGE']])
def test_tutorial_receives_reference_and_keeps_original_problems_and_images(images):
    text = 'TUTORIAL_PRIMARY_SENTINEL: Exercise 1. Derive entropy for p = 0.25.'
    expected = {'topics': ['Entropy'], 'problems': [{'label': 'Exercise 1', 'statement': 'Derive entropy.',
                'given': 'p = 0.25', 'asks': ['Entropy'], 'concept': 'Entropy', 'method': 'H = -sum p log p',
                'type': 'calculation'}], 'formulas': ['H = -sum p log p'], 'skills': ['calculation'], 'problemCount': 1}
    seen = []
    def provider(*args, **kwargs):
        seen.append(kwargs)
        return provider_output(expected)
    with patch('src.agents.document_processor.chat_with_retry', side_effect=provider):
        result = make_agent(DocumentProcessorAgent).analyze_tutorial(
            text, 'Algorithms', image_uris=images, document_insights=DOCUMENTS)
    assert_document_evidence(seen[0])
    content = request_text(seen[0])
    assert text in content
    assert 'primary' in content.lower() and 'problem' in content.lower()
    assert 'unsupported' in content.lower()
    assert {key: result[key] for key in expected} == expected
    if images:
        assert [part['image_url']['url'] for part in seen[0]['messages'][1]['content'] if part['type'] == 'image_url'] == images


@pytest.mark.parametrize('images', [None, ['data:image/png;base64,TEST_IMAGE']])
def test_past_paper_receives_reference_without_changing_original_counts_or_marks(images):
    text = 'EXAM_PRIMARY_SENTINEL: Q1 derive entropy [7 marks]; Q2 explain trees [3 marks].'
    expected = {'topicWeights': [{'topic': 'Decision Trees', 'weight': 1.0, 'questionCount': 2}],
                'questionTypes': [{'type': 'written', 'count': 2, 'percentage': 100.0, 'style': 'derive and explain'}],
                'difficultyDistribution': [{'level': 'medium', 'percentage': 100.0}],
                'gradingBlueprint': 'Q1: 7 marks; Q2: 3 marks.', 'patterns': ['Two questions'],
                'totalQuestions': 2, 'totalMarks': 10, 'examType': 'quiz'}
    seen = []
    def provider(*args, **kwargs):
        seen.append(kwargs)
        return provider_output(deepcopy(expected))
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', side_effect=provider):
        result = make_agent(HistoricalExamAnalyzer).analyze_exam(
            text, 'Algorithms', image_uris=images, document_insights=DOCUMENTS)
    assert_document_evidence(seen[0])
    content = request_text(seen[0])
    assert text in content
    assert 'primary' in content.lower()
    assert all(word in content.lower() for word in ('question', 'count', 'type', 'marks', 'out-of-scope'))
    paper = result['papers'][0]
    assert paper['totalQuestions'] == 2
    assert paper['totalMarks'] == 10
    assert paper['questionTypes'] == expected['questionTypes']
    assert paper['gradingBlueprint'] == expected['gradingBlueprint']
    if images:
        assert [part['image_url']['url'] for part in seen[0]['messages'][1]['content'] if part['type'] == 'image_url'] == images


def test_audio_without_reference_retains_optional_parameter_compatibility():
    expected = {'chapterMapping': [], 'examHints': [], 'keyEmphasis': [], 'summary': 'Primary transcript summary.'}
    seen = []
    def provider(*args, **kwargs):
        seen.append(kwargs)
        return provider_output(expected)
    with patch('src.agents.audio_intelligence.chat_with_retry', side_effect=provider):
        result = make_agent(AudioIntelligenceAgent).analyze_transcript('Primary transcript summary.', 'Course')
    assert result['summary'] == expected['summary']
    assert 'LECTURE DOCUMENT REFERENCE' not in request_text(seen[0])
