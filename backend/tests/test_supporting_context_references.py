"""Shared-context links must close over current or previously accepted originals."""
from copy import deepcopy
import json

import pytest

from src.supporting.extraction_inventory import validate_response
from src.supporting.extraction_source import previous_evidence, source_plan
from src.supporting.inventory_references import InventoryReferenceError
from src.utils.document_sources import render_source_unit
from tests.supporting_fixtures import supporting_manifest
from tests.test_supporting_extraction import Provider, extractor, item, page, pdf, proof, reader, run


def heading_response(manifest, number=1):
    text = manifest['units'][number - 1]['text']
    question_start = text.index('Question')
    question = item(proof(manifest, number, start=question_start), 'Explain process creation')
    question['contextOrigins'] = [proof(manifest, number, end=question_start - 1)]
    return page([question])


def define_heading(value):
    origin = value['items'][0]['contextOrigins'][0]
    value['sharedContexts'] = [{'origin': deepcopy(origin), 'text': origin['quote'],
                                'proofs': [deepcopy(origin)]}]
    return value


def test_bare_current_heading_origin_requires_an_actual_shared_context_record():
    manifest = supporting_manifest('tutorial', ['Tutorial #1\nCHAPTER #3\nQuestion: Explain process creation'])
    plan = source_plan(manifest, 0)
    value = heading_response(manifest)
    with pytest.raises(InventoryReferenceError, match='shared context'):
        validate_response(value, manifest, plan[0], None, [])
    assert value['sharedContexts'] == [], 'Validation must not invent a context to repair the response'


def test_same_window_shared_context_is_valid_without_rewriting_its_content():
    manifest = supporting_manifest('tutorial', ['Tutorial #1\nQuestion: Explain process creation'])
    plan = source_plan(manifest, 0)
    value = define_heading(heading_response(manifest))
    accepted = validate_response(value, manifest, plan[0], None, [])
    assert accepted['sharedContexts'] == value['sharedContexts']
    assert accepted['items'][0]['contextOrigins'] == value['items'][0]['contextOrigins']


@pytest.mark.parametrize('declared', [False, True])
def test_previous_page_heading_needs_a_previously_declared_context(declared):
    manifest = supporting_manifest('tutorial', ['Tutorial #1\nQuestion: Explain processes', 'Question: Explain threads'])
    plan = source_plan(manifest, 0)
    previous = heading_response(manifest)
    if declared:
        define_heading(previous)
    else:
        previous['items'][0]['contextOrigins'] = []
    prior = validate_response(previous, manifest, plan[0], None, [])
    current = page([item(proof(manifest, 2), 'Explain threads')])
    current['items'][0]['contextOrigins'] = [proof(manifest, end=11)]
    if declared:
        accepted = validate_response(current, manifest, plan[1], previous_evidence(plan, 1), [prior])
        assert accepted['sharedContexts'] == [], 'An earlier context need not be duplicated as a new fragment'
    else:
        with pytest.raises(InventoryReferenceError, match='shared context'):
            validate_response(current, manifest, plan[1], previous_evidence(plan, 1), [prior])


def test_context_can_reference_a_known_original_before_the_immediate_previous_page():
    manifest = supporting_manifest('tutorial', ['Tutorial #1\nQuestion: Explain processes',
        'Question: Explain threads', 'Question: Compare them'])
    plan = source_plan(manifest, 0)
    prior = validate_response(define_heading(heading_response(manifest)), manifest, plan[0], None, [])
    middle = validate_response(page([item(proof(manifest, 2))]), manifest, plan[1],
                               previous_evidence(plan, 1), [prior])
    current = page([item(proof(manifest, 3))])
    current['items'][0]['contextOrigins'] = [deepcopy(prior['sharedContexts'][0]['origin'])]
    accepted = validate_response(current, manifest, plan[2], previous_evidence(plan, 2), [prior, middle])
    assert accepted['items'][0]['contextOrigins'] == current['items'][0]['contextOrigins']


def completed_fixture():
    raw = pdf(['Tutorial #1\nQuestion: Explain processes', 'CHAPTER #3\nQuestion: Explain threads'])
    def rows(manifest):
        return {f'p{number:04d}': define_heading(heading_response(manifest, number)) for number in (1, 2)}
    _, _, manifest, states = run(raw, kind='tutorial', rows=rows)
    return raw, manifest, rows, deepcopy(states[-1])


@pytest.mark.parametrize('invalid_windows', [(0, 1), (1, 0), (1, 1)])
def test_legacy_context_gap_rewinds_the_earliest_affected_window_and_keeps_spent_calls(invalid_windows):
    raw, manifest, rows, legacy = completed_fixture()
    spent = legacy['modelCalls']
    for phase, index in zip(('extract', 'reconcile'), invalid_windows):
        legacy['responses'][phase][str(index)]['sharedContexts'] = []
    before = deepcopy(legacy)
    first = min(invalid_windows)
    provider, states = Provider(rows(manifest)), []
    result = extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=states.append,
        resume=legacy, model_call_budget=8)
    assert result['extractionCoverage']['complete'] is True
    assert len(provider.calls) == 2 * (2 - first)
    assert states[-1]['modelCalls'] == spent + len(provider.calls)
    for phase in ('extract', 'reconcile'):
        for index in range(first):
            assert states[-1]['responses'][phase][str(index)] == before['responses'][phase][str(index)]
    assert legacy == before


@pytest.mark.parametrize('guard', ['budget', 'checkpoint', 'forged_proof'])
def test_legacy_context_repair_preserves_budget_checkpoint_and_original_proof_guards(guard):
    raw, manifest, rows, legacy = completed_fixture()
    legacy['responses']['extract']['0']['sharedContexts'] = []
    if guard == 'forged_proof':
        legacy['responses']['extract']['0']['items'][0]['proofs'][0]['quote'] = 'Forged original'
    provider, states = Provider(rows(manifest)), []
    def checkpoint(state):
        if guard == 'checkpoint':
            raise RuntimeError('Claim fence rejected checkpoint')
        states.append(state)
    def execute():
        return extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
            render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=checkpoint,
            resume=legacy, model_call_budget=legacy['modelCalls'])
    if guard == 'budget':
        assert execute()['extractionCoverage']['complete'] is False
        assert states[-1]['cursor'] == 0
        assert states[-1]['modelCalls'] == legacy['modelCalls']
    else:
        with pytest.raises(RuntimeError if guard == 'checkpoint' else ValueError) as failure:
            execute()
        if guard == 'forged_proof':
            assert not isinstance(failure.value, InventoryReferenceError)
    assert provider.calls == []


def test_current_response_repairs_missing_context_before_advancing_to_the_next_window():
    raw = pdf(['Tutorial #1\nQuestion: Explain processes'])
    attempts = []
    def rows(manifest):
        def respond(request):
            attempts.append(deepcopy(request))
            value = heading_response(manifest)
            return value if len(attempts) == 1 else define_heading(value)
        return respond
    result, provider, _, _ = run(raw, kind='tutorial', rows=rows)
    assert result['extractionCoverage']['complete'] is True
    assert [request['stage'] for request in attempts] == ['extract', 'extract', 'reconcile']
    request = json.loads(provider.calls[1]['messages'][1]['content'][0]['text'])
    assert 'shared context' in request['contractFeedback']
