"""Real extraction/audit transport path with strict span-ID provider responses."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.supporting.contracts import canonical_bytes
from src.supporting.reconciliation import validate_certificate
from src.supporting.structured_output import TextAnchors, WIRE_VERSION

from .test_supporting_extraction import extractor, reader
from .test_supporting_reconciliation import fixture, accepted_audit, resolver


class Interrupted(Exception):
    pass


class StrictAuditProvider:
    def __init__(self, manifest, first, second, expected):
        self.manifest, self.first, self.second = manifest, first, second
        self.remaining, self.calls = list(expected), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        packet = json.loads(kwargs['messages'][1]['content'][0]['text'])
        stage = packet['stage']
        self.calls.append(stage)
        assert self.remaining and stage == self.remaining.pop(0)
        contract = kwargs['response_format']['json_schema']
        assert kwargs['response_format']['type'] == 'json_schema'
        assert contract['strict'] is True
        assert contract['name'] == ('supporting_audit' if stage == 'audit' else 'supporting_inventory')
        allowed = []
        for name in ('currentTextProof', 'contextTextProof'):
            if name in contract['schema']['$defs']:
                properties = contract['schema']['$defs'][name]['properties']
                assert set(properties) == {'type', 'spanId'}
                allowed.extend(properties['spanId']['enum'])

        def encode(value):
            if isinstance(value, dict):
                if value.get('type') == 'text_span':
                    encoded = TextAnchors([], known_origins=[value]).encode(value)
                    assert encoded['spanId'] in allowed
                    return encoded
                result = {key: encode(child) for key, child in value.items()}
                if isinstance(value.get('proofs'), list):
                    proofs = result['proofs']
                    result['proofs'] = {'current': proofs[0] if proofs else None, 'context': proofs[1:]}
                return result
            if isinstance(value, list):
                return [encode(child) for child in value]
            return value

        if stage == 'audit':
            assert all(set(value) == {'type', 'spanId'} for value in packet['originalProofs'].values())
            value = accepted_audit(resolver(), self.manifest, self.first, self.second)
        else:
            value = self.first if stage == 'extract' else self.second
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(encode(value))))])


@pytest.mark.parametrize('interrupt_pending_audit', [False, True])
def test_strict_span_audit_persists_canonical_certificate_and_replays_without_new_calls(interrupt_pending_audit):
    manifest, source, first, second = fixture()
    for inventory in (first, second):
        inventory['items'][0].update(questionType=None, textJoin='\n')
    before = deepcopy((first, second))
    provider = StrictAuditProvider(manifest, first, second, ['extract', 'reconcile', 'audit'])
    states = []

    def checkpoint(state):
        states.append(deepcopy(state))
        if interrupt_pending_audit and state.get('resolutionPending'):
            raise Interrupted()

    options = {'course_title': 'Algorithms', 'lecture_reader': reader(),
               'render': lambda unit: ['data:image/png;base64,fixture']}
    if interrupt_pending_audit:
        with pytest.raises(Interrupted):
            extractor(provider).extract(manifest, checkpoint=checkpoint, **options)
    else:
        assert extractor(provider).extract(manifest, checkpoint=checkpoint, **options)['extractionCoverage']['complete']
    assert provider.calls == ['extract', 'reconcile', 'audit'] and not provider.remaining
    pending = next(state['resolutionPending'] for state in states if state.get('resolutionPending'))
    assert pending['wireVersion'] == WIRE_VERSION
    assert 'spanId' in pending['text'] and '"quote"' not in pending['text']

    # Match the real saved JSON representation, including canonical key sorting.
    restored = json.loads(canonical_bytes(states[-1]))
    replay = StrictAuditProvider(manifest, first, second, [])
    recovered = []
    result = extractor(replay).extract(manifest, resume=restored,
        checkpoint=lambda state: recovered.append(deepcopy(state)), **options)
    assert result['extractionCoverage']['complete']
    assert replay.calls == []
    assert recovered[-1]['modelCalls'] == 3
    certificate = recovered[-1]['resolutions']['0']
    assert certificate['accepted'] is True
    assert validate_certificate(certificate, manifest, source, None, first, second) == certificate
    assert 'spanId' not in json.dumps(certificate)
    assert certificate['response']['judgments'][0]['proofs'][0]['ref'] == source['ref']
    assert recovered[-1]['responses']['extract']['0'] == first
    assert recovered[-1]['responses']['reconcile']['0'] == second
    assert (first, second) == before
