import json
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import pytest

from src.agents.historical_exam_analyzer import HistoricalExamAnalyzer
from src.utils import pdf_extract


def pdf_bytes(count=10):
    document = fitz.open()
    for page in range(1, count + 1):
        sheet = document.new_page()
        sheet.insert_text((40, 50), f'PAGE_SENTINEL_{page} University Final Exam')
        sheet.insert_text((40, 90), 'Question 1: Explain decision trees. [5 marks]')
    result = document.tobytes()
    document.close()
    return result


def analysis(count=2, topic='Trees', kind='mcq'):
    return {'topicWeights': [{'topic': topic, 'weight': 1.0, 'questionCount': count}],
            'questionTypes': [{'type': kind, 'count': count, 'percentage': 100.0, 'style': 'explain'}],
            'difficultyDistribution': [{'level': 'medium', 'percentage': 100.0}],
            'gradingBlueprint': 'Five marks per question', 'patterns': ['Two sections'],
            'totalQuestions': count}


def response(value):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
        message=SimpleNamespace(content=json.dumps(value)))])


def agent():
    result = HistoricalExamAnalyzer.__new__(HistoricalExamAnalyzer)
    result.client, result.model_id = object(), 'mock-model'
    return result


def decisions(pages, starts=(1, 6), ambiguous=False):
    return {'pages': [{'page': number, 'startsPaper': number in starts,
        'confidence': 0.4 if ambiguous else 0.95, 'uncertain': ambiguous,
        'evidence': 'New exam header and question-number reset' if number in starts else 'Same exam page numbering',
        'examType': 'final' if number in starts else None,
        'totalMarks': 20 if number in starts else None} for number in pages]}


def test_merged_pdf_detects_two_papers_and_does_not_sum_generated_length():
    seen = []
    outputs = iter([decisions(range(1, 9)), decisions(range(9, 11)),
                    analysis(2, 'Trees'), analysis(4, 'Graphs', 'written')])
    def chat(*args, **kwargs):
        seen.append(kwargs)
        return response(next(outputs))
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', side_effect=chat):
        result = agent().analyze_pdf(pdf_bytes(), 'Algorithms')
    assert result['analysisVersion'] == 2
    assert result['paperCount'] == 2
    assert [(p['startPage'], p['endPage']) for p in result['papers']] == [(1, 5), (6, 10)]
    assert result['collectionQuestionCount'] == 6
    assert result['totalQuestions'] == 3
    assert sum(row['count'] for row in result['questionTypes']) == 3
    assert [row['weight'] for row in result['topicWeights']] == [0.5, 0.5]
    assert all(p['boundaryConfidence'] == 0.95 for p in result['papers'])
    assert 'imageUri' not in json.dumps(result)
    assert 'PAGE_SENTINEL' not in json.dumps(result)
    boundary_text = '\n'.join(str(call['messages'][1]['content']) for call in seen[:2])
    for number in range(1, 11):
        assert f'PAGE_SENTINEL_{number} ' in boundary_text
    assert [sum(block.get('type') == 'image_url' for block in call['messages'][1]['content'])
            for call in seen] == [8, 3, 5, 5]


def test_boundary_ambiguity_fails_without_analyzing_one_large_collection():
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', return_value=response(decisions(range(1, 9), ambiguous=True))) as chat:
        with pytest.raises((ValueError, RuntimeError), match='(?i)boundar|ambiguous'):
            agent().analyze_pdf(pdf_bytes(), 'Algorithms')
    assert chat.call_count <= 2


def test_missing_boundary_page_decision_is_not_accepted():
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', return_value=response(decisions(range(1, 8)))):
        with pytest.raises((ValueError, RuntimeError), match='(?i)boundar|page|complete'):
            agent().analyze_pdf(pdf_bytes(), 'Algorithms')


def test_pdf_helpers_preserve_all_page_numbers_and_contiguous_images():
    content = pdf_bytes()
    pages = pdf_extract.extract_pdf_pages(content)
    images = pdf_extract.render_pdf_page_window(content, 6, 10)
    assert [page['page'] for page in pages] == list(range(1, 11))
    assert [image['page'] for image in images] == list(range(6, 11))
    assert all(image['imageUri'].startswith('data:image/png;base64,') for image in images)


def test_pdf_page_limit_rejects_rather_than_silently_sample_tail():
    with pytest.raises(ValueError, match='(?i)limit|split|pages'):
        pdf_extract.extract_pdf_pages(pdf_bytes(4), max_pages=3)


def test_incomplete_rendered_coverage_rejects_before_provider_call():
    original = getattr(pdf_extract, 'render_pdf_page_window', None)
    def missing_last(*args, **kwargs):
        return original(*args, **kwargs)[:-1]
    with patch('src.utils.pdf_extract.render_pdf_page_window', side_effect=missing_last, create=True), \
         patch('src.agents.historical_exam_analyzer.chat_with_retry') as chat:
        with pytest.raises((ValueError, RuntimeError), match='(?i)coverage|page|complete'):
            agent().analyze_pdf(pdf_bytes(), 'Algorithms')
    chat.assert_not_called()


def test_individual_photo_analysis_wraps_one_paper_with_unknown_boundaries():
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', return_value=response(analysis())):
        result = agent().analyze_exam('', 'Algorithms', image_uris=['data:image/png;base64,test'])
    assert result['analysisVersion'] == 2
    assert result['paperCount'] == 1
    assert result['papers'][0]['startPage'] == 1
    assert result['papers'][0]['examType'] is None
    assert result['papers'][0]['totalMarks'] is None
    assert result['papers'][0]['boundaryConfidence'] is None


def test_large_individual_paper_is_rejected_without_text_excerpting():
    with patch('src.agents.historical_exam_analyzer.chat_with_retry') as chat:
        with pytest.raises(ValueError, match='(?i)split|limit|large'):
            agent().analyze_exam('x' * 80001, 'Algorithms')
    chat.assert_not_called()


def test_single_long_paper_reads_all_images_beyond_the_old_eight_page_limit():
    outputs = iter([decisions(range(1, 9), starts=(1,)), decisions(range(9, 11), starts=(1,)), analysis(4)])
    seen = []
    def chat(*args, **kwargs):
        seen.append(kwargs)
        return response(next(outputs))
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', side_effect=chat):
        result = agent().analyze_pdf(pdf_bytes(), 'Algorithms')
    assert result['paperCount'] == 1
    assert result['papers'][0]['endPage'] == 10
    assert sum(block.get('type') == 'image_url' for block in seen[-1]['messages'][1]['content']) == 10
    assert result['_contextCoverage']['imagesIncluded'] == 10


def test_scanned_pdf_pages_remain_in_boundary_and_paper_coverage():
    from PIL import Image
    import io
    image = Image.new('RGB', (200, 80), 'white')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    document = fitz.open()
    for _ in range(2):
        document.new_page().insert_image(fitz.Rect(20, 20, 220, 100), stream=buffer.getvalue())
    content = document.tobytes()
    document.close()
    assert [page['text'] for page in pdf_extract.extract_pdf_pages(content)] == ['', '']
    outputs = iter([decisions([1, 2], starts=(1,)), analysis()])
    seen = []
    def chat(*args, **kwargs):
        seen.append(kwargs)
        return response(next(outputs))
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', side_effect=chat):
        result = agent().analyze_pdf(content, 'Algorithms')
    assert result['_contextCoverage']['imagesIncluded'] == 2
    assert all(sum(block.get('type') == 'image_url' for block in call['messages'][1]['content']) == 2 for call in seen)


def test_continuation_at_start_of_second_batch_uses_prior_page_context():
    outputs = iter([decisions(range(1, 9), starts=(1,)), decisions(range(9, 11), starts=(1,)), analysis()])
    seen = []
    def chat(*args, **kwargs):
        seen.append(kwargs)
        return response(next(outputs))
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', side_effect=chat):
        agent().analyze_pdf(pdf_bytes(), 'Algorithms')
    text = seen[1]['messages'][1]['content'][0]['text']
    assert 'Current paper begins at page: 1' in text
    assert 'Previous page 8:' in text
    assert 'PAGE_SENTINEL_8' in text


def test_scanned_batch_continuity_retains_previous_image_and_current_paper_identity():
    from PIL import Image
    import io
    document = fitz.open()
    for number in range(1, 11):
        buffer = io.BytesIO()
        Image.new('RGB', (40, 40), (number * 20, 100, 200)).save(buffer, format='PNG')
        document.new_page().insert_image(fitz.Rect(20, 20, 120, 120), stream=buffer.getvalue())
    content = document.tobytes()
    document.close()
    assert all(not page['text'] for page in pdf_extract.extract_pdf_pages(content))
    first = decisions(range(1, 9))
    first['pages'][5]['evidence'] = 'Final examination 2025; Paper B starts at question 1'
    outputs = iter([first, decisions(range(9, 11)), analysis(), analysis()])
    seen = []
    def chat(*args, **kwargs):
        seen.append(kwargs)
        return response(next(outputs))
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', side_effect=chat):
        result = agent().analyze_pdf(content, 'Algorithms')
    prior_images = [block['image_url']['url'] for block in seen[0]['messages'][1]['content'] if block['type'] == 'image_url']
    next_blocks = seen[1]['messages'][1]['content']
    next_images = [block['image_url']['url'] for block in next_blocks if block['type'] == 'image_url']
    assert len(next_images) == 3  # one context-only prior page, two requested pages
    assert next_images[0] == prior_images[-1]
    next_text = '\n'.join(block['text'] for block in next_blocks if block['type'] == 'text')
    assert 'CONTEXT ONLY: Previous PDF Page 8' in next_text
    assert 'Requested pages: [9, 10]' in next_text
    assert 'Current paper begins at page: 6' in next_text
    assert 'Final examination 2025; Paper B starts at question 1' in next_text
    assert '"examType": "final"' in next_text
    assert '"totalMarks": 20' in next_text
    assert [(paper['startPage'], paper['endPage']) for paper in result['papers']] == [(1, 5), (6, 10)]


def test_nonstarting_first_page_rejects_a_fragment_instead_of_inventing_paper():
    with patch('src.agents.historical_exam_analyzer.chat_with_retry', return_value=response(decisions([1, 2], starts=()))):
        with pytest.raises(RuntimeError, match='boundary.*Split this PDF'):
            agent().analyze_pdf(pdf_bytes(2), 'Algorithms')


def test_oversized_total_text_rejects_before_any_sampling():
    with pytest.raises(ValueError, match='text.*limit'):
        pdf_extract.extract_pdf_pages(pdf_bytes(3), max_characters=100)


def test_corrupt_pdf_never_becomes_a_successful_empty_collection():
    with pytest.raises(ValueError, match='read every'):
        pdf_extract.extract_pdf_pages(b'broken-pdf')


def test_bad_render_window_rejects_instead_of_reading_other_pages():
    with pytest.raises(ValueError, match='window'):
        pdf_extract.render_pdf_page_window(pdf_bytes(2), 1, 3)
