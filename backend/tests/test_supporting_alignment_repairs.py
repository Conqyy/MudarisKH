"""Bounded contract recovery rereads originals without accepting rejected proofs."""
from copy import deepcopy

import pytest

from src.supporting.alignment import SupportingAligner
from tests.supporting_fixtures import supporting_manifest
from tests.test_source_context import source_scope
from tests.test_supporting_alignment import (
    SupportingOriginals, one_requirement, reader, request_packet, response, text_proof,
)


def setup_alignment():
    scope = source_scope(['A tree is a connected graph without cycles.'])
    manifest = supporting_manifest('tutorial', ['Define a tree.'])
    inventory = one_requirement(manifest, 'Define a tree')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    lecture_proof = text_proof(scope['allowedRefs'][0],
        scope['manifests'][0]['units'][0]['text'], 'A tree is a connected graph without cycles.')
    return scope, manifest, inventory, source_proof, lecture_proof


def judgment(stage, source_proof, lecture_proof):
    if stage == 'source_check':
        return {'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [deepcopy(source_proof)], 'queries': [],
                'explicitTeaching': False, 'reason': 'Exact supporting original'}
    return {'targetId': 'r1', 'verdict': 'support',
            'lectureProofs': [deepcopy(lecture_proof)], 'reason': 'Exact lecture definition'}


@pytest.mark.parametrize('failed_stage', ['source_check', 'search', 'verify'])
def test_invalid_exact_ref_is_repaired_against_the_same_originals(monkeypatch, failed_stage):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    calls, checkpoints = [], []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        earlier = [old for old in calls if old['task']['stage'] == stage]
        calls.append(deepcopy(packet))
        row = judgment(stage, source_proof, lecture_proof)
        if stage == failed_stage and not earlier:
            field = 'sourceProofs' if stage == 'source_check' else 'lectureProofs'
            row[field][0]['ref']['invented'] = 'not-an-exact-ref'
        return response({'judgments': [row]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert report['alignmentCoverage']['complete'] is True
    assert report['alignments'][0]['requirements'][0]['relation'] == 'lecture_supported'
    stage_calls = [call for call in calls if call['task']['stage'] == failed_stage]
    assert len(stage_calls) == 2
    first, repaired = stage_calls
    assert repaired['evidence'] == first['evidence']
    assert repaired['task']['supportingEvidence'] == first['task']['supportingEvidence']
    assert repaired['task']['targets'] == first['task']['targets']
    assert 'Invalid exact source reference' in repaired['task']['responseValidationError']
    assert checkpoints[-1]['modelCalls'] == len(calls) == 4


@pytest.mark.parametrize('damage', ['foreign_ref', 'wrong_quote', 'missing_target', 'duplicate_target'])
def test_repeated_invalid_contract_stays_unverified_with_no_accepted_ledger(monkeypatch, damage):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    calls, checkpoints = [], []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        calls.append(packet)
        row = judgment('source_check', source_proof, lecture_proof)
        if damage == 'foreign_ref':
            row['sourceProofs'][0]['ref']['materialId'] = 'another-tutorial'
        elif damage == 'wrong_quote':
            row['sourceProofs'][0]['quote'] = 'Invented source words'
        rows = [] if damage == 'missing_target' else [row, deepcopy(row)] if damage == 'duplicate_target' else [row]
        return response({'judgments': rows})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert report['alignmentCoverage']['complete'] is False
    assert report['alignments'][0]['requirements'][0]['relation'] == 'unverified'
    assert checkpoints[-1]['modelCalls'] == len(calls) == 2
    assert checkpoints[-1]['sourceChecks'] == {}
    assert checkpoints[-1]['acceptedReads']['r1'] == []
    assert checkpoints[-1]['ledgers']['r1'] == []


def test_contract_repair_does_not_exceed_the_returned_completion_budget(monkeypatch):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    calls, checkpoints = [], []

    def provider(*args, **kwargs):
        calls.append(kwargs['messages'])
        row = judgment('source_check', source_proof, lecture_proof)
        row['sourceProofs'][0]['ref']['invented'] = 'bad'
        return response({'judgments': [row]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append,
        model_call_budget=1)
    assert len(calls) == checkpoints[-1]['modelCalls'] == 1
    assert report['alignmentCoverage']['complete'] is False
    assert checkpoints[-1]['acceptedReads']['r1'] == []


def test_valid_uncertainty_does_not_request_a_more_positive_answer(monkeypatch):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    calls, checkpoints = [], []

    def provider(*args, **kwargs):
        calls.append(kwargs['messages'])
        return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'uncertain',
            'sourceProofs': [], 'queries': [], 'explicitTeaching': False,
            'reason': 'The supporting original is ambiguous'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert len(calls) == checkpoints[-1]['modelCalls'] == 1
    assert report['alignments'][0]['requirements'][0]['relation'] == 'unverified'


@pytest.mark.parametrize('failure', ['malformed', 'budget', 'transport', 'repair_bound'])
def test_failed_verification_never_turns_a_positive_search_into_not_found(monkeypatch, failure):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    calls, checkpoints = [], []
    source = reader(scope)
    if failure == 'repair_bound':
        original_fits = source.original_batch_fits
        source.original_batch_fits = lambda batch, *, policy, task: (
            False if 'responseValidationError' in task else original_fits(batch, policy=policy, task=task))

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        calls.append(stage)
        if stage == 'verify' and failure == 'transport':
            raise RuntimeError('transport unavailable')
        row = judgment(stage, source_proof, lecture_proof)
        if stage == 'verify':
            row['lectureProofs'][0]['ref']['invented'] = True
        return response({'judgments': [row]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(source, SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append,
        model_call_budget=2 if failure == 'budget' else 8)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'unverified'
    assert finding['reviewCoverage']['checkState'] == 'pending'
    assert report['alignmentCoverage']['complete'] is False
    assert checkpoints[-1]['failedReads']['r1']
    expected_verify_calls = {'malformed': 2, 'budget': 0, 'transport': 1, 'repair_bound': 1}[failure]
    assert calls.count('verify') == expected_verify_calls
    assert checkpoints[-1]['modelCalls'] == len(calls) - (failure == 'transport')


def test_context_verification_contract_is_repaired_without_changing_originals(monkeypatch):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    inventory['sharedContexts'] = [{'id': 'context1', 'text': 'Define a tree.',
        'supportingSourceRefs': [deepcopy(source_proof['ref'])],
        'supportingSourceProofs': [deepcopy(source_proof)]}]
    inventory['items'][0]['sharedContextIds'] = ['context1']
    calls, checkpoints = [], []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        prior = [call for call in calls if call['task']['stage'] == stage]
        calls.append(packet)
        rows = []
        for target in packet['task']['targets']:
            row = judgment('source_check' if stage == 'context_verify' else stage,
                           source_proof, lecture_proof)
            row['targetId'] = target['id']
            if 'contextForItemId' in target:
                row.update(decision='required', contentKind='academic_claim', methodRequired=True)
            if stage == 'context_verify' and not prior:
                row['sourceProofs'][0]['ref']['invented'] = True
            rows.append(row)
        return response({'judgments': rows})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert report['alignmentCoverage']['complete'] is True
    assert report['alignments'][0]['contextDependencies'][0]['usable'] is True
    checks = [call for call in calls if call['task']['stage'] == 'context_verify']
    assert len(checks) == 2
    assert checks[0]['evidence'] == checks[1]['evidence']
    assert checks[0]['task']['supportingEvidence'] == checks[1]['task']['supportingEvidence']
    assert checkpoints[-1]['modelCalls'] == len(calls)


@pytest.mark.parametrize('legacy', [False, True])
def test_owned_retry_clears_transient_verification_failure_and_keeps_call_accounting(monkeypatch, legacy):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    checkpoints, calls = [], []
    invalid = True

    def provider(*args, **kwargs):
        stage = request_packet(kwargs['messages'])['task']['stage']
        calls.append(stage)
        row = judgment(stage, source_proof, lecture_proof)
        if stage == 'verify' and invalid:
            row['lectureProofs'][0]['ref']['invented'] = True
        return response({'judgments': [row]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    originals = SupportingOriginals(manifest)
    aligner = SupportingAligner(reader(scope), originals)
    first = aligner.align(manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert first['alignmentCoverage']['complete'] is False
    stored = deepcopy(checkpoints[-1])
    spent = stored['modelCalls']
    if legacy:
        stored.pop('failedReads')
        stored['uncertain'] = {}
    originals.load_checkpoint = lambda identity, revision: deepcopy(stored)
    invalid = False
    result = aligner.align(manifest['identity'], inventory, scope=scope,
        checkpoint=checkpoints.append, resume_revision='a' * 64)
    assert result['alignments'][0]['requirements'][0]['relation'] == 'lecture_supported'
    assert result['alignmentCoverage']['complete'] is True
    assert checkpoints[-1]['modelCalls'] == len(calls) == spent + 2
    assert checkpoints[-1]['failedReads'] == {}
    assert checkpoints[-1]['uncertain'] == {}
    assert checkpoints[-1]['error'] is None
