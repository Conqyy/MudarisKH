from copy import deepcopy

import pytest

from src.supporting.contracts import validate_source_proof
from src.supporting.source_ranges import SourceRanges


REF = {'kind': 'tutorial', 'materialId': 'm', 'sourceRevision': 'a' * 64, 'unitId': 'p0001'}


def source(text, start=0, field='text'):
    return {'ref': deepcopy(REF), 'ranges': [{'field': field, 'start': start,
            'end': start + len(text), 'text': text}], 'assetIds': []}


def test_selected_code_restores_original_indentation_blank_lines_and_literal_escapes():
    original = 'Question 1\n  int main() {\n\n    printf("x\\n");\n  }\nNext question'
    registry = SourceRanges(source(original))
    presented = registry.presentation()
    assert presented['ranges'][0]['text'] == original
    lines = presented['ranges'][0]['lines']
    proof = registry.decode({'firstLine': lines[1]['id'], 'lastLine': lines[4]['id']})
    assert proof == {'type': 'text_span', 'ref': REF, 'field': 'text', 'start': 11, 'end': 50,
                     'quote': '  int main() {\n\n    printf("x\\n");\n  }\n'}
    assert validate_source_proof(proof, ref=REF, unit={'unitId': 'p0001', 'text': original}) == proof


def selection(registry, first=0, last=0, range_index=0):
    lines = registry.presentation()['ranges'][range_index]['lines']
    return {'firstLine': lines[first]['id'], 'lastLine': lines[last]['id']}


def test_physical_lines_do_not_split_code_statements_or_printed_list_markers():
    original = 'if (fork() == 0) { x = 1; y = 2; }\n1. First task. 2. Second task.'
    registry = SourceRanges(source(original))
    assert len(registry.presentation()['ranges'][0]['lines']) == 2
    assert registry.decode(selection(registry))['quote'] == 'if (fork() == 0) { x = 1; y = 2; }\n'


def test_unicode_offsets_and_crlf_are_preserved_at_nonzero_source_offset():
    original = 'مقدمة\r\nسؤال 😀؟\r\n  أ = ٢;\r\n'
    registry = SourceRanges(source(original, start=23))
    proof = registry.decode(selection(registry, 1, 1))
    assert proof == {'type': 'text_span', 'ref': REF, 'field': 'text',
                     'start': 30, 'end': 39, 'quote': 'سؤال 😀؟\r\n'}
    assert validate_source_proof(proof, ref=REF,
        unit={'unitId': 'p0001', 'text': ' ' * 23 + original}) == proof


@pytest.mark.parametrize(('key', 'value'), [
    ('unitId', 'p0002'), ('sourceRevision', 'b' * 64), ('materialId', 'other'),
])
def test_identical_text_cannot_reuse_line_ids_from_another_source(key, value):
    original = source('Same question\nSame code\n')
    first = SourceRanges(original)
    other = deepcopy(original)
    other['ref'][key] = value
    with pytest.raises(ValueError):
        SourceRanges(other).decode(selection(first, 0, 1))
    assert SourceRanges(original).presentation() == first.presentation()


@pytest.mark.parametrize('replacement', [
    {'field': 'text', 'start': 10, 'end': 15, 'text': 'Same\n'},
    {'field': 'visualText', 'start': 0, 'end': 5, 'text': 'Same\n'},
    {'field': 'text', 'start': 0, 'end': 11, 'text': 'Same\nExtra\n'},
    {'field': 'text', 'start': 0, 'end': 5, 'text': 'Else\n'},
])
def test_ids_are_bound_to_complete_supplied_range(replacement):
    first = SourceRanges(source('Same\n'))
    other = source('Same\n')
    other['ranges'] = [replacement]
    with pytest.raises(ValueError):
        SourceRanges(other).decode(selection(first))


@pytest.mark.parametrize('field', ['text', 'visualText'])
def test_selection_cannot_cross_ranges_even_when_endpoints_fit_original_text(field):
    current = source('First\nSecond\n')
    current['ranges'].append({'field': field, 'start': 6, 'end': 13, 'text': 'Second\n'})
    registry = SourceRanges(current)
    crossed = {'firstLine': selection(registry)['firstLine'],
               'lastLine': selection(registry, range_index=1)['lastLine']}
    with pytest.raises(ValueError):
        registry.decode(crossed)
    assert registry.decode(selection(registry, range_index=1))['quote'] == 'Second\n'


def test_reversed_line_selection_is_rejected_even_if_span_would_be_nonempty():
    registry = SourceRanges(source('First\nSecond\nThird\n'))
    with pytest.raises(ValueError):
        registry.decode(selection(registry, 2, 0))


def test_duplicate_supplied_ranges_are_rejected_instead_of_aliasing_selectors():
    current = source('Question\n')
    current['ranges'].append(deepcopy(current['ranges'][0]))
    with pytest.raises(ValueError):
        SourceRanges(current)


@pytest.mark.parametrize('invalid', [None, [], {}, {'firstLine': 'unknown'},
    {'firstLine': 'unknown', 'lastLine': 'unknown'},
    {'firstLine': [], 'lastLine': None},
])
def test_malformed_or_unknown_selections_raise_value_error(invalid):
    with pytest.raises(ValueError):
        SourceRanges(source('Question\n')).decode(invalid)


def test_selection_cannot_supply_extra_ref_or_quote_overrides():
    registry = SourceRanges(source('Question\n'))
    for key, value in [('quote', 'invented'), ('ref', {**REF, 'unitId': 'p0002'})]:
        with pytest.raises(ValueError):
            registry.decode({**selection(registry), key: value})


def test_blank_lines_can_join_content_but_are_not_valid_standalone_proofs():
    registry = SourceRanges(source('\n \t\nCode\n\n'))
    with pytest.raises(ValueError):
        registry.decode(selection(registry, 0, 1))
    assert registry.decode(selection(registry, 0, 3))['quote'] == '\n \t\nCode\n\n'


@pytest.mark.parametrize('ranges', [[], [{'field': 'text', 'start': 0, 'end': 0, 'text': ''}],
    [{'field': 'text', 'start': 0, 'end': 3, 'text': ' \n\t'}]])
def test_empty_or_whitespace_only_source_has_no_selectable_schema(ranges):
    current = source('')
    current['ranges'] = ranges
    registry = SourceRanges(current)
    assert registry.schema() is None
    assert [{key: span[key] for key in ('field', 'start', 'end', 'text')}
            for span in registry.presentation()['ranges']] == ranges


def test_schema_allows_only_registered_line_ids_and_exact_selector_fields():
    registry = SourceRanges(source('First\nSecond\n'))
    schema = registry.schema()
    ids = [line['id'] for line in registry.presentation()['ranges'][0]['lines']]
    assert schema == {'type': 'object', 'properties': {
        'firstLine': {'type': 'string', 'enum': ids},
        'lastLine': {'type': 'string', 'enum': ids}},
        'required': ['firstLine', 'lastLine'], 'additionalProperties': False}


def test_mutating_input_presentation_schema_or_decoded_proof_cannot_change_registry():
    current = source('Original\n')
    registry = SourceRanges(current)
    selected = selection(registry)
    presented = registry.presentation()
    presented['ref']['unitId'] = 'forged'
    presented['ranges'][0]['text'] = 'forged'
    presented['ranges'][0]['lines'][0]['start'] = 500
    current['ranges'][0]['text'] = 'forged'
    current['ref']['sourceRevision'] = 'b' * 64
    schema = registry.schema()
    schema['properties']['firstLine']['enum'].clear()
    proof = registry.decode(selected)
    proof['quote'] = 'forged'
    proof['ref']['unitId'] = 'forged'
    assert registry.decode(selected) == {'type': 'text_span', 'ref': REF, 'field': 'text',
                                        'start': 0, 'end': 9, 'quote': 'Original\n'}
    assert registry.schema()['properties']['firstLine']['enum']


@pytest.mark.parametrize('change', [
    {'start': -1}, {'start': True}, {'end': 1.0}, {'end': 20}, {'end': -1},
    {'field': 'invented'}, {'text': None},
])
def test_invalid_supplied_range_bounds_or_fields_are_rejected(change):
    current = source('Text\n')
    current['ranges'][0].update(change)
    with pytest.raises(ValueError):
        SourceRanges(current)


@pytest.mark.parametrize('invalid', [None, [], {'ref': REF}, {'ref': REF, 'ranges': None},
    {'ref': REF, 'ranges': [None]}, {'ref': {**REF, 'sourceRevision': 'bad'}, 'ranges': []},
    {'ref': {**REF, 'unitId': '../page'}, 'ranges': []}])
def test_invalid_source_container_or_reference_is_rejected(invalid):
    with pytest.raises(ValueError):
        SourceRanges(invalid)
