"""Topic references must close over actual extracted items and requirements."""
from copy import deepcopy

import pytest

from src.supporting.inventory_references import InventoryReferenceError, validate_topic_links


def origin(start):
    return {'type': 'text_span', 'ref': {'kind': 'tutorial', 'materialId': 'm',
            'sourceRevision': 'a' * 64, 'unitId': 'p0001'},
            'field': 'text', 'start': start, 'end': start + 1, 'quote': 'x'}


def requirement(start, text='Explain trees', category='concept'):
    return {'origin': origin(start), 'text': text, 'category': category}


def item(start, requirements, kind='question'):
    return {'origin': origin(start), 'itemType': kind, 'requirements': requirements}


def item_ref(row):
    return {'origin': deepcopy(row['origin']), 'itemType': row['itemType']}


def topic(items, requirements):
    return {'items': [item_ref(row) for row in items], 'requirements': deepcopy(requirements)}


def test_current_item_and_exact_requirement_references_are_valid_without_mutation():
    req = requirement(1)
    question = item(0, [req])
    value = {'items': [question], 'topics': [topic([question], [req])]}
    before = deepcopy(value)
    assert validate_topic_links(value, []) is value
    assert value == before


def test_unknown_item_reference_is_a_reference_error():
    question = item(0, [requirement(1)])
    invented = item(20, [requirement(21)])
    value = {'items': [question], 'topics': [topic([invented], [requirement(1)])]}
    with pytest.raises(InventoryReferenceError, match='item'):
        validate_topic_links(value, [])


def test_unknown_requirement_reference_is_a_reference_error():
    question = item(0, [requirement(1)])
    value = {'items': [question], 'topics': [topic([question], [requirement(8)])]}
    with pytest.raises(InventoryReferenceError, match='requirement'):
        validate_topic_links(value, [])


def test_requirement_must_belong_to_an_item_referenced_by_the_same_topic():
    first, second = item(0, [requirement(1)]), item(10, [requirement(11)])
    value = {'items': [first, second], 'topics': [topic([first], second['requirements'])]}
    with pytest.raises(InventoryReferenceError, match='referenced item'):
        validate_topic_links(value, [])


@pytest.mark.parametrize('changed', ['text', 'category', 'origin'])
def test_requirement_reference_cannot_paraphrase_or_change_the_actual_requirement(changed):
    req = requirement(1)
    question = item(0, [req])
    value = {'items': [question], 'topics': [topic([question], [req])]}
    reference = value['topics'][0]['requirements'][0]
    if changed == 'text': reference['text'] = 'Describe the concept of trees'
    elif changed == 'category': reference['category'] = 'deduction'
    else: reference['origin'] = origin(2)
    with pytest.raises(InventoryReferenceError, match='requirement'):
        validate_topic_links(value, [])


def test_same_original_location_with_a_different_item_type_is_not_the_same_item():
    question = item(0, [requirement(1)])
    value = {'items': [question], 'topics': [topic([question], question['requirements'])]}
    value['topics'][0]['items'][0]['itemType'] = 'subpart'
    with pytest.raises(InventoryReferenceError, match='item'):
        validate_topic_links(value, [])


def test_prior_and_current_items_can_both_authorize_the_topic_references():
    prior, current = item(0, [requirement(1)]), item(10, [requirement(11)])
    earlier = [{'items': [prior], 'topics': []}]
    value = {'items': [current], 'topics': [topic([prior, current],
                                              prior['requirements'] + current['requirements'])]}
    before = deepcopy((earlier, value))
    assert validate_topic_links(value, earlier) is value
    assert (earlier, value) == before


def test_continued_item_can_reference_requirements_from_both_fragments():
    first_req, continued_req = requirement(1), requirement(2, 'Calculate the tree depth', 'calculation')
    first = item(0, [first_req])
    continued = item(0, [continued_req])
    earlier = [{'items': [first], 'topics': []}]
    value = {'items': [continued], 'topics': [topic([continued], [first_req, continued_req])]}
    assert validate_topic_links(value, earlier) is value


def test_prior_requirement_does_not_authorize_a_topic_pointing_only_to_another_item():
    prior, current = item(0, [requirement(1)]), item(10, [requirement(11)])
    value = {'items': [current], 'topics': [topic([current], prior['requirements'])]}
    with pytest.raises(InventoryReferenceError, match='referenced item'):
        validate_topic_links(value, [{'items': [prior], 'topics': []}])


def test_no_topics_needs_no_extra_requirements_or_items():
    value = {'items': [], 'topics': []}
    assert validate_topic_links(value, []) is value


def test_reference_error_is_a_value_error_for_the_existing_validation_boundary():
    assert issubclass(InventoryReferenceError, ValueError)


def test_legacy_checkpoint_with_bad_topic_links_rereads_only_affected_suffix():
    from .test_supporting_extraction import run, pdf, page, item as extracted_item, proof, Provider, extractor, reader
    from src.utils.document_sources import render_source_unit

    raw = pdf(['Question 1: Explain trees', 'Question 2: Explain graphs'])
    def rows(manifest):
        result = {}
        for number in (1, 2):
            question = extracted_item(proof(manifest, number), f'Question {number}')
            response = page([question], start=number == 1)
            response['topics'] = [{'text': question['text'], 'items': [item_ref(question)],
                'requirements': [{key: question['requirements'][0][key] for key in ('origin', 'text', 'category')}],
                'proofs': question['proofs']}]
            result[f'p{number:04d}'] = response
        return result
    _, _, manifest, checkpoints = run(raw, rows=rows)
    legacy = deepcopy(checkpoints[-1])
    for phase in ('extract', 'reconcile'):
        legacy['responses'][phase]['1']['topics'][0]['requirements'][0]['text'] = 'Paraphrased nonexistent identity'
    before = deepcopy(legacy)
    provider, saved = Provider(rows(manifest)), []
    result = extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=saved.append,
        resume=legacy, model_call_budget=6)
    assert result['extractionCoverage']['complete']
    assert len(provider.calls) == 2
    assert saved[-1]['modelCalls'] == 6  # prior successes were not erased
    for phase in ('extract', 'reconcile'):
        assert saved[-1]['responses'][phase]['0'] == legacy['responses'][phase]['0']
    assert legacy == before


def test_legacy_bad_topic_link_does_not_hide_a_forged_original_proof():
    from .test_supporting_extraction import run, pdf, page, item as extracted_item, proof, Provider, extractor, reader
    from src.utils.document_sources import render_source_unit

    raw = pdf(['Question 1: Explain trees'])
    _, _, manifest, states = run(raw, rows=lambda source: {'p0001': page([extracted_item(proof(source))], start=True)})
    legacy = deepcopy(states[-1])
    response = legacy['responses']['extract']['0']
    question = response['items'][0]
    response['topics'] = [{'text': 'Trees', 'items': [item_ref(question)],
        'requirements': [{'origin': proof(manifest), 'text': 'Unknown requirement', 'category': 'concept'}],
        'proofs': [proof(manifest)]}]
    response['topics'][0]['proofs'][0]['quote'] = 'FORGED ORIGINAL'
    provider = Provider({})
    with pytest.raises(ValueError):
        extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
            render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']),
            checkpoint=lambda state: None, resume=legacy)
    assert provider.calls == []
