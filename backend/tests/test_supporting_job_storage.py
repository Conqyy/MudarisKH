"""Real local/fake-cloud transactions fence supporting retries and deletion."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import time
import pytest

from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.foundation_fixtures import lecture_document
from src.utils.course_foundation import foundation_material_revision
from src.supporting.repository import SupportingRepository
from src.supporting.contracts import CLAIM_LEASE_MS


@pytest.fixture
def repository(job_db):
    doc = lecture_document('lecture', userId='u', courseId='c')
    row = {k: v for k, v in doc.items() if not k.startswith('_') and k != 'id'}
    if job_db.use_local:
        local = job_db._read_local_db()
        local['documents'] = {'lecture': row}
        job_db._write_local_db(local)
    else:
        job_db.db.rows['documents/lecture'] = row
    revision = foundation_material_revision([{**row, 'id': 'lecture'}])
    job_db.confirm_document_foundation('u', 'c', revision, require_current_documents=True)
    result = SupportingRepository(job_db)
    result.test_foundation_revision = revision
    result.test_lecture = doc
    return result


def identity(kind='historical_exam', material='source'):
    return {'userId': 'u', 'courseId': 'c', 'kind': kind, 'materialId': material}


def queue_claim(repo, *, material=None, now=None, original='a'*64):
    material = material or identity()
    now = int(time.time()*1000) if now is None else now
    job = repo.queue(material, input_revision='b'*64, source_digest=original,
                     foundation_revision=repo.test_foundation_revision, now_ms=now,
                     initial_data={'title': 'Past paper', 'sourceType': 'notes' if material['kind'] == 'notes' else 'file'})
    claim = repo.claim(material, job['id'], worker_id='worker', now_ms=now)
    return job, claim, now


def test_new_material_and_queue_are_atomic_and_cannot_overwrite(repository):
    job, claim, now = queue_claim(repository)
    row = repository.get_owned(identity())
    assert row['processingJob']['id'] == job['id'] and row['status'] == 'processing'
    with pytest.raises(ValueError): queue_claim(repository)
    assert repository.get_owned(identity())['processingJob']['id'] == job['id']


def test_competing_claims_and_recovery_rotate_token(repository):
    job, old, now = queue_claim(repository, now=100)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda n: repository.claim(identity(), job['id'], worker_id=str(n), now_ms=100+CLAIM_LEASE_MS), range(2)))
    winners = [claim for claim in claims if claim]
    assert len(winners) == 1 and winners[0]['claimToken'] != old['claimToken']
    assert not repository.checkpoint(identity(), old, changes={}, now_ms=101+CLAIM_LEASE_MS)
    assert repository.checkpoint(identity(), winners[0], changes={'cursor': {'batchIndex': 3}}, now_ms=101+CLAIM_LEASE_MS)


def test_retry_preserves_foundation_and_fences_old_claim(repository):
    job, claim, now = queue_claim(repository)
    retry = repository.queue(identity(), input_revision='b'*64, source_digest='a'*64,
                             foundation_revision=repository.test_foundation_revision, now_ms=now+1)
    assert retry['id'] != job['id']
    assert not repository.checkpoint(identity(), claim, changes={}, now_ms=now+2)
    assert repository.database.get_document_foundation('u', 'c')['revision'] == repository.test_foundation_revision


@pytest.mark.parametrize('change', ['foundation', 'course', 'account', 'source'])
def test_source_foundation_and_deletion_changes_fence_workers(repository, change):
    job, claim, now = queue_claim(repository)
    db = repository.database
    if change == 'foundation': db.invalidate_document_foundation('u', 'c')
    if change == 'course': db._begin_course_deletion('u', 'c')
    if change == 'account': db.begin_account_deletion('u')
    if change == 'source': db._flat_update('historical_exams', 'source', {'originalDigest': 'c'*64})
    assert not repository.checkpoint(identity(), claim, changes={}, now_ms=now+1)
    assert repository.claim(identity(), job['id'], worker_id='late', now_ms=now+CLAIM_LEASE_MS) is None
    assert repository.pending(now_ms=now+CLAIM_LEASE_MS) == []


@pytest.mark.parametrize('field,value', [('userId', 'other'), ('sourceRevision', 'c'*64), ('claimToken', 'fake'), ('modelCalls', -1)])
def test_checkpoint_cannot_rewrite_identity_or_reduce_budget(repository, field, value):
    job, claim, now = queue_claim(repository)
    before = repository.get_owned(identity())
    with pytest.raises(ValueError): repository.checkpoint(identity(), claim, changes={field: value}, now_ms=now)
    assert repository.get_owned(identity()) == before


def test_notes_cannot_be_read_as_recorded_audio(repository):
    queue_claim(repository, material=identity('notes'))
    with pytest.raises(ValueError): repository.get_owned(identity('audio'))


def test_budget_survives_recovery_and_resets_only_explicit_retry(repository):
    job, claim, now = queue_claim(repository)
    assert repository.checkpoint(identity(), claim, changes={'modelCalls': 9}, now_ms=now)
    recovered = repository.claim(identity(), job['id'], worker_id='recovery', now_ms=now+CLAIM_LEASE_MS)
    assert repository.get_owned(identity())['processingJob']['modelCalls'] == 9
    assert not repository.checkpoint(identity(), claim, changes={'modelCalls': 10}, now_ms=now+CLAIM_LEASE_MS)
    retry = repository.queue(identity(), input_revision='b'*64, source_digest='a'*64,
                             foundation_revision=repository.test_foundation_revision, now_ms=now+CLAIM_LEASE_MS+1)
    assert repository.get_owned(identity())['processingJob']['modelCalls'] == 0
    assert retry['id'] != recovered['id']


def test_pending_discovers_only_expired_valid_owned_jobs(repository):
    job, claim, now = queue_claim(repository, now=100)
    assert repository.pending(now_ms=100) == []
    assert repository.pending(now_ms=100+CLAIM_LEASE_MS) == [identity()]
