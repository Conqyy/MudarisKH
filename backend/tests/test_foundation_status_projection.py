"""Refreshes read published metadata; actions still verify exact source bytes."""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from tests.foundation_fixtures import install_source_artifacts, lecture_document
from src.utils.course_foundation import foundation_material_revision
from src.utils.source_contracts import guide_digest


@pytest.fixture
def saved_foundation(api_module, monkeypatch):
    db = MagicMock()
    documents = [lecture_document()]
    install_source_artifacts(db, documents)
    db.get_owned_course.return_value = {'id': 'course', 'userId': 'owner'}
    db.get_document_foundation.return_value = {
        'userId': 'owner', 'courseId': 'course',
        'revision': foundation_material_revision(documents),
    }
    monkeypatch.setattr(api_module, 'db_client', db)
    return api_module, db, documents


def test_confirmed_refresh_never_loads_stored_artifacts(saved_foundation):
    api, db, documents = saved_foundation
    # These are test-only hydration fields, never persisted source proof.
    documents[0].pop('_sourceManifest')
    documents[0].pop('_sourceArtifactsValid')
    db.download_file_from_storage.side_effect = AssertionError('Status must not read source bytes')
    result = api.get_course_foundation('course', uid='owner')
    assert result['ready'] is True
    assert result['completedCount'] == 1
    db.download_file_from_storage.assert_not_called()
    db.get_owned_document.assert_not_called()
    db.get_owned_course.assert_called_once_with('owner', 'course')
    db.get_course_documents.assert_called_once_with('course', user_id='owner')
    db.get_document_foundation.assert_called_once_with('owner', 'course')
    assert set(result) == {'ready', 'state', 'revision', 'documentCount', 'completedCount',
                           'pendingCount', 'failedCount', 'message', 'failedDocumentIds', 'failedStages'}


@pytest.mark.parametrize('field,value', [
    ('sourceVersions', {}), ('sourceVersions', []),
    ('originalDigest', 'not-a-digest'), ('sourceRevision', 'b' * 64),
    ('guideRevision', 'b' * 64), ('guide', None),
    ('unitCount', 2), ('processingJob', {'id': 'a' * 32, 'stage': 'guiding'}),
    ('storagePath', 'documents/someone-else/course/original.docx'),
])
def test_completed_flags_do_not_override_invalid_current_metadata(saved_foundation, field, value):
    api, db, documents = saved_foundation
    documents[0][field] = value
    # Even a matching confirmation cannot rescue malformed published data.
    db.get_document_foundation.return_value['revision'] = foundation_material_revision(documents)
    result = api.get_course_foundation('course', uid='owner')
    assert result['ready'] is False
    assert result['failedDocumentIds'] == ['doc']
    db.download_file_from_storage.assert_not_called()


@pytest.mark.parametrize('field,value', [
    ('coverageComplete', False), ('coverageComplete', 1),
    ('originalDigest', 'b' * 64), ('manifestDigest', 'invalid'),
    ('manifestPath', 'documents/owner/other/source.json'),
    ('originalPath', 'documents/owner/course/other.docx'),
    ('fileType', 'pdf'), ('unitCount', True), ('unitCount', 0),
])
def test_invalid_source_descriptors_fail_status_without_artifact_reads(saved_foundation, field, value):
    api, db, documents = saved_foundation
    row = documents[0]
    row['sourceVersions'][row['sourceRevision']][field] = value
    result = api.get_course_foundation('course', uid='owner')
    assert result['state'] == 'failed'
    assert result['failedStages']['doc']['stage'] == 'preparation'
    db.download_file_from_storage.assert_not_called()


@pytest.mark.parametrize('case', [
    'missing-coverage', 'unresolved', 'missing-unit', 'duplicate-unit', 'empty-readable',
    'overlap', 'incomplete', 'wrong-revision', 'invented-reference', 'missing-sections',
    'empty-section-label', 'no-academic-content',
])
def test_guide_hash_alone_cannot_make_invalid_coverage_ready(saved_foundation, case):
    api, db, documents = saved_foundation
    guide = documents[0]['guide']
    coverage = guide['unitCoverage']
    if case == 'missing-coverage':
        guide.pop('unitCoverage')
    elif case == 'unresolved':
        coverage['unresolvedUnitIds'] = list(coverage['unitIds'])
    elif case == 'missing-unit':
        coverage['unitIds'] = []
    elif case == 'duplicate-unit':
        coverage['unitIds'] *= 2
    elif case == 'empty-readable':
        coverage['readableUnitIds'] = []
    elif case == 'overlap':
        coverage['blankUnitIds'] = list(coverage['readableUnitIds'])
    elif case == 'incomplete':
        coverage['complete'] = False
    elif case == 'wrong-revision':
        guide['sourceRevision'] = 'b' * 64
    elif case == 'invented-reference':
        guide['sections'][0]['unitIds'] = ['b9999']
    elif case == 'missing-sections':
        guide.pop('sections')
    elif case == 'empty-section-label':
        guide['sections'][0]['label'] = ''
    else:
        guide['sections'] = guide['concepts'] = []
    documents[0]['guideRevision'] = guide_digest(guide)
    db.get_document_foundation.return_value['revision'] = foundation_material_revision(documents)
    result = api.get_course_foundation('course', uid='owner')
    assert result['state'] == 'failed'
    assert result['failedStages']['doc']['stage'] == 'guide'
    db.download_file_from_storage.assert_not_called()


@pytest.mark.parametrize('change', ['retry', 'upload', 'delete', 'confirmation'])
def test_refresh_detects_revision_changes_without_a_process_cache(saved_foundation, change):
    api, db, documents = saved_foundation
    assert api.get_course_foundation('course', uid='owner')['ready'] is True
    if change == 'retry':
        documents[0]['processingJob']['id'] = 'd' * 32
    elif change == 'upload':
        documents.append(lecture_document('new'))
    elif change == 'delete':
        documents.clear()
    else:
        db.get_document_foundation.return_value = {}
    assert api.get_course_foundation('course', uid='owner')['ready'] is False


def test_refresh_always_rechecks_course_ownership(saved_foundation):
    api, db, _ = saved_foundation
    assert api.get_course_foundation('course', uid='owner')['ready'] is True
    db.get_owned_course.return_value = {'id': 'course', 'userId': 'other'}
    with pytest.raises(api.HTTPException) as error:
        api.get_course_foundation('course', uid='owner')
    assert error.value.status_code == 404


@pytest.mark.parametrize('path_kind', ['upload', 'original', 'manifest'])
def test_authoritative_guard_rejects_corrupt_bytes_after_ready_snapshot(saved_foundation, path_kind):
    api, db, documents = saved_foundation
    row = documents[0]
    descriptor = row['sourceVersions'][row['sourceRevision']]
    path = row['storagePath'] if path_kind == 'upload' else descriptor[path_kind + 'Path']
    row['_artifactFiles'][path].write_bytes(b'corrupt stored source')
    assert api.get_course_foundation('course', uid='owner')['ready'] is True
    with pytest.raises(api.HTTPException) as error:
        api._require_document_foundation('course', 'owner')
    assert error.value.status_code == 409
    with pytest.raises(api.HTTPException) as error:
        api.confirm_course_foundation('course', api.FoundationConfirmRequest(
            revision=db.get_document_foundation.return_value['revision']), uid='owner')
    assert error.value.status_code == 409
    db.confirm_document_foundation.assert_not_called()


def test_status_projection_does_not_modify_published_metadata(saved_foundation):
    api, _, documents = saved_foundation
    before = deepcopy(documents)
    api.get_course_foundation('course', uid='owner')
    assert documents == before
