"""User-selected past-paper types fence uploads and generation reads."""
from copy import deepcopy
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from src.utils.exam_blueprint import build_exam_blueprint
from tests.test_exam_blueprint import paper, source
from tests.test_supporting_context import _setup, _compiler, _scope, _selected


@pytest.fixture
def typed_api(api_module, monkeypatch):
    api = api_module
    api.app.dependency_overrides[api.require_uid] = lambda: 'owner'
    monkeypatch.setattr(api, 'db_client', MagicMock())
    monkeypatch.setattr(api, '_require_course', lambda *a, **kw: {'id': 'course', 'userId': 'owner'})
    monkeypatch.setattr(api, '_require_document_foundation', lambda *a, **kw: {'revision': 'f'*64})
    yield api
    api.app.dependency_overrides.clear()


@pytest.mark.parametrize('category', [None, 'other'])
def test_upload_requires_a_valid_user_selected_category(typed_api, monkeypatch, category):
    queue = MagicMock(return_value={})
    monkeypatch.setattr(typed_api, '_queue_supporting_acceptance', queue)
    data = {'course_id': 'course', 'user_id': 'owner'}
    if category is not None: data['exam_type'] = category
    with TestClient(typed_api.app) as client:
        response = client.post('/api/historical-exams/upload', data=data,
                               files={'file': ('past.pdf', b'%PDF-test', 'application/pdf')})
    assert response.status_code == 422
    queue.assert_not_called()


@pytest.mark.parametrize('category', ['quiz', 'midterm', 'final'])
def test_upload_preserves_user_category_in_queued_metadata(typed_api, monkeypatch, category):
    seen = {}
    def queue(identity, foundation, metadata, **kwargs):
        seen.update(identity=identity, metadata=metadata, foundation=foundation)
        return {'materialId': identity['materialId'], 'kind': 'historical_exam', 'jobId': 'j'}
    monkeypatch.setattr(typed_api, '_queue_supporting_acceptance', queue)
    with TestClient(typed_api.app) as client:
        response = client.post('/api/historical-exams/upload',
            data={'course_id': 'course', 'user_id': 'attacker', 'exam_type': category},
            files={'file': ('past.pdf', b'%PDF-test', 'application/pdf')})
    assert response.status_code == 202
    assert seen['metadata']['examType'] == category
    assert seen['identity']['userId'] == 'owner'
    assert seen['identity']['kind'] == 'historical_exam'
    assert response.json()['examType'] == category


def test_category_list_queries_only_the_requested_collection(typed_api, monkeypatch):
    getter = typed_api.db_client.get_course_historical_exams
    getter.return_value = [{'id': 'm', 'userId': 'owner', 'courseId': 'course', 'examType': 'midterm'}]
    monkeypatch.setattr(typed_api, '_supporting_projection', lambda row, kind: row)
    with TestClient(typed_api.app) as client:
        response = client.get('/api/historical-exams/course?exam_type=midterm')
        invalid = client.get('/api/historical-exams/course?exam_type=other')
    assert response.status_code == 200 and invalid.status_code == 422
    getter.assert_called_once_with('course', user_id='owner', exam_type='midterm')
    assert response.json()['historical_exams'][0]['examType'] == 'midterm'


def test_legacy_classification_keeps_id_and_does_not_start_analysis(typed_api, monkeypatch):
    legacy = {'id': 'old', 'userId': 'owner', 'courseId': 'course', 'analysis': {'kept': True}}
    typed_api.db_client.get_historical_exam.return_value = legacy
    typed_api.db_client.classify_historical_exam.return_value = {**legacy, 'examType': 'quiz'}
    monkeypatch.setattr(typed_api, '_supporting_projection', lambda row, kind: row)
    workflow = MagicMock()
    monkeypatch.setattr(typed_api, 'supporting_workflow', workflow)
    with TestClient(typed_api.app) as client:
        response = client.post('/api/historical-exams/old/classify', json={'exam_type': 'quiz'})
    assert response.status_code == 200
    assert response.json()['historical_exam']['id'] == 'old'
    assert response.json()['historical_exam']['analysis'] == {'kept': True}
    typed_api.db_client.classify_historical_exam.assert_called_once_with(
        'old', 'quiz', 'owner', course_id='course')
    workflow.prepare.assert_not_called()


def test_readiness_uses_category_before_any_retry_or_other_source_read(typed_api):
    getter = typed_api.db_client.get_course_historical_exams
    getter.return_value = [{
        'id': 'quiz', 'userId': 'owner', 'courseId': 'course', 'examType': 'quiz',
        'status': 'completed', 'supportingAnalysis': {'version': 1, 'state': 'completed',
        'sourceRevision': 'a'*64, 'reportRevision': 'b'*64},
        'processingJob': {'foundationRevision': 'f'*64}}]
    typed_api._require_selected_supporting_ready('course', 'owner',
        foundation_revision='f'*64, historical_exam_type='quiz',
        historical_exam_ids=None, tutorial_ids=[], audio_ids=[])
    getter.assert_called_once_with('course', user_id='owner', exam_type='quiz')
    typed_api.db_client.get_course_tutorials.assert_not_called()
    typed_api.db_client.get_course_audio_recordings.assert_not_called()


def test_compiler_category_reaches_the_read_and_saved_snapshot():
    entry = _setup()
    compiler = _compiler(entry)
    row = deepcopy(compiler.repository.rows[0])
    row['examType'] = 'quiz'
    compiler.repository.rows[0]['examType'] = 'quiz'
    calls = []
    def query(course_id, user_id=None, exam_type=None):
        calls.append(exam_type)
        assert exam_type == 'quiz', 'Generation must not query the union of exam types'
        return [deepcopy(row)]
    compiler.repository.database.get_course_historical_exams = query
    packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
        selected=_selected(historical_ids=None), purpose='summary', historical_exam_type='quiz')
    assert calls == ['quiz']
    assert packet['snapshot']['historicalExamType'] == 'quiz'
    assert [item['identity']['materialId'] for item in packet['snapshot']['materials']] == ['past']


def test_empty_historical_selection_keeps_its_type_without_loading_any_rows():
    entry = _setup()
    compiler = _compiler(entry)
    compiler.repository.database.get_course_historical_exams = MagicMock(side_effect=AssertionError('Unexpected query'))
    packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
        selected=_selected(), purpose='exam', historical_exam_type='midterm')
    assert packet['snapshot'] == {'version': 1, 'materials': [], 'historicalExamType': 'midterm'}


def test_user_category_keeps_every_embedded_paper_despite_detected_type():
    rows = [source('merged', [paper('a', count=4, marks=None, kind='Quiz'),
                              paper('b', count=12, marks=None, kind='Final')])]
    original = deepcopy(rows)
    blueprint = build_exam_blueprint(rows, exam_type='Quiz', authoritative_exam_type='quiz')
    assert blueprint['totalQuestions'] == 8
    assert blueprint['evidence']['structureCohort'] == 'selected_upload_category'
    assert all(item['usedForStructure'] for item in blueprint['evidence']['sources'])
    assert rows == original


@pytest.mark.parametrize('label,expected', [('Exam', 'final'), ('Practice paper', 'final'),
                                           ('Quiz', 'quiz'), ('Midterm', 'midterm')])
def test_older_exam_labels_still_choose_one_category(typed_api, monkeypatch, label, expected):
    def stop_after_intelligence(*args, **kwargs):
        raise typed_api.HTTPException(status_code=418, detail='Observed scoped intelligence')
    monkeypatch.setattr(typed_api, '_require_sources', stop_after_intelligence)
    with TestClient(typed_api.app) as client:
        response = client.post('/api/exams/generate-enhanced', json={
            'course_id': 'course', 'user_id': 'owner', 'exam_type': label, 'total_marks': 15,
            'historical_exam_ids': [], 'tutorial_ids': [], 'audio_ids': []})
    assert response.status_code == 418
    assert typed_api.db_client.get_course_intelligence.call_args.kwargs['historical_exam_type'] == expected
