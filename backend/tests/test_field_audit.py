"""Closed field claims cannot contradict the original saved inventory."""
from copy import deepcopy
import importlib

import pytest

from src.supporting.contracts import digest
from src.supporting.extraction_source import source_plan
from src.supporting.structured_output import TextAnchors, source_references
from .test_inventory_comparison import fixture, span, question, response, requirement
from .test_supporting_native_inventory import manifest


def audit_fixture(data=None, first=None, second=None):
    assert importlib.util.find_spec('src.supporting.field_audit') is not None, 'Closed field audit is missing'
    module = importlib.import_module('src.supporting.field_audit')
    if data is None:
        data, first, second = fixture()
    source = source_plan(data, 1)[0]
    return module.FieldAudit(data, source, None, first, second), data, first, second


def accepted(check, data):
    proof = span(data, data['units'][0]['text'])
    return {'protocolVersion': 2, 'taskId': check.envelope()['taskId'],
        'verdict': 'accept_first', 'missingContent': [],
        'sourceCompleteness': {'status': 'complete', 'proofs': [proof],
                               'reason': 'Every original obligation was checked independently.'},
        'judgments': [{'obligationId': key, 'decision': 'faithful' if key.startswith('A/') else 'represented',
            'firstIds': [key if key.startswith('A/') else 'A/' + key[2:]],
            'proofs': [proof], 'reason': 'This obligation preserves the supplied original.', 'findings': []}
            for key in check.envelope()['fieldFacts']]}


def finding(check, key, field, proof, kind='literal_missing'):
    facts = check.envelope()['fieldFacts'][key]['fields']
    return {'obligationId': key, 'field': field, 'observedDigest': facts[field]['digest'],
            'kind': kind, 'proofs': [proof]}


def reject_missing(check, data, claim):
    value = accepted(check, data)
    value['verdict'] = 'reject'
    value['sourceCompleteness']['status'] = 'incomplete'
    value['missingContent'] = [{'text': 'The named original content is missing.',
                               'proofs': deepcopy(claim['proofs']), 'finding': claim}]
    return value


def test_certificate_binds_exact_task_policy_comparison_and_source_without_editing_inventories():
    check, data, first, second = audit_fixture()
    before = deepcopy((first, second))
    value = accepted(check, data)
    certificate = check.validate(value)
    assert certificate['accepted'] is True
    assert certificate['bindings']['version'] == 2
    assert certificate['bindings']['comparisonDigest']
    assert check.validate_certificate(certificate) == certificate
    assert (first, second) == before
    assert certificate['response'] == value


@pytest.mark.parametrize('key,field,quote', [
    ('A/items/0', 'printedLabel', 'Question 1:'),
    ('A/items/0', 'requirements', '1. Draw the tree.'),
    ('A/items/0/requirements/1', 'text', '2. State the output.'),
])
def test_literal_absence_of_retained_named_field_is_a_contract_error(key, field, quote):
    check, data, _, _ = audit_fixture()
    claim = finding(check, key, field, span(data, quote))
    with pytest.raises(ValueError, match='contradict'):
        check.validate(reject_missing(check, data, claim))


@pytest.mark.parametrize('item_type', ['question', 'subpart'])
def test_task_in_the_same_items_requirements_need_not_be_duplicated_in_its_stem(item_type):
    data, first, second = fixture()
    if item_type == 'subpart':
        for value in (first, second):
            value['items'][0]['itemType'] = 'subpart'
            value['items'][0]['parent'] = {'itemType': 'question', 'origin': deepcopy(value['items'][1]['origin'])}
    check, _, _, _ = audit_fixture(data, first, second)
    claim = finding(check, 'A/items/0', 'text', span(data, '1. Draw the tree.'))
    with pytest.raises(ValueError, match='own requirements|same item'):
        check.validate(reject_missing(check, data, claim))


def test_same_owner_guard_also_rejects_false_second_inventory_stem_findings():
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    row = next(row for row in value['judgments'] if row['obligationId'] == 'B/items/0')
    row.update(decision='incorrect', firstIds=[],
        findings=[finding(check, 'B/items/0', 'text', span(data, '1. Draw the tree.'))])
    for child in value['judgments']:
        if child['obligationId'].startswith('B/items/0/requirements/'):
            child.update(decision='incorrect', firstIds=[], findings=[finding(check,
                child['obligationId'], 'text', span(data, '1. Draw the tree.'), 'semantic_mismatch')])
    value['verdict'] = 'reject'
    with pytest.raises(ValueError, match='own requirements|same item'):
        check.validate(value)


def test_other_questions_requirement_cannot_disprove_a_missing_stem_claim():
    check, data, _, _ = audit_fixture()
    claim = finding(check, 'A/items/1', 'text', span(data, '1. Draw the tree.'))
    assert check.validate(reject_missing(check, data, claim))['accepted'] is False


def test_same_task_words_at_a_different_source_position_do_not_trigger_same_owner_guard():
    data = manifest('Question 1:\nDraw the tree.\nQuestion 2:\nDraw the tree.\n')
    one, two = span(data, 'Draw the tree.'), span(data, 'Draw the tree.', start=data['units'][0]['text'].rindex('Draw the tree.'))
    first = response(question(span(data, 'Question 1:'), [requirement(one)]),
                     question(span(data, 'Question 2:'), [requirement(two)]))
    check, _, _, _ = audit_fixture(data, first, deepcopy(first))
    claim = finding(check, 'A/items/0', 'text', two)
    assert check.validate(reject_missing(check, data, claim))['accepted'] is False


def test_same_owner_stem_exception_does_not_replace_required_atomic_requirement_records():
    data, first, second = fixture()
    first['items'][0]['text'] += '\n1. Draw the tree.'
    first['items'][0]['requirements'] = []
    check, _, _, _ = audit_fixture(data, first, deepcopy(first))
    claim = finding(check, 'A/items/0', 'requirements', span(data, '1. Draw the tree.'))
    assert check.validate(reject_missing(check, data, claim))['accepted'] is False


@pytest.mark.parametrize('kind,field', [('semantic_mismatch', 'text'), ('wrong_relationship', 'requirements')])
def test_real_semantic_or_ownership_defect_remains_reportable_when_task_text_is_retained(kind, field):
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    row = next(row for row in value['judgments'] if row['obligationId'] == 'A/items/0')
    row.update(decision='incorrect', findings=[finding(check, 'A/items/0', field, span(data, '1. Draw the tree.'), kind)])
    value['verdict'] = 'reject'
    assert check.validate(value)['accepted'] is False


def test_real_missing_question_label_remains_rejected():
    data, first, second = fixture()
    first['items'][1]['printedLabel'] = None
    check, _, _, _ = audit_fixture(data, first, second)
    claim = finding(check, 'A/items/1', 'printedLabel', span(data, 'Question 2:'))
    assert check.validate(reject_missing(check, data, claim))['accepted'] is False


@pytest.mark.parametrize('change', ['wrong_digest', 'wrong_field', 'wrong_obligation', 'no_findings', 'foreign_proof'])
def test_incorrect_judgment_needs_matching_observed_field_and_current_original(change):
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    judgment = next(row for row in value['judgments'] if row['obligationId'] == 'A/items/0')
    judgment['decision'] = 'incorrect'
    claim = finding(check, 'A/items/0', 'questionType', span(data, 'Question 1:'), 'semantic_mismatch')
    judgment['findings'] = [claim]
    value['verdict'] = 'reject'
    if change == 'wrong_digest': claim['observedDigest'] = digest('invented value')
    elif change == 'wrong_field': claim['field'] = 'pageRole'
    elif change == 'wrong_obligation': claim['obligationId'] = 'A/items/1'
    elif change == 'no_findings': judgment['findings'] = []
    else: claim['proofs'][0]['ref']['sourceRevision'] = 'f' * 64
    with pytest.raises(ValueError):
        check.validate(value)


def test_nonacademic_item_type_cannot_be_reported_as_the_page_classification():
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    row = next(row for row in value['judgments'] if row['obligationId'] == 'A/classification')
    row['decision'] = 'incorrect'
    row['findings'] = [{'obligationId': 'A/classification', 'field': 'itemType',
        'observedDigest': digest('nonacademic'), 'kind': 'semantic_mismatch',
        'proofs': [span(data, 'Question 1:')]}]
    with pytest.raises(ValueError, match='field'):
        check.validate(value)


@pytest.mark.parametrize('status', ['incomplete', 'uncertain'])
def test_independent_original_completeness_is_mandatory_even_when_inventories_agree(status):
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    value['sourceCompleteness']['status'] = status
    assert check.validate(value)['accepted'] is False


def test_completeness_cannot_be_asserted_without_current_original_evidence():
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    value['sourceCompleteness']['proofs'] = []
    with pytest.raises(ValueError, match='proof'):
        check.validate(value)


def test_novel_missing_item_escape_cannot_relabel_existing_exact_content():
    check, data, _, _ = audit_fixture()
    claim = {'obligationId': None, 'field': None, 'observedDigest': None,
             'kind': 'literal_missing', 'proofs': [span(data, 'Question 1:')]}
    with pytest.raises(ValueError, match='represented|contradict'):
        check.validate(reject_missing(check, data, claim))


def test_novel_whole_page_claim_cannot_hide_content_already_retained_across_fields():
    check, data, _, _ = audit_fixture()
    claim = {'obligationId': None, 'field': None, 'observedDigest': None,
             'kind': 'literal_missing', 'proofs': [span(data, data['units'][0]['text'])]}
    with pytest.raises(ValueError, match='represented|contradict'):
        check.validate(reject_missing(check, data, claim))


def test_image_only_claim_cannot_assert_literal_absence_from_a_text_backed_named_field():
    check, data, _, _ = audit_fixture()
    proof = {'type': 'visual_region', 'ref': check.source['ref'],
             'assetId': 'p0001-page', 'box': [0, 0, 1, 1]}
    claim = finding(check, 'A/items/0', 'printedLabel', proof)
    with pytest.raises(ValueError, match='text proof'):
        check.validate(reject_missing(check, data, claim))


def test_genuinely_visual_only_original_can_still_report_a_missing_label_without_acceptance():
    data = manifest('')
    source = source_plan(data, 1)[0]
    proof = {'type': 'visual_region', 'ref': source['ref'],
             'assetId': 'p0001-page', 'box': [0, 0, 1, 1]}
    _, first, _ = fixture()
    first['items'] = [first['items'][0]]
    first['items'][0].update(origin=deepcopy(proof), proofs=[deepcopy(proof)],
                            requirements=[], givenData=[], printedLabel=None)
    check, _, _, _ = audit_fixture(data, first, deepcopy(first))
    value = reject_missing(check, data, finding(check, 'A/items/0', 'printedLabel', proof))
    value['sourceCompleteness']['proofs'] = [deepcopy(proof)]
    for row in value['judgments']: row['proofs'] = [deepcopy(proof)]
    assert check.validate(value)['accepted'] is False


def test_source_obligation_missing_from_both_inventories_can_be_reported_as_novel():
    data = manifest('Question 1: Explain trees.\nQuestion 2: Draw a graph.\n')
    first = response(question(span(data, 'Question 1: Explain trees.')))
    check, _, _, _ = audit_fixture(data, first, deepcopy(first))
    claim = {'obligationId': None, 'field': None, 'observedDigest': None,
             'kind': 'literal_missing', 'proofs': [span(data, 'Question 2: Draw a graph.')]}
    assert check.validate(reject_missing(check, data, claim))['accepted'] is False


def test_uncertainty_can_be_reported_without_invented_evidence_but_never_accepts():
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    value['verdict'] = 'uncertain'
    value['sourceCompleteness'].update(status='uncertain', proofs=[])
    row = value['judgments'][0]
    claim = finding(check, row['obligationId'], 'pageRole', span(data, 'Question 1:'), 'uncertain')
    claim['proofs'] = []
    row.update(decision='uncertain', proofs=[], findings=[claim])
    assert check.validate(value)['accepted'] is False


@pytest.mark.parametrize('field', ['taskId', 'policyDigest', 'comparisonDigest', 'accepted'])
def test_task_or_certificate_tampering_cannot_authorize_replay(field):
    check, data, _, _ = audit_fixture()
    certificate = check.validate(accepted(check, data))
    if field == 'taskId': certificate['response']['taskId'] = 'other-task'
    elif field == 'accepted': certificate['accepted'] = False
    else: certificate['bindings'][field] = 'f' * 64
    with pytest.raises(ValueError):
        check.validate_certificate(certificate)


@pytest.mark.parametrize('change', ['integer_accepted', 'float_version'])
def test_certificate_replay_preserves_exact_json_types(change):
    check, data, _, _ = audit_fixture()
    certificate = check.validate(accepted(check, data))
    if change == 'integer_accepted': certificate['accepted'] = 1
    else: certificate['bindings']['version'] = 2.0
    with pytest.raises(ValueError):
        check.validate_certificate(certificate)


def test_existing_owner_mapping_rules_still_reject_cross_question_requirements():
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    one = next(row for row in value['judgments'] if row['obligationId'] == 'B/items/0/requirements/0')
    two = next(row for row in value['judgments'] if row['obligationId'] == 'B/items/1/requirements/0')
    one['firstIds'], two['firstIds'] = two['firstIds'], one['firstIds']
    with pytest.raises(ValueError, match='owning'):
        check.validate(value)


@pytest.mark.parametrize('mode', ['accept', 'missing', 'uncertain'])
def test_schema_and_wire_decode_preserve_typed_findings_and_completeness_proofs(mode):
    check, data, _, _ = audit_fixture()
    source = source_plan(data, 1)[0]
    references = source_references(source, None)
    anchors = TextAnchors([source], known_origins=[span(data, data['units'][0]['text']), span(data, 'int x = 1;')])
    value = accepted(check, data)
    if mode == 'missing':
        value = reject_missing(check, data, finding(check, 'A/items/0', 'text', span(data, 'int x = 1;')))
    elif mode == 'uncertain':
        value['verdict'] = 'uncertain'
        value['sourceCompleteness'].update(status='uncertain', proofs=[])
        row = value['judgments'][0]
        claim = finding(check, row['obligationId'], 'pageRole', span(data, 'Question 1:'), 'uncertain')
        claim['proofs'] = []
        row.update(decision='uncertain', proofs=[], findings=[claim])
    schema = check.schema(references, anchors)

    def wire(row):
        if isinstance(row, list): return [wire(child) for child in row]
        if not isinstance(row, dict): return row
        if row.get('type') == 'text_span': return anchors.encode(row)
        result = {key: wire(child) for key, child in row.items()}
        if isinstance(row.get('proofs'), list):
            proofs = result['proofs']
            result['proofs'] = {'current': proofs[0] if proofs else None, 'context': proofs[1:]}
        return result

    encoded = wire(value)
    if mode != 'accept':
        for row in encoded['missingContent']:
            claim = row['finding']
            claim['observedDigest'] = check.wire_envelope()['fieldFacts'][claim['obligationId']]['fields'][claim['field']]
        for row in encoded['judgments']:
            for claim in row['findings']:
                claim['observedDigest'] = check.wire_envelope()['fieldFacts'][claim['obligationId']]['fields'][claim['field']]
    assert schema['properties']['taskId']['enum'] == [value['taskId']]
    assert check.decode(encoded, references, anchors) == value
    assert check.validate(check.decode(encoded, references, anchors))['accepted'] is (mode == 'accept')


def test_compact_field_digest_handles_preserve_exact_code_bytes_without_repeating_hashes():
    check, data, first, second = audit_fixture()
    wire = check.wire_envelope()
    assert wire['taskId'] == check.envelope()['taskId']
    handle = wire['fieldFacts']['A/items/0']['fields']['givenData']
    assert isinstance(handle, str) and len(handle) < 10
    assert handle == wire['fieldFacts']['B/items/0']['fields']['givenData']
    changed = deepcopy(second)
    changed['items'][0]['givenData'] = ['int x=1;']
    changed_check, _, _, _ = audit_fixture(data, first, changed)
    fields = changed_check.wire_envelope()['fieldFacts']
    assert fields['A/items/0']['fields']['givenData'] != fields['B/items/0']['fields']['givenData']


def test_same_unit_previous_range_cannot_substitute_for_current_finding_or_completeness():
    check, data, first, second = audit_fixture()
    previous = deepcopy(check.source)
    previous['ranges'] = [{'field': 'text', 'start': 0, 'end': 12, 'text': data['units'][0]['text'][:12]}]
    current = deepcopy(check.source)
    current['ranges'] = [{'field': 'text', 'start': 12, 'end': len(data['units'][0]['text']),
                          'text': data['units'][0]['text'][12:]}]
    check = type(check)(data, current, previous, first, second)
    value = accepted(check, data)
    value['sourceCompleteness']['proofs'] = [span(data, 'Question 1:')]
    with pytest.raises(ValueError, match='current-window'):
        check.validate(value)


def test_certificate_cannot_be_replayed_after_source_or_inventory_field_changes():
    check, data, first, second = audit_fixture()
    certificate = check.validate(accepted(check, data))
    changed = deepcopy(first)
    changed['items'][0]['givenData'] = ['int x=1;']
    updated, _, _, _ = audit_fixture(data, changed, second)
    with pytest.raises(ValueError):
        updated.validate_certificate(certificate)


def test_complete_claim_with_typed_missing_content_is_contradictory():
    check, data, _, _ = audit_fixture()
    claim = finding(check, 'A/items/0', 'text', span(data, 'int x = 1;'))
    value = reject_missing(check, data, claim)
    value['sourceCompleteness']['status'] = 'complete'
    with pytest.raises(ValueError, match='contradict'):
        check.validate(value)


def test_bare_reject_verdict_cannot_override_resolved_faithful_complete_checks():
    check, data, _, _ = audit_fixture()
    value = accepted(check, data)
    value['verdict'] = 'reject'
    with pytest.raises(ValueError, match='reject|contradict'):
        check.validate(value)
