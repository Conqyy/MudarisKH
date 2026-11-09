"""Persisted numeric window keys must not change continuation evidence on resume."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.supporting.contracts import canonical_bytes
from src.supporting.extraction_inventory import identifier
from src.supporting.extraction_source import source_plan
from src.supporting.structured_output import TextAnchors, WIRE_VERSION

from .test_supporting_extraction import extractor, item, page, pdf, reader


class Interrupted(Exception):
    pass


def continuation_fixture():
    raw = pdf([f'Question {number}: Explain trees\nDescribe their structure.'
               for number in range(1, 12)] + ['Continue the preceding question\nCompare the branches.'])
    manifest = extractor().prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}, raw, 'pdf')
    plan = source_plan(manifest, 1)
    assert len(plan) == 12
    anchors = [next(iter(TextAnchors([source]).proofs.values())) for source in plan]
    rows = []
    for index, source in enumerate(plan):
        origin = anchors[10] if index == 11 else anchors[index]
        row = item(deepcopy(origin), text=source['ranges'][0]['text'])
        row.update(questionType=None, textJoin='\n', printedLabel='11' if index == 11 else str(index + 1))
        row['proofs'] = [deepcopy(anchors[index])]
        row['requirements'][0]['proofs'] = [deepcopy(anchors[index])]
        response = page([row])
        response['paper'] = None
        rows.append(response)
    return manifest, plan, rows


class SpanProvider:
    """Finite fake provider: every returned proof obeys the actual v3 ID schema."""

    def __init__(self, plan, rows, allowed_calls):
        self.plan, self.rows = plan, rows
        self.remaining = list(allowed_calls)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        request = json.loads(kwargs['messages'][1]['content'][0]['text'])
        source_ref = request['source']['ref']
        if isinstance(source_ref, str):
            source_ref = request['sourceReferences'][source_ref]
        index = next(i for i, source in enumerate(self.plan) if source['ref'] == source_ref)
        call = (request['stage'], index)
        self.calls.append(call)
        assert self.remaining, 'A durable pending response must not trigger another provider call'
        assert call == self.remaining.pop(0)
        contract = kwargs['response_format']['json_schema']
        assert kwargs['response_format']['type'] == 'json_schema'
        assert contract['strict'] is True
        assert contract['name'] == 'supporting_inventory'
        assert kwargs['extra_body']['reasoning']['enabled'] is False
        assert kwargs['extra_body']['provider']['require_parameters'] is True
        supplied_ids = []
        for name in ('currentTextProof', 'contextTextProof'):
            if name in contract['schema']['$defs']:
                properties = contract['schema']['$defs'][name]['properties']
                assert set(properties) == {'type', 'spanId'}
                supplied_ids.extend(properties['spanId']['enum'])

        def encode(value):
            if isinstance(value, dict):
                if value.get('type') == 'text_span':
                    registry = TextAnchors([], known_origins=[value])
                    encoded = registry.encode(value)
                    assert encoded['spanId'] in supplied_ids
                    return encoded
                return {key: encode(child) for key, child in value.items()}
            if isinstance(value, list):
                return [encode(child) for child in value]
            return value

        encoded = encode(self.rows[index])
        # Keep all v4 proof slots selected from exactly the supplied IDs.
        def claims(value):
            if isinstance(value, dict):
                result = {key: claims(child) for key, child in value.items()}
                if isinstance(value.get('proofs'), list):
                    proofs = value['proofs']
                    result['proofs'] = {'current': proofs[0] if proofs else None, 'context': proofs[1:]}
                return result
            if isinstance(value, list):
                return [claims(child) for child in value]
            return value
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(claims(encoded))))])


@pytest.mark.parametrize('interrupted_stage', ['extract', 'reconcile'])
@pytest.mark.parametrize('pending_version', [3, WIRE_VERSION])
def test_pending_continuation_after_ten_windows_survives_canonical_checkpoint_roundtrip(interrupted_stage, pending_version):
    manifest, plan, rows = continuation_fixture()
    all_calls = [(stage, index) for stage in ('extract', 'reconcile') for index in range(len(plan))]
    stop_at = all_calls.index((interrupted_stage, 11)) + 1
    provider = SpanProvider(plan, rows, all_calls[:stop_at])
    checkpoints = []

    def interrupt_after_response(state):
        checkpoints.append(deepcopy(state))
        pending = state.get('pending')
        if pending and pending['stage'] == interrupted_stage and pending['cursor'] == 11:
            raise Interrupted()

    options = {'course_title': 'Algorithms', 'lecture_reader': reader(),
               'render': lambda unit: ['data:image/png;base64,fixture']}
    with pytest.raises(Interrupted):
        extractor(provider).extract(manifest, checkpoint=interrupt_after_response, **options)
    assert provider.calls == all_calls[:stop_at]
    assert not provider.remaining

    # The real checkpoint writer sorts JSON keys. An in-memory deepcopy misses
    # the resulting 0, 1, 10, 2, ..., 9 order and would hide this regression.
    restored = json.loads(canonical_bytes(checkpoints[-1]))
    assert list(restored['responses'][interrupted_stage])[-1] == '9'
    assert restored['pending']['wireVersion'] == WIRE_VERSION
    assert 'spanId' in restored['pending']['text']
    if pending_version == 3:
        def legacy(value):
            if isinstance(value, dict):
                result = {key: legacy(child) for key, child in value.items()}
                if isinstance(value.get('proofs'), dict):
                    claims = value['proofs']
                    result['proofs'] = [claims['current'], *claims['context']]
                return result
            if isinstance(value, list):
                return [legacy(child) for child in value]
            return value
        restored['pending'].update(wireVersion=3, text=json.dumps(legacy(json.loads(restored['pending']['text']))))
    resumed = SpanProvider(plan, rows, all_calls[stop_at:])
    resumed_states = []
    result = extractor(resumed).extract(manifest, resume=restored,
        checkpoint=lambda state: resumed_states.append(deepcopy(state)), **options)

    assert resumed.calls == all_calls[stop_at:], 'The persisted pending response must replay without another call'
    assert not resumed.remaining
    assert result['extractionCoverage']['complete'], result['extractionCoverage']
    assert resumed_states[-1]['modelCalls'] == len(all_calls)
    accepted = resumed_states[-1]['responses'][interrupted_stage]['11']['items'][0]
    assert accepted['origin'] == rows[10]['items'][0]['origin']
    assert accepted['proofs'] == rows[11]['items'][0]['proofs']
    continued = next(row for row in result['items'] if row['id'] == identifier(accepted['origin'], 'question'))
    assert [ref['unitId'] for ref in continued['supportingSourceRefs']] == ['p0011', 'p0012']


def test_strict_span_provider_completes_both_reads_and_persists_canonical_proofs_only():
    manifest, plan, rows = continuation_fixture()
    calls = [(stage, index) for stage in ('extract', 'reconcile') for index in range(len(plan))]
    provider, checkpoints = SpanProvider(plan, rows, calls), []
    result = extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: ['data:image/png;base64,fixture'], checkpoint=checkpoints.append)

    assert result['extractionCoverage']['complete']
    assert provider.calls == calls and not provider.remaining
    assert result['extractionCoverage']['modelCalls'] == len(calls)
    pending = [state['pending'] for state in checkpoints if state.get('pending')]
    assert len(pending) == len(calls)
    assert all(response['wireVersion'] == WIRE_VERSION for response in pending)
    assert all('spanId' in response['text'] and '"quote"' not in response['text'] for response in pending)
    for phase in ('extract', 'reconcile'):
        saved = checkpoints[-1]['responses'][phase]
        assert 'spanId' not in json.dumps(saved)
        for index, original in enumerate(rows):
            assert saved[str(index)] == original


def test_known_continuation_span_cannot_replace_current_fragment_evidence_at_provider_seam():
    manifest, plan, rows = continuation_fixture()
    calls = [('extract', index) for index in range(11)] + [('extract', 11), ('extract', 11)]
    provider, checkpoints = SpanProvider(plan, rows, calls), []
    create = provider.create

    def previous_only(**kwargs):
        response = create(**kwargs)
        if provider.calls[-1] == ('extract', 11):
            value = json.loads(response.choices[0].message.content)
            old_origin = value['items'][0]['origin']
            # This ID is valid and explicitly supplied for continuity identity.
            # It still cannot prove that the current page was read.
            value['items'][0]['proofs'] = {'current': deepcopy(old_origin), 'context': []}
            value['items'][0]['requirements'][0]['proofs'] = {'current': deepcopy(old_origin), 'context': []}
            response.choices[0].message.content = json.dumps(value)
        return response

    provider.chat.completions.create = previous_only
    result = extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: ['data:image/png;base64,fixture'], checkpoint=checkpoints.append)

    assert not result['extractionCoverage']['complete']
    assert provider.calls == calls and not provider.remaining
    assert checkpoints[-1]['modelCalls'] == 13
    assert '11' not in checkpoints[-1]['responses']['extract']
    assert not checkpoints[-1]['responses']['reconcile']
    assert 'current source window' in checkpoints[-1]['error']
