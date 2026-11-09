"""Unverified extraction stays retryable without entering lecture alignment."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.supporting.contracts import digest
from src.supporting.library import SupportingLibrary
from src.supporting.workflows import SupportingWorkflow


IDENTITY = {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}


def workflow_fixture(monkeypatch, *, allow_terminal=True, extraction_error=None):
    foundation, source_revision = 'f' * 64, 's' * 64
    source_digest = 'a' * 64
    handle = {'id': 'new-job', 'claimToken': 'claim', 'inputRevision': 'i' * 64,
              'sourceDigest': source_digest, 'foundationRevision': foundation}
    manifest = {'identity': deepcopy(IDENTITY), 'sourceRevision': source_revision,
                'originalDigest': source_digest, 'units': [{'unitId': 'p1'}, {'unitId': 'p2'}]}
    prefix = {'0': {'original': 'accepted original prefix'}}
    extracted_state = {'stage': 'reconcile', 'cursor': 1, 'modelCalls': 7,
                       'responses': {'extract': prefix, 'reconcile': prefix},
                       'progress': {'completedUnits': 1, 'totalUnits': 2},
                       'error': extraction_error}
    partial = {'items': [{'id': 'q1', 'sharedContextIds': ['missing-context']}],
               'sharedContexts': [], 'papers': [], 'topics': [],
               'extractionCoverage': {'complete': False, 'unitIds': ['p1', 'p2'],
                   'accountedUnitIds': ['p1'], 'unresolvedUnitIds': ['p2'],
                   'error': extraction_error}}

    class Repository:
        database = SimpleNamespace(get_owned_course=lambda *args: {'title': 'Algorithms'})

        def __init__(self):
            self.row = {'userId': 'u', 'courseId': 'c', 'originalDigest': source_digest,
                'supportingAnalysis': {'version': 1, 'state': 'processing',
                    'sourceRevision': source_revision, 'reportRevision': 'old-report',
                    'analysisId': 'old-job'},
                'processingJob': {**handle, 'stage': 'queued', 'modelCalls': 0,
                                  'modelCallBudget': 10}}
            self.changes = []

        def get_owned(self, identity):
            assert identity == IDENTITY
            return deepcopy(self.row)

        def claim(self, identity, job_id, **kwargs):
            return deepcopy(handle)

        def checkpoint(self, identity, job, *, changes, now_ms):
            assert job == handle
            self.changes.append(deepcopy(changes))
            if changes.get('stage') in ('incomplete', 'failed') and not allow_terminal:
                return False
            self.row['processingJob'].update(deepcopy(changes))
            if changes.get('stage') in ('incomplete', 'failed'):
                self.row['supportingAnalysis']['state'] = changes['stage']
            return True

    class Library:
        def __init__(self):
            self.saved = {}
            self.reports = []

        def load_source(self, *args):
            return deepcopy(manifest)

        def save_checkpoint(self, identity, job, state, *, publication_changes=None, revision_fields=()):
            revision = digest(state)
            self.saved[revision] = deepcopy(state)
            repo.row['processingJob'].update(publication_changes or {}, checkpointRevision=revision,
                **{field: revision for field in revision_fields})
            return {'revision': revision}

        def load_checkpoint(self, identity, revision):
            return deepcopy(self.saved[revision])

        def save_report(self, *args):
            self.reports.append(args)

    resumes, alignments = [], []

    class Extractor:
        def extract(self, manifest, **kwargs):
            resumes.append(deepcopy(kwargs['resume']))
            kwargs['checkpoint'](deepcopy(extracted_state))
            return deepcopy(partial)

    class Aligner:
        def __init__(self, *args):
            alignments.append(True)
            raise KeyError('missing-context')

    monkeypatch.setattr('src.supporting.workflows.SupportingAligner', Aligner)
    repo, library = Repository(), Library()
    reader = SimpleNamespace(scope={'foundationRevision': foundation, 'allowedRefs': ['owned']})
    workflow = SupportingWorkflow(repo, library, Extractor(), None, lambda _: reader)
    return workflow, repo, library, resumes, alignments, extracted_state


@pytest.mark.parametrize('error,expected_message', [
    ('Invalid original inventory: Context-only content cannot become a new fragment',
     'The AI returned an invalid source analysis. Retry analysis.'),
    ('Supporting provider failure (RateLimitError) private provider body',
     'The AI provider has reached its rate or quota limit. Wait for the limit to reset or choose another model, then retry.'),
    (None, 'Some source content could not be checked.'),
])
def test_incomplete_extraction_stops_before_alignment_and_keeps_its_checkpoint(monkeypatch, error, expected_message):
    workflow, repo, library, resumes, alignments, original_state = workflow_fixture(
        monkeypatch, extraction_error=error)
    assert workflow.run(IDENTITY) is True
    assert alignments == []
    assert library.reports == []
    job = repo.row['processingJob']
    assert job['stage'] == repo.row['supportingAnalysis']['state'] == 'incomplete'
    assert job['error'] == expected_message
    assert job['modelCalls'] == 7
    assert job['checkpointRevision'] == job['extractionRevision']
    assert library.saved[job['extractionRevision']] == original_state
    assert 'inventoryRevision' not in job
    assert repo.row['supportingAnalysis']['reportRevision'] == 'old-report'
    assert repo.row['supportingAnalysis']['analysisId'] == 'old-job'
    assert resumes == [None]

    # A retry adopts the same durable extraction checkpoint, not a partial
    # alignment result. No accepted original content was removed or rewritten.
    repo.row['processingJob']['stage'] = 'queued'
    repo.row['processingJob']['modelCalls'] = 0
    assert workflow.run(IDENTITY) is True
    assert resumes[-1] == original_state
    assert alignments == [] and library.reports == []


def test_incomplete_transition_cannot_bypass_a_lost_job_claim(monkeypatch):
    workflow, repo, library, _, alignments, _ = workflow_fixture(monkeypatch, allow_terminal=False)
    assert workflow.run(IDENTITY) is False
    assert any(change.get('stage') == 'incomplete' for change in repo.changes)
    assert alignments == [] and library.reports == []
    assert repo.row['processingJob']['stage'] == 'extracting'


def test_incomplete_retry_shows_its_saved_progress_instead_of_previous_report(monkeypatch):
    row = {'supportingAnalysis': {'version': 1, 'state': 'incomplete', 'sourceRevision': 'source',
                                 'reportRevision': 'old-report', 'analysisId': 'old-job'},
           'processingJob': {'id': 'new-job', 'stage': 'incomplete',
                             'progress': {'completedUnits': 1, 'totalUnits': 3},
                             'error': 'The AI returned an invalid source analysis. Retry analysis.'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda _: row, database=None))

    def no_artifact(*args):
        pytest.fail('An incomplete retry must use its current durable progress')

    for method in ('load_source', 'load_report', 'load_checkpoint'):
        monkeypatch.setattr(library, method, no_artifact)
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == 1
    assert status['progress']['totalUnits'] == 3
    assert status['reportRevision'] == 'old-report'
    assert status['jobId'] == 'new-job'
    assert status['status'] == 'incomplete'


def test_incomplete_current_report_keeps_its_richer_verified_progress(monkeypatch):
    row = {'supportingAnalysis': {'version': 1, 'state': 'incomplete',
                                 'reportRevision': 'current-report', 'analysisId': 'current-job'},
           'processingJob': {'id': 'current-job', 'stage': 'incomplete',
                             'progress': {'completedUnits': 1, 'totalUnits': 3}}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda _: row, database=None))
    monkeypatch.setattr(library, 'load_report', lambda *args: {
        'items': [], 'alignments': [],
        'extractionCoverage': {'complete': False, 'unitIds': ['p1', 'p2', 'p3'],
            'accountedUnitIds': ['p1', 'p2'], 'unresolvedUnitIds': ['p3']},
        'alignmentCoverage': {},
    })
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == 2
    assert status['progress']['totalUnits'] == 3
    assert status['coverage']['extraction']['complete'] is False
