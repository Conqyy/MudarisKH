from types import SimpleNamespace

import pytest

from src.supporting.library import SupportingLibrary


IDENTITY = {'userId': 'owner', 'courseId': 'course', 'kind': 'tutorial', 'materialId': 'sheet'}


@pytest.mark.parametrize('error,reasons,message', [
    ('Invalid original inventory: AI response is missing or truncated', {}, 'The AI response was incomplete. Retry analysis to read the remaining source content.'),
    (None, {'page': ['Independent original reconciliation disagrees']}, 'The independent source checks disagreed. Retry analysis to recheck the original file.'),
    ('Invalid original inventory: invalid JSON with private/path', {}, 'The AI returned an invalid source analysis. Retry analysis.'),
    ('Successful model-call budget exhausted; retry with a fresh budget or split the source', {}, 'Analysis reached its processing limit. Retry analysis to continue.'),
    (None, {}, 'Some source content could not be verified. Open the report for details, then retry analysis.'),
])
def test_incomplete_analysis_exposes_a_safe_actionable_reason(monkeypatch, error, reasons, message):
    row = {'supportingAnalysis': {'version': 1, 'state': 'incomplete', 'reportRevision': 'report'},
           'processingJob': {'stage': 'incomplete'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    monkeypatch.setattr(library, 'load_report', lambda *args: {
        'items': [], 'alignments': [],
        'extractionCoverage': {'complete': False, 'unitIds': ['page'], 'accountedUnitIds': ['page'],
                               'unresolvedUnitIds': ['page'], 'error': error, 'reasons': reasons},
        'alignmentCoverage': {'complete': True, 'topicIds': [], 'unresolvedTopicIds': []},
    })
    status = library.public_status(IDENTITY)
    assert status['errorMessage'] == message
    assert status['progress']['completedUnits'] == 0
    assert status['progress']['totalUnits'] == 1
    assert 'private/path' not in status['errorMessage']


def test_existing_failure_message_is_not_replaced():
    row = {'supportingAnalysis': {'version': 1, 'state': 'failed'},
           'processingJob': {'stage': 'failed', 'error': 'Lecture foundation changed; confirm documents and retry'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    assert library.public_status(IDENTITY)['errorMessage'] == row['processingJob']['error']


@pytest.mark.parametrize('marker,message', [
    ('Supporting provider failure (NotFoundError); retry with a compatible model', 'The selected AI model is unavailable or lacks required analysis features. Choose a compatible model, then retry analysis.'),
    ('Reconciliation provider failure (BadRequestError)', 'The AI provider rejected this analysis request. Check that the selected model supports images and structured responses, then retry.'),
    ('Supporting provider failure (RateLimitError)', 'The AI provider has reached its rate or quota limit. Wait for the limit to reset or choose another model, then retry.'),
    ('Supporting provider failure (AuthenticationError)', 'The AI provider rejected the API credentials. Check the backend API key, then retry analysis.'),
    ('PermissionDeniedError', 'The AI provider rejected the API credentials. Check the backend API key, then retry analysis.'),
    ('Supporting provider failure (APITimeoutError)', 'The AI provider did not respond in time. Retry analysis; if this continues, choose another model.'),
    ('Supporting provider failure (APIConnectionError)', 'The AI provider could not be reached. Retry analysis when the connection is available.'),
])
@pytest.mark.parametrize('origin', ['extraction', 'job'])
def test_provider_failure_markers_produce_actionable_messages_without_provider_data(monkeypatch, marker, message, origin):
    private = ' provider body: secret-key /private/user/document'
    stored_error = marker + private if origin == 'extraction' or '(' in marker else marker
    row = {'supportingAnalysis': {'version': 1, 'state': 'incomplete', 'reportRevision': 'report'},
           'processingJob': {'stage': 'incomplete', 'error': stored_error if origin == 'job' else None}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    monkeypatch.setattr(library, 'load_report', lambda *args: {
        'items': [], 'alignments': [],
        'extractionCoverage': {'complete': False, 'unitIds': ['page'], 'error': stored_error if origin == 'extraction' else None},
        'alignmentCoverage': {},
    })
    status = library.public_status(IDENTITY)
    assert status['errorMessage'] == message
    assert 'secret-key' not in str(status)
    assert '/private/' not in str(status)


def test_prepared_source_pages_are_not_reported_as_analyzed(monkeypatch):
    row = {'supportingAnalysis': {'version': 1, 'state': 'processing', 'sourceRevision': 'source'},
           'processingJob': {'stage': 'extracting'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    monkeypatch.setattr(library, 'load_source', lambda *args: {
        'units': [{}, {}, {}], 'coverage': {'complete': True, 'unresolvedUnitIds': []},
    })
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == 0
    assert status['progress']['totalUnits'] == 3


def test_live_status_uses_small_persisted_progress_without_loading_artifacts(monkeypatch):
    row = {'supportingAnalysis': {'version': 1, 'state': 'processing', 'sourceRevision': 'source',
                                 'reportRevision': 'previous-report'},
           'processingJob': {'stage': 'extracting', 'phase': 'reconcile',
                             'progress': {'completedUnits': 1, 'totalUnits': 3}}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    def no_artifact_read(*args):
        pytest.fail('Active status polls must use persisted progress, not load source/report/checkpoint artifacts')
    for method in ('load_source', 'load_report', 'load_checkpoint'):
        monkeypatch.setattr(library, method, no_artifact_read)
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == 1
    assert status['progress']['totalUnits'] == 3
    assert status['stage'] == 'reconciling'


@pytest.mark.parametrize('report_owner', [None, 'previous-job', 'current-job'])
def test_failed_job_keeps_its_durable_progress_and_previous_report_link(monkeypatch, report_owner):
    analysis = {'version': 1, 'state': 'failed', 'sourceRevision': 'source'}
    if report_owner:
        analysis.update(reportRevision='saved-report', analysisId=report_owner)
    row = {'supportingAnalysis': analysis,
           'processingJob': {'id': 'current-job', 'stage': 'failed',
                             'progress': {'completedUnits': 1, 'totalUnits': 3},
                             'error': 'Analysis interrupted'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))

    def no_artifact_read(*args):
        pytest.fail('A failed job must retain its own saved progress without loading an older report')

    for method in ('load_source', 'load_report', 'load_checkpoint'):
        monkeypatch.setattr(library, method, no_artifact_read)
    status = library.public_status(IDENTITY)
    assert status['jobId'] == 'current-job'
    assert status['status'] == 'failed'
    assert status['progress']['completedUnits'] == 1
    assert status['progress']['totalUnits'] == 3
    assert status['reportRevision'] == ('saved-report' if report_owner else None)
    assert status['coverage'] is None


@pytest.mark.parametrize('previous_owner', ['previous-job', None])
def test_failed_retry_without_saved_progress_does_not_borrow_previous_report_counts(monkeypatch, previous_owner):
    row = {'supportingAnalysis': {'version': 1, 'state': 'failed', 'sourceRevision': 'source',
                                 'reportRevision': 'previous-report', 'analysisId': previous_owner},
           'processingJob': {'id': 'current-job', 'stage': 'failed'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    monkeypatch.setattr(library, 'load_source', lambda *args: {
        'units': [{}, {}, {}], 'coverage': {'complete': True, 'unresolvedUnitIds': []},
    })
    monkeypatch.setattr(library, 'load_report', lambda *args: pytest.fail('Previous report is not current job progress'))
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == 0
    assert status['progress']['totalUnits'] == 3
    assert status['reportRevision'] == 'previous-report'
    assert 'extraction' not in status['coverage']


@pytest.mark.parametrize('job_id', [None, 'same-job'])
@pytest.mark.parametrize('state', ['failed', 'incomplete'])
def test_terminal_status_without_saved_progress_keeps_compatible_current_report_counts(monkeypatch, job_id, state):
    row = {'supportingAnalysis': {'version': 1, 'state': state, 'reportRevision': 'report'},
           'processingJob': {'stage': state}}
    if job_id:
        row['supportingAnalysis']['analysisId'] = row['processingJob']['id'] = job_id
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    monkeypatch.setattr(library, 'load_report', lambda *args: {
        'items': [], 'alignments': [],
        'extractionCoverage': {'complete': False, 'unitIds': ['p1', 'p2', 'p3'],
                               'accountedUnitIds': ['p1'], 'unresolvedUnitIds': ['p2', 'p3']},
        'alignmentCoverage': {},
    })
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == 1
    assert status['progress']['totalUnits'] == 3


@pytest.mark.parametrize('progress', [
    {'completedUnits': 5, 'totalUnits': 3}, {'completedUnits': True, 'totalUnits': 3},
    {'completedUnits': -1, 'totalUnits': 3}, {'completedUnits': 3, 'totalUnits': None},
])
def test_invalid_live_counts_never_claim_verified_progress(monkeypatch, progress):
    row = {'supportingAnalysis': {'version': 1, 'state': 'processing', 'sourceRevision': 'source'},
           'processingJob': {'stage': 'extracting', 'progress': progress}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    monkeypatch.setattr(library, 'load_source', lambda *args: {
        'units': [{}, {}, {}], 'coverage': {'complete': True, 'unresolvedUnitIds': []},
    })
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == 0
    assert status['progress']['totalUnits'] == 3


def test_job_schema_failure_does_not_expose_validation_details():
    row = {'supportingAnalysis': {'version': 1, 'state': 'failed'},
           'processingJob': {'stage': 'failed', 'error': 'Invalid original inventory: private/file copied source body'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    status = library.public_status(IDENTITY)
    assert status['errorMessage'] == 'The AI returned an invalid source analysis. Retry analysis.'


def test_public_report_sanitizes_provider_diagnostics_without_changing_academic_reasons(monkeypatch):
    from copy import deepcopy
    report = {
        'items': [{'id': 'q1', 'sharedContextIds': [], 'paperId': None}],
        'alignments': [{'itemId': 'q1', 'requirements': [{'reason': 'The lecture explains error code 429.'}]}],
        'sharedContexts': [], 'papers': [], 'topics': [], 'scopeSnapshot': {},
        'extractionCoverage': {'complete': False, 'unitIds': ['page'],
            'error': "Error code: 400 - {'provider_body': 'secret-key private/file'}",
            'reasons': {'page': ["Error code: 429 - {'provider_body': 'secret-key'}"]}},
        'alignmentCoverage': {},
    }
    original = deepcopy(report)
    library = SupportingLibrary(SimpleNamespace(database=None))
    monkeypatch.setattr(library, 'load_report', lambda *args: report)
    page = library.report_page(IDENTITY, report_revision='report')
    assert page['extractionCoverage']['error'] == 'The AI provider rejected this analysis request. Check that the selected model supports images and structured responses, then retry.'
    assert page['extractionCoverage']['reasons']['page'] == ['The AI provider has reached its rate or quota limit. Wait for the limit to reset or choose another model, then retry.']
    assert 'secret-key' not in str(page)
    assert page['alignments'] == original['alignments']
    assert report == original


@pytest.mark.parametrize('complete,expected', [(False, 1), (True, 3)])
def test_progress_counts_verified_extraction_units(monkeypatch, complete, expected):
    row = {'supportingAnalysis': {'version': 1, 'state': 'completed' if complete else 'incomplete',
                                 'sourceRevision': 'source', 'reportRevision': 'report'},
           'processingJob': {'stage': 'completed' if complete else 'incomplete'}}
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: row, database=None))
    monkeypatch.setattr(library, 'load_source', lambda *args: {
        'units': [{}, {}, {}], 'coverage': {'complete': True, 'unresolvedUnitIds': []},
    })
    monkeypatch.setattr(library, 'load_report', lambda *args: {
        'items': [], 'alignments': [],
        'extractionCoverage': {'complete': complete, 'unitIds': ['p1', 'p2', 'p3'],
                               'accountedUnitIds': ['p1', 'p2'],
                               'unresolvedUnitIds': [] if complete else ['p2', 'p3']},
        'alignmentCoverage': {'complete': True, 'topicIds': [], 'unresolvedTopicIds': []},
    })
    status = library.public_status(IDENTITY)
    assert status['progress']['completedUnits'] == expected
    assert status['progress']['totalUnits'] == 3
    if complete:
        assert status['errorMessage'] is None
