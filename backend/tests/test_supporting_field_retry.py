"""Fresh field-review jobs reuse source passes unless actual source repair is needed."""
from copy import deepcopy

import pytest

from src.config.supporting_prompts import EXTRACTION, RECONCILIATION
from src.supporting.contracts import digest
from src.supporting.extraction import SupportingExtractor
from src.supporting.extraction_inventory import comparable, validate_response
from src.supporting.extraction_source import previous_evidence, source_plan
from src.supporting.field_audit import FieldAudit
from src.supporting.reconciliation import validate_audit
from src.utils.document_sources import render_source_unit
from .test_supporting_extraction import Provider, item, page, pdf, proof, reader


def checkpoint_fixture():
    raw = pdf(['Question 1: Explain trees', 'Question 2: Explain processes', 'Question 3: Explain memory'])
    engine = SupportingExtractor(None, 'fixture-model', field_audits=True)
    data = engine.prepare_pages({'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}, raw, 'pdf')
    plan, lectures = source_plan(data, 1), reader()
    ledgers = {'extract': {}, 'reconcile': {}}
    for phase in ledgers:
        earlier = []
        for index, source in enumerate(plan):
            row = page([item(proof(data, index + 1), data['units'][index]['text'])])
            row['items'][0]['printedLabel'] = f'Question {index + 1}:'
            if phase == 'reconcile':
                row['items'][0]['requirements'][0]['text'] = f'Explain the original subject of question {index + 1}.'
            row = validate_response(row, data, source, previous_evidence(plan, index), earlier)
            ledgers[phase][str(index)] = row
            earlier.append(row)
    bindings = {'version': 1, 'sourceRevision': data['sourceRevision'], 'identity': data['identity'],
        'planDigest': digest(plan), 'policyDigest': digest(EXTRACTION['tutorial'] + RECONCILIATION),
        'contextDigest': digest({'courseTitle': 'Algorithms', 'lectureScope': lectures.snapshot()})}
    state = {**bindings, 'stage': 'complete', 'cursor': len(plan), 'responses': ledgers,
        'pending': None, 'resolutionPending': None, 'resolutions': {}, 'modelCalls': 10,
        'countedResponses': 10, 'modelCallBudget': 24, 'nativeFallbackWindows': [], 'error': None}
    return data, plan, raw, lectures, state


def certificate(data, plan, state, index, mode='accepted'):
    key = str(index)
    check = FieldAudit(data, plan[index], previous_evidence(plan, index),
                       state['responses']['extract'][key], state['responses']['reconcile'][key])
    source = plan[index]
    span = source['ranges'][0]
    original = {'type': 'text_span', 'ref': deepcopy(source['ref']), 'field': span['field'],
                'start': span['start'], 'end': span['end'], 'quote': span['text']}
    value = {'protocolVersion': 2, 'taskId': check.envelope()['taskId'], 'verdict': 'accept_first',
        'sourceCompleteness': {'status': 'complete', 'proofs': [original], 'reason': 'Checked current original.'},
        'missingContent': [], 'judgments': [
            {'obligationId': oid, 'decision': 'faithful' if oid.startswith('A/') else 'represented',
             'firstIds': [oid if oid.startswith('A/') else 'A/' + oid[2:]],
             'proofs': [original], 'reason': 'Checked this original obligation.', 'findings': []}
            for oid in check.obligations]}
    if mode in ('uncertain', 'incomplete'):
        value['verdict'] = 'uncertain' if mode == 'uncertain' else 'reject'
        value['sourceCompleteness']['status'] = mode
    elif mode in ('incorrect_first', 'incorrect_second', 'uncertain_second'):
        key = 'A/items/0' if mode == 'incorrect_first' else 'B/items/0/requirements/0'
        field = 'questionType' if mode == 'incorrect_first' else 'category'
        target = next(row for row in value['judgments'] if row['obligationId'] == key)
        target['decision'] = 'uncertain' if mode == 'uncertain_second' else 'incorrect'
        if mode != 'incorrect_first':
            target['firstIds'] = []
        target['findings'] = [{'obligationId': key, 'field': field,
            'observedDigest': check.envelope()['fieldFacts'][key]['fields'][field]['digest'],
            'kind': 'uncertain' if mode == 'uncertain_second' else 'semantic_mismatch', 'proofs': [original]}]
        value['verdict'] = 'uncertain' if mode == 'uncertain_second' else 'reject'
    elif mode in ('legacy_accepted', 'legacy_reject'):
        legacy = {name: deepcopy(value[name]) for name in ('verdict', 'missingContent', 'judgments')}
        legacy['verdict'] = 'uncertain' if mode == 'legacy_reject' else 'accept_first'
        for judgment in legacy['judgments']:
            judgment.pop('findings')
        return validate_audit(legacy, data, plan[index], previous_evidence(plan, index),
                              state['responses']['extract'][str(index)], state['responses']['reconcile'][str(index)])
    return check.validate(value)


def finish_audits(monkeypatch, data, plan):
    """Replace only the audit provider path, keeping real checkpoint validation."""
    calls = []
    def audit(state, manifest, supplied_plan, *, save, **kwargs):
        for index in range(len(supplied_plan)):
            key = str(index)
            first = state['responses']['extract'].get(key)
            second = state['responses']['reconcile'].get(key)
            if (first is None or second is None or key in state['resolutions']
                    or (not state.get('fieldAuditRequired') and comparable(first) == comparable(second))):
                continue
            calls.append(index)
            state['modelCalls'] += 1
            state['countedResponses'] += 1
            state['resolutions'][key] = certificate(data, plan, state, index)
            state['resolutionPending'] = None
            save()
    monkeypatch.setattr('src.supporting.extraction.audit_disagreements', audit)
    return calls


def retry(data, raw, lectures, state, *, field_audits=True, model_calls=0):
    provider = Provider({f'p{index + 1:04d}': row for index, row in
                         enumerate(state['responses']['extract'].values())})
    engine = SupportingExtractor(provider, 'fixture-model', field_audits=field_audits)
    saved = []
    result = engine.extract(data, course_title='Algorithms', lecture_reader=lectures,
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=saved.append,
        resume=state, model_calls=model_calls)
    return result, provider, saved


@pytest.mark.parametrize('failure', ['contract_failure', 'false_missing', 'uncertain', 'uncertain_second'])
@pytest.mark.parametrize('field_audits', [True, False])
def test_failed_field_review_retries_only_audits_and_preserves_both_source_ledgers(monkeypatch, failure, field_audits):
    data, plan, raw, lectures, state = checkpoint_fixture()
    state['resolutions']['0'] = certificate(data, plan, state, 0)
    if failure in ('uncertain', 'uncertain_second'):
        state['resolutions']['1'] = certificate(data, plan, state, 1, failure)
    state['error'] = ('Invalid original reconciliation audit: missing claim contradicts retained field'
                      if failure == 'false_missing' else 'Reconciliation provider failure')
    before = deepcopy(state)
    audits = finish_audits(monkeypatch, data, plan)
    result, provider, saved = retry(data, raw, lectures, state, field_audits=field_audits)
    assert provider.calls == []
    assert audits == [1, 2]
    assert saved[0]['stage'] == 'complete'
    assert saved[0]['responses'] == before['responses']
    assert saved[0]['resolutions'] == {'0': before['resolutions']['0']}
    assert saved[0]['modelCalls'] == saved[0]['countedResponses'] == 0
    assert saved[-1]['resolutions']['0'] == before['resolutions']['0']
    assert result['extractionCoverage']['complete'] is True
    assert result['extractionCoverage']['modelCalls'] == saved[-1]['countedResponses'] == 2
    assert state == before


def test_definite_second_pass_error_rebuilds_only_second_pass_and_its_dependent_suffix(monkeypatch):
    import json
    data, plan, raw, lectures, state = checkpoint_fixture()
    state['resolutions'] = {str(index): certificate(data, plan, state, index,
                            'incorrect_second' if index == 1 else 'accepted') for index in range(3)}
    before = deepcopy(state)
    audits = finish_audits(monkeypatch, data, plan)
    result, provider, saved = retry(data, raw, lectures, state)
    assert saved[0]['stage'] == 'reconcile' and saved[0]['cursor'] == 1
    assert saved[0]['responses']['extract'] == before['responses']['extract']
    assert saved[-1]['responses']['extract'] == before['responses']['extract']
    assert saved[0]['responses']['reconcile'] == {'0': before['responses']['reconcile']['0']}
    assert saved[0]['resolutions'] == {'0': before['resolutions']['0']}
    requests = [json.loads(call['messages'][1]['content'][0]['text']) for call in provider.calls]
    assert [request['stage'] for request in requests] == ['reconcile', 'reconcile']
    assert [request['sourceReferences'][request['source']['ref']]['unitId'] for request in requests] == ['p0002', 'p0003']
    assert audits == [1, 2]
    assert saved[-1]['resolutions']['0'] == before['resolutions']['0']
    assert saved[-1]['resolutions']['2'] != before['resolutions']['2']
    assert result['extractionCoverage']['complete'] is True
    assert result['extractionCoverage']['modelCalls'] == saved[-1]['countedResponses'] == 4


@pytest.mark.parametrize('reason', ['incorrect_first', 'incomplete', 'legacy_reject', 'structural'])
def test_actual_source_repair_rewinds_affected_window_and_continuations_only(monkeypatch, reason):
    data, plan, raw, lectures, state = checkpoint_fixture()
    state['resolutions']['0'] = certificate(data, plan, state, 0)
    if reason == 'structural':
        target = state['responses']['extract']['1']['items'][0]
        target['parent'] = {'origin': deepcopy(target['origin']), 'itemType': 'question'}
    else:
        state['resolutions']['1'] = certificate(data, plan, state, 1, reason)
    # Fresh extraction restores the actual source, including a previously broken parent.
    original = deepcopy(state)
    audits = finish_audits(monkeypatch, data, plan)
    provider = Provider({f'p{index + 1:04d}': deepcopy(state['responses']['extract'][str(index)]) for index in range(3)})
    provider.rows['p0002']['items'][0]['parent'] = None
    saved = []
    result = SupportingExtractor(provider, 'fixture-model', field_audits=True).extract(data,
        course_title='Algorithms', lecture_reader=lectures,
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=saved.append,
        resume=state, model_calls=0)
    assert saved[0]['stage'] == 'extract' and saved[0]['cursor'] == 1
    assert all(set(rows) == {'0'} for rows in saved[0]['responses'].values())
    assert saved[0]['resolutions'] == {'0': original['resolutions']['0']}
    assert len(provider.calls) == 4
    assert audits == [1, 2]
    assert result['extractionCoverage']['complete'] is True
    assert result['extractionCoverage']['modelCalls'] == saved[-1]['countedResponses'] == 6


def test_feature_disabled_keeps_legacy_disagreement_reextraction(monkeypatch):
    data, plan, raw, lectures, state = checkpoint_fixture()
    state['resolutions']['0'] = certificate(data, plan, state, 0, 'legacy_accepted')
    finish_audits(monkeypatch, data, plan)
    result, provider, saved = retry(data, raw, lectures, state, field_audits=False)
    assert saved[0]['stage'] == 'extract' and saved[0]['cursor'] == 1
    assert len(provider.calls) == 4
    assert result['extractionCoverage']['complete'] is True


@pytest.mark.parametrize('pending_error', [None, 'Provider returned no content'])
def test_retry_retains_unvalidated_paid_response_but_drops_explicit_failed_response(monkeypatch, pending_error):
    data, plan, raw, lectures, state = checkpoint_fixture()
    state['resolutionPending'] = {'cursor': 0, 'text': '{}', 'error': pending_error,
        'auditProtocol': 2, 'wireVersion': 4, 'taskId': 'unchanged-task', 'comparisonDigest': 'unchanged-comparison'}
    pending = deepcopy(state['resolutionPending'])
    finish_audits(monkeypatch, data, plan)
    _, provider, saved = retry(data, raw, lectures, state)
    assert provider.calls == []
    assert saved[0]['resolutionPending'] == (pending if pending_error is None else None)


def test_definite_failure_rewinds_exact_window_not_an_already_checked_part_of_the_same_page():
    from .test_supporting_native_inventory import manifest
    _, _, _, lectures, state = checkpoint_fixture()
    data = manifest('Question 1: Explain each operation.\n' + 'Source instruction about processes and memory.\n' * 110)
    plan = source_plan(data, 1)
    assert len(plan) >= 2 and plan[0]['ref']['unitId'] == plan[1]['ref']['unitId']
    state.update(sourceRevision=data['sourceRevision'], identity=data['identity'], planDigest=digest(plan), cursor=len(plan))
    for phase in ('extract', 'reconcile'):
        state['responses'][phase] = {}
        earlier = []
        for index, source in enumerate(plan):
            part = source['ranges'][0]
            original = {'type': 'text_span', 'ref': deepcopy(source['ref']), 'field': part['field'],
                        'start': part['start'], 'end': part['end'], 'quote': part['text']}
            row = page([item(original, part['text'])])
            row['items'][0]['printedLabel'] = None
            if phase == 'reconcile':
                row['items'][0]['requirements'][0]['text'] = 'Explain the original instructions.'
            row = validate_response(row, data, source, previous_evidence(plan, index), earlier)
            state['responses'][phase][str(index)] = row
            earlier.append(row)
    state['resolutions'] = {str(index): certificate(data, plan, state, index,
                              'accepted' if index == 0 else 'incomplete') for index in range(len(plan))}
    saved = []
    class CheckpointCaptured(Exception):
        pass
    def checkpoint(value):
        saved.append(value)
        raise CheckpointCaptured
    with pytest.raises(CheckpointCaptured):
        SupportingExtractor(None, 'fixture-model', field_audits=True).extract(data,
            course_title='Algorithms', lecture_reader=lectures, render=lambda unit: None,
            checkpoint=checkpoint, resume=state, model_calls=0)
    assert saved[0]['cursor'] == 1 and saved[0]['stage'] == 'extract'
    assert all(set(rows) == {'0'} for rows in saved[0]['responses'].values())
    assert set(saved[0]['resolutions']) == {'0'}
