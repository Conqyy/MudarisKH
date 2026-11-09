"""Supporting preparation reuses verified sources inside one request only."""
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.services.document_library import DocumentLibrary
from src.utils.source_context import resolve_source_scope
from tests.foundation_fixtures import confirm_lecture_foundation, lecture_document


@pytest.fixture
def supporting_foundation(api_module, monkeypatch):
    db = MagicMock()
    documents = [lecture_document('first'), lecture_document('second', topic='Derivatives')]
    confirm_lecture_foundation(db, documents)
    monkeypatch.setattr(api_module, 'db_client', db)
    monkeypatch.setattr(api_module, 'doc_processor', SimpleNamespace(client=object(), model_id='test-model'))
    return api_module, db, documents


def identity():
    return {'userId': 'owner', 'courseId': 'course', 'kind': 'tutorial', 'materialId': 'tutorial'}


def test_supporting_scope_matches_full_resolver_with_only_one_artifact_validation(supporting_foundation):
    api, db, documents = supporting_foundation
    expected = resolve_source_scope(db, DocumentLibrary(db), 'owner', 'course', None)
    db.download_file_from_storage.reset_mock()
    source = api._supporting_reader(identity())
    assert source.scope == expected
    reads = Counter(call.args[0] for call in db.download_file_from_storage.call_args_list)
    paths = {path for document in documents for path in document['_artifactFiles']}
    assert dict(reads) == {path: 1 for path in paths}
    assert source.client is api.doc_processor.client
    assert source.model == 'test-model'


def test_reused_scope_is_detached_from_persisted_documents(supporting_foundation):
    api, _, documents = supporting_foundation
    before = deepcopy(documents)
    source = api._supporting_reader(identity())
    source.scope['documents'][0]['guide']['sections'][0]['label'] = 'Modified consumer guide'
    source.scope['manifests'][0]['units'][0]['text'] = 'Modified consumer source'
    source.scope['allowedRefs'][0]['unitId'] = 'b9999'
    assert documents == before


@pytest.mark.parametrize('damage', ['upload', 'original', 'manifest'])
def test_supporting_scope_still_rejects_corrupt_originals_before_reuse(supporting_foundation, damage):
    api, _, documents = supporting_foundation
    row = documents[0]
    version = row['sourceVersions'][row['sourceRevision']]
    path = row['storagePath'] if damage == 'upload' else version[damage + 'Path']
    row['_artifactFiles'][path].write_bytes(b'corrupt')
    with pytest.raises(api.HTTPException) as error:
        api._supporting_reader(identity())
    assert error.value.status_code == 409


@pytest.mark.parametrize('change', ['delete', 'retry', 'upload', 'unconfirm', 'owner', 'guide'])
def test_final_metadata_fence_rejects_changes_during_artifact_validation(supporting_foundation, monkeypatch, change):
    api, db, documents = supporting_foundation
    original = api._require_document_foundation

    def changed_after_validation(*args, **kwargs):
        foundation = original(*args, **kwargs)
        if change == 'delete':
            documents.pop(0)
        elif change == 'retry':
            documents[0]['processingJob']['id'] = 'd' * 32
        elif change == 'upload':
            documents.append(lecture_document('new'))
        elif change == 'unconfirm':
            db.get_document_foundation.return_value = {}
        elif change == 'owner':
            db.get_owned_course.return_value = {'id': 'course', 'userId': 'someone-else'}
        else:
            documents[0]['guide'] = {}
        return foundation

    monkeypatch.setattr(api, '_require_document_foundation', changed_after_validation)
    with pytest.raises((api.HTTPException, ValueError)):
        api._supporting_reader(identity())


def test_separate_supporting_requests_revalidate_source_bytes(supporting_foundation):
    api, db, _ = supporting_foundation
    api._supporting_reader(identity())
    db.download_file_from_storage.reset_mock()
    api._supporting_reader(identity())
    assert db.download_file_from_storage.call_count == 6
