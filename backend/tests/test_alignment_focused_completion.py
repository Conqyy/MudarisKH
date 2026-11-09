"""Positive original evidence can finish before an exhaustive absence search."""
from copy import deepcopy

import pytest

from src.supporting.alignment import SupportingAligner
from src.utils.source_context import build_source_plan
from tests.supporting_fixtures import supporting_manifest
from tests.test_source_context import source_scope
from tests.test_supporting_alignment import (
    SupportingOriginals, one_requirement, reader, request_packet, response, text_proof,
)


@pytest.mark.parametrize('combine_premises', [False, True])
def test_focused_support_finishes_before_full_plan_is_constructed(monkeypatch, combine_premises):
    scope = source_scope(['Alpha is a taught rule.', 'Beta is another taught rule.'])
    manifest = supporting_manifest('historical_exam', ['Apply alpha and beta.'])
    inventory = one_requirement(manifest, 'Apply alpha and beta')
    source_proof = inventory['items'][0]['supportingSourceProofs'][0]
    proofs = [text_proof(ref, unit['text'], unit['text']) for ref, unit in
              zip(scope['allowedRefs'], scope['manifests'][0]['units'])]
    stages, full_plans = [], []

    def planner(*args, **kwargs):
        if args[1] == 'summary':
            full_plans.append(True)
            raise ValueError('Source plan needs at least 129 batches; limit 128')
        return build_source_plan(*args, **kwargs)

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        task = packet['task']
        stage = task['stage']
        stages.append(stage)
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': ['alpha', 'beta'],
                'explicitTeaching': False, 'reason': 'Actual question'}]})
        if stage == 'verify':
            nominated = task['nominatedProofs']['r1']['lectureProofs']
            supported = not combine_premises or len(nominated) == 2
            return response({'judgments': [{'targetId': 'r1',
                'verdict': 'support' if supported else 'reject',
                'lectureProofs': nominated if supported else [], 'reason': 'Checked exact rules'}]})
        units = {entry['ref']['unitId'] for entry in packet['evidence']}
        matching = [proof for proof in proofs if proof['ref']['unitId'] in units]
        return response({'judgments': [{'targetId': 'r1',
            'verdict': 'premise' if combine_premises else 'support',
            'lectureProofs': matching, 'reason': 'Original taught rule'}]})

    monkeypatch.setattr('src.supporting.alignment.build_source_plan', planner)
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    saved = []
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=saved.append)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'lecture_supported'
    assert not full_plans
    assert 'verify' in stages
    assert saved[-1]['modelCalls'] == len(stages)
    if combine_premises:
        assert len(finding['lectureSupportProofs']) == 2


def test_unresolved_target_keeps_full_sweep_and_never_claims_absence_at_limit(monkeypatch):
    scope = source_scope(['Alpha rule is unrelated.', 'Beta rule is unrelated.'])
    manifest = supporting_manifest('historical_exam', ['Find an alpha counterexample.'])
    inventory = one_requirement(manifest, 'Find an alpha counterexample')
    source_proof = inventory['items'][0]['supportingSourceProofs'][0]
    full_limits = []

    def planner(*args, **kwargs):
        if args[1] == 'summary':
            full_limits.append(kwargs.get('max_batches'))
            raise ValueError('Source plan exceeds remaining analysis budget')
        return build_source_plan(*args, **kwargs)

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual question'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'no_support',
            'lectureProofs': [], 'reason': 'Checked partial navigation only'}]})

    monkeypatch.setattr('src.supporting.alignment.build_source_plan', planner)
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    saved = []
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=saved.append,
        model_call_budget=6)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'unverified'
    assert finding['reviewCoverage']['complete'] is False
    assert full_limits == [4]
    assert saved[-1]['modelCalls'] == 2


def test_source_plan_default_bound_is_preserved_and_explicit_bound_is_complete():
    scope = source_scope(['A readable unit.'] * 129)
    kwargs = {'text_budget': 1300, 'image_budget': 0}
    with pytest.raises(ValueError, match='limit 128'):
        build_source_plan(scope, 'summary', **kwargs)
    batches = build_source_plan(scope, 'summary', **kwargs, max_batches=129)
    assert len(batches) == 129
    assert [entry['ref'] for batch in batches for entry in batch['evidence']] == scope['allowedRefs']
    for bound in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match='budget'):
            build_source_plan(scope, 'summary', **kwargs, max_batches=bound)
