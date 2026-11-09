"""Original-backed audits resolve independent inventories without replacing them."""
import copy
import importlib

import pytest
from types import SimpleNamespace
import json

from .test_supporting_extraction import extractor, pdf, proof, item, page, reader, provider_wire_response
from src.supporting.extraction_source import source_plan
from src.utils.document_sources import render_source_unit


def resolver():
    assert importlib.util.find_spec('src.supporting.reconciliation') is not None
    return importlib.import_module('src.supporting.reconciliation')


def fixture():
    manifest = extractor().prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'},
        pdf(['Tutorial 1: Explain trees']), 'pdf')
    source = source_plan(manifest, 1)[0]
    first = page([item(proof(manifest))])
    first['paper'] = None
    second = copy.deepcopy(first)
    second['items'][0]['requirements'][0]['text'] = 'Explain the concept of trees'
    return manifest, source, first, second


def accepted_audit(module, manifest, first, second):
    obligations = module.audit_obligations(first, second)
    return {'verdict': 'accept_first', 'missingContent': [], 'judgments': [
        {'obligationId': key, 'decision': 'faithful' if key.startswith('A/') else 'represented',
         'firstIds': [key if key.startswith('A/') else 'A/' + key[2:]],
         'proofs': [proof(manifest)], 'reason': 'The exact original establishes the complete same task.'}
        for key in obligations]}


def test_semantic_audit_keeps_both_independent_reads_and_binds_originals():
    module = resolver()
    manifest, source, first, second = fixture()
    before = copy.deepcopy((first, second))
    audit = accepted_audit(module, manifest, first, second)
    certificate = module.validate_audit(audit, manifest, source, None, first, second)
    assert certificate['accepted'] is True
    assert module.validate_certificate(certificate, manifest, source, None, first, second) == certificate
    assert (first, second) == before


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown', 'foreign_proof', 'unknown_mapping'])
def test_incomplete_or_forged_audit_cannot_authorize_coverage(change):
    module = resolver()
    manifest, source, first, second = fixture()
    audit = accepted_audit(module, manifest, first, second)
    if change == 'missing': audit['judgments'].pop()
    elif change == 'duplicate': audit['judgments'].append(copy.deepcopy(audit['judgments'][0]))
    elif change == 'unknown': audit['judgments'][0]['obligationId'] = 'A/unknown'
    elif change == 'foreign_proof': audit['judgments'][0]['proofs'][0]['ref']['materialId'] = 'foreign'
    else: audit['judgments'][-1]['firstIds'] = ['A/items/99']
    with pytest.raises(ValueError): module.validate_audit(audit, manifest, source, None, first, second)


@pytest.mark.parametrize('failure', ['missing_content', 'uncertain', 'unfaithful', 'missing_subpart'])
def test_real_omissions_uncertainty_and_incorrect_first_content_remain_incomplete(failure):
    module = resolver()
    manifest, source, first, second = fixture()
    if failure == 'missing_subpart':
        second['items'].append(item(proof(manifest), 'Draw the tree', item_type='subpart'))
    audit = accepted_audit(module, manifest, first, second)
    if failure == 'missing_content':
        audit['missingContent'] = [{'text': 'A missing source task', 'proofs': [proof(manifest)]}]
    elif failure == 'uncertain': audit['verdict'] = 'uncertain'
    elif failure == 'unfaithful': audit['judgments'][0]['decision'] = 'incorrect'
    else:
        for judgment in audit['judgments']:
            if judgment['obligationId'].startswith('B/items/1'):
                judgment['decision'], judgment['firstIds'] = 'incorrect', []
    certificate = module.validate_audit(audit, manifest, source, None, first, second)
    assert certificate['accepted'] is False


@pytest.mark.parametrize('field', ['first', 'second', 'source', 'policy', 'accepted'])
def test_audit_certificate_tampering_is_rejected(field):
    module = resolver()
    manifest, source, first, second = fixture()
    certificate = module.validate_audit(accepted_audit(module, manifest, first, second),
                                        manifest, source, None, first, second)
    if field == 'first': first['items'][0]['text'] = 'Changed original task'
    elif field == 'second': second['items'][0]['printedMarks'] = 20
    elif field == 'source': source = {**source, 'assetIds': []}
    elif field == 'policy': certificate['bindings']['policyDigest'] = 'f' * 64
    else: certificate['accepted'] = False
    with pytest.raises(ValueError): module.validate_certificate(certificate, manifest, source, None, first, second)


def test_distinct_extra_academic_items_cannot_collapse_onto_one_first_item():
    module = resolver()
    manifest, source, first, second = fixture()
    second['items'].append(item(proof(manifest), 'A second separate task'))
    audit = accepted_audit(module, manifest, first, second)
    for judgment in audit['judgments']:
        if judgment['obligationId'].startswith('B/items/1'):
            judgment['firstIds'] = [judgment['obligationId'].replace('B/items/1', 'A/items/0')]
    with pytest.raises(ValueError, match='distinct|collapse'):
        module.validate_audit(audit, manifest, source, None, first, second)


class AuditProvider:
    def __init__(self, manifest, first, second, *, truncated_first=False, missing_first=False):
        self.manifest, self.first, self.second = manifest, first, second
        self.truncated_first, self.missing_first = truncated_first, missing_first
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        request = json.loads(kwargs['messages'][1]['content'][0]['text'])
        stage = request['stage']
        if stage == 'audit':
            value = accepted_audit(resolver(), self.manifest, self.first, self.second)
        else:
            value = self.second if stage == 'reconcile' else self.first
        value = provider_wire_response(value, request)
        if self.missing_first and len(self.calls) == 1:
            return SimpleNamespace(choices=[])
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason='length' if self.truncated_first and len(self.calls) == 1 else 'stop',
            message=SimpleNamespace(content=json.dumps(value)))], usage=SimpleNamespace(
                prompt_tokens=100, completion_tokens=200,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=20)))


def execute(manifest, provider, states, **kwargs):
    raw = pdf(['Tutorial 1: Explain trees'])
    # Use the exact source bytes retained by the fixture, never real uploads.
    return extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']),
        checkpoint=lambda state: states.append(copy.deepcopy(state)), **kwargs)


def test_extractor_audits_disagreement_and_resumes_without_repeating_the_model_call():
    manifest, source, first, second = fixture()
    provider, states = AuditProvider(manifest, first, second), []
    result = execute(manifest, provider, states)
    assert result['extractionCoverage']['complete'] is True
    state = states[-1]
    assert state['responses']['extract']['0'] != state['responses']['reconcile']['0']
    assert state['resolutions']['0']['accepted'] is True
    assert len(provider.calls) == 3
    assert state['lastCompletion']['outputTokens'] == 200
    replay = AuditProvider(manifest, first, second)
    assert execute(manifest, replay, [], resume=state)['extractionCoverage']['complete'] is True
    assert replay.calls == []


def test_audit_budget_exhaustion_stays_incomplete_without_an_extra_model_call():
    manifest, source, first, second = fixture()
    provider, states = AuditProvider(manifest, first, second), []
    result = execute(manifest, provider, states, model_call_budget=2)
    assert not result['extractionCoverage']['complete']
    assert len(provider.calls) == 2


@pytest.mark.parametrize('truncated', [True, False])
def test_only_confirmed_truncation_increases_the_single_retry_output_allowance(truncated):
    manifest, source, first, second = fixture()
    provider = AuditProvider(manifest, first, first,
        truncated_first=truncated, missing_first=not truncated)
    states = []
    assert execute(manifest, provider, states)['extractionCoverage']['complete']
    assert [call['max_tokens'] for call in provider.calls] == [16000, 32000 if truncated else 16000, 16000]
    assert states[-1]['modelCalls'] == 3
    assert any(state.get('lastCompletion', {}).get('truncated') is truncated for state in states)


def test_previous_context_proofs_alone_cannot_authorize_current_window_coverage():
    module = resolver()
    manifest = extractor().prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'},
        pdf(['Previous context', 'Current task: Explain trees']), 'pdf')
    previous, source = source_plan(manifest, 1)
    first = page([item(proof(manifest, 2))]); first['paper'] = None
    second = copy.deepcopy(first)
    audit = accepted_audit(module, manifest, first, second)
    with pytest.raises(ValueError, match='current'):
        module.validate_audit(audit, manifest, source, previous, first, second)


@pytest.mark.parametrize('target', ['judgment', 'missing_content'])
def test_same_unit_previous_range_cannot_substitute_for_current_audit_evidence(target):
    module = resolver()
    manifest, source, first, second = fixture()
    text = manifest['units'][0]['text']
    previous = copy.deepcopy(source)
    previous['ranges'] = [{'field': 'text', 'start': 0, 'end': 10, 'text': text[:10]}]
    previous['assetIds'] = []
    source['ranges'] = [{'field': 'text', 'start': 10, 'end': len(text), 'text': text[10:]}]
    source['assetIds'] = []
    audit = accepted_audit(module, manifest, first, second)
    for row in audit['judgments']:
        row['proofs'] = [proof(manifest, start=10)]
    prior = proof(manifest, end=10)
    if target == 'judgment':
        audit['judgments'][-1]['proofs'] = [prior]
    else:
        audit['missingContent'] = [{'text': 'A purported omission', 'proofs': [prior]}]
    with pytest.raises(ValueError, match='current-window'):
        module.validate_audit(audit, manifest, source, previous, first, second)


def test_uncertain_audit_can_report_no_proof_without_authorizing_coverage():
    module = resolver()
    manifest, source, first, second = fixture()
    audit = accepted_audit(module, manifest, first, second)
    audit['verdict'] = 'uncertain'
    for row in audit['judgments']:
        row['decision'], row['proofs'] = 'uncertain', []
    assert module.validate_audit(audit, manifest, source, None, first, second)['accepted'] is False


def test_requirement_mapping_cannot_switch_its_owning_item():
    module = resolver()
    manifest, source, first, second = fixture()
    first['items'].append(item(proof(manifest), 'Explain a second independent task'))
    second['items'].append(copy.deepcopy(first['items'][1]))
    audit = accepted_audit(module, manifest, first, second)
    for judgment in audit['judgments']:
        if judgment['obligationId'] == 'B/items/0/requirements/0':
            judgment['firstIds'] = ['A/items/1/requirements/0']
        elif judgment['obligationId'] == 'B/items/1/requirements/0':
            judgment['firstIds'] = ['A/items/0/requirements/0']
    with pytest.raises(ValueError, match='owning item'):
        module.validate_audit(audit, manifest, source, None, first, second)


def test_pending_audit_response_is_replayed_without_another_paid_call():
    manifest, _, first, second = fixture()
    provider, states = AuditProvider(manifest, first, second), []
    raw = pdf(['Tutorial 1: Explain trees'])
    def interrupt(state):
        states.append(copy.deepcopy(state))
        if state.get('resolutionPending') is not None:
            raise InterruptedError('Interrupted after the audit response was saved')
    with pytest.raises(InterruptedError):
        extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
            render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=interrupt)
    assert states[-1]['modelCalls'] == len(provider.calls) == 3
    replay = AuditProvider(manifest, first, second)
    result = execute(manifest, replay, [], resume=states[-1])
    assert result['extractionCoverage']['complete']
    assert replay.calls == []


def test_pending_v3_span_array_audit_replays_after_current_proof_wire_upgrade():
    from src.supporting.structured_output import TextAnchors, encode_proof, source_references

    manifest, source, first, second = fixture()
    provider, states = AuditProvider(manifest, first, second), []
    raw = pdf(['Tutorial 1: Explain trees'])
    def interrupt(state):
        states.append(copy.deepcopy(state))
        if state.get('resolutionPending') is not None:
            raise InterruptedError('Interrupted after saved audit response')
    with pytest.raises(InterruptedError):
        extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
            render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=interrupt)
    legacy = copy.deepcopy(states[-1])
    anchors = TextAnchors([source], known_origins=[proof(manifest)])
    references = source_references(source, None)
    old_response = accepted_audit(resolver(), manifest, first, second)
    for row in old_response['judgments']:
        row['proofs'] = [encode_proof(value, references, anchors) for value in row['proofs']]
    legacy['resolutionPending'].update(wireVersion=3, text=json.dumps(old_response))
    replay, recovered = AuditProvider(manifest, first, second), []
    result = execute(manifest, replay, recovered, resume=legacy)
    assert result['extractionCoverage']['complete'] is True
    assert recovered[-1]['modelCalls'] == legacy['modelCalls']
    assert replay.calls == []


def test_audit_inventory_encoding_losslessly_deduplicates_repeated_original_proofs():
    module = resolver()
    manifest, source, first, second = fixture()
    long_quote = 'Exact original source text. ' * 120
    original = proof(manifest)
    original['quote'], original['end'] = long_quote, len(long_quote)
    first['items'] = [item(copy.deepcopy(original), f'Independent task {index}') for index in range(8)]
    second['items'] = copy.deepcopy(first['items'])
    encoded, table = module.encode_inventories(first, second)
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'originalProof'}:
                return copy.deepcopy(table[value['originalProof']])
            return {key: expand(row) for key, row in value.items()}
        if isinstance(value, list):
            return [expand(row) for row in value]
        return value
    assert expand(encoded) == {'firstInventory': first, 'secondInventory': second}
    assert len(table) == 1
    assert len(json.dumps({'inventories': encoded, 'originalProofs': table})) < 16000
    assert len(json.dumps({'firstInventory': first, 'secondInventory': second})) > 24000


def test_verbose_original_proofs_fit_the_bounded_audit_without_losing_claims():
    raw = pdf(['\n'.join(f'Question {number}: Explain this original example of trees.' for number in range(1, 31))])
    manifest = extractor().prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}, raw, 'pdf')
    first = page([]); first['paper'] = None
    for index in range(6):
        question = item(proof(manifest, start=index * 10, end=index * 10 + 8), f'Explain original task {index}')
        question['proofs'] = [proof(manifest)]
        question['requirements'][0]['proofs'] = [proof(manifest)]
        first['items'].append(question)
    second = copy.deepcopy(first)
    second['items'][0]['requirements'][0]['text'] = 'Explain the first original task'
    provider = AuditProvider(manifest, first, second)
    result = extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=lambda state: None)
    assert result['extractionCoverage']['complete']
    audit_call = provider.calls[-1]
    encoded = audit_call['messages'][1]['content'][0]['text']
    envelope = json.loads(encoded)
    assert envelope['stage'] == 'audit'
    assert len(json.dumps({'firstInventory': first, 'secondInventory': second})) > 24000
    assert len(encoded) + len(audit_call['messages'][0]['content']) <= 24000
    assert len(envelope['firstInventory']['items']) == len(envelope['secondInventory']['items']) == 6


def test_audit_can_describe_a_known_old_origin_without_authorizing_old_evidence_as_current():
    from src.supporting.extraction_inventory import comparable
    manifest = extractor().prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'},
        pdf(['Question 1: Explain trees', 'Continues trees', 'Draw the trees']), 'pdf')
    plan = source_plan(manifest, 1)
    first = page([item(proof(manifest))]); first['paper'] = None
    first['items'][0]['proofs'] = [proof(manifest, 3)]
    first['items'][0]['requirements'][0]['proofs'] = [proof(manifest, 3)]
    second = copy.deepcopy(first)
    second['items'][0]['requirements'][0]['text'] = 'Explain the concept of trees'
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        request = json.loads(kwargs['messages'][1]['content'][0]['text'])
        audit = accepted_audit(resolver(), manifest, first, second)
        for row in audit['judgments']: row['proofs'] = [proof(manifest, 3)]
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(provider_wire_response(audit, request))))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    state = {'responses': {'extract': {'2': first}, 'reconcile': {'2': second}},
        'modelCalls': 0, 'countedResponses': 0, 'modelCallBudget': 1}
    resolver().audit_disagreements(state, manifest, plan, client=client, model='fixture',
        render=lambda unit: ['data:image/png;base64,fixture'], save=lambda: None,
        comparable=comparable, structural_errors=set())
    assert state['resolutions']['2']['accepted']
    request = json.loads(calls[0]['messages'][1]['content'][0]['text'])
    assert {ref['unitId'] for ref in request['sourceReferences'].values()} == {'p0001', 'p0002', 'p0003'}
