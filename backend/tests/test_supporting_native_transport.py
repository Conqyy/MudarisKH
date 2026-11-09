"""Native selection retains independent passes and restart-safe rich fallback."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.supporting.extraction import SupportingExtractor
from src.utils.document_sources import render_source_unit
from .test_supporting_extraction import pdf, reader, proof, item, page, provider_wire_response


def setup(pages=('Explain fork.',)):
    raw = pdf(pages)
    identity = {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}
    manifest = SupportingExtractor.prepare_pages(identity, raw, 'pdf')
    return raw, manifest


def native_value(envelope):
    lines = envelope['native']['current']['ranges'][0]['lines']
    selection = {'firstLine': lines[0]['id'], 'lastLine': lines[-1]['id'], 'quote': None}
    return {'needsRichExtraction': False, 'pageRole': 'questions', 'headings': [],
            'sharedContexts': [], 'questions': [{
                'continuationOf': None, 'stem': selection, 'printedLabel': None,
                'printedMarks': None, 'questionType': None, 'givenData': [], 'choices': [],
                'contextKeys': [], 'requirements': [{'source': selection, 'category': 'concept'}],
                'subparts': []}]}


class Provider:
    def __init__(self, manifest, *, decline=None, decline_page=None):
        self.manifest, self.decline, self.calls = manifest, decline, []
        self.decline_page = decline_page
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        envelope = json.loads(kwargs['messages'][1]['content'][0]['text'])
        if 'native' in envelope:
            value = native_value(envelope)
            if envelope['stage'] == self.decline and (self.decline_page is None or
                                                       envelope['source']['position'] == self.decline_page):
                value.update(needsRichExtraction=True, questions=[])
        else:
            anchor = proof(self.manifest, envelope['source']['position'])
            canonical = page([item(anchor, anchor['quote'])])
            canonical['paper'] = None
            value = provider_wire_response(canonical, envelope)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(value)))])


def run(raw, manifest, provider, *, checkpoint=None, native_tutorials=True, **kwargs):
    saved = []
    def save(value):
        saved.append(deepcopy(value))
        if checkpoint:
            checkpoint(value)
    engine = SupportingExtractor(provider, 'fixture-model', native_tutorials=native_tutorials)
    result = engine.extract(manifest, course_title='Processes', lecture_reader=reader(),
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']),
        checkpoint=save, **kwargs)
    return result, saved


def test_native_path_retains_original_images_and_two_independent_passes():
    raw, manifest = setup()
    provider = Provider(manifest)
    result, saved = run(raw, manifest, provider)
    assert result['extractionCoverage']['complete'] is True
    assert len(provider.calls) == 2
    envelopes = [json.loads(call['messages'][1]['content'][0]['text']) for call in provider.calls]
    assert [row['stage'] for row in envelopes] == ['extract', 'reconcile']
    assert all(row['native']['knownQuestions'] == [] for row in envelopes)
    assert all(row.get('lectureNavigation', {}) == {} for row in envelopes)
    assert all(sum(part['type'] == 'image_url' for part in call['messages'][1]['content']) == 1
               for call in provider.calls)
    assert result['items'][0]['text'] == manifest['units'][0]['text']
    assert any(row.get('pending', {}).get('wireVersion') == 5 for row in saved if row.get('pending'))


@pytest.mark.parametrize('phase, count', [('extract', 3), ('reconcile', 4)])
def test_explicit_rich_fallback_rechecks_both_passes_and_keeps_spent_calls(phase, count):
    raw, manifest = setup()
    provider = Provider(manifest, decline=phase)
    result, saved = run(raw, manifest, provider)
    assert result['extractionCoverage']['complete'] is True
    assert len(provider.calls) == count
    assert saved[-1]['modelCalls'] == count
    assert saved[-1]['nativeFallbackWindows'] == [0]
    envelopes = [json.loads(call['messages'][1]['content'][0]['text']) for call in provider.calls]
    assert ['native' in envelope for envelope in envelopes][-2:] == [False, False]
    assert [envelope['stage'] for envelope in envelopes][-2:] == ['extract', 'reconcile']


def test_later_rich_fallback_preserves_the_independently_checked_prefix():
    raw, manifest = setup(('Explain fork.', 'Explain wait.'))
    provider = Provider(manifest, decline='reconcile', decline_page=2)
    result, saved = run(raw, manifest, provider)
    assert result['extractionCoverage']['complete'] is True
    assert saved[-1]['nativeFallbackWindows'] == [1]
    envelopes = [json.loads(call['messages'][1]['content'][0]['text']) for call in provider.calls]
    assert [(row['stage'], row['source']['position']) for row in envelopes] == [
        ('extract', 1), ('extract', 2), ('reconcile', 1), ('reconcile', 2),
        ('extract', 2), ('reconcile', 2)]
    assert saved[-1]['responses']['extract']['0'] == saved[-1]['responses']['reconcile']['0']
    assert saved[-1]['modelCalls'] == 6


def test_rich_fallback_cannot_reset_or_exceed_the_successful_call_budget():
    raw, manifest = setup()
    provider = Provider(manifest, decline='reconcile')
    result, saved = run(raw, manifest, provider, model_call_budget=2)
    assert result['extractionCoverage']['complete'] is False
    assert len(provider.calls) == saved[-1]['modelCalls'] == 2
    assert saved[-1]['nativeFallbackWindows'] == [0]
    assert saved[-1]['responses'] == {'extract': {}, 'reconcile': {}}
    result, saved = run(raw, manifest, provider, resume=saved[-1], model_calls=0, model_call_budget=2)
    assert result['extractionCoverage']['complete'] is True
    assert len(provider.calls) == 4
    assert saved[-1]['modelCalls'] == 2


def test_returned_native_completion_replays_before_another_provider_call():
    raw, manifest = setup()
    provider, recovered = Provider(manifest), []
    def interrupt(state):
        if state.get('pending'):
            recovered.append(deepcopy(state))
            raise RuntimeError('simulated process stop after durable completion')
    with pytest.raises(RuntimeError, match='simulated process stop'):
        run(raw, manifest, provider, checkpoint=interrupt)
    assert len(provider.calls) == 1
    assert recovered[0]['pending']['wireVersion'] == 5
    result, saved = run(raw, manifest, provider, resume=recovered[0])
    assert result['extractionCoverage']['complete'] is True
    assert len(provider.calls) == 2
    assert saved[-1]['modelCalls'] == 2


@pytest.mark.parametrize('wire_native, resumed_native', [(True, False), (False, True)])
def test_pending_response_keeps_its_transport_when_rollout_preference_changes(wire_native, resumed_native):
    raw, manifest = setup()
    provider, recovered = Provider(manifest), []
    def interrupt(state):
        if state.get('pending') and state['stage'] == 'reconcile':
            recovered.append(deepcopy(state))
            raise RuntimeError('simulated process stop')
    with pytest.raises(RuntimeError, match='simulated process stop'):
        run(raw, manifest, provider, checkpoint=interrupt, native_tutorials=wire_native)
    assert len(provider.calls) == 2
    assert recovered[0]['pending']['wireVersion'] == (5 if wire_native else 4)
    result, _ = run(raw, manifest, provider, resume=recovered[0], native_tutorials=resumed_native)
    assert result['extractionCoverage']['complete'] is True
    assert len(provider.calls) == 2


def test_durable_native_completion_replays_even_if_new_request_budget_is_smaller(monkeypatch):
    raw, manifest = setup()
    provider, recovered = Provider(manifest), []
    def interrupt(state):
        if state.get('pending') and state['stage'] == 'reconcile':
            recovered.append(deepcopy(state))
            raise RuntimeError('simulated process stop')
    with pytest.raises(RuntimeError, match='simulated process stop'):
        run(raw, manifest, provider, checkpoint=interrupt)
    assert len(provider.calls) == 2
    monkeypatch.setattr('src.supporting.extraction.MAX_TEXT_PER_CALL', 1)
    result, _ = run(raw, manifest, provider, resume=recovered[0])
    assert result['extractionCoverage']['complete'] is True
    assert len(provider.calls) == 2


def test_malformed_native_response_does_not_publish_partial_success():
    raw, manifest = setup()
    provider = Provider(manifest)
    original = provider.create
    def malformed(**kwargs):
        answer = original(**kwargs)
        value = json.loads(answer.choices[0].message.content)
        value['questions'][0]['stem']['firstLine'] = 'not-a-current-source-line'
        answer.choices[0].message.content = json.dumps(value)
        return answer
    provider.chat.completions.create = malformed
    result, saved = run(raw, manifest, provider)
    assert result['extractionCoverage']['complete'] is False
    assert result['items'] == []
    assert len(provider.calls) == 2
    assert saved[-1]['responses']['extract'] == {}


def test_native_repair_receives_rejected_answer_without_leaking_it_to_independent_pass():
    raw, manifest = setup()
    provider = Provider(manifest)
    original = provider.create
    rejected = []
    def malformed_first(**kwargs):
        answer = original(**kwargs)
        if len(provider.calls) == 1:
            value = json.loads(answer.choices[0].message.content)
            value['headings'] = [{'source': deepcopy(value['questions'][0]['stem']), 'academic': False}]
            rejected.append(deepcopy(value))
            answer.choices[0].message.content = json.dumps(value)
        return answer
    provider.chat.completions.create = malformed_first
    result, saved = run(raw, manifest, provider)
    envelopes = [json.loads(call['messages'][1]['content'][0]['text']) for call in provider.calls]
    assert len(envelopes) == 3
    assert envelopes[1]['rejectedResponse'] == rejected[0]
    assert 'overlap' in envelopes[1]['contractFeedback'].lower()
    assert 'rejectedResponse' not in envelopes[0]
    assert 'rejectedResponse' not in envelopes[2]
    assert 'contractFeedback' not in envelopes[2]
    assert envelopes[2]['stage'] == 'reconcile'
    assert all(sum(part['type'] == 'image_url' for part in call['messages'][1]['content']) == 1
               for call in provider.calls)
    assert result['extractionCoverage']['complete'] is True
    assert saved[-1]['responses']['extract']['0']['items'][0]['text'] == manifest['units'][0]['text']


def test_oversized_rejected_answer_does_not_prevent_bounded_source_repair():
    raw, manifest = setup()
    provider = Provider(manifest)
    original = provider.create
    def malformed_first(**kwargs):
        answer = original(**kwargs)
        if len(provider.calls) == 1:
            value = json.loads(answer.choices[0].message.content)
            value['unrecognized'] = 'x' * 100_000
            answer.choices[0].message.content = json.dumps(value)
        return answer
    provider.chat.completions.create = malformed_first
    result, _ = run(raw, manifest, provider)
    envelopes = [json.loads(call['messages'][1]['content'][0]['text']) for call in provider.calls]
    assert len(envelopes) == 3
    assert 'rejectedResponse' not in envelopes[1]
    assert 'contractFeedback' in envelopes[1]
    assert result['extractionCoverage']['complete'] is True


@pytest.mark.parametrize('invalid', [[True], [-1], [1], [0, 0], '0'])
def test_invalid_native_fallback_state_is_rejected_before_provider_call(invalid):
    raw, manifest = setup()
    provider = Provider(manifest)
    _, saved = run(raw, manifest, provider)
    state = deepcopy(saved[-1])
    state['nativeFallbackWindows'] = invalid
    calls = len(provider.calls)
    with pytest.raises(ValueError, match='fallback'):
        run(raw, manifest, provider, resume=state)
    assert len(provider.calls) == calls
