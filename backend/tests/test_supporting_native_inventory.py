"""The native transport selects originals; it cannot rewrite their contents."""
from copy import deepcopy
import importlib
import re

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.supporting.contracts import source_coverage, supporting_revision
from src.supporting.extraction_source import source_plan, previous_evidence
from src.supporting.extraction_inventory import inventory, validate_response


def api():
    assert importlib.util.find_spec('src.supporting.native_inventory') is not None, 'Native source selector adapter is missing'
    return importlib.import_module('src.supporting.native_inventory')


def manifest(*texts):
    units = [{'unitId': f'p{i:04}', 'position': i, 'kind': 'page', 'text': text,
              'visualText': '', 'visualAssets': [{'assetId': f'p{i:04}-page', 'kind': 'page', 'mimeType': 'image/png'}],
              'timing': None, 'disposition': 'readable'} for i, text in enumerate(texts, 1)]
    return {'version': 1, 'identity': {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'tutorial'},
            'originalDigest': 'a' * 64, 'extractorVersion': 1, 'fileType': 'pdf', 'units': units,
            'sourceRevision': supporting_revision('a' * 64, units), 'coverage': source_coverage(units)}


def adapter(data, number=0, earlier=()):
    return api().NativeInventory(data, source_plan(data, 1)[number], earlier)


def selection(native, first, last=None, *, quote=None, data=False):
    lines = native.envelope()['current']['ranges'][0]['lines']
    ids = {row['line']: row['id'] for row in lines}
    result = {'firstLine': ids[first], 'lastLine': ids[last or first]}
    if not data:
        result['quote'] = quote
    return result


def question(stem, *, parts=(), **overrides):
    value = {'continuationOf': None, 'stem': stem, 'printedLabel': None, 'printedMarks': None,
             'questionType': None, 'givenData': [], 'choices': [], 'contextKeys': [], 'requirements': [],
             'subparts': list(parts)}
    value.update(overrides)
    return value


def subpart(stem, **overrides):
    result = question(stem, **overrides)
    result.pop('subparts')
    return result


def response(*questions, headings=(), contexts=()):
    return {'needsRichExtraction': False, 'pageRole': 'questions', 'headings': list(headings),
            'sharedContexts': list(contexts), 'questions': list(questions)}


def req(source, category='operation'):
    return {'source': source, 'category': category}


@pytest.mark.parametrize(('stem', 'label'), [
    ('  Question 2: State the output.\r\n', 'Question 2:'),
    ('question 12 : Explain the result.\n', 'question 12 :'),
    ('السؤال ٢: اشرح الناتج.\n', 'السؤال ٢:'),
    ('السؤال الثاني: اشرح الناتج.\n', 'السؤال الثاني:'),
    ('السؤال الأول: اشرح الناتج.\n', 'السؤال الأول:'),
])
def test_missing_explicit_question_label_is_restored_with_exact_current_proof(stem, label):
    native = adapter(manifest(stem))
    selected = selection(native, 1)
    wire = response(question(selected, requirements=[req(selected)]))
    original = deepcopy(wire)

    decoded = native.decode(wire)

    row = decoded['items'][0]
    assert row['printedLabel'] == label
    assert row['text'] == stem
    assert row['printedMarks'] is None
    assert row['questionType'] is None
    proof = next(proof for proof in row['proofs'] if proof['quote'] == label)
    assert proof['type'] == 'text_span'
    assert proof['ref'] == row['origin']['ref']
    assert proof['start'] == (2 if stem.startswith('  ') else 0)
    assert stem[proof['start']:proof['end']] == label
    assert wire == original


@pytest.mark.parametrize('stem', [
    'Find n.\n',
    'Q2: Find n.\n',
    'Question 2 asks for the output.\n',
    'Question 2 (5 marks)\n',
    'Question II: Find n.\n',
    'Refer to Question 2: Find n.\n',
    'السؤال التالي: اشرح الناتج.\n',
    'Question 1: Find n.\nQuestion 2: Find m.\n',
    'Question 1: Find n. Question 2: Find m.\n',
])
def test_absent_or_ambiguous_question_labels_stay_unknown(stem):
    native = adapter(manifest(stem))
    selected = selection(native, 1, len(stem.splitlines()))

    decoded = native.decode(response(question(selected, requirements=[req(selected)])))

    assert decoded['items'][0]['printedLabel'] is None
    assert decoded['items'][0]['text'] == stem


def test_question_words_selected_from_inside_code_do_not_infer_a_printed_label():
    native = adapter(manifest('printf("Question 2: Find n.");\n'))
    stem = selection(native, 1, quote='Question 2: Find n.')

    decoded = native.decode(response(question(stem, requirements=[req(stem)],
                    givenData=[selection(native, 1, data=True)])))

    assert decoded['items'][0]['printedLabel'] is None
    assert decoded['items'][0]['givenData'] == ['printf("Question 2: Find n.");\n']


def test_printed_subpart_and_parent_marks_are_not_guessed_from_task_prefixes():
    native = adapter(manifest('Question 1 (8 marks)\n(a) Find n.\n'))
    part = selection(native, 2)

    decoded = native.decode(response(question(selection(native, 1), printedMarks=8,
        parts=[subpart(part, requirements=[req(part)])])))

    parent, child = decoded['items']
    assert parent['printedLabel'] is None
    assert child['printedLabel'] is None
    assert parent['printedMarks'] == 8
    assert child['printedMarks'] is None


@pytest.mark.parametrize('stem', [
    'Question 1: For each program, state the output.\n',
    'السؤال الثاني: اشرح ناتج البرنامج.\n',
])
def test_printed_label_cannot_swallow_the_question_task_wording(stem):
    native = adapter(manifest(stem))
    selected = selection(native, 1)
    value = response(question(selected, printedLabel=selected, requirements=[req(selected)]))

    with pytest.raises(ValueError, match='printed label') as error:
        native.decode(value)

    feedback = native.repair_feedback(value, error.value)
    assert stem.split(':', 1)[0] + ':' in feedback
    assert 'task wording' in feedback


@pytest.mark.parametrize('label', ['Question 2', 'Question 2:'])
def test_correct_supplied_question_label_preserves_its_exact_printed_form(label):
    native = adapter(manifest('Question 2: Find n.\n'))
    selected = selection(native, 1)

    decoded = native.decode(response(question(selected, printedLabel=selection(native, 1, quote=label),
                                              requirements=[req(selected)])))

    assert decoded['items'][0]['printedLabel'] == label


def test_label_recovery_preserves_accepted_legacy_continuation_metadata():
    first_stem = 'Question 1: State the first output.\n'
    data = manifest(first_stem, 'Question 1: State the next output.\n')
    first = adapter(data)
    selected = selection(first, 1)
    earlier = first.decode(response(question(selected, requirements=[req(selected)])))
    # Pending v5 checkpoints can contain the old overly broad source-backed label.
    earlier['items'][0]['printedLabel'] = first_stem
    second = adapter(data, 1, [earlier])
    handle = second.envelope()['knownQuestions'][0]['handle']
    current = selection(second, 1)

    decoded = second.decode(response(question(current, continuationOf=handle,
                                               requirements=[req(current)])))

    assert decoded['items'][0]['printedLabel'] == first_stem
    assert decoded['items'][0]['origin'] == earlier['items'][0]['origin']
    assert decoded['items'][0]['text'] == 'Question 1: State the next output.\n'


def test_selector_retains_complete_code_and_real_tasks_through_three_page_merge():
    first_program = '// Code 1\nint main() {\n  printf("value = %d\\n", 5);\n}\n'
    second_program = '// Code 2\nfor (int i=1; i<=3; i++) {\n\n  printf("i=%d\\n", i);\n}\n'
    third_program = 'int nums[] = {0, 1};\nprintf("%d\\n", nums[0]);\n'
    data = manifest('Tutorial 1\nProcesses\nQuestion 1 (8 marks)\n(a) Draw the tree.\n(b) State the output.\n' + first_program,
                    second_program, 'Question 2: State the output.\n' + third_program)
    one = adapter(data)
    parts = [subpart(selection(one, n), printedLabel=selection(one, n, quote=label),
                     requirements=[req(selection(one, n, quote=task))])
             for n, label, task in [(4, '(a)', 'Draw the tree.'), (5, '(b)', 'State the output.')]]
    first = one.decode(response(question(selection(one, 3), parts=parts,
                        printedLabel=selection(one, 3, quote='Question 1'), printedMarks=8, questionType='code',
                        givenData=[selection(one, 6, 9, data=True)]),
                        headings=[{'source': selection(one, 1), 'academic': False},
                                  {'source': selection(one, 2), 'academic': True}]))
    two = adapter(data, 1, [first])
    handle = next(row['handle'] for row in two.envelope()['knownQuestions'] if row['itemType'] == 'question')
    second = two.decode(response(question(None, continuationOf=handle,
                                         givenData=[selection(two, 1, 5, data=True)])))
    three = adapter(data, 2, [first, second])
    third = three.decode(response(question(selection(three, 1), printedLabel=selection(three, 1, quote='Question 2'),
                          questionType='code', givenData=[selection(three, 2, 3, data=True)],
                          requirements=[req(selection(three, 1, quote='State the output.'))])))
    plan = source_plan(data, 1)
    rows = [first, second, third]
    for index, row in enumerate(rows):
        validate_response(row, data, plan[index], previous_evidence(plan, index), rows[:index])
    result, errors = inventory(data, plan, {str(i): row for i, row in enumerate(rows)})
    assert errors == {}
    questions = [row for row in result['items'] if row['itemType'] == 'question']
    assert len(questions) == 2
    assert questions[0]['givenData'] == [first_program, second_program]
    assert questions[0]['printedLabel'] == 'Question 1'
    assert questions[0]['printedMarks'] == 8
    assert questions[0]['questionType'] == 'code'
    assert questions[1]['givenData'] == [third_program]
    assert [row['text'] for row in result['items'] if row['itemType'] == 'subpart'] == ['(a) Draw the tree.\n', '(b) State the output.\n']
    assert len(result['topics']) == 1


def test_shared_context_choices_and_same_line_parts_keep_distinct_original_origins():
    data = manifest('Assume n=7.\nQuestion 1 (4 marks)\n(a) Find n. (b) Explain n.\nA: seven\nB: eight\n')
    native = adapter(data)
    q = question(selection(native, 2), printedLabel=selection(native, 2, quote='Question 1'), printedMarks=4,
                 contextKeys=['scenario'], choices=[selection(native, 4), selection(native, 5)],
                 parts=[subpart(selection(native, 3, quote='(a) Find n.'),
                                requirements=[req(selection(native, 3, quote='Find n.'))]),
                        subpart(selection(native, 3, quote='(b) Explain n.'),
                                requirements=[req(selection(native, 3, quote='Explain n.'), 'concept')])])
    value = native.decode(response(q, contexts=[{'key': 'scenario', 'continuationOf': None, 'source': selection(native, 1)}]))
    assert value['sharedContexts'][0]['text'] == 'Assume n=7.\n'
    assert value['items'][0]['choices'] == ['A: seven\n', 'B: eight\n']
    assert len({row['origin']['start'] for row in value['items']}) == 3
    assert value['items'][0]['contextOrigins'] == [value['sharedContexts'][0]['origin']]


def test_unknown_prior_question_and_previous_page_selectors_cannot_create_current_content():
    data = manifest('Question 1: Explain trees.\n', 'Question 2: Explain trees.\n')
    one, two = adapter(data), adapter(data, 1)
    with pytest.raises(ValueError, match='line|selector|Unknown'):
        two.decode(response(question(selection(one, 1), requirements=[req(selection(one, 1))])))
    with pytest.raises(ValueError, match='continuation|handle|Unknown'):
        two.decode(response(question(selection(two, 1), continuationOf='Question 1', requirements=[req(selection(two, 1))])))


@pytest.mark.parametrize('quote', ['Find n.', 'Find m.', 'find n.'])
def test_ambiguous_or_modified_task_quote_is_rejected(quote):
    native = adapter(manifest('Question 1: Find n. Find n.\n'))
    with pytest.raises(ValueError, match='quote|ambiguous|found'):
        native.decode(response(question(selection(native, 1), requirements=[req(selection(native, 1, quote=quote))])))


def test_unselected_current_source_text_cannot_be_silently_lost():
    native = adapter(manifest('Question 1: Explain trees.\nUse height three.\n'))
    with pytest.raises(ValueError, match='coverage|unselected|retained'):
        native.decode(response(question(selection(native, 1), requirements=[req(selection(native, 1))])))


def test_heading_cannot_exclude_or_duplicate_a_question_stem():
    native = adapter(manifest('Question 1: Explain trees.\n'))
    for academic in (False, True):
        with pytest.raises(ValueError, match='heading.*overlap|overlap.*heading'):
            native.decode(response(question(selection(native, 1), requirements=[req(selection(native, 1))]),
                                   headings=[{'source': selection(native, 1), 'academic': academic}]))


@pytest.mark.parametrize('damage', ['category', 'duplicate_context', 'unknown_context', 'extra_field', 'nested_part'])
def test_malformed_semantic_structure_is_rejected_before_acceptance(damage):
    native = adapter(manifest('Question 1: Explain trees.\n'))
    value = response(question(selection(native, 1), requirements=[req(selection(native, 1))]))
    if damage == 'category':
        value['questions'][0]['requirements'][0].pop('category')
    elif damage == 'duplicate_context':
        context = {'key': 'c', 'continuationOf': None, 'source': selection(native, 1)}
        value['sharedContexts'] = [context, deepcopy(context)]
    elif damage == 'unknown_context':
        value['questions'][0]['contextKeys'] = ['absent']
    elif damage == 'extra_field':
        value['questions'][0]['madeUp'] = True
    else:
        value['questions'][0]['subparts'] = [question(selection(native, 1))]
    with pytest.raises(ValueError):
        native.decode(value)


def test_explicit_visual_fallback_never_turns_into_an_empty_accepted_inventory():
    native = adapter(manifest('Question 1: Interpret the graph.\n'))
    value = response()
    value['needsRichExtraction'] = True
    with pytest.raises(api().NeedsRichExtraction):
        native.decode(value)


def test_eligibility_rejects_partial_or_non_native_windows_without_changing_sources():
    data = manifest('Question 1: Explain trees.\n')
    source = source_plan(data, 1)[0]
    assert api().eligible(data, source)
    assert source == source_plan(data, 1)[0]
    for key, replacement in [('fileType', 'image'), ('fileType', 'docx')]:
        changed = deepcopy(data)
        changed[key] = replacement
        assert not api().eligible(changed, source)
    partial = deepcopy(source)
    partial['ranges'][0]['text'] = partial['ranges'][0]['text'][1:]
    partial['ranges'][0]['start'] = 1
    assert not api().eligible(data, partial)
    missing_image = deepcopy(source)
    missing_image['assetIds'] = []
    assert not api().eligible(data, missing_image)


def test_schema_and_envelope_retain_only_supplied_current_selectors_and_detached_metadata():
    native = adapter(manifest('Question 1: Explain trees.\n'))
    before = native.envelope()
    wire_schema = native.schema()
    current_ids = {line['id'] for row in before['current']['ranges'] for line in row['lines']}
    assert set(wire_schema['$defs']['range']['properties']['firstLine']['enum']) == current_ids
    before['current']['ranges'][0]['text'] = 'changed'
    assert native.envelope()['current']['ranges'][0]['text'] == 'Question 1: Explain trees.\n'


@pytest.mark.parametrize('item_type', ['question', 'subpart'])
@pytest.mark.parametrize('known', [False, True])
def test_new_record_schema_requires_an_original_stem_even_when_continuations_exist(item_type, known):
    data = manifest('Question 1\n(a) State the output.\n', 'Question 2\n(b) State the next output.\n')
    first = adapter(data)
    prior = first.decode(response(question(selection(first, 1), parts=[
        subpart(selection(first, 2), requirements=[req(selection(first, 2))])])))
    native = adapter(data, 1, [prior]) if known else first
    if item_type == 'question':
        value = response(question(None, givenData=[selection(native, 1, 2, data=True)]))
    else:
        value = response(question(selection(native, 1), parts=[
            subpart(None, givenData=[selection(native, 2, data=True)])]))
    schema = native.schema()
    Draft202012Validator.check_schema(schema)

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize('item_type', ['question', 'subpart'])
def test_known_continuation_schema_still_allows_data_only_fragments(item_type):
    data = manifest('Question 1\n(a) State the output.\n', 'int next = 2;\n')
    first = adapter(data)
    prior = first.decode(response(question(selection(first, 1), parts=[
        subpart(selection(first, 2), requirements=[req(selection(first, 2))])])))
    native = adapter(data, 1, [prior])
    handles = {row['itemType']: row['handle'] for row in native.envelope()['knownQuestions']}
    fragment = {'continuationOf': handles[item_type], 'givenData': [selection(native, 1, data=True)]}
    value = response(question(None, **fragment) if item_type == 'question' else
                     question(None, continuationOf=handles['question'], parts=[subpart(None, **fragment)]))
    schema = native.schema()
    Draft202012Validator.check_schema(schema)

    Draft202012Validator(schema).validate(value)
    decoded = native.decode(value)

    assert decoded['items'][0]['itemType'] == item_type
    assert decoded['items'][0]['givenData'] == ['int next = 2;\n']
    assert decoded['items'][0]['origin'] == prior['items'][0 if item_type == 'question' else 1]['origin']


def test_new_record_schema_with_known_handles_preserves_exact_current_source_selectors():
    data = manifest('Question 1: Find n.\n', 'Question 2: Find m.\n')
    first = adapter(data)
    prior = first.decode(response(question(selection(first, 1), requirements=[req(selection(first, 1))])))
    native = adapter(data, 1, [prior])
    selected = selection(native, 1)
    value = response(question(selected, requirements=[req(selected)]))
    validator = Draft202012Validator(native.schema())

    validator.validate(value)
    decoded = native.decode(value)

    assert decoded['items'][0]['origin']['ref']['unitId'] == 'p0002'
    assert decoded['items'][0]['text'] == 'Question 2: Find m.\n'
    value['questions'][0]['stem'] = selection(first, 1)
    with pytest.raises(ValidationError):
        validator.validate(value)


def test_schema_keeps_explicit_rich_fallback_with_no_fabricated_questions():
    native = adapter(manifest('Interpret the diagram.\n'))
    value = response()
    value['needsRichExtraction'] = True

    Draft202012Validator(native.schema()).validate(value)

    with pytest.raises(api().NeedsRichExtraction):
        native.decode(value)


def test_context_only_continuation_page_remains_readable_not_a_nonacademic_exclusion():
    data = manifest('Assume a tree with height three.\n')
    native = adapter(data)
    value = response(contexts=[{'key': 'scenario', 'continuationOf': None, 'source': selection(native, 1)}])
    value['pageRole'] = 'other'
    decoded = native.decode(value)
    assert decoded['disposition'] == 'readable'
    assert decoded['sharedContexts'][0]['text'] == 'Assume a tree with height three.\n'


def test_continued_subpart_uses_parent_identity_instead_of_parent_quote_length():
    data = manifest('Question 1\n(a) State the output.\n', 'More data for (a).\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 1), parts=[
        subpart(selection(one, 2), requirements=[req(selection(one, 2))])])) )
    # A valid legacy parent link can cite a shorter quote at the same origin.
    first['items'][1]['parent']['origin']['quote'] = 'Question'
    first['items'][1]['parent']['origin']['end'] = 8
    two = adapter(data, 1, [first])
    handles = {row['itemType']: row['handle'] for row in two.envelope()['knownQuestions']}
    decoded = two.decode(response(question(None, continuationOf=handles['question'], parts=[
        subpart(None, continuationOf=handles['subpart'], givenData=[selection(two, 1, data=True)])])))
    assert len(decoded['items']) == 1
    assert decoded['items'][0]['parent'] == first['items'][1]['parent']
    result, errors = inventory(data, source_plan(data, 1), {'0': first, '1': decoded})
    assert errors == {}
    assert next(row for row in result['items'] if row['itemType'] == 'subpart')['givenData'] == ['More data for (a).\n']


@pytest.mark.parametrize('marks', [True, -1, float('nan'), float('inf'), '1'])
def test_invalid_continued_marks_cannot_be_hidden_by_inherited_metadata(marks):
    data = manifest('Question 1 (1 mark): Explain trees.\n', 'More data.\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 1), printedMarks=1, requirements=[req(selection(one, 1))])))
    two = adapter(data, 1, [first])
    handle = two.envelope()['knownQuestions'][0]['handle']
    with pytest.raises(ValueError, match='marks|Marks|number'):
        two.decode(response(question(None, continuationOf=handle, printedMarks=marks,
                                     givenData=[selection(two, 1, data=True)])))


def test_a_repeated_printed_label_does_not_choose_a_prior_question():
    data = manifest('Question 1: Explain trees.\n', 'Question 1: Explain graphs.\n', 'More graph data.\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 1), printedLabel=selection(one, 1, quote='Question 1'),
                                        requirements=[req(selection(one, 1))])))
    two = adapter(data, 1, [first])
    second = two.decode(response(question(selection(two, 1), printedLabel=selection(two, 1, quote='Question 1'),
                                         requirements=[req(selection(two, 1))])))
    three = adapter(data, 2, [first, second])
    handles = three.envelope()['knownQuestions']
    assert len({row['handle'] for row in handles}) == 2
    chosen = next(row['handle'] for row in handles if row['originPosition'] == 2)
    third = three.decode(response(question(None, continuationOf=chosen, givenData=[selection(three, 1, data=True)])))
    assert third['items'][0]['origin'] == second['items'][0]['origin']


def test_prior_shared_context_handles_preserve_the_original_link_without_recopied_current_data():
    data = manifest('Assume n=7.\nQuestion 1: Find n.\n', 'Question 2: Explain n.\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 2), contextKeys=['scenario'], requirements=[req(selection(one, 2))]),
                                contexts=[{'key': 'scenario', 'continuationOf': None, 'source': selection(one, 1)}]))
    two = adapter(data, 1, [first])
    key = two.envelope()['knownContexts'][0]['handle']
    second = two.decode(response(question(selection(two, 1), contextKeys=[key], requirements=[req(selection(two, 1))])))
    assert second['sharedContexts'] == []
    assert second['items'][0]['contextOrigins'] == [first['sharedContexts'][0]['origin']]
    assert all(proof['ref']['unitId'] == 'p0002' for proof in second['items'][0]['proofs'])


@pytest.mark.parametrize('same_line', [False, True])
def test_choices_only_continuation_preserves_original_text_metadata_and_existing_requirements(same_line):
    choices_text = 'A. One  B. Two\n' if same_line else 'A. One\nB. Two\n'
    data = manifest('Question 1 (3 marks): Select the answer.\n', choices_text)
    one = adapter(data)
    first = one.decode(response(question(selection(one, 1), printedLabel=selection(one, 1, quote='Question 1'),
                                        printedMarks=3, questionType='mcq',
                                        requirements=[req(selection(one, 1, quote='Select the answer.'))])))
    two = adapter(data, 1, [first])
    handle = two.envelope()['knownQuestions'][0]['handle']
    choices = ([selection(two, 1, quote='A. One'), selection(two, 1, quote='B. Two')] if same_line
               else [selection(two, 1), selection(two, 2)])
    second = two.decode(response(question(None, continuationOf=handle, choices=choices)))
    assert second['items'][0]['origin'] == first['items'][0]['origin']
    assert second['items'][0]['text'] == (choices_text.rstrip('\n') if same_line else choices_text)
    assert all(proof['ref']['unitId'] == 'p0002' for proof in second['items'][0]['proofs'])
    result, errors = inventory(data, source_plan(data, 1), {'0': first, '1': second})
    assert errors == {}
    merged = result['items'][0]
    assert merged['printedLabel'] == 'Question 1'
    assert merged['printedMarks'] == 3
    assert merged['questionType'] == 'mcq'
    assert merged['choices'] == (['A. One', 'B. Two'] if same_line else ['A. One\n', 'B. Two\n'])
    assert [row['text'] for row in merged['requirements']] == ['Select the answer.']


def test_requirement_only_continuation_explicitly_requests_rich_extraction():
    data = manifest('Question 1: Explain trees.\n', 'Also explain the result.\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 1), requirements=[req(selection(one, 1))])))
    two = adapter(data, 1, [first])
    handle = two.envelope()['knownQuestions'][0]['handle']
    with pytest.raises(api().NeedsRichExtraction, match='requirement|fragment'):
        two.decode(response(question(None, continuationOf=handle, requirements=[req(selection(two, 1))])))


def test_choices_only_continuation_does_not_copy_intervening_unrelated_heading_into_question():
    data = manifest('Question 1: Select the answer.\n', 'A. One\nContinued worksheet\nB. Two\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 1), requirements=[req(selection(one, 1))])))
    two = adapter(data, 1, [first])
    handle = two.envelope()['knownQuestions'][0]['handle']
    with pytest.raises(api().NeedsRichExtraction):
        two.decode(response(question(None, continuationOf=handle, choices=[selection(two, 1), selection(two, 3)]),
                            headings=[{'source': selection(two, 2), 'academic': False}]))


def test_new_context_schema_prevents_prior_handle_redeclaration_without_limiting_local_context_count():
    data = manifest('Assume n=7.\nQuestion 1: Find n.\n', 'Question 2: Explain n.\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 2), contextKeys=['scenario'], requirements=[req(selection(one, 2))]),
                                contexts=[{'key': 'scenario', 'continuationOf': None, 'source': selection(one, 1)}]))
    two = adapter(data, 1, [first])
    prior = two.envelope()['knownContexts'][0]['handle']
    schema = two.schema()
    declaration = schema['properties']['sharedContexts']['items']['properties']['key']
    pattern = declaration.get('pattern', '.*')
    assert re.fullmatch(pattern, prior) is None
    assert re.fullmatch(pattern, 'local_scenario_100000') is not None
    links = schema['$defs']['question']['properties']['contextKeys']['items']['anyOf']
    assert any(prior in branch.get('enum', []) for branch in links)
    assert any(re.fullmatch(branch['pattern'], 'local_scenario_100000') for branch in links if 'pattern' in branch)
    assert 'maxItems' not in schema['properties']['sharedContexts']


def test_pending_free_string_context_keys_still_decode_after_new_request_namespace_constraint():
    native = adapter(manifest('Assume n=7.\nQuestion 1: Find n.\n'))
    raw = response(question(selection(native, 2), contextKeys=['saved-v5-key'], requirements=[req(selection(native, 2))]),
                   contexts=[{'key': 'saved-v5-key', 'continuationOf': None, 'source': selection(native, 1)}])
    decoded = native.decode(raw)
    assert decoded['items'][0]['contextOrigins'] == [decoded['sharedContexts'][0]['origin']]
    assert decoded['sharedContexts'][0]['text'] == 'Assume n=7.\n'


def test_repair_feedback_reports_both_prior_context_collision_and_task_heading_overlap_without_mutating_claims():
    data = manifest('Assume n=7.\nQuestion 1: Find n.\n', 'Find the output.\n// Code 2\nprintf("%d\\n", n);\n')
    one = adapter(data)
    first = one.decode(response(question(selection(one, 2), contextKeys=['scenario'], requirements=[req(selection(one, 2))]),
                                contexts=[{'key': 'scenario', 'continuationOf': None, 'source': selection(one, 1)}]))
    two = adapter(data, 1, [first])
    prior = two.envelope()['knownContexts'][0]['handle']
    handle = two.envelope()['knownQuestions'][0]['handle']
    raw = response(question(selection(two, 1), continuationOf=handle, givenData=[selection(two, 2, 3, data=True)], contextKeys=[prior]),
                   contexts=[{'key': prior, 'continuationOf': None, 'source': selection(two, 1)}],
                   headings=[{'source': selection(two, 1), 'academic': False}])
    before = deepcopy(raw)
    with pytest.raises(ValueError) as failure:
        two.decode(raw)
    feedback = two.repair_feedback(raw, failure.value)
    assert 'sharedContexts[0].key' in feedback and prior in feedback and 'contextKeys' in feedback
    assert 'headings[0]' in feedback and 'questions[0].stem' in feedback and 'overlap' in feedback
    assert raw == before
    with pytest.raises(ValueError, match='context'):
        two.decode(raw)


def test_repair_feedback_identifies_duplicate_local_context_declarations():
    native = adapter(manifest('Assume n=7.\n'))
    context = {'key': 'local_scenario', 'continuationOf': None, 'source': selection(native, 1)}
    raw = response(contexts=[context, deepcopy(context)])
    feedback = native.repair_feedback(raw, ValueError('Invalid context key'))
    assert 'sharedContexts[1].key' in feedback and 'sharedContexts[0]' in feedback
    assert 'local_scenario' in feedback


def test_repair_feedback_uses_exact_subquotes_when_checking_subpart_overlap():
    native = adapter(manifest('Worksheet (a) Find n.\n'))
    raw = response(question(selection(native, 1, quote='(a) Find n.'), parts=[
        subpart(selection(native, 1, quote='Find n.'), requirements=[req(selection(native, 1, quote='Find n.'))])]),
        headings=[{'source': selection(native, 1, quote='Worksheet'), 'academic': False}])
    assert 'overlap' not in native.repair_feedback(raw, ValueError('Other contract issue'))
    raw['headings'][0]['source']['quote'] = 'Find n.'
    feedback = native.repair_feedback(raw, ValueError('Other contract issue'))
    assert 'headings[0]' in feedback and 'overlap' in feedback


@pytest.mark.parametrize('raw', [None, [], {'sharedContexts': [None, {'key': []}], 'headings': [None], 'questions': 'bad'}])
def test_repair_feedback_handles_malformed_rejected_json_without_another_failure(raw):
    native = adapter(manifest('Question 1: Find n.\n'))
    feedback = native.repair_feedback(raw, ValueError('Invalid original response'))
    assert 'Invalid original response' in feedback
    assert len(feedback) <= 1000


def test_nonacademic_caption_inside_complete_given_data_preserves_both_records_and_original_proofs():
    code = '// Code 2\nprintf("%d\\n", n);\n'
    native = adapter(manifest('Question 1: Find the output.\n' + code))
    raw = response(question(selection(native, 1), requirements=[req(selection(native, 1))],
                            givenData=[selection(native, 2, 3, data=True)]),
                   headings=[{'source': selection(native, 2, quote='// Code 2'), 'academic': False}])
    before = deepcopy(raw)
    decoded = native.decode(raw)
    assert raw == before
    assert len(decoded['items']) == 2
    caption, item = decoded['items']
    assert caption['itemType'] == 'nonacademic'
    assert caption['text'] == '// Code 2'
    assert caption['proofs'][0]['quote'] == '// Code 2'
    assert caption['requirements'] == []
    assert item['givenData'] == [code]
    assert code in [proof['quote'] for proof in item['proofs']]
    assert [r['text'] for r in item['requirements']] == ['Question 1: Find the output.\n']
    assert 'overlap' not in native.repair_feedback(raw, ValueError('Other contract issue'))


@pytest.mark.parametrize('task_field', ['stem', 'requirements', 'choices'])
def test_nonacademic_data_caption_exception_cannot_hide_overlapping_task_fields(task_field):
    native = adapter(manifest('Question 1: Find n.\nAnswer n.\n'))
    item = question(selection(native, 1), requirements=[req(selection(native, 1))],
                    givenData=[selection(native, 1, 2, data=True)])
    if task_field == 'stem':
        heading = selection(native, 1)
    elif task_field == 'requirements':
        item['requirements'].append(req(selection(native, 2)))
        heading = selection(native, 2)
    else:
        item['choices'] = [selection(native, 2)]
        heading = selection(native, 2)
    raw = response(item, headings=[{'source': heading, 'academic': False}])
    with pytest.raises(ValueError, match='heading.*overlap'):
        native.decode(raw)
    feedback = native.repair_feedback(raw, ValueError('Other contract issue'))
    assert 'overlap' in feedback and task_field in feedback


@pytest.mark.parametrize('academic', [False, True])
def test_caption_must_be_contained_in_every_overlapping_data_range(academic):
    native = adapter(manifest('Question 1: Find n.\nFirst data line\nSecond data line\nThird data line\n'))
    raw = response(question(selection(native, 1), requirements=[req(selection(native, 1))],
                            givenData=[selection(native, 2, 4, data=True), selection(native, 3, 4, data=True)]),
                   headings=[{'source': selection(native, 2, 3), 'academic': academic}])
    with pytest.raises(ValueError, match='heading.*overlap'):
        native.decode(raw)
    assert 'overlap' in native.repair_feedback(raw, ValueError('Other contract issue'))


def test_academic_heading_inside_given_data_is_still_rejected():
    native = adapter(manifest('Question 1: Find n.\nTree traversal\n'))
    raw = response(question(selection(native, 1), requirements=[req(selection(native, 1))],
                            givenData=[selection(native, 2, data=True)]),
                   headings=[{'source': selection(native, 2), 'academic': True}])
    with pytest.raises(ValueError, match='heading.*overlap'):
        native.decode(raw)

