from unittest.mock import MagicMock
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from src.utils.ai_contracts import validate_exam_contract, validate_analysis
from src.utils.topic_scope import retag_topic_weights
from src.agents.exam_generator import ExamGeneratorAgent
from tests.foundation_fixtures import source_refs
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_supporting_job_storage import repository, identity, queue_claim
from tests.test_supporting_storage import library, report_for
from tests.supporting_fixtures import supporting_manifest
from src.supporting.contracts import supporting_revision
from src.database.firebase_client import DataConflict


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


def _publish_paper(library, source_id, kind, count):
    """Publish immutable originals and reports through the real managed pipeline."""
    material = identity(material=source_id)
    raw = f'Original past paper {source_id}'.encode()
    manifest = supporting_manifest()
    manifest['identity'] = material
    manifest['originalDigest'] = sha256(raw).hexdigest()
    manifest['sourceRevision'] = supporting_revision(manifest['originalDigest'], manifest['units'])
    _, claim, _ = queue_claim(library.repository, material=material, original=manifest['originalDigest'])
    library.save_source(material, claim, raw, manifest)
    report = report_for(library, manifest, count=count)

    def set_material(value):
        if isinstance(value, dict):
            if value.get('kind') == 'historical_exam' and value.get('materialId') == 'source':
                value['materialId'] = source_id
            for child in value.values(): set_material(child)
        elif isinstance(value, list):
            for child in value: set_material(child)

    set_material(report)
    report['papers'][0].update(examType='Final', unknownQuestionTypeIds=[], questionTypes=[{
        'type': kind, 'count': count, 'percentage': 100,
        'questionIds': [item['id'] for item in report['items']]}])
    return library.save_report(material, claim, report)


def _install_generation(monkeypatch, api, library, *, on_provider=None):
    db = library.repository.database
    monkeypatch.setattr(api, 'db_client', db)
    monkeypatch.setattr(api, 'supporting_repository', library.repository)
    monkeypatch.setattr(api, 'supporting_library', library)
    agent = ExamGeneratorAgent.__new__(ExamGeneratorAgent)
    agent.client, agent.model_id = object(), 'fake'
    monkeypatch.setattr(api, 'ai_agent', agent)
    refs = source_refs([library.repository.test_lecture])
    rubrics = {'questions': {key: {**deepcopy(value), 'sourceRefs': refs}
                             for key, value in RUBRICS['questions'].items()}}
    rubrics['provenance'] = [{
        'path': path, 'authority': 'lecture', 'relation': 'lecture_supported',
        'sourceRefs': refs, 'supportingSourceRefs': [], 'supportingSourceProofs': [],
        'lectureAnchorRefs': []} for path in (
            '/sharedContext',
            '/questions/q1/text', '/questions/q1/correct_answer',
            '/questions/q2/text', '/questions/q2/criteria')]
    complete = TEX + '\n<secret-rubrics>' + json.dumps(rubrics) + '</secret-rubrics>'
    seen = []

    def provider(*args, **kwargs):
        seen.append(deepcopy(kwargs['messages']))
        if on_provider: on_provider()
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=complete))])

    monkeypatch.setattr('src.agents.exam_generator.chat_with_retry', provider)
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a, **kw: None)
    monkeypatch.setattr(agent, 'repair_latex', lambda tex, **kwargs: tex)
    return seen


def _assert_no_exam_or_secret(db):
    assert db.get_course_exams('c', 'u') == []
    if db.use_local:
        assert not db._read_local_db().get('users', {}).get('u', {}).get('courses', {}).get('c', {}).get('exams')
    else:
        assert not any(path.startswith('users/u/courses/c/exams/') for path in db.db.rows)


def test_generation_uses_and_saves_one_combined_prediction(monkeypatch, api_module, library):
    api = api_module
    versions = {}
    for source_id, kind, count in [('a', 'mcq', 1), ('b', 'written', 3)]:
        versions[source_id] = _publish_paper(library, source_id, kind, count)
        library.repository.database.classify_historical_exam(source_id, 'final', 'u', course_id='c')
    seen = _install_generation(monkeypatch, api, library)
    result = api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(
        user_id='u', course_id='c', total_marks=5, exam_type='Final',
        historical_exam_ids=['a', 'b'], tutorial_ids=[], audio_ids=[]), uid='u')
    blueprint = result['exam_blueprint']
    assert blueprint['totalQuestions'] == 2
    assert [(row['type'], row['count']) for row in blueprint['questionTypes']] == [('mcq', 1), ('written', 1)]
    assert blueprint['evidence']['paperCount'] == 2
    assert blueprint['evidence']['sourceCount'] == 2
    db = library.repository.database
    saved = db.get_exam(result['doc_id'])
    assert saved['examBlueprint'] == blueprint
    materials = saved['supportingSnapshot']['materials']
    assert [row['identity']['materialId'] for row in materials] == ['a', 'b']
    assert [row['reportRevision'] for row in materials] == [versions[key]['revision'] for key in ('a', 'b')]
    assert saved['rubrics']['provenance']
    if db.use_local:
        secret = db._read_local_db()['users']['u']['courses']['c']['exams'][result['exam_id']]
    else:
        secret = db.db.rows[f"users/u/courses/c/exams/{result['exam_id']}"]['rubrics']
    assert secret == saved['rubrics']
    provider_text = json.dumps(seen, ensure_ascii=False)
    assert all(version['revision'] in provider_text for version in versions.values())
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


@pytest.mark.parametrize('disappearance', ['before_compile', 'during_generation'])
def test_generation_stops_if_selected_past_source_disappears_on_refresh(monkeypatch, api_module, library, disappearance):
    api = api_module
    db = library.repository.database
    _publish_paper(library, 'a', 'mcq', 1)
    _publish_paper(library, 'b', 'written', 3)
    for source_id in ('a', 'b'):
        db.classify_historical_exam(source_id, 'final', 'u', course_id='c')
    deleted = []

    def disappear():
        library.repository.delete(identity(material='b'))
        deleted.append('b')

    seen = _install_generation(monkeypatch, api, library,
        on_provider=disappear if disappearance == 'during_generation' else None)
    if disappearance == 'before_compile':
        prepare = api._source_prepare
        def prepare_then_disappear(*args, **kwargs):
            result = prepare(*args, **kwargs)
            disappear()
            return result
        monkeypatch.setattr(api, '_source_prepare', prepare_then_disappear)
    with pytest.raises((api.HTTPException, DataConflict)) as error:
        api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(
            user_id='u', course_id='c', total_marks=5, exam_type='Final',
            historical_exam_ids=['a', 'b'], tutorial_ids=[], audio_ids=[]), uid='u')
    if isinstance(error.value, api.HTTPException):
        assert error.value.status_code in (409, 422)
    if disappearance == 'during_generation':
        assert isinstance(error.value, DataConflict)
    assert deleted == ['b']
    assert bool(seen) == (disappearance == 'during_generation')
    _assert_no_exam_or_secret(db)


@pytest.fixture(autouse=True)
def source_provider_boundary(monkeypatch):
    from tests.foundation_fixtures import stub_source_provider
    stub_source_provider(monkeypatch)
