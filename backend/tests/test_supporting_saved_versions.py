"""Selected supporting versions fence generated-output publication."""

from copy import deepcopy

import pytest

from src.database.firebase_client import DataConflict, saved_exam_revision
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_supporting_job_storage import repository, identity
from tests.test_supporting_storage import library, prepare, report_for, completed_snapshot


def ready_evidence(library):
    manifest, claim = prepare(library)
    report = report_for(library, manifest)
    version = library.save_report(identity(), claim, report)
    snapshot = completed_snapshot(library, manifest, claim, version)
    scope_revision = report['scopeSnapshot']['scopeRevision']
    library.repository.assert_snapshot(snapshot, scope_revision=scope_revision)
    return library.repository.database, snapshot, scope_revision


def selected_source_changed(db):
    db._flat_update('historical_exams', 'source', {'originalDigest': 'f' * 64})


@pytest.mark.parametrize('method,collection', [
    ('save_exam_flat', 'exams'),
    ('save_flashcard_set', 'flashcard_sets'),
    ('save_summary', 'summaries'),
    ('save_tutor_chat', 'tutor_chats'),
])
def test_generated_save_uses_selected_snapshot_inside_write(library, method, collection):
    db, snapshot, scope = ready_evidence(library)
    save = getattr(db, method)
    identifier = save('u', 'c', {'content': 'verified'},
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=snapshot, scope_revision=scope)
    saved = db._flat_get(collection, identifier)
    assert saved['supportingSnapshot'] == snapshot
    selected_source_changed(db)
    with pytest.raises(DataConflict):
        save('u', 'c', {'content': 'stale'},
            expected_foundation_revision=library.repository.test_foundation_revision,
            expected_supporting_snapshot=snapshot, scope_revision=scope)
    assert len(db._flat_query_by_course(collection, 'c', 'u')) == (2 if collection == 'tutor_chats' else 1)


def test_unselected_change_does_not_fence_selected_or_empty_snapshot(library):
    db, snapshot, scope = ready_evidence(library)
    other = db.save_historical_exam('u', 'c', {'title': 'unselected'})
    db._flat_update('historical_exams', other, {'title': 'changed'})
    saved = db.save_summary('u', 'c', {'content': 'selected'},
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=snapshot, scope_revision=scope)
    assert db.get_summary(saved)['content'] == 'selected'
    selected_source_changed(db)
    empty = {'version': 1, 'materials': []}
    saved = db.save_summary('u', 'c', {'content': 'lecture only'},
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=empty, scope_revision=scope)
    assert db.get_summary(saved)['supportingSnapshot'] == empty


def test_tutor_append_fences_selected_snapshot_and_preserves_source_turn(library):
    db, snapshot, scope = ready_evidence(library)
    chat_id = db.save_tutor_chat('u', 'c', {'messages': []},
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=snapshot, scope_revision=scope)
    turn = [{'role': 'user', 'content': 'Question'}, {'role': 'assistant', 'content': 'Answer'}]
    source_turn = {'sourceRefs': [], 'supportingSourceRefs': [{'kind': 'historical_exam',
        'materialId': 'source', 'sourceRevision': snapshot['materials'][0]['sourceRevision'], 'unitId': 'u1'}]}
    first = db.append_tutor_messages('u', 'c', chat_id, [], turn, 1,
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=snapshot, scope_revision=scope, source_turn=source_turn)
    assert first['sourceTurns'][0]['supportingSnapshot'] == snapshot
    assert first['sourceTurns'][0]['supportingSourceRefs'] == source_turn['supportingSourceRefs']
    selected_source_changed(db)
    with pytest.raises(DataConflict):
        db.append_tutor_messages('u', 'c', chat_id, turn, turn, 2,
            expected_foundation_revision=library.repository.test_foundation_revision,
            expected_supporting_snapshot=snapshot, scope_revision=scope, source_turn=source_turn)
    assert db.get_tutor_chat(chat_id)['messages'] == turn


def test_exam_and_secret_rubric_publish_together_with_selected_snapshot(library):
    db, snapshot, scope = ready_evidence(library)
    exam_id = 'generated-one'
    rubrics = {'questions': {'q1': {'criteria': 'correct'}}}
    flat_id = db.save_generated_exam_with_rubrics('u', 'c', exam_id,
        {'texContent': 'Question', 'examId': exam_id}, rubrics,
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=snapshot, scope_revision=scope)
    assert db.get_exam(flat_id)['supportingSnapshot'] == snapshot
    if db.use_local:
        secret = db._read_local_db()['users']['u']['courses']['c']['exams'][exam_id]
    else:
        secret = db.db.rows[f'users/u/courses/c/exams/{exam_id}']['rubrics']
    assert secret == rubrics
    selected_source_changed(db)
    with pytest.raises(DataConflict):
        db.save_generated_exam_with_rubrics('u', 'c', 'stale-exam',
            {'texContent': 'stale'}, deepcopy(rubrics),
            expected_foundation_revision=library.repository.test_foundation_revision,
            expected_supporting_snapshot=snapshot, scope_revision=scope)
    assert len(db.get_course_exams('c', 'u')) == 1
    if db.use_local:
        assert 'stale-exam' not in db._read_local_db()['users']['u']['courses']['c']['exams']
    else:
        assert 'users/u/courses/c/exams/stale-exam' not in db.db.rows


def test_exam_publication_rejects_oversized_secret_before_flat_write(library):
    db, snapshot, scope = ready_evidence(library)
    with pytest.raises(ValueError):
        db.save_generated_exam_with_rubrics('u', 'c', 'huge',
            {'texContent': 'Question'}, {'questions': {'q1': {'criteria': 'x' * 750001}}},
            expected_foundation_revision=library.repository.test_foundation_revision,
            expected_supporting_snapshot=snapshot, scope_revision=scope)
    assert db.get_course_exams('c', 'u') == []
    if db.use_local:
        assert 'huge' not in db._read_local_db().get('users', {}).get('u', {}).get('courses', {}).get('c', {}).get('exams', {})
    else:
        assert 'users/u/courses/c/exams/huge' not in db.db.rows


def test_combined_exam_publication_rejects_divergent_hidden_rubric(library):
    db, snapshot, scope = ready_evidence(library)
    with pytest.raises(ValueError, match='(?i)rubric'):
        db.save_generated_exam_with_rubrics('u', 'c', 'mismatch',
            {'texContent': 'Question', 'rubrics': {'questions': {'q1': {'criteria': 'one'}}}},
            {'questions': {'q1': {'criteria': 'two'}}},
            expected_foundation_revision=library.repository.test_foundation_revision,
            expected_supporting_snapshot=snapshot, scope_revision=scope)
    assert db.get_course_exams('c', 'u') == []


@pytest.mark.parametrize('field,changed', [
    ('supportingSnapshot', {'version': 1, 'materials': [{'analysisId': 'new'}]}),
    ('sharedSupportingSourceRefs', [{'kind': 'historical_exam', 'materialId': 'new',
                                     'sourceRevision': 'a' * 64, 'unitId': 'u1'}]),
    ('provenance', [{'path': '/sharedContext', 'start': 0, 'end': 1, 'authority': 'lecture'}]),
])
def test_saved_exam_revision_includes_authoritative_supporting_identity(field, changed):
    exam = {'userId': 'u', 'courseId': 'c', 'examId': 'one', 'texContent': 'Q',
            'rubrics': {'questions': {'q1': {'criteria': 'correct'}}},
            'supportingSnapshot': {'version': 1, 'materials': []},
            'sharedSupportingSourceRefs': [], 'provenance': []}
    original = saved_exam_revision(exam)
    assert saved_exam_revision({**exam, field: changed}) != original


def test_saved_exam_restores_exact_old_supporting_versions_without_current_analysis(monkeypatch):
    from src import api
    from src.services import document_library
    from src.supporting import library as supporting_library, repository as supporting_repository
    from src.services.source_evidence import saved_question_identity
    from src.services import source_evidence
    from tests.test_saved_exam_source_versions import TEX
    lecture_ref = {'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}
    scope = {'version': 1, 'scopeRevision': 'e' * 64, 'foundationRevision': 'b' * 64,
             'documents': [], 'allowedRefs': [lecture_ref]}
    source = {'identity': {'userId': 'u', 'courseId': 'c', 'kind': 'historical_exam', 'materialId': 'old'},
              'sourceRevision': 'a' * 64, 'reportRevision': 'c' * 64,
              'scopedReportRevision': 'd' * 64, 'analysisId': 'old-analysis'}
    rubrics = {'sharedSourceRefs': [lecture_ref], 'questions': {'q1': {
        'question_type': 'mcq', 'max_score': 3, 'correct_answer': 'B',
        'sourceRefs': [lecture_ref], 'supportingSourceRefs': []}}}
    identity = saved_question_identity(TEX, rubrics)
    exam = {'userId': 'u', 'courseId': 'c', 'texContent': TEX, 'rubrics': rubrics,
            'questionIdentity': identity, 'questionStructure': identity['questions'],
            'sharedSourceRefs': [lecture_ref], 'sourceScope': scope, 'totalMarks': 3,
            'foundationRevision': scope['foundationRevision'],
            'supportingSnapshot': {'version': 1, 'materials': [source]}}
    calls = []
    missing_old_source = [False]
    monkeypatch.setattr(api, '_require_course', lambda *a: {'userId': 'u'})
    monkeypatch.setattr(document_library, 'DocumentLibrary', lambda *a: type('Docs', (), {
        'restore_scope': lambda self, *a: scope})())
    monkeypatch.setattr(source_evidence, 'SourceEvidence', lambda *a: object())
    class Repo:
        def __init__(self, db): pass
        def get_version(self, material, kind, revision):
            calls.append((kind, revision))
            if missing_old_source[0] and kind == 'source':
                raise ValueError('Exact old source is missing')
            return {'identity': material, 'versionKind': kind, 'revision': revision,
                    'state': 'adopted', 'coverageComplete': True,
                    'sourceRevision': source['sourceRevision'], 'scopeRevision': scope['scopeRevision'],
                    'foundationRevision': scope['foundationRevision']}
    class Lib:
        def __init__(self, *a): pass
        def read_refs(self, material, refs): return [{'unitId': ref['unitId']} for ref in refs]
        def load_source(self, material, revision):
            calls.append(('load_source', revision))
            return {'identity': material, 'sourceRevision': revision, 'coverage': {'complete': True}}
        def load_report(self, material, revision):
            calls.append(('load_report', revision))
            return {'sourceRevision': source['sourceRevision'], 'scopeSnapshot': scope,
                    'extractionCoverage': {'complete': True}, 'alignmentCoverage': {'complete': True},
                    'alignments': [], 'items': []}
    monkeypatch.setattr(supporting_repository, 'SupportingRepository', Repo)
    monkeypatch.setattr(supporting_library, 'SupportingLibrary', Lib)
    restored = api._load_saved_exam_evidence(exam, 'u')
    assert ('source', source['sourceRevision']) in calls
    assert ('report', source['reportRevision']) in calls
    assert ('report', source['scopedReportRevision']) in calls
    assert restored['supporting']['snapshot'] == exam['supportingSnapshot']
    missing_old_source[0] = True
    with pytest.raises(api.HTTPException) as exc:
        api._load_saved_exam_evidence(exam, 'u')
    assert exc.value.status_code == 409


def test_saved_exam_real_old_versions_survive_current_analysis_change(library, monkeypatch):
    from src import api
    from src.services.source_evidence import saved_question_identity
    from tests.test_saved_exam_source_versions import TEX
    db, snapshot, scope_revision = ready_evidence(library)
    report = library.load_report(identity(), snapshot['materials'][0]['scopedReportRevision'])
    source_scope = {key: deepcopy(report['scopeSnapshot'][key])
                    for key in ('documents', 'allowedRefs', 'scopeRevision')}
    source_scope['version'] = 1
    lecture_ref = source_scope['allowedRefs'][0]
    support_ref = {'kind': 'historical_exam', 'materialId': 'source',
                   'sourceRevision': snapshot['materials'][0]['sourceRevision'], 'unitId': 'u1'}
    rubrics = {'sharedSourceRefs': [lecture_ref], 'sharedSupportingSourceRefs': [support_ref],
        'questions': {'q1': {'question_type': 'mcq', 'max_score': 3,
                            'correct_answer': 'B', 'sourceRefs': [lecture_ref],
                            'supportingSourceRefs': [support_ref]}}}
    question_identity = saved_question_identity(TEX, rubrics)
    exam = {'userId': 'u', 'courseId': 'c', 'texContent': TEX, 'rubrics': rubrics,
            'totalMarks': 3, 'sourceScope': source_scope, 'questionIdentity': question_identity,
            'questionStructure': question_identity['questions'], 'sharedSourceRefs': [lecture_ref],
            'sharedSupportingSourceRefs': [support_ref], 'supportingSnapshot': snapshot,
            'foundationRevision': library.repository.test_foundation_revision}
    monkeypatch.setattr(api, 'db_client', db)
    monkeypatch.setattr(api, '_require_course', lambda *a: {'userId': 'u'})
    selected_source_changed(db)
    restored = api._load_saved_exam_evidence(exam, 'u')
    assert restored['supporting']['snapshot'] == snapshot
    assert restored['reader'].scope['scopeRevision'] == scope_revision
