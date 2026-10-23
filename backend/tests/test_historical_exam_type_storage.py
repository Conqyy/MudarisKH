"""Canonical historical categories retain exact source identities and fences."""
from copy import deepcopy

import pytest

from src.database.firebase_client import DataConflict
from src.supporting.contracts import CLAIM_LEASE_MS
from src.supporting.repository import version_id
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_supporting_job_storage import repository, identity, queue_claim
from tests.test_supporting_storage import library, prepare, report_for, completed_snapshot


def put(db, collection, key, value):
    if db.use_local:
        local = db._read_local_db()
        local.setdefault(collection, {})[key] = deepcopy(value)
        db._write_local_db(local)
    else:
        db.db.rows[f'{collection}/{key}'] = deepcopy(value)


@pytest.mark.parametrize('category,collection', [('quiz', 'historical_quizzes'), ('midterm', 'historical_midterms'), ('final', 'historical_finals')])
def test_selected_category_uses_only_its_collection(job_db, monkeypatch, category, collection):
    db = job_db
    legacy = db.save_historical_exam('u', 'c', {'title': 'unknown'})
    ids = {kind: db.save_historical_exam('u', 'c', {'title': kind, 'examType': kind})
           for kind in ('quiz', 'midterm', 'final')}
    calls = []
    original = db._flat_query_by_course
    def query(name, *args):
        calls.append(name)
        return original(name, *args)
    monkeypatch.setattr(db, '_flat_query_by_course', query)
    assert [row['id'] for row in db.get_course_historical_exams('c', 'u', exam_type=category)] == [ids[category]]
    assert calls == [collection]
    assert ids[category].startswith(collection + '_')
    assert db.get_historical_exam(ids[category])['examType'] == category
    db.update_historical_exam(ids[category], {'examType': category, 'title': 'same category'})
    with pytest.raises(DataConflict):
        db.update_historical_exam(ids[category], {'examType': 'final' if category != 'final' else 'quiz'})
    assert {row['id'] for row in db.get_course_historical_exams('c', 'u')} == {legacy, *ids.values()}


def test_classification_moves_opaque_legacy_id_and_keeps_claims_and_versions(repository):
    db = repository.database
    job, claim, now = queue_claim(repository, now=100)
    before = repository.get_owned(identity())
    descriptor = {**identity(), 'versionKind': 'source', 'revision': 'd'*64, 'state': 'adopted'}
    key = version_id(identity(), 'source', 'd'*64)
    put(db, 'supporting_material_versions', key, descriptor)
    classified = db.classify_historical_exam('source', 'midterm', 'u', 'c')
    assert classified == {**before, 'id': 'source', 'examType': 'midterm'}
    assert not db._flat_get('historical_exams', 'source')
    assert db._flat_get('historical_midterms', 'source')['processingJob'] == before['processingJob']
    assert repository.get_version(identity(), 'source', 'd'*64) == descriptor
    assert repository.checkpoint(identity(), claim, changes={'cursor': {'batchIndex': 1}}, now_ms=101)
    assert repository.pending(now_ms=101+CLAIM_LEASE_MS) == [identity()]
    assert db.classify_historical_exam('source', 'midterm', 'u', 'c')['id'] == 'source'
    with pytest.raises(DataConflict): db.classify_historical_exam('source', 'final', 'u', 'c')
    with pytest.raises(DataConflict): db.classify_historical_exam('source', 'midterm', 'other', 'c')
    with pytest.raises(DataConflict): db.update_historical_exam('source', {'examType': 'final'})


@pytest.mark.parametrize('category,collection', [('quiz', 'historical_quizzes'), ('midterm', 'historical_midterms'), ('final', 'historical_finals')])
def test_typed_jobs_recover_delete_and_fence_old_claims(repository, monkeypatch, category, collection):
    monkeypatch.setattr(repository.database, '_cleanup_storage_namespace', lambda *args, **kwargs: 0)
    material = identity(material=collection + '_source')
    job = repository.queue(material, input_revision='b'*64, source_digest='a'*64,
        foundation_revision=repository.test_foundation_revision, now_ms=100,
        initial_data={'title': 'Paper', 'examType': category})
    assert repository.database._flat_get(collection, material['materialId'])['examType'] == category
    old = repository.claim(material, job['id'], worker_id='worker', now_ms=100)
    assert repository.pending(now_ms=100+CLAIM_LEASE_MS) == [material]
    current = repository.claim(material, job['id'], worker_id='recovery', now_ms=100+CLAIM_LEASE_MS)
    assert current and current['claimToken'] != old['claimToken']
    assert not repository.checkpoint(material, old, changes={}, now_ms=101+CLAIM_LEASE_MS)
    assert repository.delete(material)['materials'] == 1
    assert not repository.database.get_historical_exam(material['materialId'])
    assert not repository.checkpoint(material, current, changes={}, now_ms=102+CLAIM_LEASE_MS)


def test_category_snapshot_rejects_untyped_or_wrong_category_and_preserves_saved_refs(library):
    manifest, claim = prepare(library)
    version = library.save_report(identity(), claim, report_for(library, manifest))
    snapshot = completed_snapshot(library, manifest, claim, version)
    db = library.repository.database
    scope = report_for(library, manifest)['scopeSnapshot']['scopeRevision']
    legacy_saved = db.save_summary('u', 'c', {'content': 'saved before classification'},
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=snapshot, scope_revision=scope)
    persisted_snapshot = deepcopy(snapshot)
    original_version = library.repository.get_version(identity(), 'source', manifest['sourceRevision'])
    typed = {**snapshot, 'historicalExamType': 'quiz'}
    with pytest.raises(DataConflict): library.repository.assert_snapshot(typed)
    library.repository.database.classify_historical_exam('source', 'midterm', 'u', 'c')
    assert db.get_summary(legacy_saved)['supportingSnapshot'] == persisted_snapshot
    assert library.repository.get_version(identity(), 'source', manifest['sourceRevision']) == original_version
    assert library.load_source(identity()) == manifest
    with pytest.raises(DataConflict): library.repository.assert_snapshot(typed)
    snapshot['historicalExamType'] = 'midterm'
    library.repository.assert_snapshot(snapshot)
    scope = report_for(library, manifest)['scopeSnapshot']['scopeRevision']
    saved_id = library.repository.database.save_summary('u', 'c', {'content': 'selected'},
        expected_foundation_revision=library.repository.test_foundation_revision,
        expected_supporting_snapshot=snapshot, scope_revision=scope)
    assert library.repository.database.get_summary(saved_id)['supportingSnapshot'] == snapshot
    library.repository.assert_snapshot({'version': 1, 'historicalExamType': 'final', 'materials': []})
    with pytest.raises(ValueError): library.repository.assert_snapshot({'version': 1, 'historicalExamType': 'Final', 'materials': []})
    library.repository.queue(identity(), input_revision='b'*64, source_digest=manifest['originalDigest'],
        foundation_revision=library.repository.test_foundation_revision, now_ms=claim.get('createdAt', 1))
    with pytest.raises(DataConflict): library.repository.assert_snapshot(snapshot)
    library.repository.delete(identity())
    with pytest.raises(DataConflict): library.repository.assert_snapshot(snapshot)


def test_owned_locator_never_redirects_legacy_source_to_another_owners_record(repository):
    db = repository.database
    queue_claim(repository)
    before = repository.get_owned(identity())
    put(db, 'historical_midterms', 'source', {**before, 'examType': 'midterm', 'userId': 'foreign'})
    put(db, 'historical_exam_locations', 'source', {'materialId': 'source', 'userId': 'u', 'courseId': 'c',
        'collection': 'historical_midterms', 'examType': 'midterm'})
    with pytest.raises(DataConflict): db.get_historical_exam('source')
    with pytest.raises(DataConflict): repository.get_owned(identity())
    with pytest.raises(DataConflict): db.classify_historical_exam('source', 'midterm', 'u', 'c')
    assert db._flat_get('historical_exams', 'source')['processingJob'] == before['processingJob']


def test_new_category_identity_requires_matching_authoritative_metadata(repository):
    for category in (None, 'final', True, 'Quiz'):
        with pytest.raises(ValueError):
            repository.queue(identity(material='historical_quizzes_bad'), input_revision='b'*64,
                source_digest='a'*64, foundation_revision=repository.test_foundation_revision,
                now_ms=100, initial_data={'examType': category})
    assert not repository.database._flat_get('historical_quizzes', 'historical_quizzes_bad')


def test_typed_read_rejects_corrupt_category_metadata(job_db):
    put(job_db, 'historical_quizzes', 'historical_quizzes_bad', {'userId': 'u', 'courseId': 'c', 'examType': 'final'})
    with pytest.raises(DataConflict): job_db.get_historical_exam('historical_quizzes_bad')


def test_classification_cannot_orphan_a_typed_id_with_corrupt_missing_metadata(job_db):
    put(job_db, 'historical_quizzes', 'historical_quizzes_bad', {'userId': 'u', 'courseId': 'c'})
    with pytest.raises(DataConflict): job_db.classify_historical_exam('historical_quizzes_bad', 'final', 'u', 'c')
    assert not job_db._flat_get('historical_finals', 'historical_quizzes_bad')


def test_selected_category_excludes_another_categories_prefixed_identity(job_db):
    put(job_db, 'historical_midterms', 'historical_quizzes_bad', {'userId': 'u', 'courseId': 'c', 'examType': 'midterm'})
    assert job_db.get_course_historical_exams('c', 'u', exam_type='midterm') == []


def test_intelligence_initial_query_is_restricted_to_selected_category(job_db, monkeypatch):
    db = job_db
    for category in ('quiz', 'midterm', 'final'):
        db.save_historical_exam('u', 'c', {'examType': category, 'status': 'completed',
            'analysis': {'topics': [category]}})
    calls = []
    original = db._flat_query_by_course
    def query(name, *args):
        calls.append(name)
        return original(name, *args)
    monkeypatch.setattr(db, '_flat_query_by_course', query)
    result = db.get_course_intelligence('c', user_id='u', historical_exam_type='midterm')
    assert [name for name in calls if name.startswith('historical_')] == ['historical_midterms']
    assert result['counts']['historical_exams'] == 1
    assert db.get_course_intelligence('c', user_id='u')['counts']['historical_exams'] == 3


def test_classification_racing_legacy_update_never_recreates_old_location(job_db, monkeypatch):
    db = job_db
    old = db.save_historical_exam('u', 'c', {'title': 'old'})
    original = db._flat_update
    def update(collection, key, data, **kwargs):
        db.classify_historical_exam(old, 'quiz', 'u', 'c')
        return original(collection, key, data, **kwargs)
    monkeypatch.setattr(db, '_flat_update', update)
    db.update_historical_exam(old, {'title': 'late update'})
    assert not db._flat_get('historical_exams', old)
    assert db.get_historical_exam(old)['examType'] == 'quiz'


@pytest.mark.parametrize('lifecycle', ['course', 'account'])
def test_lifecycle_purges_all_categories_and_owned_locators(job_db, monkeypatch, lifecycle):
    db = job_db
    monkeypatch.setattr(db, '_cleanup_storage_namespace', lambda *args, **kwargs: 0)
    for category in ('quiz', 'midterm', 'final'):
        db.save_historical_exam('u', 'c', {'examType': category})
    old = db.save_historical_exam('u', 'c', {'title': 'old'})
    db.classify_historical_exam(old, 'quiz', 'u', 'c')
    if lifecycle == 'course': db.delete_course_data('u', 'c')
    else:
        db.begin_account_deletion('u')
        db.delete_user_data('u')
    for name in ('historical_exams', 'historical_quizzes', 'historical_midterms', 'historical_finals', 'historical_exam_locations'):
        assert db._flat_query_by_course(name, 'c', 'u') == []
