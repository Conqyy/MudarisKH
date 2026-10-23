"""Whole-branch review regressions through real workflows and owned local storage."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.services.source_evidence import SourceEvidence
from src.supporting.contracts import CLAIM_LEASE_MS, digest
from src.supporting.extraction import SupportingExtractor
from src.supporting.repository import SupportingRepository
from src.supporting.workflows import SupportingWorkflow
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_supporting_job_storage import repository, identity
from tests.test_supporting_storage import library
from tests.test_supporting_extraction import Provider, pdf, proof, item, page
from tests.test_supporting_alignment import (reader, source_scope, supporting_manifest,
    SupportingOriginals, one_requirement, response, request_packet, text_proof)


def workflow_source(library, monkeypatch, *, budget):
    repo = library.repository
    material = identity()
    raw = pdf(['Question 1', 'Question 2'])
    path = 'historical_exams/u/c/recovery.pdf'
    repo.database.upload_file_to_storage(raw, path, 'u')
    source_digest = hashlib.sha256(raw).hexdigest()
    input_revision = digest({'identity': material, 'sourceDigest': source_digest,
        'storagePath': path, 'sourceUrl': None, 'fileType': 'pdf', 'sourceType': None})
    repo.queue(material, input_revision=input_revision, source_digest=source_digest,
        foundation_revision=repo.test_foundation_revision, now_ms=100,
        initial_data={'storagePath': path, 'fileType': 'pdf'}, model_call_budget=budget)
    lecture = repo.test_lecture
    scope = {'documents': [{k: lecture[k] for k in
        ('id', 'title', 'sourceRevision', 'guideRevision', 'guide')}],
        'manifests': [lecture['_sourceManifest']],
        'allowedRefs': [{'documentId': lecture['id'], 'sourceRevision': lecture['sourceRevision'],
                         'unitId': u['unitId']} for u in lecture['_sourceManifest']['units']],
        'foundationRevision': repo.test_foundation_revision}
    scope['scopeRevision'] = digest([{k: d[k] for k in
        ('id', 'sourceRevision', 'guideRevision')} for d in scope['documents']])
    lecture_reader = SourceEvidence(scope, library, 'u', 'c', None, 'fake')
    manifest = SupportingExtractor.prepare_pages(material, raw, 'pdf')
    rows = {f'p{n:04d}': page([item(proof(manifest, n), f'Question {n}')], start=n == 1)
            for n in (1, 2)}
    provider = Provider(rows)

    def align_provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        return response({'judgments': [
            {'targetId': t['id'], 'sourceVerdict': 'established',
             'sourceProofs': [proof(manifest, 2 if '2' in t['text'] else 1)],
             'queries': [], 'explicitTeaching': False, 'reason': 'Original question'}
            if stage == 'source_check' else
            {'targetId': t['id'], 'verdict': 'no_support', 'lectureProofs': [],
             'reason': 'Full selected original does not teach this question'}
            for t in packet['task']['targets']]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', align_provider)
    workflow = SupportingWorkflow(repo, library, SupportingExtractor(provider, 'fake'), None,
                                  lambda owned: lecture_reader)
    monkeypatch.setattr(workflow, '_now', lambda: 100)
    monkeypatch.setattr(library, '_now', lambda: workflow._now())
    return workflow, provider, manifest, rows


@pytest.mark.parametrize('failure', ['budget', 'uncertain', 'invalid'])
def test_incomplete_workflow_explicit_retry_completes_exact_extraction_prefix(library, monkeypatch, failure):
    workflow, provider, manifest, rows = workflow_source(library, monkeypatch,
        budget=1 if failure == 'budget' else 8)
    original_rows = deepcopy(rows)
    if failure == 'uncertain':
        rows['p0002']['disposition'] = 'uncertain'
    elif failure == 'invalid':
        rows['p0002'] = {'invalid': True}
    assert workflow.run(identity()) is True
    first = library.load_report(identity())
    assert first['extractionCoverage']['complete'] is False
    first_job = library.repository.get_owned(identity())['processingJob']
    assert first_job.get('extractionRevision'), 'alignment must retain the exact extraction checkpoint'
    assert not first_job.get('inventoryRevision'), 'incomplete extraction cannot be reused as inventory'
    prefix = library.load_checkpoint(identity(), first_job['extractionRevision'])
    assert prefix['responses']['extract']['0']['items'][0]['text'] == 'Question 1'
    provider.rows = provider.reconciliation = original_rows
    provider.calls.clear()
    monkeypatch.setattr(workflow, '_model_call_budget', lambda: 16)
    workflow.prepare(identity(), retry=True)
    queued = library.repository.get_owned(identity())['processingJob']
    assert queued['id'] != first_job['id'] and queued['modelCalls'] == 0
    assert queued['extractionRevision'] == first_job['extractionRevision']
    assert workflow.run(identity()) is True
    final = library.load_report(identity())
    assert final['extractionCoverage']['complete'] is True
    assert len(final['items']) == 2
    assert library.repository.get_owned(identity())['status'] == 'completed'
    requests = [json.loads(c['messages'][1]['content'][0]['text']) for c in provider.calls]
    assert [r['source']['ref']['unitId'] for r in requests if r['stage'] == 'extract'] == ['p0002']


def test_existing_incomplete_inventory_retry_reextracts_retained_original(library, monkeypatch):
    workflow, provider, manifest, _ = workflow_source(library, monkeypatch, budget=16)
    repo = library.repository
    row = repo.get_owned(identity())
    job = repo.claim(identity(), row['processingJob']['id'], worker_id='legacy', now_ms=100)
    raw = repo.database.download_file_from_storage(row['storagePath'], 'u').read_bytes()
    library.save_source(identity(), job, raw, manifest)
    incomplete = {'items': [], 'sharedContexts': [], 'papers': [], 'topics': [],
        'extractionCoverage': {'complete': False, 'unitIds': ['p0001', 'p0002'],
                               'accountedUnitIds': [], 'unresolvedUnitIds': ['p0001', 'p0002']}}
    state = {'phase': 'inventory', 'sourceRevision': manifest['sourceRevision'],
             'inventoryDigest': digest(incomplete), 'inventory': incomplete, 'modelCalls': 1}
    version = library.save_checkpoint(identity(), job, state)
    repo.checkpoint(identity(), job, changes={'inventoryRevision': version['revision'],
        'modelCalls': 1, 'stage': 'incomplete'}, now_ms=100)
    monkeypatch.setattr(workflow, '_model_call_budget', lambda: 16)
    workflow.prepare(identity(), retry=True)
    assert workflow.run(identity()) is True
    assert library.load_report(identity())['extractionCoverage']['complete'] is True
    assert len(provider.calls) == 4


def test_lease_recovery_keeps_spent_calls_and_pending_extraction_without_fresh_budget(library, monkeypatch):
    workflow, provider, manifest, _ = workflow_source(library, monkeypatch, budget=2)
    save_checkpoint = library.save_checkpoint

    class WorkerCrash(BaseException):
        pass

    def interrupted(identity, job, state):
        version = save_checkpoint(identity, job, state)
        if state.get('stage') == 'extract' and state.get('modelCalls') == 2 and state.get('pending'):
            raise WorkerCrash()
        return version

    monkeypatch.setattr(library, 'save_checkpoint', interrupted)
    with pytest.raises(WorkerCrash):
        workflow.run(identity())
    before = library.repository.get_owned(identity())['processingJob']
    monkeypatch.setattr(library, 'save_checkpoint', save_checkpoint)
    monkeypatch.setattr(workflow, '_now', lambda: 100 + CLAIM_LEASE_MS)
    assert workflow.run(identity()) is True
    recovered = library.repository.get_owned(identity())['processingJob']
    assert recovered['id'] == before['id'] and recovered['claimToken'] != before['claimToken']
    assert recovered['modelCalls'] == 2 and len(provider.calls) == 2
    state = library.load_checkpoint(identity(), recovered['extractionRevision'])
    assert state['cursor'] == 0 and state['stage'] == 'reconcile'
    assert len(state['responses']['extract']) == 2 and state['pending'] is None


def test_extraction_pointer_is_validated_and_does_not_cross_changed_input(repository):
    repo = repository
    material = identity()
    queued = repo.queue(material, input_revision='b' * 64, source_digest='a' * 64,
        foundation_revision=repo.test_foundation_revision, now_ms=100,
        initial_data={'fileType': 'pdf'})
    job = repo.claim(material, queued['id'], worker_id='original', now_ms=100)
    with pytest.raises(ValueError, match='revision'):
        repo.checkpoint(material, job, changes={'extractionRevision': 'untrusted'}, now_ms=100)
    assert repo.checkpoint(material, job, changes={'extractionRevision': 'e' * 64}, now_ms=100)
    repo.queue(material, input_revision='c' * 64, source_digest='a' * 64,
        foundation_revision=repo.test_foundation_revision, now_ms=100)
    assert 'extractionRevision' not in repo.get_owned(material)['processingJob']


def test_resume_pointer_cannot_silently_accept_another_prepared_source(library, monkeypatch):
    workflow, provider, manifest, _ = workflow_source(library, monkeypatch, budget=1)
    assert workflow.run(identity()) is True
    repo = library.repository
    row = repo.get_owned(identity())
    prefix = library.load_checkpoint(identity(), row['processingJob']['extractionRevision'])
    monkeypatch.setattr(workflow, '_model_call_budget', lambda: 16)
    workflow.prepare(identity(), retry=True)
    queued = repo.get_owned(identity())['processingJob']
    job = repo.claim(identity(), queued['id'], worker_id='write-invalid-prefix', now_ms=100)
    prefix['sourceRevision'] = 'd' * 64
    version = library.save_checkpoint(identity(), job, prefix)
    repo.checkpoint(identity(), job, changes={'extractionRevision': version['revision'],
        'stage': 'incomplete'}, now_ms=100)
    workflow.prepare(identity(), retry=True)
    provider.calls.clear()
    assert workflow.run(identity()) is False
    failed = repo.get_owned(identity())
    assert 'different source/context/plan' in failed['error']
    assert not provider.calls


@pytest.mark.parametrize('competing', [False, True])
def test_url_capture_heartbeat_survives_long_operation_but_never_adopts_competing_claim(
        library, api_module, monkeypatch, tmp_path, competing):
    repo = library.repository
    material = identity('audio')
    queued = repo.queue(material, input_revision='b' * 64, source_digest=None,
        foundation_revision=repo.test_foundation_revision, now_ms=100,
        initial_data={'sourceType': 'url', 'sourceUrl': 'https://example.test/audio'})
    job = repo.claim(material, queued['id'], worker_id='original', now_ms=100)
    captured = tmp_path / 'capture.mp3'
    captured.write_bytes(b'exact original captured recording')
    monkeypatch.setattr(api_module, '_download_url_audio_to_mp3', lambda url, directory: (str(captured), 'Audio'))
    workflow = SupportingWorkflow(repo, library, None, None, lambda owned: None)
    clock = [100]
    monkeypatch.setattr(workflow, '_now', lambda: clock[0])
    # Capture races the first heartbeat checkpoint, before the worker receives its bound handle.
    checkpoint = repo.checkpoint
    bound = []
    observed = []

    def capture_race(material, handle, *, changes, now_ms):
        checked = deepcopy(handle)
        if not bound:
            _, _, value = workflow._read_original(material, repo.get_owned(material), job)
            bound.append(value)
            if competing:
                clock[0] += CLAIM_LEASE_MS
                winner = repo.claim(material, job['id'], worker_id='competitor', now_ms=clock[0])
                assert winner and winner['claimToken'] != job['claimToken']
        result = checkpoint(material, checked, changes=changes, now_ms=clock[0])
        observed.append(result)
        return result

    monkeypatch.setattr(repo, 'checkpoint', capture_race)

    class LongOperation:
        ticks = 0
        def wait(self, interval):
            self.ticks += 1
            if self.ticks == 8:
                return True
            clock[0] += 60000
            return False

    stop = LongOperation()
    workflow._heartbeat(material, job, stop)
    current = repo.get_owned(material)
    if competing:
        assert observed and not any(observed)
        assert job['claimToken'] != current['processingJob']['claimToken']
    else:
        assert clock[0] > 100 + CLAIM_LEASE_MS
        assert SupportingRepository._live(current, bound[0], clock[0]) is True
        assert checkpoint(material, bound[0], changes={'stage': 'extracting'}, now_ms=clock[0])


@pytest.mark.parametrize('verify_agrees', [False, True])
def test_context_provider_follows_actual_source_check_contract_and_independent_second_stage(monkeypatch, verify_agrees):
    from src.supporting.alignment import SupportingAligner
    scope = source_scope(['A tree is a connected acyclic graph.'])
    manifest = supporting_manifest('historical_exam', ['Given a hypothetical value 3. Define a tree.'])
    inventory = one_requirement(manifest, 'Define a tree')
    source_proof = inventory['items'][0]['supportingSourceProofs'][0]
    inventory['items'][0]['sharedContextIds'] = ['stem']
    inventory['sharedContexts'] = [{'id': 'stem', 'text': 'Given a hypothetical value 3.',
        'supportingSourceRefs': [source_proof['ref']], 'supportingSourceProofs': [source_proof]}]
    lecture_proof = text_proof(scope['allowedRefs'][0], scope['manifests'][0]['units'][0]['text'],
                               'A tree is a connected acyclic graph.')
    seen = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        policy = kwargs['messages'][0]['content']
        seen.append(stage)
        judgments = []
        for target in packet['task']['targets']:
            if stage in ('source_check', 'context_verify'):
                value = {'targetId': target['id'], 'sourceVerdict': 'established',
                    'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                    'reason': 'Original hypothetical data'}
                # Emulate a schema-faithful provider: emit conditional fields only when instructed.
                if target.get('contextForItemId') and all(k in policy for k in
                        ('decision', 'contentKind', 'methodRequired')):
                    value.update(decision='required' if stage == 'source_check' or verify_agrees else 'unresolved',
                        contentKind='hypothetical_data', methodRequired=False)
            else:
                value = {'targetId': target['id'], 'verdict': 'support',
                         'lectureProofs': [lecture_proof], 'reason': 'Exact definition'}
            judgments.append(value)
        return response({'judgments': judgments})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None)
    assert 'source_check' in seen and 'context_verify' in seen
    dependency = report['alignments'][0]['contextDependencies'][0]
    if verify_agrees:
        assert dependency['relation'] == 'source_only' and dependency['usable'] is True
        assert report['alignments'][0]['status'] == 'covered'
        assert report['alignmentCoverage']['complete'] is True
    else:
        assert dependency['usable'] is False and dependency['decision'] == 'unresolved'
        assert report['alignmentCoverage']['complete'] is False
