"""Forged provider proofs must not enter an alignment's accepted evidence."""
from copy import deepcopy

import pytest

import src.supporting.alignment as alignment
from src.services.source_evidence import SourceEvidence
from src.supporting.alignment import SupportingAligner
from tests.test_source_context import source_scope
from tests.test_supporting_alignment import (
    SupportingOriginals, one_requirement, reader, request_packet, response,
    text_proof, visual_proof,
)
from tests.supporting_fixtures import supporting_manifest


@pytest.mark.parametrize('damage', [
    'invented_asset', 'altered_ref', 'invalid_box', 'outside_supplied_range',
])
def test_forged_search_proof_never_reaches_independent_verification(monkeypatch, damage):
    lecture = ('Target concept. ' + 'x' * 10000 + ' Exact tail quote.'
               if damage == 'outside_supplied_range' else 'Diagram of target concept.')
    scope = source_scope([lecture], visual=damage != 'outside_supplied_range')
    manifest = supporting_manifest('historical_exam', ['Identify the target concept.'])
    inventory = one_requirement(manifest, 'Identify the target concept')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    ref = scope['allowedRefs'][0]
    if damage == 'outside_supplied_range':
        forged = text_proof(ref, lecture, 'Exact tail quote.')
    else:
        forged = visual_proof(ref)
        if damage == 'invented_asset':
            forged['assetId'] = 'invented-page'
        elif damage == 'altered_ref':
            forged['ref']['unitId'] = 'p9999'
        else:
            forged['box'] = [0.8, 0.8, 0.2, 0.2]

    stages = []
    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        stages.append(stage)
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Exact supporting original'}]})
        if stage == 'search':
            if damage == 'outside_supplied_range':
                spans = [part for entry in packet['evidence'] for part in entry['ranges']
                         if part['textField'] == 'text']
                assert not any(part['start'] <= forged['start'] and
                               forged['end'] <= part['end'] for part in spans)
            return response({'judgments': [{'targetId': 'r1', 'verdict': 'support',
                'lectureProofs': [deepcopy(forged)], 'reason': 'Forged provider claim'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'reject',
            'lectureProofs': [], 'reason': 'No semantic match'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    checkpoints = []
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append,
    )['alignments'][0]['requirements'][0]
    assert stages[:2] == ['source_check', 'search']
    assert 'verify' not in stages
    assert finding['relation'] == 'unverified'
    assert checkpoints[-1]['ledgers']['r1'] == []
    assert checkpoints[-1]['error']

    # Control: bypass the named proof/ref/range guards and the same fake answer
    # enters independent verification. The assertions above would then fail.
    monkeypatch.setattr(alignment, 'validate_source_proof',
                        lambda proof, *, ref, unit: deepcopy(proof))
    monkeypatch.setattr(alignment, 'proof_in_supplied',
                        lambda proof, supplied: None)
    if damage == 'altered_ref':
        real_ref_key = alignment.ref_key
        monkeypatch.setattr(alignment, 'ref_key', lambda value:
                            real_ref_key(ref) if value.get('unitId') == 'p9999'
                            else real_ref_key(value))
    stages.clear()
    SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None,
    )
    assert 'verify' in stages


def test_altered_image_locator_stops_search_before_provider(monkeypatch):
    scope = source_scope(['Diagram of target concept.'], visual=True)
    manifest = supporting_manifest('historical_exam', ['Identify the target concept.'])
    inventory = one_requirement(manifest, 'Identify the target concept')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    real_plan = alignment.build_source_plan
    plan_calls = []

    def altered_search_plan(*args, **kwargs):
        batches = real_plan(*args, **kwargs)
        plan_calls.append(args[1])
        if len(plan_calls) > 1:
            for batch in batches:
                for entry in batch['evidence']:
                    for image in entry['images']:
                        image['asset']['mimeType'] = 'image/jpeg'
        return batches

    stages = []
    def provider(*args, **kwargs):
        stage = request_packet(kwargs['messages'])['task']['stage']
        stages.append(stage)
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Exact supporting original'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'no_support',
            'lectureProofs': [], 'reason': 'No match'}]})

    monkeypatch.setattr(alignment, 'build_source_plan', altered_search_plan)
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    checkpoints = []
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append,
    )['alignments'][0]['requirements'][0]
    assert len(plan_calls) > 1
    assert stages == ['source_check']
    assert finding['relation'] == 'unverified'
    assert 'locator' in checkpoints[-1]['error'].lower()

    # A reader with the locator check bypassed sends the tampered search packet.
    real_materialize = SourceEvidence._materialize
    def unchecked_materialize(self, batch):
        clean = deepcopy(batch)
        for entry in clean['evidence']:
            for image in entry['images']:
                image['asset'] = deepcopy(self._units[(
                    image['ref']['documentId'], image['ref']['sourceRevision'],
                    image['ref']['unitId'])]['visualAssets'][image['assetIndex']])
        packet = real_materialize(self, clean)
        packet['evidence'] = deepcopy(batch['evidence'])
        return packet

    monkeypatch.setattr(SourceEvidence, '_materialize', unchecked_materialize)
    plan_calls.clear()
    stages.clear()
    SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None,
    )
    assert 'search' in stages
