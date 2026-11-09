from copy import deepcopy

import pytest

from src.supporting.workflows import SupportingWorkflow
from src.supporting.repository import SupportingRepository


def test_progress_is_published_only_after_durable_checkpoint():
    events = []

    class Repository:
        def checkpoint(self, identity, job, *, changes, now_ms):
            events.append(deepcopy(changes))
            return True

    class Library:
        def save_checkpoint(self, identity, job, state, *, publication_changes, revision_fields):
            events.append({'saved': deepcopy(state), 'published': deepcopy(publication_changes),
                           'revision_fields': revision_fields})
            return {'revision': 'a' * 64}

    progress = {'completedUnits': 1, 'totalUnits': 3}
    workflow = SupportingWorkflow(Repository(), Library(), None, None, lambda _: None)
    workflow._persist_checkpoint({}, {}, 'extracting', {
        'stage': 'reconcile', 'modelCalls': 4, 'progress': progress})
    assert 'progress' not in events[0]
    assert events[1]['saved']['progress'] == events[1]['published']['progress'] == progress
    assert events[1]['published']['phase'] == 'reconcile'
    assert events[1]['revision_fields'] == ('extractionRevision',)
    assert len(events) == 2


@pytest.mark.parametrize('progress', [
    {'completedUnits': True, 'totalUnits': 3},
    {'completedUnits': -1, 'totalUnits': 3},
    {'completedUnits': 4, 'totalUnits': 3},
    {'completedUnits': 1, 'totalUnits': None},
    {'completedUnits': 1, 'totalUnits': 3, 'privateData': 'not allowed'},
])
def test_repository_rejects_invalid_progress_before_any_database_access(progress):
    with pytest.raises(ValueError, match='progress'):
        SupportingRepository(None).checkpoint({}, {}, changes={'progress': progress}, now_ms=1)


def test_repository_accepts_bounded_progress_before_claim_check(monkeypatch):
    repository = SupportingRepository(None)
    observed = []
    monkeypatch.setattr(repository, '_atomic', lambda *args, **kwargs: observed.append(True) or False)
    assert repository.checkpoint({}, {'foundationRevision': 'a' * 64},
        changes={'progress': {'completedUnits': 1, 'totalUnits': 3}, 'phase': 'reconcile'}, now_ms=1) is False
    assert observed == [True]
