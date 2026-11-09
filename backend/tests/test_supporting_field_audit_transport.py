"""Field reviews retain original evidence, bounded repairs and durable replay."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.supporting.contracts import canonical_bytes, digest
from src.supporting.extraction import SupportingExtractor
from src.supporting.extraction_source import source_plan
from src.supporting.reconciliation import validate_certificate
from src.supporting.structured_output import TextAnchors
from .test_supporting_extraction import reader, proof, provider_wire_response
from .test_supporting_extraction import pdf, page, item
from .test_supporting_reconciliation import fixture, accepted_audit, resolver


class StopAfterResponse(Exception):
    pass


class FieldProvider:
    def __init__(self, manifest, first, second, *, false_missing=False, always_invalid=False, shared_omission=False):
        self.manifest, self.first, self.second = manifest, first, second
        self.false_missing, self.always_invalid = false_missing, always_invalid
        self.shared_omission = shared_omission
        self.calls, self.packets, self.audit_calls = [], [], 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        packet = json.loads(kwargs['messages'][1]['content'][0]['text'])
        self.calls.append(packet['stage'])
        self.packets.append(deepcopy(packet))
        if packet['stage'] != 'audit':
            value = self.first if packet['stage'] == 'extract' else self.second
            wire = provider_wire_response(value, packet)
        else:
            self.audit_calls += 1
            value = accepted_audit(resolver(), self.manifest, self.first, self.second)
            if packet.get('protocolVersion') == 2:
                value.update(protocolVersion=2, taskId=packet['taskId'], sourceCompleteness={
                    'status': 'complete', 'proofs': [proof(self.manifest)],
                    'reason': 'The entire original was independently checked for shared omissions.'})
                for row in value['judgments']:
                    row['findings'] = []
                if self.shared_omission:
                    start = self.manifest['units'][0]['text'].index('Question 2:')
                    original = proof(self.manifest, start=start)
                    for row in value['judgments']:
                        row['proofs'] = deepcopy(self.first['items'][0]['proofs'])
                    value['sourceCompleteness']['proofs'] = [original]
                    value.update(verdict='reject', missingContent=[{
                        'text': 'A second printed question is absent from both inventories.',
                        'proofs': [original], 'finding': {'obligationId': None, 'field': None,
                            'observedDigest': None, 'kind': 'literal_missing', 'proofs': [original]}}])
                    value['sourceCompleteness']['status'] = 'incomplete'
                if (self.false_missing and self.audit_calls == 1) or self.always_invalid:
                    # The literal original is already retained in this owner's
                    # text and own proof, so this rejection must be repaired.
                    value['verdict'] = 'reject'
                    value['sourceCompleteness']['status'] = 'incomplete'
                    value['missingContent'] = [{'text': 'The original task was supposedly omitted.',
                        'proofs': [proof(self.manifest)], 'finding': {
                            'obligationId': 'A/items/0', 'field': 'text',
                            'observedDigest': (packet['fieldFacts']['A/items/0']['fields']['text']
                                if isinstance(packet['fieldFacts']['A/items/0']['fields']['text'], str) else
                                packet['fieldFacts']['A/items/0']['fields']['text']['digest']),
                            'kind': 'literal_missing', 'proofs': [proof(self.manifest)]}}]
            def encode(row):
                if isinstance(row, list):
                    return [encode(child) for child in row]
                if not isinstance(row, dict):
                    return row
                if row.get('type') == 'text_span':
                    return TextAnchors([], known_origins=[row]).encode(row)
                result = {key: encode(child) for key, child in row.items()}
                if isinstance(row.get('proofs'), list):
                    proofs = result['proofs']
                    result['proofs'] = {'current': proofs[0] if proofs else None, 'context': proofs[1:]}
                return result
            wire = encode(value)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(wire)))])


def setup():
    manifest, source, first, second = fixture()
    for value in (first, second):
        value['items'][0].update(questionType=None, textJoin='\n')
    # Contract fixtures need the exact original text to demonstrate a
    # mechanically contradicted omission in the named text field.
    first['items'][0]['text'] = proof(manifest)['quote']
    return manifest, source, first, second


def run(manifest, provider, *, fields=True, resume=None, checkpoint=None, **kwargs):
    saved = []
    def persist(state):
        saved.append(deepcopy(state))
        if checkpoint:
            checkpoint(state)
    result = SupportingExtractor(provider, 'fixture-model', field_audits=fields).extract(
        manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: ['data:image/png;base64,fixture'], checkpoint=persist, resume=resume, **kwargs)
    return result, saved


@pytest.mark.parametrize('interrupt', [False, True])
@pytest.mark.parametrize('identical', [False, True])
def test_field_certificate_replays_without_another_call_or_changing_source_candidates(interrupt, identical):
    manifest, source, first, second = setup()
    if identical:
        second = deepcopy(first)
    before = deepcopy((first, second))
    provider = FieldProvider(manifest, first, second)
    recovered = []
    def stop(state):
        if interrupt and state.get('resolutionPending'):
            recovered.append(deepcopy(state))
            raise StopAfterResponse()
    if interrupt:
        with pytest.raises(StopAfterResponse):
            run(manifest, provider, checkpoint=stop)
        state = recovered[0]
        assert state['resolutionPending']['auditProtocol'] == 2
        assert state['resolutionPending']['taskId']
        assert state['resolutionPending']['comparisonDigest']
    else:
        result, saved = run(manifest, provider)
        assert result['extractionCoverage']['complete'] is True
        state = saved[-1]
    assert provider.calls == ['extract', 'reconcile', 'audit']
    replay = FieldProvider(manifest, first, second)
    result, saved = run(manifest, replay, resume=json.loads(canonical_bytes(state)), fields=False)
    assert result['extractionCoverage']['complete'] is True
    assert replay.calls == []
    assert saved[-1]['modelCalls'] == 3
    certificate = saved[-1]['resolutions']['0']
    assert certificate['bindings']['version'] == 2
    assert validate_certificate(certificate, manifest, source, None, first, second) == certificate
    assert (first, second) == before


def test_false_literal_omission_is_repaired_against_same_original_without_reextracting():
    manifest, source, first, second = setup()
    provider = FieldProvider(manifest, first, second, false_missing=True)
    result, saved = run(manifest, provider)
    assert result['extractionCoverage']['complete'] is True
    assert provider.calls == ['extract', 'reconcile', 'audit', 'audit']
    assert saved[-1]['modelCalls'] == 4
    assert 'contradict' in provider.packets[-1]['contractFeedback'].lower()
    assert provider.packets[-1]['rejectedResponse']['missingContent']
    assert provider.packets[-1]['taskId'] == provider.packets[-2]['taskId']


def test_contradiction_at_last_budget_unit_stays_incomplete_without_a_fabricated_certificate():
    manifest, source, first, second = setup()
    provider = FieldProvider(manifest, first, second, always_invalid=True)
    result, saved = run(manifest, provider, model_call_budget=3)
    assert result['extractionCoverage']['complete'] is False
    assert saved[-1]['resolutions'] == {}
    assert saved[-1]['modelCalls'] == 3
    assert provider.calls == ['extract', 'reconcile', 'audit']


@pytest.mark.parametrize('field', ['taskId', 'comparisonDigest', 'auditProtocol'])
def test_changed_pending_field_task_is_rejected_before_any_new_provider_call(field):
    manifest, source, first, second = setup()
    provider = FieldProvider(manifest, first, second)
    captured = []
    def stop(state):
        if state.get('resolutionPending'):
            captured.append(deepcopy(state))
            raise StopAfterResponse()
    with pytest.raises(StopAfterResponse):
        run(manifest, provider, checkpoint=stop)
    state = captured[0]
    state['resolutionPending'][field] = 99 if field == 'auditProtocol' else 'changed'
    replay = FieldProvider(manifest, first, second)
    with pytest.raises(ValueError, match='pending|Pending|protocol|tasks'):
        run(manifest, replay, resume=state)
    assert replay.calls == []


def test_saved_legacy_pending_audit_retains_its_decoder_after_field_rollout():
    manifest, source, first, second = setup()
    provider = FieldProvider(manifest, first, second)
    captured = []
    def stop(state):
        if state.get('resolutionPending'):
            captured.append(deepcopy(state))
            raise StopAfterResponse()
    with pytest.raises(StopAfterResponse):
        run(manifest, provider, fields=False, checkpoint=stop)
    assert 'auditProtocol' not in captured[0]['resolutionPending']
    replay = FieldProvider(manifest, first, second)
    result, saved = run(manifest, replay, resume=captured[0], fields=True)
    assert result['extractionCoverage']['complete'] is True
    assert saved[-1]['resolutions']['0']['bindings']['version'] == 1
    assert replay.calls == []


def test_matching_inventories_cannot_hide_a_shared_original_omission():
    raw = pdf(['Question 1: Explain trees.\nQuestion 2: Draw a graph.'])
    manifest = SupportingExtractor.prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}, raw, 'pdf')
    boundary = manifest['units'][0]['text'].index('Question 2:')
    anchor = proof(manifest, end=boundary)
    first = page([item(anchor, anchor['quote'])])
    first['paper'] = None
    second = deepcopy(first)
    provider = FieldProvider(manifest, first, second, shared_omission=True)
    result, saved = run(manifest, provider)
    assert provider.calls == ['extract', 'reconcile', 'audit']
    assert result['extractionCoverage']['complete'] is False
    assert saved[-1]['fieldAuditRequired'] is True
    assert saved[-1]['resolutions']['0']['accepted'] is False
    assert saved[-1]['resolutions']['0']['response']['missingContent']
