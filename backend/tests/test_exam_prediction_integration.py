from unittest.mock import MagicMock
import json
from types import SimpleNamespace

import pytest

from src.utils.ai_contracts import validate_exam_contract, validate_analysis
from src.utils.topic_scope import retag_topic_weights
from src.agents.exam_generator import ExamGeneratorAgent
from tests.foundation_fixtures import confirm_lecture_foundation, lecture_document, source_refs


TEX = r'\begin{document}\textbf{Question 1:} Choose. [2 marks]\textbf{Question 2:} Explain. [3 marks]\end{document}'
RUBRICS = {'questions': {
    'q1': {'question_type': 'mcq', 'max_score': 2, 'correct_answer': 'A'},
    'q2': {'question_type': 'written', 'max_score': 3, 'criteria': 'Explain the concept'},
}}
BLUEPRINT = {'totalQuestions': 2, 'questionTypes': [{'type': 'mcq', 'count': 1}, {'type': 'written', 'count': 1}]}


def test_versioned_historical_analysis_rejects_inconsistent_paper_metadata():
    paper = {'paperId': 'p1', 'startPage': 1, 'endPage': 2, 'totalQuestions': 2,
             'questionTypes': [{'type': 'mcq', 'count': 2, 'percentage': 100}],
             'topicWeights': [{'topic': 'AI', 'weight': 1, 'questionCount': 2}],
             'difficultyDistribution': [{'level': 'easy', 'percentage': 100}],
             'gradingBlueprint': 'MCQs', 'patterns': []}
    analysis = {**paper, 'analysisVersion': 2, 'paperCount': 2, 'papers': [paper], 'collectionQuestionCount': 2}
    with pytest.raises(ValueError, match='paper'):
        validate_analysis('historical', analysis)


def test_exam_contract_checks_prediction_instead_of_first_historical_paper():
    historical = [{'totalQuestions': 10, 'questionTypes': [{'type': 'mcq', 'count': 10}]}]
    assert validate_exam_contract(TEX, RUBRICS, historical, 5, blueprint=BLUEPRINT) == RUBRICS
    wrong = {'totalQuestions': 2, 'questionTypes': [{'type': 'mcq', 'count': 2}]}
    with pytest.raises(ValueError, match='mix'):
        validate_exam_contract(TEX, RUBRICS, historical, 5, blueprint=wrong)


def test_selected_scope_retags_each_paper_without_mutating_stored_analysis():
    historical = [{'papers': [{'topicWeights': [{'topic': 'Calculus', 'weight': 1, 'inScope': True}]}]}]
    tagged = retag_topic_weights(historical, [{'topics': ['Decision trees']}])
    assert tagged[0]['papers'][0]['topicWeights'][0]['inScope'] is False
    assert historical[0]['papers'][0]['topicWeights'][0]['inScope'] is True


def test_legacy_selected_pdf_is_rescanned_once_and_cached(monkeypatch, api_module, tmp_path):
    api = api_module
    path = tmp_path / 'saved.pdf'
    path.write_bytes(b'saved source')
    row = {'id': 'past', 'userId': 'owner', 'courseId': 'course',
           'storagePath': 'historical_exams/owner/course/saved.pdf', 'analysis': {'totalQuestions': 100}}
    db = MagicMock()
    db.get_course_historical_exams.return_value = [row]
    db.get_historical_exam.return_value = row
    db.download_file_from_storage.return_value = path
    monkeypatch.setattr(api, 'db_client', db)
    monkeypatch.setattr(api, '_require_record_storage', lambda *a: None)
    monkeypatch.setattr(api, '_require_course', lambda *a: {'title': 'AI'})
    paper = {'paperId': 'p1', 'startPage': 1, 'endPage': 1, 'totalQuestions': 1,
             'questionTypes': [{'type': 'mcq', 'count': 1, 'percentage': 100}],
             'topicWeights': [], 'difficultyDistribution': [], 'patterns': [], 'gradingBlueprint': 'One MCQ'}
    versioned = {**paper, 'analysisVersion': 2, 'paperCount': 2,
                 'papers': [paper, {**paper, 'paperId': 'p2', 'startPage': 2, 'endPage': 2}],
                 'collectionQuestionCount': 2}
    analyzer = MagicMock()
    analyzer.analyze_pdf.return_value = versioned
    monkeypatch.setattr(api, 'hist_analyzer', analyzer)
    api._ensure_historical_paper_analysis('course', 'owner', ['past'], [{'topics': ['AI']}])
    analyzer.analyze_pdf.assert_called_once_with(b'saved source', 'AI', document_insights=[{'topics': ['AI']}])
    assert db.update_historical_exam.call_args.args[1]['analysis'] == versioned
    row['analysis'] = versioned
    api._ensure_historical_paper_analysis('course', 'owner', ['past'], [{'topics': ['AI']}])
    assert analyzer.analyze_pdf.call_count == 1


def test_missing_legacy_source_does_not_fall_back_to_collection_question_count(monkeypatch, api_module):
    api = api_module
    db = MagicMock()
    db.get_course_historical_exams.return_value = [
        {'id': 'past', 'userId': 'owner', 'courseId': 'course', 'analysis': {'totalQuestions': 100}}]
    monkeypatch.setattr(api, 'db_client', db)
    monkeypatch.setattr(api, '_require_course', lambda *a: {'title': 'AI'})
    with pytest.raises(api.HTTPException) as error:
        api._ensure_historical_paper_analysis('course', 'owner', ['past'], [])
    assert error.value.status_code == 422
    db.update_historical_exam.assert_not_called()


def test_generation_uses_and_saves_one_combined_prediction(monkeypatch, api_module):
    api = api_module
    db = MagicMock()
    db.get_owned_course.return_value = {'id': 'course', 'userId': 'owner', 'title': 'AI'}
    documents = confirm_lecture_foundation(db, [lecture_document(topic='AI')])
    foundation_revision = db.get_document_foundation.return_value['revision']
    rows = []
    for source_id, kind, count in [('a', 'mcq', 1), ('b', 'written', 3)]:
        paper = {'paperId': 'p1', 'startPage': 1, 'endPage': 1, 'examType': None,
                 'totalQuestions': count, 'questionTypes': [{'type': kind, 'count': count, 'percentage': 100}],
                 'topicWeights': [{'topic': 'AI', 'weight': 1, 'questionCount': count}],
                 'difficultyDistribution': [], 'patterns': [], 'gradingBlueprint': 'Different question styles'}
        analysis = {**paper, 'analysisVersion': 2, 'papers': [paper], 'paperCount': 1,
                    'collectionQuestionCount': count, 'sourceId': source_id}
        rows.append({'id': source_id, 'userId': 'owner', 'courseId': 'course',
            'status': 'completed', 'analysis': analysis,
            'processingJob': {'foundationRevision': foundation_revision},
            'supportingAnalysis': {'version': 1, 'state': 'completed',
                'sourceRevision': (source_id * 64)[:64],
                'reportRevision': ((source_id + 'r') * 64)[:64]}})
    db.get_course_historical_exams.return_value = rows
    db.get_course_intelligence.return_value = {
        'document_analyses': [documents[0]['analysis']], 'document_texts': ['AI concepts'],
        'historical_analyses': [row['analysis'] for row in rows],
        'source_ids': {'document_ids': ['doc'], 'historical_exam_ids': ['a', 'b']},
        'counts': {'documents': 1, 'historical_exams': 2},
    }
    monkeypatch.setattr(api, 'db_client', db)
    agent = ExamGeneratorAgent.__new__(ExamGeneratorAgent)
    agent.client, agent.model_id = object(), 'fake'
    monkeypatch.setattr(api, 'ai_agent', agent)
    complete = TEX + '\n<secret-rubrics>' + json.dumps({'questions': {k: {**v, 'sourceRefs': source_refs(documents)} for k, v in RUBRICS['questions'].items()}}) + '</secret-rubrics>'
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=complete))])
    monkeypatch.setattr('src.agents.exam_generator.chat_with_retry', lambda *a, **kw: response)
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a, **kw: None)
    monkeypatch.setattr(agent, 'repair_latex', lambda tex, **kwargs: tex)
    result = api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(
        user_id='owner', course_id='course', total_marks=5, exam_type='Final', historical_exam_ids=['a', 'b']), uid='owner')
    blueprint = result['exam_blueprint']
    assert blueprint['totalQuestions'] == 2
    assert [(row['type'], row['count']) for row in blueprint['questionTypes']] == [('mcq', 1), ('written', 1)]
    assert blueprint['evidence']['paperCount'] == 2
    assert db.save_exam_flat.call_args.args[2]['examBlueprint'] == blueprint
    assert len(result['question_structure']) == 2


@pytest.mark.parametrize('change', ['deleted', 'owner', 'course', 'file'])
def test_legacy_rescan_rechecks_source_before_caching(monkeypatch, api_module, tmp_path, change):
    api = api_module
    path = tmp_path / 'saved.pdf'
    path.write_bytes(b'saved source')
    row = {'id': 'past', 'userId': 'owner', 'courseId': 'course',
           'storagePath': 'historical_exams/owner/course/saved.pdf', 'analysis': {'totalQuestions': 100}}
    latest = {} if change == 'deleted' else dict(row)
    if change == 'owner': latest['userId'] = 'other'
    if change == 'course': latest['courseId'] = 'other'
    if change == 'file': latest['storagePath'] = 'historical_exams/owner/course/replaced.pdf'
    db = MagicMock()
    db.get_course_historical_exams.return_value = [row]
    db.get_historical_exam.return_value = latest
    db.download_file_from_storage.return_value = path
    monkeypatch.setattr(api, 'db_client', db)
    monkeypatch.setattr(api, '_require_record_storage', lambda *a: None)
    monkeypatch.setattr(api, '_require_course', lambda *a: {'title': 'AI'})
    monkeypatch.setattr(api, 'hist_analyzer', MagicMock())
    monkeypatch.setattr('src.utils.ai_contracts.validate_analysis', lambda *a: None)
    with pytest.raises(api.HTTPException) as error:
        api._ensure_historical_paper_analysis('course', 'owner', ['past'], [])
    assert error.value.status_code in (404, 409)
    db.update_historical_exam.assert_not_called()


@pytest.mark.parametrize('remaining_documents', [[], [{'topics': ['AI']}]])
def test_generation_stops_if_selected_past_source_disappears_on_refresh(monkeypatch, api_module, remaining_documents):
    api = api_module
    db = MagicMock()
    documents = confirm_lecture_foundation(db, [lecture_document(topic='AI')])
    foundation_revision = db.get_document_foundation.return_value['revision']
    db.get_course_historical_exams.return_value = [{
        'id': 'past', 'userId': 'owner', 'courseId': 'course', 'status': 'completed',
        'processingJob': {'foundationRevision': foundation_revision},
        'supportingAnalysis': {'version': 1, 'state': 'completed',
            'sourceRevision': 's' * 64, 'reportRevision': 'r' * 64}}]
    db.get_course_intelligence.side_effect = [
        {'document_analyses': [documents[0]['analysis']],
         'historical_analyses': [{'totalQuestions': 100}],
         'source_ids': {'historical_exam_ids': ['past']}},
        {'document_analyses': remaining_documents, 'historical_analyses': [],
         'source_ids': {'historical_exam_ids': []}},
    ]
    monkeypatch.setattr(api, 'db_client', db)
    monkeypatch.setattr(api, '_ensure_historical_paper_analysis', lambda *a, **kw: True)
    agent = MagicMock()
    monkeypatch.setattr(api, 'ai_agent', agent)
    with pytest.raises(api.HTTPException) as error:
        api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(
            user_id='owner', course_id='course', historical_exam_ids=['past']), uid='owner')
    assert error.value.status_code in (409, 422)
    assert db.get_course_intelligence.call_count == 2
    agent.compile_enhanced_exam.assert_not_called()
    db.save_exam_flat.assert_not_called()


@pytest.fixture(autouse=True)
def source_provider_boundary(monkeypatch):
    from tests.foundation_fixtures import stub_source_provider
    stub_source_provider(monkeypatch)
