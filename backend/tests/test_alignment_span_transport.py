from copy import deepcopy
import re

import pytest

from src.utils.source_context import build_source_plan
from tests.test_source_context import source_scope
from tests.test_supporting_alignment import reader, request_packet, response
from tests.test_supporting_alignment_repairs import setup_alignment


def test_search_selects_exact_application_text_without_retyping_whitespace(monkeypatch):
    original = 'A  tree\tis a connected graph.'
    scope = source_scope([original])
    batch = build_source_plan(scope, 'summary')[0]
    task = {'stage': 'search', 'targets': [{'id': 'r1', 'text': 'Define a tree.'}],
            'supportingEvidence': []}
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        schema = kwargs['response_format']['json_schema']['schema']
        properties = schema['$defs']['textProof']['properties']
        assert set(properties) == {'type', 'spanId'}
        span_id = properties['spanId']['enum'][0]
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'support',
            'lectureProofs': [{'type': 'text_span', 'spanId': span_id}], 'reason': 'Exact span'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    result, supplied = reader(scope).read_original_batch(batch, policy='Check originals.', task=task)
    proof = result['judgments'][0]['lectureProofs'][0]
    assert proof['quote'] == original[proof['start']:proof['end']]
    assert '  ' in proof['quote'] and '\t' in proof['quote']
    wire_range = request_packet(calls[0]['messages'])['evidence'][0]['ranges'][0]
    assert re.sub(r'\[/?t_[a-f0-9]+\]', '', wire_range['text']) == original
    assert supplied == batch['evidence'], 'Transport markers must not enter the source ledger'


def test_unknown_span_id_cannot_authorize_an_original_read(monkeypatch):
    scope, _, _, _, _ = setup_alignment()
    batch = build_source_plan(scope, 'summary')[0]
    task = {'stage': 'search', 'targets': [{'id': 'r1'}], 'supportingEvidence': []}
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', lambda *a, **kw:
        response({'judgments': [{'targetId': 'r1', 'lectureProofs': [
            {'type': 'text_span', 'spanId': 't999999'}]}]}))
    source, returned = reader(scope), []
    with pytest.raises(ValueError):
        source.read_original_batch(batch, policy='Check originals.', task=task,
                                   on_response=lambda: returned.append(True))
    assert source.supplied == []
    assert returned == [True]


@pytest.mark.parametrize('stage', ['source_check', 'context_verify', 'verify'])
def test_prior_span_ids_select_repeated_quotes_without_crossing_target_boundaries(monkeypatch, stage):
    scope, _, _, supporting_proof, lecture_proof = setup_alignment()
    original = supporting_proof if stage != 'verify' else lecture_proof
    quote = original['quote']
    text = quote + ' ' + quote
    anchors = [deepcopy(original), {**deepcopy(original), 'start': len(quote) + 1, 'end': len(text)}]
    anchors[0].update(start=0, end=len(quote))
    batch = build_source_plan(scope, 'summary')[0]
    targets = [{'id': 'r1'}, {'id': 'r2'}]
    if stage == 'context_verify':
        for target in targets:
            target['contextForItemId'] = target['id'] + '-item'
    task = {'stage': stage, 'targets': targets, 'supportingEvidence': [{
        'ref': supporting_proof['ref'], 'ranges': [{'field': 'text', 'start': 0, 'end': len(text), 'text': text}]}]}
    if stage == 'verify':
        batch['evidence'][0]['ranges'] = [{'textField': 'text', 'start': 0, 'end': len(text), 'text': text}]
        task['nominatedProofs'] = {key: {'lectureProofs': [proof]} for key, proof in zip(('r1', 'r2'), anchors)}
    else:
        task['supportingProofs'] = {key: [proof] for key, proof in zip(('r1', 'r2'), anchors)}
    wrong_target = [False]

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        known = packet['task']['nominatedProofs' if stage == 'verify' else 'supportingProofs']
        output_field = 'lectureProofs' if stage == 'verify' else 'sourceProofs'
        rows = []
        for target_id in ('r1', 'r2'):
            owner = 'r2' if wrong_target[0] and target_id == 'r1' else target_id
            proof = known[owner]['lectureProofs'][0] if stage == 'verify' else known[owner][0]
            assert set(proof) == {'type', 'spanId'}
            rows.append({'targetId': target_id, output_field: [proof]})
        return response({'judgments': rows})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    result, _ = reader(scope).read_original_batch(batch, policy='Check originals.', task=task)
    field = 'lectureProofs' if stage == 'verify' else 'sourceProofs'
    assert [row[field][0] for row in result['judgments']] == anchors
    wrong_target[0] = True
    with pytest.raises(ValueError, match='target|nominated|anchor'):
        reader(scope).read_original_batch(batch, policy='Check originals.', task=task)
