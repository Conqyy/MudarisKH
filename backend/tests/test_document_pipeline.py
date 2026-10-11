from copy import deepcopy
from hashlib import sha256
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_document_library import library, pdf_bytes
from src.utils.source_contracts import guide_digest

class Processor:
    def __init__(self):
        self.visual_calls = self.guide_calls = 0
        self.fail_guide = False
        self.on_guide = None
    def read_source_visual(self, unit, images):
        self.visual_calls += 1
        assert images
        return {'text': '', 'visualDescription': 'Lecture about limits.', 'readability': 'readable', 'warnings': []}
    def analyze_source_guide(self, manifest, title, render_unit):
        self.guide_calls += 1
        if self.on_guide: self.on_guide()
        if self.fail_guide: raise RuntimeError('private source text')
        ids = manifest['coverage']['readableUnitIds']
        return {'version': 1, 'sourceRevision': manifest['sourceRevision'],
                'sections': [{'label': 'Limits', 'purpose': 'Understand limits', 'unitIds': ids}],
                'concepts': [{'name': 'Limits', 'unitIds': ids}], 'visualReferences': [],
                'warnings': [], 'unitCoverage': deepcopy(manifest['coverage'])}

def queued(library):
    db = library.database
    raw = pdf_bytes('Complete lecture about limits')
    path = 'documents/u/c/input.pdf'
    db.upload_file_to_storage(raw, path, 'u', require_remote=True)
    doc = db.save_document('u', 'c', {'storagePath': path, 'fileType': 'pdf', 'extractedText': 'legacy large text'})
    db.start_document_job('u', 'c', doc, source_digest=sha256(raw).hexdigest())
    return doc

def pipeline(library, processor):
    from src.services.document_pipeline import DocumentPipeline
    return DocumentPipeline(library.database, library, processor)

def test_automatic_complete_source_publication_and_compact_record(library):
    doc, processor = queued(library), Processor()
    assert pipeline(library, processor).run(doc) is True
    row = library.database.get_document(doc)
    manifest = library.load_manifest('u', 'c', doc)
    assert row['status'] == row['preparationStatus'] == row['guideStatus'] == 'completed'
    assert manifest['coverage']['complete']
    assert row['guideRevision'] == guide_digest(row['guide'])
    assert row['unitCount'] == manifest['unitCount']
    assert not row.get('extractedText')
    assert processor.guide_calls == 1

def test_guide_retry_reuses_durable_preparation_and_requires_confirmation(library):
    doc, processor = queued(library), Processor()
    processor.fail_guide = True
    worker = pipeline(library, processor)
    assert worker.run(doc) is False
    db = library.database
    failed = db.get_document(doc)
    assert failed['status'] == failed['guideStatus'] == 'failed'
    assert failed['preparationStatus'] == 'completed'
    assert 'private source' not in failed['guideError']
    calls = processor.visual_calls
    db.confirm_document_foundation('u', 'c', 'old')
    processor.fail_guide = False
    db.start_document_job('u', 'c', doc, source_digest=failed['originalDigest'], force_guide=True)
    assert worker.run(doc) is True
    assert processor.visual_calls == calls
    assert db.get_document(doc)['guideError'] is None
    assert db.get_document_foundation('u', 'c') == {}

def test_missing_original_fails_after_claim_without_provider_work(library):
    doc, processor = queued(library), Processor()
    library.database.delete_file_from_storage('documents/u/c/input.pdf', 'u')
    assert pipeline(library, processor).run(doc) is False
    assert processor.guide_calls == processor.visual_calls == 0
    assert library.database.get_document(doc)['preparationStatus'] == 'failed'

@pytest.mark.parametrize('action', ['delete', 'retry'])
def test_job_changes_during_provider_work_cannot_publish(library, action):
    doc, processor = queued(library), Processor()
    db = library.database
    def change():
        if action == 'delete': db.delete_document_data('u', doc)
        else:
            row = db.get_document(doc)
            db.start_document_job('u', 'c', doc, source_digest=row['originalDigest'], force_guide=True)
    processor.on_guide = change
    assert pipeline(library, processor).run(doc) is False
    row = db.get_document(doc)
    assert not row or row['processingJob']['stage'] == 'queued'

def test_two_workers_only_one_provider_and_expired_claim_recovers(library):
    doc, processor = queued(library), Processor()
    db = library.database
    row = db.get_document(doc)
    db.claim_document_job('u', 'c', doc, row['processingJob']['id'], worker_id='dead', now_ms=0, lease_ms=1)
    entered, release = threading.Event(), threading.Event()
    processor.on_guide = lambda: (entered.set(), release.wait(5))
    worker = pipeline(library, processor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.run, doc)
        assert entered.wait(5)
        assert pool.submit(worker.run, doc).result(5) is False
        release.set()
        assert first.result(5) is True
    assert processor.guide_calls == 1

def test_runner_capacity_keeps_persisted_job(library):
    from src.utils.document_job_runner import DocumentJobRunner
    doc = queued(library)
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    def run(identity):
        entered.set()
        release.wait(5)
        result = pipeline(library, Processor()).run(identity)
        done.set()
        return result
    runner = DocumentJobRunner(library.database, run, max_workers=1, max_pending=1)
    try:
        assert runner.submit(doc)
        assert entered.wait(5)
        assert not runner.submit(doc)
        assert not runner.submit('other')
        assert library.database.get_document(doc)['processingJob']['stage'] == 'queued'
        release.set()
        assert done.wait(5)
    finally:
        release.set()
        runner.close()
    assert not runner.submit(doc)

def test_source_size_failure_has_split_guidance(library):
    import pymupdf
    db = library.database
    with pymupdf.open() as pdf:
        for _ in range(161): pdf.new_page()
        raw = pdf.tobytes()
    path = 'documents/u/c/large.pdf'
    db.upload_file_to_storage(raw, path, 'u', require_remote=True)
    doc = db.save_document('u', 'c', {'storagePath': path, 'fileType': 'pdf'})
    db.start_document_job('u', 'c', doc, source_digest=sha256(raw).hexdigest())
    assert pipeline(library, Processor()).run(doc) is False
    assert 'split' in db.get_document(doc)['preparationError'].lower()


def test_heartbeat_renews_during_provider_and_stops_after_completion(library, monkeypatch):
    import time
    import src.services.document_pipeline as module
    monkeypatch.setattr(module, 'HEARTBEAT_SECONDS', 0.01)
    doc, processor = queued(library), Processor()
    db = library.database
    renewed = threading.Event()
    original_checkpoint = db.checkpoint_document_job
    def checkpoint(*args, **kwargs):
        if threading.current_thread().name.startswith('document-lease-'):
            renewed.set()
        return original_checkpoint(*args, **kwargs)
    monkeypatch.setattr(db, 'checkpoint_document_job', checkpoint)
    processor.on_guide = lambda: renewed.wait(2)
    assert pipeline(library, processor).run(doc)
    assert renewed.is_set()
    assert not any(t.name.startswith('document-lease-') and t.is_alive() for t in threading.enumerate())


def test_restart_after_preparation_reuses_published_manifest(library, monkeypatch):
    doc, processor = queued(library), Processor()
    db = library.database
    worker = pipeline(library, processor)
    processor.on_guide = lambda: (_ for _ in ()).throw(SystemExit('simulated process death'))
    with pytest.raises(SystemExit): worker.run(doc)
    row = db.get_document(doc)
    assert row['preparationStatus'] == 'completed'
    assert row['processingJob']['stage'] == 'guiding'
    old_visual_calls = processor.visual_calls
    # Expire only the lease in the real test storage, as elapsed downtime would.
    if db.use_local:
        local = db._read_local_db()
        local['documents'][doc]['processingJob']['leaseUntil'] = 0
        db._write_local_db(local)
    else:
        row['processingJob']['leaseUntil'] = 0
        db.db.collection('documents').document(doc).update({'processingJob': row['processingJob']})
    processor.on_guide = None
    assert worker.run(doc)
    assert processor.visual_calls == old_visual_calls


def test_capacity_discovery_runs_second_persisted_job_when_slot_frees(library):
    from src.utils.document_job_runner import DocumentJobRunner
    first = queued(library)
    second = queued(library)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def run(doc):
        if doc == first:
            entered.set()
            release.wait(5)
        result = pipeline(library, Processor()).run(doc)
        if doc == second: finished.set()
        return result
    runner = DocumentJobRunner(library.database, run, max_workers=1, max_pending=1)
    try:
        assert runner.submit(first)
        assert entered.wait(5)
        assert runner.submit(second) is False
        release.set()
        assert finished.wait(5)
        assert library.database.get_document(second)['status'] == 'completed'
    finally:
        release.set()
        runner.close()

@pytest.mark.parametrize('artifact,damage', [('manifestPath', 'missing'), ('manifestPath', 'corrupt'),
                                           ('originalPath', 'missing'), ('originalPath', 'corrupt')])
def test_explicit_retry_restores_identical_version_from_preserved_original(library, artifact, damage):
    doc = queued(library)
    assert pipeline(library, Processor()).run(doc)
    db = library.database
    row = db.get_document(doc)
    revision = row['sourceRevision']
    ref = {'documentId': doc, 'sourceRevision': revision, 'unitId': 'p0001'}
    before = library.load_units('u', 'c', [ref])
    broken = row['sourceVersions'][revision][artifact]
    if damage == 'missing': db.delete_file_from_storage(broken, 'u')
    else: db.upload_file_to_storage(b'corrupt artifact', broken, 'u', require_remote=True)
    db.start_document_job('u', 'c', doc, source_digest=row['originalDigest'], force_guide=True)
    assert pipeline(library, Processor()).run(doc)
    restored = db.get_document(doc)
    assert restored['sourceRevision'] == revision
    assert restored['sourceVersions'][revision][artifact] != broken
    assert library.load_units('u', 'c', [ref]) == before
    assert library.render_reference('u', 'c', ref)


def test_stale_restoration_cannot_publish_or_overwrite_successor(library, monkeypatch):
    doc = queued(library)
    assert pipeline(library, Processor()).run(doc)
    db = library.database
    row = db.get_document(doc)
    old_version = deepcopy(row['sourceVersions'][row['sourceRevision']])
    db.delete_file_from_storage(old_version['manifestPath'], 'u')
    db.start_document_job('u', 'c', doc, source_digest=row['originalDigest'], force_guide=True)
    upload = db.upload_file_to_storage
    def supersede(raw, path, user_id=None, **kwargs):
        result = upload(raw, path, user_id, **kwargs)
        if path.endswith('manifest.json'):
            db.start_document_job('u', 'c', doc, source_digest=row['originalDigest'], force_guide=True)
        return result
    monkeypatch.setattr(db, 'upload_file_to_storage', supersede)
    assert pipeline(library, Processor()).run(doc) is False
    current = db.get_document(doc)
    assert current['processingJob']['stage'] == 'queued'
    assert current['sourceVersions'][row['sourceRevision']] == old_version

def test_restoration_ambiguous_commit_keeps_adopted_assets(library, monkeypatch):
    doc = queued(library)
    assert pipeline(library, Processor()).run(doc)
    db = library.database
    row = db.get_document(doc)
    revision = row['sourceRevision']
    old = row['sourceVersions'][revision]['originalPath']
    db.delete_file_from_storage(old, 'u')
    db.start_document_job('u', 'c', doc, source_digest=row['originalDigest'], force_guide=True)
    publish = db.publish_document_source
    def unknown(*args, **kwargs):
        receipt = publish(*args, **kwargs)
        assert receipt is not None
        raise RuntimeError('response lost after commit')
    monkeypatch.setattr(db, 'publish_document_source', unknown)
    assert pipeline(library, Processor()).run(doc) is False
    restored = db.get_document(doc)
    assert restored['sourceVersions'][revision]['originalPath'] != old
    ref = {'documentId': doc, 'sourceRevision': revision, 'unitId': 'p0001'}
    assert library.load_units('u', 'c', [ref])[0]['text'].startswith('Complete lecture')
    assert library.render_reference('u', 'c', ref)
