import asyncio
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from unittest.mock import MagicMock
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_document_library import library, pdf_bytes
from tests.test_document_pipeline import queued, pipeline, Processor

@pytest.fixture
def source_api(api_module, library, monkeypatch):
    monkeypatch.setattr(api_module, 'db_client', library.database)
    monkeypatch.setattr(api_module, '_spawn_document_job', MagicMock(return_value=False), raising=False)
    api_module.app.dependency_overrides[api_module.require_uid] = lambda: 'u'
    yield api_module
    api_module.app.dependency_overrides.clear()

def test_upload_accepts_durable_queued_automatic_work(source_api, library):
    client = TestClient(source_api.app)
    response = client.post('/api/documents/upload', data={'user_id': 'foreign', 'course_id': 'c'},
                           files={'file': ('lecture.pdf', pdf_bytes('Limits lecture'), 'application/pdf')})
    assert response.status_code == 202
    doc = library.database.get_document(response.json()['document_id'])
    assert doc['preparationStatus'] in ('pending', 'processing', 'completed')
    assert doc['guideStatus'] == 'pending'
    assert doc['processingJob']['stage'] == 'queued'
    assert pipeline(library, Processor()).run(doc['id'])
    assert source_api.get_course_foundation('c', uid='u')['state'] == 'confirmation_required'

def complete(library):
    doc = queued(library)
    assert pipeline(library, Processor()).run(doc)
    return doc

def test_readiness_validates_actual_artifacts_and_public_projection(source_api, library):
    doc = complete(library)
    result = source_api.get_course_foundation('c', uid='u')
    assert result['state'] == 'confirmation_required'
    source_api.confirm_course_foundation('c', source_api.FoundationConfirmRequest(revision=result['revision']), uid='u')
    client = TestClient(source_api.app)
    metadata = client.get(f'/api/documents/{doc}/sources').json()
    text = str(metadata)
    for private in ('sourceVersions', 'manifestPath', 'originalPath', 'claimToken', 'Complete lecture'):
        assert private not in text
    row = library.database.get_document(doc)
    assert client.get(f'/api/documents/{doc}/sources/p0001').status_code == 422
    unit = client.get(f'/api/documents/{doc}/sources/p0001', params={'source_revision': row['sourceRevision']})
    assert unit.status_code == 200
    assert 'Complete lecture' in unit.text
    library.database.delete_file_from_storage(row['sourceVersions'][row['sourceRevision']]['originalPath'], 'u')
    failed = source_api.get_course_foundation('c', uid='u')
    assert failed['ready'] is False
    assert failed['failedDocumentIds'] == [doc]

def test_identical_retry_reconfirmation_fences_inflight_generation(source_api, library, monkeypatch):
    from tests.foundation_fixtures import stub_source_provider
    stub_source_provider(monkeypatch)
    doc = complete(library)
    first = source_api.get_course_foundation('c', uid='u')
    source_api.confirm_course_foundation('c', source_api.FoundationConfirmRequest(revision=first['revision']), uid='u')
    agent = MagicMock()
    def generate(**kwargs):
        source_api.reanalyze_document(doc, uid='u')
        assert pipeline(library, Processor()).run(doc)
        current = source_api.get_course_foundation('c', uid='u')
        assert current['revision'] != first['revision']
        source_api.confirm_course_foundation('c', source_api.FoundationConfirmRequest(revision=current['revision']), uid='u')
        return [{'front': 'Limit?', 'back': 'Value', 'topic': 'Limits'}]
    agent.generate_flashcards.side_effect = generate
    monkeypatch.setattr(source_api, 'ai_agent', agent)
    with pytest.raises(source_api.HTTPException) as error:
        source_api.generate_flashcards_endpoint(source_api.FlashcardGenerateRequest(user_id='u', course_id='c'), uid='u')
    assert error.value.status_code == 409

def test_legacy_only_requires_explicit_upgrade_and_polling_is_stable(source_api, library):
    db = library.database
    doc = complete(library)
    before = source_api.get_course_foundation('c', uid='u')
    db.update_document(doc, {'updatedAt': 9000, 'processedAt': 5000})
    assert source_api.get_course_foundation('c', uid='u')['revision'] == before['revision']
    legacy = db.save_document('u', 'c', {'status': 'completed', 'analysis': {'topics': ['Legacy']}})
    result = source_api.get_course_foundation('c', uid='u')
    assert legacy in result['failedDocumentIds']
    assert result['failedStages'][legacy]['stage'] == 'upgrade_required'
    assert db.get_pending_document_jobs(now_ms=10**15) == []

def test_upload_record_already_contains_recoverable_job_at_save(source_api, library, monkeypatch):
    db = library.database
    save = db.save_document
    at_commit = []
    def commit(*args, **kwargs):
        identity = save(*args, **kwargs)
        at_commit.append(db.get_document(identity))
        return identity
    monkeypatch.setattr(db, 'save_document', commit)
    response = TestClient(source_api.app).post('/api/documents/upload', data={'user_id': 'u', 'course_id': 'c'},
                    files={'file': ('atomic.pdf', pdf_bytes('Atomic source'), 'application/pdf')})
    assert response.status_code == 202
    assert at_commit[0]['processingJob']['stage'] == 'queued'


def test_legacy_digest_discovery_revalidates_association(source_api, library, monkeypatch):
    db = library.database
    path = 'documents/u/c/legacy.pdf'
    db.upload_file_to_storage(pdf_bytes('Legacy source'), path, 'u', require_remote=True)
    doc = db.save_document('u', 'c', {'storagePath': path, 'fileType': 'pdf', 'analysis': {'topics': ['Legacy']}})
    download = db.download_file_from_storage
    def changed(*args, **kwargs):
        result = download(*args, **kwargs)
        db.update_document(doc, {'storagePath': 'documents/u/c/replaced.pdf'})
        return result
    monkeypatch.setattr(db, 'download_file_from_storage', changed)
    with pytest.raises(source_api.HTTPException) as error:
        source_api.prepare_document(doc, uid='u')
    assert error.value.status_code == 409
    assert not db.get_document(doc).get('processingJob')


def test_lifespan_periodic_recovery_is_cancelled_and_runner_reopens(api_module, monkeypatch):
    calls = []
    sleeps = []
    repeated = __import__('threading').Event()
    real_sleep = asyncio.sleep
    async def fast_sleep(delay):
        sleeps.append(delay)
        await real_sleep(0.001)
    monkeypatch.setattr(api_module.asyncio, 'sleep', fast_sleep)
    monkeypatch.setattr(api_module, '_recover_audio_jobs', lambda: None)
    monkeypatch.setattr(api_module, '_close_audio_jobs', lambda: None)
    def recover():
        calls.append('recover')
        if calls.count('recover') > 1: repeated.set()
    monkeypatch.setattr(api_module, '_recover_document_jobs', recover)
    monkeypatch.setattr(api_module, '_close_document_jobs', lambda: calls.append('close'))
    async def lifecycle():
        async with api_module._lifespan(api_module.app):
            assert await asyncio.to_thread(repeated.wait, 2)
        count = len(calls)
        await real_sleep(0.01)
        assert len(calls) == count
    asyncio.run(lifecycle())
    assert calls[0] == 'recover' and calls[-1] == 'close'
    assert calls.count('recover') > 1
    assert set(sleeps) == {10}

def test_local_executor_failure_does_not_reject_durable_acceptance(source_api, library, monkeypatch):
    monkeypatch.setattr(source_api, '_spawn_document_job', MagicMock(side_effect=RuntimeError('executor unavailable')))
    response = TestClient(source_api.app, raise_server_exceptions=False).post('/api/documents/upload',
        data={'user_id': 'u', 'course_id': 'c'}, files={'file': ('retained.pdf', pdf_bytes('Retained source'), 'application/pdf')})
    assert response.status_code == 202
    doc = library.database.get_document(response.json()['document_id'])
    assert doc['processingJob']['stage'] == 'queued'
    assert pipeline(library, Processor()).run(doc['id'])


@pytest.mark.parametrize('method,url', [('get', '/sources'), ('get', '/sources/p0001?source_revision=' + 'a'*64), ('post', '/prepare')])
def test_source_routes_reject_foreign_owner(source_api, library, method, url):
    doc = complete(library)
    source_api.app.dependency_overrides[source_api.require_uid] = lambda: 'foreign'
    response = getattr(TestClient(source_api.app), method)(f'/api/documents/{doc}{url}')
    assert response.status_code == 404


def test_original_upload_requires_remote_durability(source_api, library, monkeypatch):
    db = library.database
    upload = db.upload_file_to_storage
    def durable(raw, path, user_id=None, **kwargs):
        assert kwargs.get('require_remote') is True
        raise OSError('remote storage unavailable')
    monkeypatch.setattr(db, 'upload_file_to_storage', durable)
    response = TestClient(source_api.app, raise_server_exceptions=False).post('/api/documents/upload',
        data={'user_id': 'u', 'course_id': 'c'}, files={'file': ('missing.pdf', pdf_bytes('Source'), 'application/pdf')})
    assert response.status_code == 500
    assert db.get_course_documents('c', user_id='u') == []


def test_repeat_lifespan_reopens_document_runner(api_module, monkeypatch):
    db = MagicMock()
    db.get_pending_audio_jobs.return_value = []
    db.get_pending_document_jobs.return_value = []
    monkeypatch.setattr(api_module, 'db_client', db)
    for _ in range(2):
        with TestClient(api_module.app):
            assert api_module._document_job_runner._closed is False
        assert api_module._document_job_runner._closed is True

def test_original_view_works_before_foundation_and_keeps_private_paths_hidden(source_api, library):
    doc = queued(library)
    assert source_api.get_course_foundation('c', uid='u')['ready'] is False
    response = TestClient(source_api.app).get(f'/api/documents/{doc}/original')
    assert response.status_code == 200
    assert response.content.startswith(b'%PDF')
    assert response.headers['content-type'] == 'application/pdf'
    assert 'documents/' not in str(response.headers)


def test_original_view_rechecks_owner_after_download(source_api, library, monkeypatch):
    doc = queued(library)
    db = library.database
    download = db.download_file_from_storage
    def removed(*args, **kwargs):
        path = download(*args, **kwargs)
        db.delete_document(doc)
        return path
    monkeypatch.setattr(db, 'download_file_from_storage', removed)
    response = TestClient(source_api.app).get(f'/api/documents/{doc}/original')
    assert response.status_code == 404
    assert not response.content.startswith(b'%PDF')

def test_readiness_rechecks_document_after_artifact_io(source_api, library, monkeypatch):
    doc = complete(library)
    db = library.database
    status = source_api.get_course_foundation('c', uid='u')
    source_api.confirm_course_foundation('c', source_api.FoundationConfirmRequest(revision=status['revision']), uid='u')
    download = db.download_file_from_storage
    original = db.get_document(doc)['storagePath']
    def delete_during_read(path, user_id=None):
        result = download(path, user_id)
        if path == original: db.delete_document(doc)
        return result
    monkeypatch.setattr(db, 'download_file_from_storage', delete_during_read)
    result = source_api.get_course_foundation('c', uid='u')
    assert result['ready'] is False
