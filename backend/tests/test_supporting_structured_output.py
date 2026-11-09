"""Compact transport references retain the exact canonical evidence contract."""
import copy
import importlib
import json
from types import SimpleNamespace

import pytest

from .test_supporting_extraction import extractor, pdf, proof, item, page, reader, provider_wire_response
from src.supporting.extraction_source import source_plan
from src.supporting.extraction_inventory import validate_response
from src.utils.document_sources import render_source_unit


def wire():
    assert importlib.util.find_spec('src.supporting.structured_output') is not None
    return importlib.import_module('src.supporting.structured_output')


def fixture():
    raw = pdf(['Tutorial 1: Explain trees'])
    manifest = extractor().prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}, raw, 'pdf')
    source = source_plan(manifest, 1)[0]
    value = page([item(proof(manifest))]); value['paper'] = None
    return raw, manifest, source, value


def compact(value, ref='s0'):
    if isinstance(value, dict):
        return {key: ref if key == 'ref' and isinstance(row, dict) else compact(row, ref)
                for key, row in value.items()}
    if isinstance(value, list):
        return [compact(row, ref) for row in value]
    return value


def test_compact_source_ids_expand_to_exact_canonical_proofs_without_changing_claims():
    module = wire()
    _, manifest, source, value = fixture()
    refs = module.source_references(source, None)
    assert refs == {'s0': source['ref']}
    decoded = module.decode_inventory(compact(value), refs, records=[source])
    assert decoded == value
    assert validate_response(decoded, manifest, source, None, [])['items'][0]['text'] == value['items'][0]['text']
    assert isinstance(compact(value)['items'][0]['origin']['ref'], str)


@pytest.mark.parametrize('bad_ref', ['s99', '', None, {'kind': 'tutorial'}, 0])
def test_wire_references_cannot_invent_or_omit_source_identity(bad_ref):
    module = wire()
    _, _, source, value = fixture()
    response = compact(value)
    response['items'][0]['origin']['ref'] = bad_ref
    with pytest.raises(ValueError, match='reference'):
        module.decode_inventory(response, module.source_references(source, None), records=[source])


def test_compact_references_do_not_relax_original_quote_or_current_window_checks():
    module = wire()
    _, manifest, source, value = fixture()
    response = compact(value)
    response['items'][0]['proofs'][0]['quote'] = 'not the original quote'
    with pytest.raises(ValueError):
        validate_response(module.decode_inventory(response, module.source_references(source, None), records=[source]),
                          manifest, source, None, [])


def test_structured_requests_are_closed_require_all_fields_and_disable_reasoning():
    module = wire()
    _, _, source, _ = fixture()
    schema = module.inventory_schema(module.source_references(source, None), 'tutorial')
    options = module.structured_options('supporting_inventory', schema)
    assert options['response_format'] == {'type': 'json_schema', 'json_schema': {
        'name': 'supporting_inventory', 'strict': True, 'schema': schema}}
    assert options['extra_body']['reasoning'] == {'enabled': False}
    def check(row):
        if isinstance(row, dict):
            if row.get('type') == 'object':
                assert row['additionalProperties'] is False
                assert set(row['required']) == set(row['properties'])
            for value in row.values(): check(value)
        elif isinstance(row, list):
            for value in row: check(value)
    check(schema)
    assert len(json.dumps(schema)) < 8000
    assert schema['$defs']['textProof']['properties']['ref']['enum'] == ['s0']


class CompactProvider:
    def __init__(self, response, *, corrupt=False):
        self.response, self.corrupt, self.calls = response, corrupt, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        request = json.loads(kwargs['messages'][1]['content'][0]['text'])
        value = provider_wire_response(self.response, request)
        if self.corrupt:
            value['items'][0]['origin']['ref'] = 'foreign'
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(value)))])


def execute(raw, manifest, provider, states, **kwargs):
    return extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']),
        checkpoint=lambda state: states.append(copy.deepcopy(state)), **kwargs)


def test_extract_and_independent_read_use_schema_and_persist_only_canonical_responses():
    raw, manifest, source, value = fixture()
    provider, states = CompactProvider(value), []
    result = execute(raw, manifest, provider, states)
    assert result['extractionCoverage']['complete']
    assert len(provider.calls) == states[-1]['modelCalls'] == 2
    for call in provider.calls:
        assert call['response_format']['json_schema']['strict']
        assert call['extra_body']['reasoning']['enabled'] is False
        envelope = json.loads(call['messages'][1]['content'][0]['text'])
        assert envelope['sourceReferences'] == {'s0': source['ref']}
        assert envelope['source']['sourceId'] == 's0'
    assert states[-1]['responses']['extract']['0']['items'][0]['origin']['ref'] == source['ref']


def test_foreign_wire_response_spends_bounded_attempts_and_explicit_retry_recovers():
    raw, manifest, _, value = fixture()
    provider, states = CompactProvider(value, corrupt=True), []
    assert not execute(raw, manifest, provider, states)['extractionCoverage']['complete']
    assert len(provider.calls) == states[-1]['modelCalls'] == 2
    assert states[-1]['responses'] == {'extract': {}, 'reconcile': {}}
    retry = CompactProvider(value)
    assert execute(raw, manifest, retry, [], resume=states[-1], model_calls=0)['extractionCoverage']['complete']


def test_legacy_canonical_pending_response_is_replayed_without_another_paid_call():
    raw, manifest, _, value = fixture()
    provider, states = CompactProvider(value), []
    class Interrupted(Exception): pass
    def stop(state):
        states.append(copy.deepcopy(state))
        if state['pending'] is not None: raise Interrupted()
    with pytest.raises(Interrupted):
        extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
            render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=stop)
    legacy = states[-1]
    legacy['pending'].pop('wireVersion', None)
    legacy['pending']['text'] = json.dumps(value)
    retry = CompactProvider(value)
    assert execute(raw, manifest, retry, [], resume=legacy)['extractionCoverage']['complete']
    assert len(retry.calls) == 1


def test_omitted_academic_content_cannot_be_cured_by_compact_reference_resolution():
    raw, manifest, _, value = fixture()
    value['items'] = []
    provider, states = CompactProvider(value), []
    assert not execute(raw, manifest, provider, states)['extractionCoverage']['complete']
    assert len(provider.calls) == 2


def test_progress_counts_only_independently_reconciled_original_units():
    raw, manifest, _, value = fixture()
    provider, states = CompactProvider(value), []
    assert execute(raw, manifest, provider, states)['extractionCoverage']['complete']
    extracted = next(state for state in states if state['responses']['extract'] and not state['responses']['reconcile'])
    assert extracted['progress'] == {'completedUnits': 0, 'totalUnits': 1}
    assert states[-1]['progress'] == {'completedUnits': 1, 'totalUnits': 1}


def test_audit_request_uses_strict_compact_proofs_and_unchanged_canonical_certificates():
    from .test_supporting_reconciliation import fixture as audit_fixture, AuditProvider, execute as audit_execute
    manifest, source, first, second = audit_fixture()
    provider, states = AuditProvider(manifest, first, second), []
    assert audit_execute(manifest, provider, states)['extractionCoverage']['complete']
    call = provider.calls[-1]
    assert call['response_format']['json_schema']['name'] == 'supporting_audit'
    assert call['response_format']['json_schema']['strict'] is True
    assert call['extra_body']['reasoning'] == {'enabled': False}
    packet = json.loads(call['messages'][1]['content'][0]['text'])
    assert packet['sourceReferences'] == {'s0': source['ref']}
    assert all(value.get('spanId', '').startswith('t_') for value in packet['originalProofs'].values())
    assert states[-1]['resolutions']['0']['response']['judgments'][0]['proofs'][0]['ref'] == source['ref']


def test_unsupported_structured_provider_never_retries_without_contract_options():
    raw, manifest, _, value = fixture()
    provider, states = CompactProvider(value), []
    def unsupported(**kwargs):
        provider.calls.append(kwargs)
        raise ValueError('Provider does not support response_format json_schema')
    provider.chat.completions.create = unsupported
    result = execute(raw, manifest, provider, states)
    assert not result['extractionCoverage']['complete']
    assert len(provider.calls) == 1
    assert provider.calls[0]['response_format']['type'] == 'json_schema'
    assert states[-1]['modelCalls'] == 0


@pytest.mark.parametrize('fresh_retry', [False, True])
def test_extract_phase_and_zero_progress_are_saved_before_first_provider_request(fresh_retry):
    raw, manifest, _, value = fixture()
    resume = None
    if fresh_retry:
        old_states = []
        execute(raw, manifest, CompactProvider(value, corrupt=True), old_states)
        resume = old_states[-1]
        assert resume['modelCalls'] == 2
    provider, states = CompactProvider(value), []
    original_create = provider.create
    def create(**kwargs):
        if not provider.calls:
            assert states, 'The extraction phase must be durable before waiting for the provider'
            assert states[-1]['stage'] == 'extract'
            assert states[-1]['cursor'] == states[-1]['modelCalls'] == 0
            assert states[-1]['error'] is None
            assert states[-1]['progress'] == {'completedUnits': 0, 'totalUnits': 1}
        return original_create(**kwargs)
    provider.chat.completions.create = create
    assert execute(raw, manifest, provider, states, resume=resume,
                   model_calls=0 if fresh_retry else None)['extractionCoverage']['complete']


def test_exact_unique_original_quote_resolves_bad_model_arithmetic():
    module = wire()
    _, manifest, source, _ = fixture()
    canonical = proof(manifest)
    malformed = {**canonical, 'start': 7, 'end': 9}
    assert module.resolve_text_span(malformed, [source]) == canonical
    assert malformed['start'] == 7  # transport input remains immutable
    quote_only = {key: value for key, value in canonical.items() if key not in ('start', 'end')}
    assert module.resolve_text_span(quote_only, [source]) == canonical


@pytest.mark.parametrize('quote', ['trees trees', 'trees  ', 'Trees', 'invented'])
def test_text_span_resolution_rejects_absent_or_invented_quotes_without_normalizing(quote):
    module = wire()
    _, manifest, source, _ = fixture()
    with pytest.raises(ValueError, match='exact|Exact'):
        module.resolve_text_span({**proof(manifest), 'start': -1, 'end': 0, 'quote': quote}, [source])


def test_repeated_quote_is_ambiguous_unless_original_supplied_offsets_are_already_exact():
    module = wire()
    ref = {'kind': 'notes', 'materialId': 'm', 'sourceRevision': 'a' * 64, 'unitId': 'n1'}
    record = {'ref': ref, 'ranges': [{'field': 'text', 'start': 10, 'end': 21, 'text': 'trees trees'}]}
    candidate = {'type': 'text_span', 'ref': ref, 'field': 'text', 'quote': 'trees'}
    with pytest.raises(ValueError, match='ambiguous|Ambiguous'):
        module.resolve_text_span(candidate, [record])
    canonical = {**candidate, 'start': 16, 'end': 21}
    assert module.resolve_text_span(canonical, [record]) == canonical


def test_quote_resolution_cannot_cross_supplied_windows_or_change_original_identity():
    module = wire()
    _, manifest, source, _ = fixture()
    canonical = proof(manifest)
    split = copy.deepcopy(source)
    original = split['ranges'][0]
    split['ranges'] = [{**original, 'end': 10, 'text': original['text'][:10]},
                       {**original, 'start': 10, 'text': original['text'][10:]}]
    with pytest.raises(ValueError, match='exact|Exact'):
        module.resolve_text_span(canonical, [split])
    foreign = {**canonical, 'ref': {**canonical['ref'], 'unitId': 'other'}}
    with pytest.raises(ValueError, match='exact|Exact'):
        module.resolve_text_span(foreign, [source])


def test_only_explicit_previously_validated_origins_can_restore_old_continuity_spans():
    module = wire()
    _, manifest, source, _ = fixture()
    canonical = proof(manifest)
    quote_only = {key: value for key, value in canonical.items() if key not in ('start', 'end')}
    assert module.resolve_text_span(quote_only, [], known_origins=[canonical]) == canonical
    with pytest.raises(ValueError):
        module.resolve_text_span(quote_only, [])


def test_quote_only_inventory_schema_and_decoder_preserve_canonical_saved_contract():
    module = wire()
    _, manifest, source, value = fixture()
    references = module.source_references(source, None)
    schema = module.inventory_schema(references, 'tutorial')
    assert 'start' not in schema['$defs']['textProof']['properties']
    assert 'end' not in schema['$defs']['textProof']['properties']
    def omit(value):
        if isinstance(value, dict):
            return {key: omit(row) for key, row in value.items() if key not in ('start', 'end')}
        if isinstance(value, list): return [omit(row) for row in value]
        return value
    decoded = module.decode_inventory(omit(compact(value)), references, records=[source])
    assert decoded == value
    assert validate_response(decoded, manifest, source, None, [])['items'][0]['origin'] == proof(manifest)


def _quote_only(value):
    if isinstance(value, dict):
        return {key: _quote_only(row) for key, row in value.items()
                if value.get('type') != 'text_span' or key not in ('start', 'end')}
    if isinstance(value, list):
        return [_quote_only(row) for row in value]
    return value


def test_quote_only_responses_complete_extraction_reconciliation_and_audit():
    from .test_supporting_reconciliation import fixture as audit_fixture, AuditProvider, execute as audit_execute
    manifest, _, first, second = audit_fixture()
    provider, states = AuditProvider(manifest, first, second), []
    original_create = provider.create

    def create(**kwargs):
        response = original_create(**kwargs)
        response.choices[0].message.content = json.dumps(_quote_only(
            json.loads(response.choices[0].message.content)))
        return response

    provider.chat.completions.create = create
    result = audit_execute(manifest, provider, states)
    assert result['extractionCoverage']['complete']
    assert len(provider.calls) == 3
    assert states[-1]['resolutions']['0']['response']['judgments'][0]['proofs'][0] == proof(manifest)
    assert states[-1]['responses']['extract']['0']['items'][0]['origin'] == proof(manifest)
    assert all(state['pending']['wireVersion'] == wire().WIRE_VERSION for state in states if state.get('pending'))


def test_v1_pending_bad_offsets_replay_from_exact_quote_without_another_extraction_call():
    raw, manifest, _, value = fixture()
    provider, states = CompactProvider(value), []

    class Interrupted(Exception):
        pass

    def stop(state):
        states.append(copy.deepcopy(state))
        if state['pending'] is not None:
            raise Interrupted()

    with pytest.raises(Interrupted):
        extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
            render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']), checkpoint=stop)
    resume = states[-1]
    malformed = compact(value)

    def corrupt_offsets(row):
        if isinstance(row, dict):
            if row.get('type') == 'text_span':
                row.update(start=1, end=2)
            for child in row.values():
                corrupt_offsets(child)
        elif isinstance(row, list):
            for child in row:
                corrupt_offsets(child)

    corrupt_offsets(malformed)
    resume['pending'].update(wireVersion=1, text=json.dumps(malformed))
    retry, recovered = CompactProvider(value), []
    assert execute(raw, manifest, retry, recovered, resume=resume)['extractionCoverage']['complete']
    assert len(retry.calls) == 1
    assert recovered[-1]['responses']['extract']['0']['items'][0]['origin'] == proof(manifest)


def test_known_continuation_origin_does_not_authorize_new_claim_evidence():
    module = wire()
    _, _, _, value = fixture()
    old = value['items'][0]['origin']
    references = {'s0': old['ref']}
    response = _quote_only(compact(value))
    # The origin is allowed for continuation identity, but all actual proof
    # claims still need to be in the current/previous physical request ranges.
    with pytest.raises(ValueError, match='Exact original quote'):
        module.decode_inventory(response, references, records=[], known_origins=[old])
