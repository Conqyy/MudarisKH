"""Private manifests preserve exact original versions and clean race artifacts."""
from hashlib import sha256
import json
from pathlib import Path
import time
from copy import deepcopy

import pymupdf
import pytest

from tests.test_document_job_storage import job_db
from tests.test_atomic_data import database, cloud_database
from src.utils.document_sources import extract_source_units
from src.utils.source_contracts import build_source_manifest


@pytest.fixture
def library(job_db, monkeypatch, tmp_path):
    monkeypatch.setattr('src.database.firebase_client.UPLOADS_ROOT', tmp_path / 'uploads')
    if not job_db.use_local:
        from firebase_admin import storage
        class Blob:
            def __init__(self, name): self.name = name
            def exists(self): return self.name in objects
            def upload_from_string(self, data): objects[self.name] = bytes(data)
            def download_to_filename(self, path): Path(path).write_bytes(objects[self.name])
            def delete(self): objects.pop(self.name, None)
        class Bucket:
            def blob(self, name): return Blob(name)
            def list_blobs(self, prefix): return [Blob(name) for name in list(objects) if name.startswith(prefix)]
        objects = {}
        monkeypatch.setattr(storage, 'bucket', lambda: Bucket())
    from src.services.document_library import DocumentLibrary
    return DocumentLibrary(job_db)


def pdf_bytes(text):
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((30, 30), text)
        return pdf.tobytes()


def prepare(library, text='old source', doc=None, path='documents/u/c/original.pdf'):
    db = library.database
    original = pdf_bytes(text)
    digest = sha256(original).hexdigest()
    db.upload_file_to_storage(original, path, 'u')
    if doc is None:
        doc = db.save_document('u', 'c', {'storagePath': path, 'fileType': 'pdf', 'originalDigest': digest})
    else:
        db.update_document(doc, {'storagePath': path, 'originalDigest': digest})
    job = db.start_document_job('u', 'c', doc, source_digest=digest)
    claim = db.claim_document_job('u', 'c', doc, job['id'], worker_id='worker', now_ms=int(time.time() * 1000))
    manifest = build_source_manifest(doc, digest, 'pdf', extract_source_units(original, 'pdf'))
    return doc, job, claim, manifest


def test_manifest_and_rendering_keep_exact_immutable_original_after_replacement(library):
    db = library.database
    doc, job, claim, old = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], old)
    ref = {'documentId': doc, 'sourceRevision': old['sourceRevision'], 'unitId': 'p0001'}
    old_render = library.render_reference('u', 'c', ref)
    doc, job, claim, new = prepare(library, 'new source', doc=doc)
    with pytest.raises(ValueError): library.load_manifest('u', 'c', doc)
    assert library.load_manifest('u', 'c', doc, old['sourceRevision'])['sourceRevision'] == old['sourceRevision']
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], new)
    assert library.load_manifest('u', 'c', doc, old['sourceRevision'])['sourceRevision'] == old['sourceRevision']
    assert library.load_manifest('u', 'c', doc)['units'][0]['text'].strip() == 'new source'
    assert library.load_units('u', 'c', [ref])[0]['text'].strip() == 'old source'
    assert library.render_reference('u', 'c', ref) == old_render
    row = db.get_document(doc)
    assert 'units' not in row and 'manifest' not in row
    assert 'old source' not in json.dumps(row) and 'data:image' not in json.dumps(row)
    assert len(row['sourceVersions']) == 2
    original_path = row['sourceVersions'][old['sourceRevision']]['originalPath']
    db.delete_file_from_storage(original_path, 'u')
    with pytest.raises(FileNotFoundError):
        library.render_reference('u', 'c', ref)


@pytest.mark.parametrize('owner,course', [('v', 'c'), ('u', 'foreign')])
def test_library_rejects_foreign_ownership_course_and_locations(library, owner, course):
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    with pytest.raises(ValueError): library.load_manifest(owner, course, doc)
    with pytest.raises(ValueError): library.load_units(owner, course, [{'documentId': doc, 'sourceRevision': manifest['sourceRevision'], 'unitId': 'p0001'}])
    with pytest.raises(ValueError): library.load_units('u', 'c', [{'documentId': doc, 'sourceRevision': manifest['sourceRevision'], 'unitId': 'p0002'}])
    with pytest.raises(ValueError): library.load_manifest('u', 'c', doc, 'b' * 64)


def test_stale_publication_compensates_only_its_reserved_artifacts(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    original_upload = db.upload_file_to_storage
    def replace_job(data, path, user_id=None, **kwargs):
        result = original_upload(data, path, user_id, **kwargs)
        db.start_document_job('u', 'c', doc, source_digest=manifest['originalDigest'])
        return result
    monkeypatch.setattr(db, 'upload_file_to_storage', replace_job)
    with pytest.raises(ValueError): library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    assert db.get_document(doc).get('sourceVersions', {}) == {}
    assert db.get_document(doc).get('pendingArtifactPaths', []) == []
    assert db.download_file_from_storage('documents/u/c/original.pdf', 'u').is_file()
    assert len(list(db.download_file_from_storage('documents/u/c/original.pdf', 'u').parent.glob('*'))) == 1


def test_deletion_during_artifact_upload_cannot_recreate_metadata_or_leave_files(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    original_upload = db.upload_file_to_storage
    def delete_during_upload(data, path, user_id=None, **kwargs):
        result = original_upload(data, path, user_id, **kwargs)
        db.delete_document_data('u', doc)
        return result
    monkeypatch.setattr(db, 'upload_file_to_storage', delete_during_upload)
    with pytest.raises(ValueError): library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    assert db.get_document(doc) == {}
    assert db.get_pending_document_jobs(now_ms=int(time.time() * 1000)) == []


def test_upload_failure_keeps_published_versions_and_removes_only_attempt(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    original = library.render_reference('u', 'c', {'documentId': doc, 'sourceRevision': manifest['sourceRevision'], 'unitId': 'p0001'})
    job = db.start_document_job('u', 'c', doc, source_digest=manifest['originalDigest'])
    claim = db.claim_document_job('u', 'c', doc, job['id'], worker_id='retry', now_ms=int(time.time() * 1000))
    upload = db.upload_file_to_storage
    def fail_manifest(data, path, user_id=None, **kwargs):
        upload(data, path, user_id, **kwargs)
        if path.endswith('.json'): raise RuntimeError('Upload interrupted')
    monkeypatch.setattr(db, 'upload_file_to_storage', fail_manifest)
    with pytest.raises(RuntimeError): library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    assert library.render_reference('u', 'c', {'documentId': doc, 'sourceRevision': manifest['sourceRevision'], 'unitId': 'p0001'}) == original
    assert db.get_document(doc)['pendingArtifactPaths'] == []


@pytest.mark.parametrize('cleanup', ['document', 'course', 'account'])
def test_cleanup_removes_versions_pending_and_orphaned_assets_without_adjacent_id_collision(library, cleanup):
    from src.utils.storage_paths import document_artifact_prefix
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    adjacent = doc + '_neighbor'
    orphan = 'documents/u/c/' + document_artifact_prefix(doc) + 'orphan.json'
    pending = 'documents/u/c/' + document_artifact_prefix(doc) + 'pending.json'
    keep = 'documents/u/c/' + document_artifact_prefix(adjacent) + 'keep.json'
    for path in (orphan, pending, keep): db.upload_file_to_storage(b'{}', path, 'u')
    db.update_document(doc, {'pendingArtifactPaths': [pending]})
    db.confirm_document_foundation('u', 'c', 'confirmed')
    if cleanup == 'document':
        assert db.delete_document_data('u', doc)['documents'] == 1
        assert db.download_file_from_storage(keep, 'u').is_file()
        with pytest.raises(FileNotFoundError): db.download_file_from_storage(orphan, 'u')
    elif cleanup == 'course': db.delete_course_data('u', 'c')
    else:
        db.begin_account_deletion('u')
        db.delete_user_data('u')
    assert db.get_document(doc) == {}
    assert db.get_document_foundation('u', 'c') == {}


def test_remote_first_failure_retains_deleting_record_and_cancels_job(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    db.confirm_document_foundation('u', 'c', 'confirmed')
    def fail(*args, **kwargs): raise RuntimeError('Remote cleanup unavailable')
    monkeypatch.setattr(db, 'delete_file_from_storage', fail)
    with pytest.raises(RuntimeError): db.delete_document_data('u', doc)
    row = db.get_document(doc)
    assert row['status'] == 'deleting'
    assert row['processingJob'] is None
    assert db.get_document_foundation('u', 'c') == {}
    assert not db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={}, now_ms=int(time.time() * 1000))
    with pytest.raises(ValueError): library.load_manifest('u', 'c', doc)


def complete_guide(manifest):
    return {'version': 1, 'sourceRevision': manifest['sourceRevision'],
            'sections': [{'label': 'Source', 'purpose': 'Read source', 'unitIds': ['p0001']}],
            'concepts': [{'name': 'source', 'unitIds': ['p0001']}], 'visualReferences': [],
            'warnings': [], 'unitCoverage': manifest['coverage']}


def test_valid_guide_completion_and_same_digest_guide_retry_preserve_preparation(library):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    guide = complete_guide(manifest)
    now = int(time.time() * 1000)
    assert db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'stage': 'guiding', 'guide': guide, 'guideStatus': 'completed'}, now_ms=now)
    # Empty heartbeat after valid guide publication must still work.
    assert db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={}, now_ms=now)
    assert db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'stage': 'completed', 'status': 'completed'}, now_ms=now)
    db.confirm_document_foundation('u', 'c', 'confirmed')
    retry = db.start_document_job('u', 'c', doc, source_digest=manifest['originalDigest'], force_guide=True)
    row = db.get_document(doc)
    assert row['preparationStatus'] == 'completed' and row['guideStatus'] == 'pending'
    assert row['sourceManifestPath'] == row['sourceVersions'][manifest['sourceRevision']]['manifestPath']
    assert db.get_document_foundation('u', 'c') == {}
    next_claim = db.claim_document_job('u', 'c', doc, retry['id'], worker_id='guide', now_ms=now)
    assert next_claim['stage'] == 'guiding'


@pytest.mark.parametrize('changes', [
    {'preparationStatus': 'completed'}, {'guideStatus': 'completed'}, {'status': 'completed'},
    {'stage': 'completed'}, {'cursor': {'text': 'manifest body'}},
])
def test_checkpoint_cannot_forge_readiness_or_store_source_body_as_cursor(library, changes):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    before = deepcopy(db.get_document(doc))
    with pytest.raises(ValueError):
        db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes=changes, now_ms=int(time.time() * 1000))
    assert db.get_document(doc) == before


def test_checkpoint_rejects_guide_for_another_revision_and_corrupt_version_pointers(library):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    guide = complete_guide(manifest)
    guide['sourceRevision'] = 'b' * 64
    with pytest.raises(ValueError):
        db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'guide': guide, 'guideStatus': 'completed'}, now_ms=int(time.time() * 1000))
    versions = deepcopy(db.get_document(doc)['sourceVersions'])
    versions[manifest['sourceRevision']]['manifestPath'] = 'documents/u/c/foreign-document.json'
    db.update_document(doc, {'sourceVersions': versions})
    with pytest.raises(ValueError): library.load_manifest('u', 'c', doc)
    with pytest.raises(ValueError): db.delete_document_data('u', doc)
    assert db.get_document(doc)['status'] != 'deleting'


def test_failed_worker_cleanup_preserves_concurrent_published_worker_assets(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    upload = db.upload_file_to_storage
    ran = False
    def recover_and_publish(data, path, user_id=None, **kwargs):
        nonlocal ran
        result = upload(data, path, user_id, **kwargs)
        if not ran:
            ran = True
            new_job = db.start_document_job('u', 'c', doc, source_digest=manifest['originalDigest'])
            new_claim = db.claim_document_job('u', 'c', doc, new_job['id'], worker_id='new-worker', now_ms=int(time.time() * 1000))
            library.save_manifest('u', 'c', doc, new_job['id'], new_claim['claimToken'], manifest)
        return result
    monkeypatch.setattr(db, 'upload_file_to_storage', recover_and_publish)
    with pytest.raises(ValueError): library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    assert library.load_manifest('u', 'c', doc)['sourceRevision'] == manifest['sourceRevision']
    assert library.render_reference('u', 'c', {'documentId': doc, 'sourceRevision': manifest['sourceRevision'], 'unitId': 'p0001'})
    assert db.get_document(doc)['pendingArtifactPaths'] == []


def test_cloud_upload_failure_is_not_published_as_durable_manifest(library, monkeypatch):
    db = library.database
    if db.use_local:
        pytest.skip('Cloud durability boundary')
    doc, job, claim, manifest = prepare(library)
    from firebase_admin import storage
    bucket = storage.bucket()
    blob = bucket.blob
    def failing_blob(path):
        result = blob(path)
        if 'source-' in path:
            def fail(data): raise RuntimeError('Cloud storage is unavailable')
            result.upload_from_string = fail
        return result
    monkeypatch.setattr(bucket, 'blob', failing_blob)
    monkeypatch.setattr(storage, 'bucket', lambda: bucket)
    with pytest.raises(RuntimeError): library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    assert db.get_document(doc).get('sourceVersions', {}) == {}
    assert db.get_document(doc)['pendingArtifactPaths'] == []


def test_incomplete_manifest_never_completes_preparation(library):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    units = deepcopy(manifest['units'])
    units[0].update({'needsVisualRead': True, 'visualReadStatus': 'pending'})
    unresolved = build_source_manifest(doc, manifest['originalDigest'], 'pdf', units)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], unresolved)
    assert library.load_manifest('u', 'c', doc)['coverage']['complete'] is False
    assert db.get_document(doc)['preparationStatus'] == 'processing'
    with pytest.raises(ValueError):
        db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'preparationStatus': 'completed'}, now_ms=int(time.time() * 1000))


def test_publishing_over_record_limit_compensates_reserved_assets(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    # Fill only existing metadata; reservation fits, but complete version references do not.
    db.update_document(doc, {'padding': 'x' * 748900})
    upload = db.upload_file_to_storage
    uploads = []
    def track(data, path, user_id=None, **kwargs):
        uploads.append(path)
        return upload(data, path, user_id, **kwargs)
    monkeypatch.setattr(db, 'upload_file_to_storage', track)
    with pytest.raises(ValueError): library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    assert len(uploads) == 2
    assert not db.get_document(doc).get('sourceVersions')
    assert db.get_document(doc).get('pendingArtifactPaths', []) == []


def test_deleting_record_cannot_be_revived_by_generic_update(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    def fail(*args, **kwargs): raise RuntimeError('Cleanup unavailable')
    monkeypatch.setattr(db, 'delete_file_from_storage', fail)
    with pytest.raises(RuntimeError): db.delete_document_data('u', doc)
    with pytest.raises(ValueError): db.update_document(doc, {'status': 'processing'})
    assert db.get_document(doc)['status'] == 'deleting'


def test_deleted_document_cannot_leave_a_late_artifact_written_after_cleanup(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    upload = db.upload_file_to_storage
    attempted = []
    def delete_before_write(data, path, user_id=None, **kwargs):
        if not attempted:
            db.delete_document_data('u', doc)
        attempted.append(path)
        return upload(data, path, user_id, **kwargs)
    monkeypatch.setattr(db, 'upload_file_to_storage', delete_before_write)
    with pytest.raises(ValueError): library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    assert db.get_document(doc) == {}
    assert len(attempted) == 1
    with pytest.raises(FileNotFoundError): db.download_file_from_storage(attempted[0], 'u')


def test_source_publication_rejects_claim_reserved_but_forged_version(library):
    from src.utils.storage_paths import build_document_artifact_path
    db = library.database
    doc, job, claim, manifest = prepare(library)
    paths = [build_document_artifact_path('u', 'c', doc, job['id'], claim['claimToken'], 'c' * 32, suffix)
             for suffix in ('original.pdf', 'manifest.json')]
    assert db.reserve_document_artifacts('u', 'c', doc, job['id'], claim['claimToken'], paths=paths, now_ms=int(time.time() * 1000))
    for path in paths: db.upload_file_to_storage(b'forged', path, 'u')
    version = {'manifestPath': paths[1], 'manifestDigest': 'a' * 64,
               'originalPath': paths[0], 'originalDigest': manifest['originalDigest'], 'fileType': 'pdf',
               'unitCount': 1, 'coverageComplete': True}
    with pytest.raises(ValueError):
        db.publish_document_source('u', 'c', doc, job['id'], claim['claimToken'], source_revision=manifest['sourceRevision'], version=version, now_ms=int(time.time() * 1000))
    assert db.get_document(doc).get('sourceVersions', {}) == {}


def test_account_cleanup_includes_parentless_derivative_records_and_untracked_assets(library):
    from src.utils.storage_paths import document_artifact_prefix
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    db._flat_delete('courses', 'c')
    from src.database import firebase_client
    orphan = firebase_client.UPLOADS_ROOT / 'documents/u/gone' / (document_artifact_prefix('missing') + 'orphan.json')
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b'{}')
    db.begin_account_deletion('u')
    assert db.delete_user_data('u')['documents'] == 1
    assert not orphan.exists()
    assert db.get_document(doc) == {}


def test_failed_document_cleanup_is_retryable_and_retains_exact_source_assets(library, monkeypatch):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    delete = db.delete_file_from_storage
    version = db.get_document(doc)['sourceVersions'][manifest['sourceRevision']]
    def unavailable(*args, **kwargs): raise RuntimeError('Remote delete failed')
    monkeypatch.setattr(db, 'delete_file_from_storage', unavailable)
    with pytest.raises(RuntimeError): db.delete_document_data('u', doc)
    assert db.download_file_from_storage(version['manifestPath'], 'u').is_file()
    assert db.get_document(doc)['sourceVersions'][manifest['sourceRevision']] == version
    monkeypatch.setattr(db, 'delete_file_from_storage', delete)
    assert db.delete_document_data('u', doc)['documents'] == 1
    with pytest.raises(FileNotFoundError): db.download_file_from_storage(version['manifestPath'], 'u')


def test_recovery_between_preparation_publication_and_guide_checkpoint_reuses_complete_source(library):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    lease = db.get_document(doc)['processingJob']['leaseUntil']
    recovered = db.claim_document_job('u', 'c', doc, job['id'], worker_id='recovered', now_ms=lease)
    assert recovered['stage'] == 'guiding'
    assert db.get_document(doc)['preparationStatus'] == 'completed'
    assert db.get_document(doc)['guideStatus'] == 'processing'


def test_completed_document_status_checkpoint_also_finishes_job_and_prevents_recovery(library):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    library.save_manifest('u', 'c', doc, job['id'], claim['claimToken'], manifest)
    now = int(time.time() * 1000)
    assert db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'guide': complete_guide(manifest), 'guideStatus': 'completed'}, now_ms=now)
    assert db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'status': 'completed'}, now_ms=now)
    assert db.get_document(doc)['processingJob']['stage'] == 'completed'
    assert db.get_pending_document_jobs(now_ms=now + 400000) == []
    assert db.claim_document_job('u', 'c', doc, job['id'], worker_id='late', now_ms=now + 400000) is None


def test_guiding_checkpoint_requires_complete_preparation(library):
    db = library.database
    doc, job, claim, manifest = prepare(library)
    with pytest.raises(ValueError):
        db.checkpoint_document_job('u', 'c', doc, job['id'], claim['claimToken'], changes={'stage': 'guiding', 'guideStatus': 'processing'}, now_ms=int(time.time() * 1000))
