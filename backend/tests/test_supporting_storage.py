"""Private immutable source/report files with exact ownership and adoption."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time
import pytest

from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_supporting_job_storage import repository, identity, queue_claim
from tests.supporting_fixtures import supporting_manifest, alignment_report
from src.supporting.contracts import supporting_revision, aggregate_item_alignment, MAX_REPORT_CHUNK_BYTES
from src.supporting.library import SupportingLibrary


@pytest.fixture
def library(repository, monkeypatch, tmp_path):
    monkeypatch.setattr('src.database.firebase_client.UPLOADS_ROOT', tmp_path / 'uploads')
    if not repository.database.use_local:
        from firebase_admin import storage
        objects = {}
        class Blob:
            def __init__(self, name): self.name = name
            def exists(self): return self.name in objects
            def upload_from_string(self, data): objects[self.name] = bytes(data)
            def download_to_filename(self, path): Path(path).write_bytes(objects[self.name])
            def delete(self): objects.pop(self.name, None)
        class Bucket:
            def blob(self, name): return Blob(name)
            def list_blobs(self, prefix): return [Blob(name) for name in list(objects) if name.startswith(prefix)]
        monkeypatch.setattr(storage, 'bucket', lambda: Bucket())
    for path, original in repository.test_lecture['_artifactFiles'].items():
        repository.database.upload_file_to_storage(original.read_bytes(), path, 'u')
    return SupportingLibrary(repository)


def prepare(library):
    raw = b'Original file bytes for fixture'
    manifest = supporting_manifest()
    manifest['identity'] = identity()
    manifest['originalDigest'] = sha256(raw).hexdigest()
    manifest['sourceRevision'] = supporting_revision(manifest['originalDigest'], manifest['units'])
    _, claim, now = queue_claim(library.repository, original=manifest['originalDigest'])
    library.save_source(identity(), claim, raw, manifest)
    return manifest, claim


def report_for(library, manifest, count=1, size=0):
    report = alignment_report()
    lecture = library.repository.test_lecture
    scope = {'documents': [{key: lecture[key] for key in ('id', 'title', 'sourceRevision', 'guideRevision', 'guide')}],
             'manifests': [lecture['_sourceManifest']],
             'allowedRefs': [{'documentId': lecture['id'], 'sourceRevision': lecture['sourceRevision'], 'unitId': u['unitId']}
                             for u in lecture['_sourceManifest']['units']], 'scopeRevision': 'b'*64}
    report['scopeSnapshot'] = scope
    report['sourceRevision'] = manifest['sourceRevision']
    original_item, original_alignment = report['items'][0], report['alignments'][0]
    finding = original_alignment['requirements'][0]
    finding['lectureAnchorRefs'] = [scope['allowedRefs'][0]]
    finding['lectureSupportProofs'] = [{'type': 'text_span', 'ref': scope['allowedRefs'][0],
        'field': 'text', 'start': 0, 'end': 7, 'quote': 'Lecture'}]
    finding['reviewCoverage'].update(allowedRefs=deepcopy(scope['allowedRefs']), reviewedRefs=deepcopy(scope['allowedRefs']))
    report['items'], report['alignments'] = [], []
    for n in range(count):
        item, finding = deepcopy(original_item), deepcopy(original_alignment['requirements'][0])
        item['id'], item['requirements'][0]['id'], finding['requirementId'] = f'q{n}', f'r{n}', f'r{n}'
        item['text'] += 'x'*size
        refs = [item['supportingSourceRefs'][0], item['requirements'][0]['supportingSourceRefs'][0], finding['supportingSourceProofs'][0]['ref']]
        for ref in refs: ref.update(materialId='source', sourceRevision=manifest['sourceRevision'])
        report['items'].append(item)
        report['alignments'].append(aggregate_item_alignment([finding], item_id=item['id']))
    ids = [i['id'] for i in report['items']]
    report['alignmentCoverage'].update(itemIds=ids, checkedItemIds=list(ids))
    report['papers'][0].update(questionIds=ids, totalQuestions=count)
    return report


def test_private_source_roundtrip_rejects_foreign_and_stale_references(library):
    manifest, claim = prepare(library)
    assert library.load_source(identity()) == manifest
    ref = {'kind': 'historical_exam', 'materialId': 'source', 'sourceRevision': manifest['sourceRevision'], 'unitId': 'u1'}
    assert library.read_refs(identity(), [ref])[0]['text'] == 'Explain trees'
    for ref in ({**ref, 'sourceRevision': 'c'*64}, {**ref, 'materialId': 'source2'}, {**ref, 'unitId': 'missing'}):
        with pytest.raises(ValueError): library.read_refs(identity(), [ref])
    with pytest.raises(ValueError): library.load_source({**identity(), 'userId': 'foreign'})
    row = library.repository.get_owned(identity())
    assert 'units' not in row and 'sourceVersions' not in row


def test_large_report_is_private_chunked_and_paginates_without_overflow(library):
    manifest, claim = prepare(library)
    report = report_for(library, manifest, count=140, size=6000)
    version = library.save_report(identity(), claim, report)
    assert library.load_report(identity()) == report
    assert len(version['chunks']) > 1
    for chunk in version['chunks']:
        body = library.repository.database.download_file_from_storage(chunk['path'], 'u').read_bytes()
        assert len(body) <= MAX_REPORT_CHUNK_BYTES
    row = library.repository.get_owned(identity())
    assert len(json.dumps(row)) < 10000
    page = library.report_page(identity(), report_revision=version['revision'], offset=50, limit=50)
    assert [item['id'] for item in page['items']] == [f'q{n}' for n in range(50, 100)]
    assert page['total'] == 140


def test_single_oversized_report_item_fails_without_publication(library):
    manifest, claim = prepare(library)
    with pytest.raises(ValueError, match='(?i)split|size|large'):
        library.save_report(identity(), claim, report_for(library, manifest, size=MAX_REPORT_CHUNK_BYTES))
    assert not library.repository.get_owned(identity()).get('supportingAnalysis', {}).get('reportRevision')


def test_lost_publish_response_keeps_adopted_files(library, monkeypatch):
    manifest, claim = prepare(library)
    original = library.repository.publish
    def lost_response(*args, **kwargs):
        assert original(*args, **kwargs)
        raise ConnectionError('reply lost after commit')
    monkeypatch.setattr(library.repository, 'publish', lost_response)
    report = report_for(library, manifest)
    with pytest.raises(ConnectionError): library.save_report(identity(), claim, report)
    assert library.load_report(identity()) == report


def test_completed_snapshot_rejects_identical_analysis_retry(library):
    manifest, claim = prepare(library)
    version = library.save_report(identity(), claim, report_for(library, manifest))
    snapshot = {'version': 1, 'materials': [{'identity': identity(), 'sourceRevision': manifest['sourceRevision'],
        'reportRevision': version['revision'], 'analysisId': claim['id'], 'scopedReportRevision': version['revision']}]}
    library.repository.assert_snapshot(snapshot)
    library.repository.queue(identity(), input_revision='b'*64, source_digest=manifest['originalDigest'],
        foundation_revision=library.repository.test_foundation_revision, now_ms=int(time.time()*1000))
    with pytest.raises(ValueError): library.repository.assert_snapshot(snapshot)


def test_deletion_cleans_versions_and_fences_old_claim(library):
    manifest, claim = prepare(library)
    library.save_report(identity(), claim, report_for(library, manifest))
    result = library.repository.delete(identity())
    assert result['materials'] == 1
    with pytest.raises(ValueError): library.load_source(identity())
    assert not library.repository.checkpoint(identity(), claim, changes={}, now_ms=int(time.time()*1000))
    with pytest.raises(ValueError): queue_claim(library.repository)


def test_hashed_artifact_prefix_cannot_match_adjacent_material(library):
    from src.utils.storage_paths import build_supporting_artifact_path
    manifest, claim = prepare(library)
    foreign = build_supporting_artifact_path({**identity(), 'materialId': 'source2'}, claim['id'], claim['claimToken'], 'a'*32, 'manifest.json')
    with pytest.raises(ValueError): library.repository.reserve(identity(), claim, paths=[foreign], now_ms=int(time.time()*1000))


def test_scoped_report_does_not_overwrite_current_report_and_retry_fences_it(library):
    manifest, claim = prepare(library)
    original = report_for(library, manifest)
    version = library.save_report(identity(), claim, original)
    expected = deepcopy(library.repository.get_owned(identity())['supportingAnalysis'])
    scoped = deepcopy(original)
    scoped['scopeSnapshot']['scopeRevision'] = 'd'*64
    for alignment in scoped['alignments']:
        for finding in alignment['requirements']: finding['reviewCoverage']['scopeRevision'] = 'd'*64
    cached = library.save_scoped_report(identity(), expected, scoped)
    assert cached['revision'] != version['revision']
    assert library.repository.get_owned(identity())['supportingAnalysis'] == expected
    assert library.load_report(identity()) == original
    library.repository.queue(identity(), input_revision='b'*64, source_digest=manifest['originalDigest'],
        foundation_revision=library.repository.test_foundation_revision, now_ms=int(time.time()*1000))
    with pytest.raises(ValueError): library.save_scoped_report(identity(), expected, scoped)


def test_captured_recording_digest_binds_only_after_verified_preserved_bytes(library):
    from src.utils.storage_paths import build_supporting_artifact_path
    ident = identity('audio')
    _, claim, now = queue_claim(library.repository, material=ident, original=None)
    path = build_supporting_artifact_path(ident, claim['id'], claim['claimToken'], 'a'*32, 'original.bin')
    library.repository.reserve(ident, claim, paths=[path], now_ms=now)
    raw = b'Captured immutable recording'
    library.database.upload_file_to_storage(raw, path, 'u')
    with pytest.raises(ValueError): library.repository.bind_capture(ident, claim, path=path, source_digest='a'*64, now_ms=now)
    bound = library.repository.bind_capture(ident, claim, path=path, source_digest=sha256(raw).hexdigest(), now_ms=now)
    assert bound['sourceDigest'] == sha256(raw).hexdigest()
    row = library.repository.get_owned(ident)
    assert row['storagePath'] == path
    assert row['originalDigest'] == bound['sourceDigest']
    with pytest.raises(ValueError): library.repository.bind_capture(ident, claim, path=path, source_digest=sha256(raw).hexdigest(), now_ms=now)


@pytest.mark.parametrize('mode', ['material', 'course', 'account', 'missing_parent'])
def test_all_cleanup_paths_remove_new_version_objects(library, mode):
    manifest, claim = prepare(library)
    source = library.repository.get_version(identity(), 'source', manifest['sourceRevision'])
    report = library.save_report(identity(), claim, report_for(library, manifest))
    paths = source['supportingArtifactPaths'] + report['supportingArtifactPaths']
    db = library.database
    if mode == 'material': db.delete_historical_exam('source')
    if mode == 'course': db.delete_course_data('u', 'c')
    if mode == 'account':
        db.begin_account_deletion('u')
        db.delete_user_data('u')
    if mode == 'missing_parent':
        db._flat_delete('historical_exams', 'source')
        library.repository.delete(identity())
    for path in paths:
        from src.database import firebase_client
        from src.utils.storage_paths import resolve_storage_path
        assert not resolve_storage_path(path, 'u', root=firebase_client.UPLOADS_ROOT).exists()
    remaining = db._flat_query_by_course('supporting_material_versions', 'c', 'u')
    assert all(r.get('versionKind') == 'tombstone' for r in remaining)


def test_scoped_publish_stops_after_foundation_changes(library):
    manifest, claim = prepare(library)
    report = report_for(library, manifest)
    library.save_report(identity(), claim, report)
    expected = deepcopy(library.repository.get_owned(identity())['supportingAnalysis'])
    library.database.invalidate_document_foundation('u', 'c')
    with pytest.raises(ValueError): library.save_scoped_report(identity(), expected, report)


def test_snapshot_rejects_course_deletion_before_rows_are_removed(library):
    manifest, claim = prepare(library)
    version = library.save_report(identity(), claim, report_for(library, manifest))
    snapshot = {'version': 1, 'materials': [{'identity': identity(), 'sourceRevision': manifest['sourceRevision'],
        'reportRevision': version['revision'], 'analysisId': claim['id'], 'scopedReportRevision': version['revision']}]}
    library.database._begin_course_deletion('u', 'c')
    with pytest.raises(ValueError): library.repository.assert_snapshot(snapshot)


def test_incomplete_original_cannot_publish_completed_report(library):
    from src.supporting.contracts import source_coverage
    raw = b'Partly readable original'
    manifest = supporting_manifest()
    manifest['identity'] = identity()
    manifest['units'][0]['disposition'] = 'uncertain'
    manifest['coverage'] = source_coverage(manifest['units'])
    manifest['originalDigest'] = sha256(raw).hexdigest()
    manifest['sourceRevision'] = supporting_revision(manifest['originalDigest'], manifest['units'])
    _, claim, _ = queue_claim(library.repository, original=manifest['originalDigest'])
    library.save_source(identity(), claim, raw, manifest)
    with pytest.raises(ValueError): library.save_report(identity(), claim, report_for(library, manifest))


def test_private_checkpoint_survives_explicit_retry_without_reusing_call_budget(library):
    manifest, claim = prepare(library)
    state = {'batchIndex': 2, 'items': [{'text': 'Faithful extracted question'}]}
    saved = library.save_checkpoint(identity(), claim, state)
    assert library.load_checkpoint(identity(), saved['revision']) == state
    library.repository.checkpoint(identity(), claim, changes={'modelCalls': 12}, now_ms=int(time.time()*1000))
    retry = library.repository.queue(identity(), input_revision='b'*64, source_digest=manifest['originalDigest'],
        foundation_revision=library.repository.test_foundation_revision, now_ms=int(time.time()*1000))
    row = library.repository.get_owned(identity())
    assert row['processingJob']['checkpointRevision'] == saved['revision']
    assert row['processingJob']['modelCalls'] == 0
    assert retry['id'] != claim['id']
    with pytest.raises(ValueError): library.save_checkpoint(identity(), claim, {'batchIndex': 99})


@pytest.mark.parametrize('damage', ['foreign_lecture', 'invented_lecture_quote'])
def test_report_publication_resolves_lecture_proofs_against_owned_originals(library, damage):
    manifest, claim = prepare(library)
    report = report_for(library, manifest)
    if damage == 'invented_lecture_quote':
        report['alignments'][0]['requirements'][0]['lectureSupportProofs'][0]['quote'] = 'INVENT!'
    else:
        def change(value):
            if isinstance(value, dict):
                if 'documentId' in value: value['documentId'] = 'foreign'
                for child in value.values(): change(child)
            elif isinstance(value, list):
                for child in value: change(child)
        change(report)
    with pytest.raises(ValueError): library.save_report(identity(), claim, report)

