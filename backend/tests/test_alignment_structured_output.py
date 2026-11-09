"""Alignment requests constrain syntax without authorizing model-provided proofs."""
from copy import deepcopy
import json

import pytest

from src.supporting.alignment import SupportingAligner
from src.utils.source_context import build_source_plan
from tests.test_supporting_alignment import SupportingOriginals, reader, request_packet, response
from tests.test_supporting_alignment_repairs import judgment, setup_alignment


@pytest.mark.parametrize('stage', ['source_check', 'search', 'verify', 'context_verify'])
def test_alignment_requests_strict_stage_schema_and_disables_reasoning(monkeypatch, stage):
    scope, manifest, _, source_proof, lecture_proof = setup_alignment()
    batch = build_source_plan(scope, 'summary')[0]
    target = {'id': 'r1', 'text': 'Define a tree.'}
    if stage == 'context_verify':
        target['contextForItemId'] = 'q1'
    task = {'stage': stage, 'targets': [target], 'supportingEvidence': [{'ref': source_proof['ref'],
        'ranges': [{'field': 'text', 'start': source_proof['start'], 'end': source_proof['end'],
                    'text': source_proof['quote']}]}], 'supportingProofs': {'r1': [source_proof]}}
    if stage == 'verify':
        task['nominatedProofs'] = {'r1': {'lectureProofs': [lecture_proof]}}
    original_task = deepcopy(task)
    submitted = []

    def provider(*args, **kwargs):
        submitted.append(kwargs)
        return response({'judgments': []})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    reader(scope).read_original_batch(batch, policy='Check exact originals.', task=task)
    call = submitted[0]
    contract = call.get('response_format', {})
    assert contract.get('type') == 'json_schema'
    assert contract['json_schema']['strict'] is True
    assert call['extra_body']['reasoning'] == {'enabled': False}
    assert call['extra_body']['provider']['require_parameters'] is True
    schema = contract['json_schema']['schema']
    assert schema['required'] == ['judgments']
    assert schema['additionalProperties'] is False
    row = schema['properties']['judgments']['items']
    assert set(row['required']) == set(row['properties'])
    assert row['additionalProperties'] is False
    assert row['properties']['targetId']['enum'] == ['r1']
    if stage in ('source_check', 'context_verify'):
        assert row['properties']['sourceVerdict']['enum'] == ['established', 'uncertain', 'not_established']
        expected_ref = source_proof['ref']
        assert 'sourceProofs' in row['required']
        assert ('queries' in row['required']) == (stage == 'source_check')
        assert ('decision' in row['required']) == (stage == 'context_verify')
    else:
        assert 'lectureProofs' in row['required']
        expected_ref = lecture_proof['ref']
        assert ('premise' in row['properties']['verdict']['enum']) == (stage == 'search')
        assert ('reject' in row['properties']['verdict']['enum']) == (stage == 'verify')
    reference = schema['$defs']['sourceReference']
    assert reference['additionalProperties'] is False
    assert reference['properties'] == {key: {'type': 'string', 'enum': [value]} for key, value in expected_ref.items()}
    assert set(schema['$defs']['textProof']['properties']) == {'type', 'spanId'}
    assert schema['$defs']['textProof']['properties']['spanId']['enum']
    assert request_packet(call['messages'])['task']['targets'] == task['targets']
    assert task == original_task


def test_mixed_source_targets_only_require_context_fields_for_context_judgments(monkeypatch):
    scope, _, _, source_proof, _ = setup_alignment()
    task = {'stage': 'source_check', 'targets': [{'id': 'r1'}, {'id': 'context1', 'contextForItemId': 'q1'}],
            'supportingEvidence': [{'ref': source_proof['ref']}]}
    submitted = []
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
        lambda *a, **kw: submitted.append(kw) or response({'judgments': []}))
    reader(scope).read_original_batch(build_source_plan(scope, 'summary')[0], policy='Check originals.', task=task)
    rows = submitted[0]['response_format']['json_schema']['schema']['properties']['judgments']['items']['anyOf']
    regular, context = rows
    assert regular['properties']['targetId']['enum'] == ['r1']
    assert 'decision' not in regular['required']
    assert context['properties']['targetId']['enum'] == ['context1']
    assert {'decision', 'contentKind', 'methodRequired'} <= set(context['required'])


def test_non_alignment_source_read_keeps_existing_request_options(monkeypatch):
    scope, _, _, _, _ = setup_alignment()
    submitted = []
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
        lambda *a, **kw: submitted.append(kw) or response({'supported': True}))
    reader(scope).read_original_batch(build_source_plan(scope, 'summary')[0],
        policy='Check generated output.', task={'claim': 'A tree is connected.'})
    assert 'response_format' not in submitted[0]
    assert 'extra_body' not in submitted[0]


def test_alignment_schema_is_included_in_request_size_bound(monkeypatch):
    scope, _, _, source_proof, _ = setup_alignment()
    batch = build_source_plan(scope, 'summary')[0]
    task = {'stage': 'source_check', 'targets': [{'id': 'r1'}],
            'supportingEvidence': [{'ref': source_proof['ref']}]}
    source = reader(scope)
    # Fit the original message alone close to 24k; the response schema must push
    # it over the same bound used by the aligner's preflight packing.
    plain = source._request_messages(batch, '', task, strict=True)
    size = len(json.dumps(plain, ensure_ascii=False, separators=(',', ':')))
    policy = 'x' * (24000 - size - 100)
    calls = []
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
        lambda *a, **kw: calls.append(kw) or response({'judgments': []}))
    assert source.original_batch_fits(batch, policy=policy, task=task) is False
    with pytest.raises(ValueError, match='24,000'):
        source.read_original_batch(batch, policy=policy, task=task)
    assert calls == []


@pytest.mark.parametrize('damage', ['extra_ref_field', 'wrong_quote'])
def test_strict_alignment_does_not_bypass_original_proof_validation(monkeypatch, damage):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    calls, checkpoints = [], []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        stage = request_packet(kwargs['messages'])['task']['stage']
        row = judgment(stage, source_proof, lecture_proof)
        if damage == 'extra_ref_field':
            row['sourceProofs'][0]['ref']['invented'] = True
        else:
            row['sourceProofs'][0]['quote'] = 'Invented source text'
        return response({'judgments': [row]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert len(calls) == 2
    assert all(call.get('response_format', {}).get('type') == 'json_schema' for call in calls)
    assert report['alignmentCoverage']['complete'] is False
    assert checkpoints[-1]['sourceChecks'] == {}
    assert checkpoints[-1]['acceptedReads']['r1'] == []


@pytest.mark.parametrize('stage', ['source_check', 'search', 'verify', 'context_verify'])
@pytest.mark.parametrize('indices', ['absent', 'incorrect'])
def test_alignment_resolves_unique_exact_quotes_only_from_supplied_ranges(monkeypatch, stage, indices):
    scope, _, _, source_proof, lecture_proof = setup_alignment()
    batch = build_source_plan(scope, 'summary')[0]
    target = {'id': 'r1', 'text': 'Define a tree.'}
    if stage == 'context_verify':
        target['contextForItemId'] = 'q1'
    task = {'stage': stage, 'targets': [target], 'supportingEvidence': [{
        'ref': source_proof['ref'], 'ranges': [{'field': 'text', 'start': source_proof['start'],
            'end': source_proof['end'], 'text': source_proof['quote']}]}]}
    supporting = stage in ('source_check', 'context_verify')
    expected = source_proof if supporting else lecture_proof
    key = 'sourceProofs' if supporting else 'lectureProofs'
    proof = deepcopy(expected)
    if indices == 'absent':
        proof.pop('start'); proof.pop('end')
    else:
        proof.update(start=999, end=1001)
    value = {'judgments': [{'targetId': 'r1', key: [proof]}]}
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', lambda *a, **kw: response(value))
    result, _ = reader(scope).read_original_batch(batch, policy='Check originals.', task=task)
    assert result['judgments'][0][key] == [expected]
    assert value['judgments'][0][key] == [proof], 'Decoder must not mutate provider data'


@pytest.mark.parametrize('damage', ['ambiguous', 'missing', 'outside-window', 'foreign-ref'])
def test_alignment_quote_resolution_rejects_unestablished_positions(monkeypatch, damage):
    scope, _, _, source_proof, _ = setup_alignment()
    batch = build_source_plan(scope, 'summary')[0]
    proof = deepcopy(source_proof)
    proof.pop('start'); proof.pop('end')
    text = proof['quote']
    if damage == 'ambiguous':
        text = text + ' ' + text
    elif damage == 'missing':
        proof['quote'] = 'Invented quotation'
    elif damage == 'outside-window':
        text = text[:3]
    else:
        proof['ref']['materialId'] = 'foreign'
    task = {'stage': 'source_check', 'targets': [{'id': 'r1'}], 'supportingEvidence': [{
        'ref': source_proof['ref'], 'ranges': [{'field': 'text', 'start': 0, 'end': len(text), 'text': text}]}]}
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
        lambda *a, **kw: response({'judgments': [{'targetId': 'r1', 'sourceProofs': [proof]}]}))
    returned = []
    source = reader(scope)
    with pytest.raises(ValueError):
        source.read_original_batch(batch, policy='Check originals.', task=task,
                                   on_response=lambda: returned.append(True))
    assert returned == [True], 'Invalid returned completions still consume the call budget'
    assert source.supplied == [], 'Failed decoding must not record a successful source read'


@pytest.mark.parametrize('stage', ['source_check', 'verify'])
def test_exact_prior_anchor_disambiguates_only_its_target_and_physical_range(monkeypatch, stage):
    scope, _, _, source_proof, lecture_proof = setup_alignment()
    batch = build_source_plan(scope, 'summary')[0]
    original = source_proof if stage == 'source_check' else lecture_proof
    quote = original['quote']
    repeated = quote + ' ' + quote
    anchor = {**deepcopy(original), 'start': len(quote) + 1, 'end': len(repeated)}
    proof = {key: value for key, value in anchor.items() if key not in ('start', 'end')}
    field = 'sourceProofs' if stage == 'source_check' else 'lectureProofs'
    task = {'stage': stage, 'targets': [{'id': 'r1'}], 'supportingEvidence': [{
        'ref': source_proof['ref'], 'ranges': [{'field': 'text', 'start': 0,
            'end': len(repeated), 'text': repeated}]}]}
    if stage == 'source_check':
        task['supportingProofs'] = {'r1': [anchor]}
    else:
        batch['evidence'][0]['ranges'] = [{'textField': 'text', 'start': 0,
            'end': len(repeated), 'text': repeated}]
        task['nominatedProofs'] = {'r1': {'lectureProofs': [anchor]}}
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
        lambda *a, **kw: response({'judgments': [{'targetId': 'r1', field: [proof]}]}))
    decoded, _ = reader(scope).read_original_batch(batch, policy='Check originals.', task=task)
    assert decoded['judgments'][0][field] == [anchor]
    anchors = task['supportingProofs' if stage == 'source_check' else 'nominatedProofs']
    anchors['another-target'] = anchors.pop('r1')
    with pytest.raises(ValueError, match='Ambiguous'):
        reader(scope).read_original_batch(batch, policy='Check originals.', task=task)


def test_decoded_quote_cannot_change_an_independent_verification_nomination(monkeypatch):
    scope, manifest, inventory, source_proof, lecture_proof = setup_alignment()
    calls, checkpoints = [], []

    def provider(*args, **kwargs):
        stage = request_packet(kwargs['messages'])['task']['stage']
        calls.append(stage)
        row = judgment(stage, source_proof, lecture_proof)
        if stage == 'verify':
            proof = row['lectureProofs'][0]
            proof['quote'] = 'connected graph'
            proof.pop('start')
            proof.pop('end')
        return response({'judgments': [row]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert calls == ['source_check', 'search', 'verify', 'verify']
    assert report['alignmentCoverage']['complete'] is False
    assert report['alignments'][0]['requirements'][0]['relation'] == 'unverified'
    assert checkpoints[-1]['verified'] == {}
    assert 'changed nominated proofs' in checkpoints[-1]['error']
