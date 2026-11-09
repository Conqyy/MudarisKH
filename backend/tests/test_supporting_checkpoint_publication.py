"""Checkpoint adoption publishes matching progress without a second transaction."""
from copy import deepcopy

import pytest

from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_supporting_job_storage import repository, identity, queue_claim
from tests.test_supporting_storage import library
from src.supporting.workflows import SupportingWorkflow


def test_progress_and_recovery_pointer_are_visible_when_checkpoint_is_adopted(library, monkeypatch):
    repo = library.repository
    _, claim, _ = queue_claim(repo)
    original_publish = repo.publish
    original_checkpoint = repo.checkpoint
    publications = []

    def checkpoint(*args, **kwargs):
        assert not publications, 'Checkpoint adoption must not require a later job update'
        return original_checkpoint(*args, **kwargs)

    def publish(*args, **kwargs):
        result = original_publish(*args, **kwargs)
        if kwargs.get('checkpoint_version') and result:
            job = repo.get_owned(identity())['processingJob']
            # A crash immediately after publication must retain progress and its
            # exact extraction pointer together, without a later transaction.
            assert job['progress'] == {'completedUnits': 1, 'totalUnits': 3}
            assert job['phase'] == 'reconcile'
            assert job['extractionRevision'] == job['checkpointRevision']
            publications.append(deepcopy(job))
        return result

    monkeypatch.setattr(repo, 'publish', publish)
    monkeypatch.setattr(repo, 'checkpoint', checkpoint)
    workflow = SupportingWorkflow(repo, library, None, None, lambda _: None)
    version = workflow._persist_checkpoint(identity(), claim, 'extracting', {
        'stage': 'reconcile', 'modelCalls': 2,
        'progress': {'completedUnits': 1, 'totalUnits': 3}})
    assert len(publications) == 1
    assert publications[0]['checkpointRevision'] == version['revision']
    assert publications[0]['modelCalls'] == 2
    assert library.load_checkpoint(identity(), version['revision'])['stage'] == 'reconcile'


@pytest.mark.parametrize('change', ['claim', 'source', 'foundation'])
def test_rejected_publication_never_advances_progress_or_recovery_pointer(library, monkeypatch, change):
    repo = library.repository
    _, claim, now = queue_claim(repo)
    original_publish = repo.publish

    def publish(*args, **kwargs):
        if kwargs.get('checkpoint_version'):
            if change == 'claim':
                repo.queue(identity(), input_revision='b' * 64, source_digest='a' * 64,
                           foundation_revision=repo.test_foundation_revision, now_ms=now + 1)
            elif change == 'source':
                repo.database._flat_update('historical_exams', 'source', {'originalDigest': 'c' * 64})
            else:
                repo.database.invalidate_document_foundation('u', 'c')
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(repo, 'publish', publish)
    workflow = SupportingWorkflow(repo, library, None, None, lambda _: None)
    with pytest.raises(ValueError, match='publication was rejected'):
        workflow._persist_checkpoint(identity(), claim, 'extracting', {
            'stage': 'reconcile', 'modelCalls': 2,
            'progress': {'completedUnits': 1, 'totalUnits': 3}})
    current = repo.get_owned(identity())['processingJob']
    assert not {'progress', 'phase', 'checkpointRevision', 'extractionRevision'} & set(current)
    if change != 'claim':
        assert current['modelCalls'] == 2


def test_storage_failure_keeps_spent_calls_without_publishing_progress(library, monkeypatch):
    repo = library.repository
    _, claim, _ = queue_claim(repo)

    def fail(*args, **kwargs):
        raise OSError('checkpoint storage unavailable')

    monkeypatch.setattr(repo.database, 'upload_file_to_storage', fail)
    workflow = SupportingWorkflow(repo, library, None, None, lambda _: None)
    with pytest.raises(OSError, match='checkpoint storage unavailable'):
        workflow._persist_checkpoint(identity(), claim, 'extracting', {
            'stage': 'extract', 'modelCalls': 2,
            'progress': {'completedUnits': 1, 'totalUnits': 3}})
    job = repo.get_owned(identity())['processingJob']
    assert job['modelCalls'] == 2
    assert not {'progress', 'phase', 'checkpointRevision', 'extractionRevision'} & set(job)


@pytest.mark.parametrize('changes', [
    {'phase': 'invented'}, {'progress': {'completedUnits': 4, 'totalUnits': 3}},
    {'modelCalls': 0}, {'stage': 'completed'}, {'extractionRevision': 'b' * 64},
    {'phase': 'reconcile'}, {'progress': {'completedUnits': 1, 'totalUnits': 3}},
])
def test_invalid_publication_metadata_is_rejected_before_reserving_artifacts(library, monkeypatch, changes):
    repo = library.repository
    _, claim, _ = queue_claim(repo)

    def unexpected(*args, **kwargs):
        pytest.fail('Invalid checkpoint metadata reserved artifacts')

    monkeypatch.setattr(repo, 'reserve', unexpected)
    with pytest.raises(ValueError):
        library.save_checkpoint(identity(), claim, {'stage': 'extract', 'modelCalls': 1},
                                publication_changes=changes)
