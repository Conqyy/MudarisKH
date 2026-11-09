"""Field comparisons preserve source facts without deciding semantic acceptance."""
from copy import deepcopy
import importlib

import pytest

from src.supporting.extraction_source import source_plan
from .test_supporting_native_inventory import manifest


def comparison(data, first, second, source=None):
    assert importlib.util.find_spec('src.supporting.inventory_comparison') is not None, 'Source field comparison is missing'
    module = importlib.import_module('src.supporting.inventory_comparison')
    return module.InventoryComparison(data, source or source_plan(data, 1)[0], first, second)


def span(data, quote, *, page=0, start=None):
    unit = data['units'][page]
    offset = unit['text'].index(quote) if start is None else start
    return {'type': 'text_span', 'ref': {'kind': 'tutorial', 'materialId': 'tutorial',
            'sourceRevision': data['sourceRevision'], 'unitId': unit['unitId']},
            'field': 'text', 'start': offset, 'end': offset + len(quote), 'quote': quote}


def requirement(proof, category='operation'):
    return {'origin': deepcopy(proof), 'text': proof['quote'], 'category': category, 'proofs': [deepcopy(proof)]}


def question(origin, requirements=(), *, label=None, data=()):
    return {'origin': deepcopy(origin), 'itemType': 'question', 'parent': None, 'text': origin['quote'],
            'textJoin': '\n', 'printedLabel': label, 'printedMarks': None, 'questionType': None,
            'choices': [], 'givenData': [p['quote'] for p in data], 'contextOrigins': [],
            'proofs': [deepcopy(origin), *[deepcopy(r['origin']) for r in requirements], *deepcopy(list(data))],
            'requirements': deepcopy(list(requirements))}


def response(*items):
    return {'disposition': 'readable', 'pageRole': 'questions', 'paper': None,
            'items': list(items), 'sharedContexts': [], 'topics': []}


def fixture():
    data = manifest('Question 1:\n1. Draw the tree.\n2. State the output.\nint x = 1;\nQuestion 2:\nExplain memory.\n')
    one = question(span(data, 'Question 1:'), [requirement(span(data, '1. Draw the tree.')),
                   requirement(span(data, '2. State the output.'))], label='Question 1:', data=[span(data, 'int x = 1;')])
    two = question(span(data, 'Question 2:'), [requirement(span(data, 'Explain memory.'))], label='Question 2:')
    first = response(one, two)
    return data, first, deepcopy(first)


def test_pairs_follow_original_question_and_requirement_locations_not_array_order():
    data, first, second = fixture()
    second['items'].reverse()
    second['items'][1]['requirements'].reverse()
    value = comparison(data, first, second).describe()
    pairs = {row['firstId']: row for row in value['pairs']}
    assert pairs['A/items/0']['secondId'] == 'B/items/1'
    assert pairs['A/items/0/requirements/0']['secondId'] == 'B/items/1/requirements/1'
    assert pairs['A/items/1/requirements/0']['secondId'] == 'B/items/0/requirements/0'
    assert value['unmatchedFirst'] == value['unmatchedSecond'] == []
    assert pairs['A/items/0']['differingFields'] == []


def test_missing_label_and_changed_requirement_category_are_visible_even_with_identical_source_origins():
    data, first, second = fixture()
    first['items'][1]['printedLabel'] = None
    second['items'][0]['requirements'][0]['category'] = 'concept'
    value = comparison(data, first, second).describe()
    pairs = {row['firstId']: row for row in value['pairs']}
    assert pairs['A/items/1']['differingFields'] == ['printedLabel']
    assert pairs['A/items/0/requirements/0']['differingFields'] == ['category']
    assert 'accepted' not in value


def test_identical_text_from_another_question_does_not_satisfy_a_missing_requirement():
    data, first, second = fixture()
    first['items'][0]['requirements'] = []
    first['items'][1]['requirements'].append(requirement(span(data, '1. Draw the tree.')))
    check = comparison(data, first, second)
    assert check.claim_present('A/items/0', 'requirements', span(data, '1. Draw the tree.')) is False
    assert check.claim_present('A/items/1', 'requirements', span(data, '1. Draw the tree.')) is True


def test_saved_label_and_numbered_requirement_cannot_be_claimed_literally_missing():
    data, first, second = fixture()
    check = comparison(data, first, second)
    assert check.claim_present('A/items/0', 'printedLabel', span(data, 'Question 1:')) is True
    assert check.claim_present('A/items/0', 'requirements', span(data, '1. Draw the tree.')) is True
    assert check.claim_present('A/items/0/requirements/1', 'text', span(data, '2. State the output.')) is True
    assert check.claim_present('A/items/0', 'text', span(data, '1. Draw the tree.')) is False


def test_literal_presence_requires_own_field_evidence_not_merely_matching_text():
    data, first, second = fixture()
    first['items'][0]['requirements'][0]['proofs'] = [span(data, '2. State the output.')]
    check = comparison(data, first, second)
    assert check.claim_present('A/items/0', 'requirements', span(data, '1. Draw the tree.')) is False


def test_nonacademic_caption_cannot_replace_page_classification_fact():
    data, first, second = fixture()
    caption = question(span(data, 'int x = 1;'))
    caption['itemType'] = 'nonacademic'
    first['items'].insert(0, caption)
    check = comparison(data, first, second)
    assert check.field_value('A/classification', 'disposition') == 'readable'
    assert check.field_value('A/classification', 'pageRole') == 'questions'
    assert check.field_value('A/items/0', 'itemType') == 'nonacademic'
    with pytest.raises(ValueError, match='field'):
        check.field_value('A/classification', 'itemType')


def test_requirement_with_changed_owner_is_not_matched_to_other_questions_same_source_requirement():
    data, first, second = fixture()
    moved = second['items'][0]['requirements'].pop(0)
    second['items'][1]['requirements'].append(moved)
    value = comparison(data, first, second).describe()
    assert 'A/items/0/requirements/0' in value['unmatchedFirst']
    assert 'B/items/1/requirements/1' in value['unmatchedSecond']


def test_changed_parent_prevents_an_automatic_item_pair():
    data, first, second = fixture()
    first['items'][1]['itemType'] = second['items'][1]['itemType'] = 'subpart'
    first['items'][1]['parent'] = {'itemType': 'question', 'origin': deepcopy(first['items'][0]['origin'])}
    second['items'][1]['parent'] = {'itemType': 'question', 'origin': span(data, 'int x = 1;')}
    value = comparison(data, first, second).describe()
    assert 'A/items/1' in value['unmatchedFirst']
    assert 'B/items/1' in value['unmatchedSecond']


def test_ambiguous_duplicate_source_identities_are_not_collapsed():
    data, first, second = fixture()
    second['items'].append(deepcopy(second['items'][0]))
    value = comparison(data, first, second).describe()
    assert 'A/items/0' in value['unmatchedFirst']
    assert all(row['firstId'] != 'A/items/0' for row in value['pairs'])


def test_subparts_wait_for_a_unique_parent_pair_even_when_parent_appears_later():
    data, first, second = fixture()
    for value in (first, second):
        value['items'][1]['itemType'] = 'subpart'
        value['items'][1]['parent'] = {'itemType': 'question', 'origin': deepcopy(value['items'][0]['origin'])}
        value['items'].reverse()
    check = comparison(data, first, second).describe()
    assert any(pair['firstId'] == 'A/items/0' for pair in check['pairs'])
    second['items'].append(deepcopy(second['items'][1]))
    check = comparison(data, first, second).describe()
    assert 'A/items/0' in check['unmatchedFirst']


def test_topic_cannot_pair_through_an_ambiguously_duplicated_question():
    data, first, second = fixture()
    topic = {'text': 'Process trees', 'items': [{'itemType': 'question', 'origin': span(data, 'Question 1:')}],
             'requirements': [{key: deepcopy(value) for key, value in first['items'][0]['requirements'][0].items()
                               if key != 'proofs'}], 'proofs': [span(data, '1. Draw the tree.')]}
    first['topics'] = [deepcopy(topic)]
    second['topics'] = [deepcopy(topic)]
    assert any(pair['firstId'] == 'A/topics/0' for pair in comparison(data, first, second).describe()['pairs'])
    second['items'].append(deepcopy(second['items'][0]))
    assert 'A/topics/0' in comparison(data, first, second).describe()['unmatchedFirst']


def test_source_proven_outer_whitespace_can_pair_addresses_but_never_rewrite_values():
    data = manifest('  Question 1: Explain forks.\n')
    first = response(question(span(data, 'Question 1: Explain forks.')))
    second = response(question(span(data, '  Question 1: Explain forks.\n')))
    before = deepcopy((first, second))
    check = comparison(data, first, second)
    pair = next(row for row in check.describe()['pairs'] if row['firstId'] == 'A/items/0')
    assert pair['secondId'] == 'B/items/0'
    assert 'text' in pair['differingFields']
    assert check.field_value('B/items/0', 'text') == '  Question 1: Explain forks.\n'
    assert (first, second) == before


@pytest.mark.parametrize('replacement', ['int x=1;', 'int x = 2;', 'int x = 1;\\n'])
def test_code_whitespace_operators_numbers_and_escapes_remain_exact_differences(replacement):
    data, first, second = fixture()
    second['items'][0]['givenData'] = [replacement]
    check = comparison(data, first, second)
    pair = next(row for row in check.describe()['pairs'] if row['firstId'] == 'A/items/0')
    assert 'givenData' in pair['differingFields']
    assert check.field_value('A/items/0', 'givenData') == ['int x = 1;']


@pytest.mark.parametrize('mutation', ['revision', 'quote', 'offset', 'outside_current'])
def test_forged_or_context_only_missing_claim_proofs_are_rejected(mutation):
    data, first, second = fixture()
    proof = span(data, 'Question 1:')
    source = source_plan(data, 1)[0]
    if mutation == 'revision': proof['ref']['sourceRevision'] = 'f' * 64
    elif mutation == 'quote': proof['quote'] = 'Question 9:'
    elif mutation == 'offset': proof['start'] += 1
    else: source['ranges'] = [{'field': 'text', 'start': 12, 'end': len(data['units'][0]['text']), 'text': data['units'][0]['text'][12:]}]
    check = comparison(data, first, second, source)
    with pytest.raises(ValueError):
        check.claim_present('A/items/0', 'printedLabel', proof)


def test_public_values_and_comparison_bindings_do_not_leak_mutation():
    data, first, second = fixture()
    check = comparison(data, first, second)
    value = check.field_value('A/items/0', 'givenData')
    value.clear()
    shown = check.describe()
    shown['pairs'].clear()
    assert check.field_value('A/items/0', 'givenData') == ['int x = 1;']
    assert check.describe()['pairs']
    changed = deepcopy(second)
    changed['items'][0]['printedMarks'] = 10
    assert comparison(data, first, changed).describe()['bindings'] != check.describe()['bindings']


def test_matching_incomplete_inventories_do_not_claim_source_completeness():
    data, first, _ = fixture()
    first['items'][0]['requirements'] = []
    value = comparison(data, first, deepcopy(first)).describe()
    assert all(not pair['differingFields'] for pair in value['pairs'])
    assert 'complete' not in value
    assert 'accepted' not in value
    assert 'coverage' not in value


def test_equal_math_text_from_a_different_source_position_cannot_prove_literal_presence():
    data = manifest('Question 1:\nx = 2\nQuestion 2:\nx = 2\n')
    text = data['units'][0]['text']
    first_math = span(data, 'x = 2')
    second_math = span(data, 'x = 2', start=text.rindex('x = 2'))
    first = response(question(span(data, 'Question 1:'), [requirement(first_math)]),
                     question(span(data, 'Question 2:'), [requirement(second_math)]))
    check = comparison(data, first, deepcopy(first))
    assert check.claim_present('A/items/0', 'requirements', first_math) is True
    assert check.claim_present('A/items/0', 'requirements', second_math) is False


def test_source_windows_and_untrusted_origins_are_checked_against_the_immutable_manifest():
    data, first, second = fixture()
    second['items'][0]['origin']['quote'] = 'Question 9:'
    with pytest.raises(ValueError, match='original source span'):
        comparison(data, first, second)
    source = deepcopy(source_plan(data, 1)[0])
    source['ranges'][0]['text'] = 'X' * len(source['ranges'][0]['text'])
    with pytest.raises(ValueError, match='original source span'):
        comparison(data, first, deepcopy(first), source)


@pytest.mark.parametrize('field,obligation_id,quote', [
    ('printedLabel', 'A/items/0', 'Question 1:\n'),
    ('requirements', 'A/items/0', '  1. Draw the tree.\n'),
    ('text', 'A/items/0/requirements/0', '  1. Draw the tree.\n'),
])
def test_original_outer_whitespace_cannot_make_retained_label_or_owned_requirement_missing(field, obligation_id, quote):
    data = manifest('Question 1:\n  1. Draw the tree.\n')
    first = response(question(span(data, 'Question 1:'),
        [requirement(span(data, '1. Draw the tree.'))], label='Question 1:'))
    before = deepcopy(first)
    check = comparison(data, first, deepcopy(first))
    assert check.claim_present(obligation_id, field, span(data, quote)) is True
    assert first == before
    assert check.field_value('A/items/0/requirements/0', 'text') == '1. Draw the tree.'


@pytest.mark.parametrize('field', ['givenData', 'choices', 'text'])
def test_outer_whitespace_contradiction_rule_does_not_normalize_code_choices_or_item_stems(field):
    data = manifest('Question 1:\n  int x = 1;\n')
    source = span(data, '  int x = 1;\n')
    first = response(question(span(data, 'Question 1:'), data=[span(data, 'int x = 1;')]))
    first['items'][0][field] = 'int x = 1;' if field == 'text' else ['int x = 1;']
    check = comparison(data, first, deepcopy(first))
    assert check.claim_present('A/items/0', field, source) is False


def test_outer_whitespace_presence_still_requires_same_source_position_and_exact_internal_math():
    data = manifest('Question 1:\n  x = 2\nQuestion 2:\n  x = 2\n')
    first_math = span(data, 'x = 2')
    second_start = data['units'][0]['text'].rindex('  x = 2\n')
    first = response(question(span(data, 'Question 1:'), [requirement(first_math)]))
    check = comparison(data, first, deepcopy(first))
    assert check.claim_present('A/items/0', 'requirements', span(data, '  x = 2\n', start=second_start)) is False
    first['items'][0]['requirements'][0]['text'] = 'x=2'
    check = comparison(data, first, deepcopy(first))
    assert check.claim_present('A/items/0', 'requirements', span(data, '  x = 2\n')) is False
