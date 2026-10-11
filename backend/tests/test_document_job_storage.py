"""Durable document jobs fence retries, recovered leases and lifecycle races."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
import time

import pytest

from tests.test_atomic_data import database, cloud_database


@pytest.fixture(params=['database', 'cloud_database'])
def job_db(request, monkeypatch):
    client = request.getfixturevalue(request.param)
    if not client.use_local:
        # Model Firestore's serializable transaction boundary, including read-before-write.
        from google.cloud import firestore
        lock = threading.RLock()
        def transactional(fn):
            def call(tx):
                with lock:
                    return fn(tx)
            return call
        monkeypatch.setattr(firestore, 'transactional', transactional)
        original = client.db.transaction
        def transaction():
            tx = original()
            def delete(ref):
                tx.written = True
                ref.delete()
            tx.delete = delete
            return tx
        monkeypatch.setattr(client.db, 'transaction', transaction)
    return client


def seed_document(client, **fields):
    return client.save_document('u', 'c', {'originalDigest': 'a' * 64, **fields})


def start_claim(client, doc):
    job = client.start_document_job('u', 'c', doc, source_digest='a' * 64)
    now = int(time.time() * 1000)
    claim = client.claim_document_job('u', 'c', doc, job['id'], worker_id='worker', now_ms=now)
    return job, claim, now


def test_explicit_same_digest_retry_clears_confirmation_and_fences_previous_worker(job_db):
    doc = seed_document(job_db)
    old, claim, now = start_claim(job_db, doc)
    job_db.confirm_document_foundation('u', 'c', 'confirmed')
    new = job_db.start_document_job('u', 'c', doc, source_digest='a' * 64, force_guide=True)
    assert new['id'] != old['id']
    assert new['kind'] == 'guide'
    assert job_db.get_document_foundation('u', 'c') == {}
    assert job_db.checkpoint_document_job('u', 'c', doc, old['id'], claim['claimToken'], changes={'stage': 'completed'}, now_ms=now) is False
    assert job_db.get_document(doc)['processingJob']['id'] == new['id']


def test_competing_claims_have_one_winner_and_expiry_rotates_token(job_db):
    doc = seed_document(job_db)
    job = job_db.start_document_job('u', 'c', doc, source_digest='a' * 64)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda worker: job_db.claim_document_job('u', 'c', doc, job['id'], worker_id=str(worker), now_ms=100, lease_ms=100), range(2)))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    assert job_db.get_pending_document_jobs(now_ms=199) == []
    assert [r['id'] for r in job_db.get_pending_document_jobs(now_ms=200)] == [doc]
    recovered = job_db.claim_document_job('u', 'c', doc, job['id'], worker_id='recovered', now_ms=200, lease_ms=100)
    assert recovered['claimToken'] != winners[0]['claimToken']
    assert job_db.checkpoint_document_job('u', 'c', doc, job['id'], winners[0]['claimToken'], changes={}, now_ms=201) is False
    assert job_db.checkpoint_document_job('u', 'c', doc, job['id'], recovered['claimToken'], changes={}, now_ms=250, lease_ms=100)
    assert job_db.get_document(doc)['processingJob']['leaseUntil'] == 350
    assert not job_db.checkpoint_document_job('u', 'c', doc, job['id'], recovered['claimToken'], changes={}, now_ms=350)


@pytest.mark.parametrize('owner,course', [('v', 'c'), ('u', 'foreign')])
def test_foreign_claims_and_checkpoint_cannot_change_owned_document(job_db, owner, course):
    doc = seed_document(job_db)
    job, claim, now = start_claim(job_db, doc)
    before = deepcopy(job_db.get_document(doc))
    with pytest.raises(ValueError):
        job_db.start_document_job(owner, course, doc, source_digest='a' * 64)
    assert job_db.claim_document_job(owner, course, doc, job['id'], worker_id='foreign', now_ms=now + 400000) is None
    assert not job_db.checkpoint_document_job(owner, course, doc, job['id'], claim['claimToken'], changes={}, now_ms=now)
    assert job_db.get_document(doc) == before


@pytest.mark.parametrize('deletion', ['document', 'course', 'account', 'parent'])
def test_deletion_or_missing_parent_blocks_claims_checkpoints_and_discovery(job_db, deletion):
    doc = seed_document(job_db)
    job, claim, now = start_claim(job_db, doc)
    if deletion == 'document':
        job_db.delete_document(doc)
    elif deletion == 'course':
        job_db._begin_course_deletion('u', 'c')
    elif deletion == 'account':
        job_db.begin_account_deletion('u')
    else:
        job_db._flat_delete('courses', 'c')
    assert not job_db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={}, now_ms=now)
    assert job_db.claim_document_job('u', 'c', doc, job['id'], worker_id='late', now_ms=now + 400000) is None
    assert job_db.get_pending_document_jobs(now_ms=now + 400000) == []


def test_original_digest_change_and_failed_job_require_explicit_retry(job_db):
    doc = seed_document(job_db)
    job, claim, now = start_claim(job_db, doc)
    assert job_db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'stage': 'failed', 'error': 'split file'}, now_ms=now)
    assert job_db.get_pending_document_jobs(now_ms=now + 400000) == []
    assert job_db.claim_document_job('u', 'c', doc, job['id'], worker_id='late', now_ms=now + 400000) is None
    new, claim, now = start_claim(job_db, doc)
    job_db.update_document(doc, {'originalDigest': 'b' * 64})
    assert not job_db.checkpoint_document_job('u', 'c', doc, new['id'], claim['claimToken'], changes={}, now_ms=now)
    assert job_db.get_pending_document_jobs(now_ms=now + 400000) == []


def test_checkpoint_whitelist_and_record_limit_leave_existing_record_intact(job_db):
    doc = seed_document(job_db)
    job, claim, now = start_claim(job_db, doc)
    before = deepcopy(job_db.get_document(doc))
    for changes in [{'userId': 'v'}, {'sourceRevision': 'forged'}, {'processingJob': {}}, {'cursor': 'x' * 750001}]:
        with pytest.raises(ValueError):
            job_db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes=changes, now_ms=now)
        assert job_db.get_document(doc) == before


def test_invalidation_is_private_owned_and_does_not_create_confirmation(job_db):
    job_db.confirm_document_foundation('u', 'c', 'confirmed')
    with pytest.raises(ValueError):
        job_db.invalidate_document_foundation('v', 'c')
    assert job_db.get_document_foundation('u', 'c')['revision'] == 'confirmed'
    assert job_db.invalidate_document_foundation('u', 'c')
    assert job_db.get_document_foundation('u', 'c') == {}
    assert job_db.invalidate_document_foundation('u', 'c')


@pytest.mark.parametrize('cursor', [True, -1, '1', {'unexpected': 1}, {'unitIndex': True}, {'unitIndex': -1}])
def test_cursor_rejects_unknown_or_non_numeric_resume_positions(job_db, cursor):
    doc = seed_document(job_db)
    job, claim, now = start_claim(job_db, doc)
    with pytest.raises(ValueError):
        job_db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'cursor': cursor}, now_ms=now)


@pytest.mark.parametrize('change', [{'status': 'failed'}, {'preparationStatus': 'failed'}, {'guideStatus': 'failed'}])
def test_all_failure_checkpoints_are_terminal_until_explicit_retry(job_db, change):
    doc = seed_document(job_db)
    job, claim, now = start_claim(job_db, doc)
    assert job_db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes=change, now_ms=now)
    assert job_db.get_pending_document_jobs(now_ms=now + 400000) == []
    assert job_db.claim_document_job('u', 'c', doc, job['id'], worker_id='late', now_ms=now + 400000) is None
    assert job_db.get_document(doc)['processingJob']['stage'] == 'failed'


def test_adding_document_atomically_invalidates_only_its_owned_course_confirmation(job_db):
    job_db.confirm_document_foundation('u', 'c', 'confirmed')
    foreign = {'userId': 'v', 'courseId': 'v', 'revision': 'foreign'}
    if job_db.use_local:
        local = job_db._read_local_db()
        local.setdefault('document_foundations', {})['v'] = foreign
        job_db._write_local_db(local)
    else:
        job_db.db.rows['document_foundations/v'] = foreign
    doc = seed_document(job_db)
    assert job_db.get_document(doc)['userId'] == 'u'
    assert job_db.get_document_foundation('u', 'c') == {}
    assert job_db._flat_get('document_foundations', 'v') == {**foreign, 'id': 'v'}


def test_document_insertion_cannot_clear_foreign_private_metadata(job_db):
    foreign = {'userId': 'v', 'courseId': 'c', 'revision': 'foreign'}
    if job_db.use_local:
        local = job_db._read_local_db()
        local.setdefault('document_foundations', {})['c'] = foreign
        job_db._write_local_db(local)
    else:
        job_db.db.rows['document_foundations/c'] = foreign
    with pytest.raises(ValueError): seed_document(job_db)
    assert job_db.get_course_documents('c', 'u') == []
    assert job_db._flat_get('document_foundations', 'c') == {**foreign, 'id': 'c'}


@pytest.mark.parametrize('fence', ['account', 'course', 'missing'])
def test_creation_invalidation_respects_parent_and_deletion_fences(job_db, fence):
    job_db.confirm_document_foundation('u', 'c', 'confirmed')
    if fence == 'account': job_db.begin_account_deletion('u')
    elif fence == 'course': job_db._begin_course_deletion('u', 'c')
    else: job_db._flat_delete('courses', 'c')
    with pytest.raises(ValueError): seed_document(job_db)
    assert job_db.get_course_documents('c', 'u') == []
    assert job_db._flat_get('document_foundations', 'c')['revision'] == 'confirmed'


def test_view_and_metadata_updates_preserve_private_confirmation(job_db):
    doc = seed_document(job_db)
    job_db.confirm_document_foundation('u', 'c', 'confirmed')
    job_db.update_document(doc, {'lastViewedAt': 123, 'title': 'Lecture'})
    assert job_db.get_document_foundation('u', 'c')['revision'] == 'confirmed'
