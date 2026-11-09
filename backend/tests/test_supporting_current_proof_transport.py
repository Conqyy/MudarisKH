"""Wire claims explicitly select evidence from the current physical window."""
from copy import deepcopy

import pytest

from src.supporting.structured_output import TextAnchors, inventory_schema, decode_inventory


def windows():
    ref = {'kind': 'tutorial', 'materialId': 'm', 'sourceRevision': 'a' * 64, 'unitId': 'p0001'}
    previous = {'ref': ref, 'ranges': [{'field': 'text', 'start': 0, 'end': 6, 'text': 'Prior\n'}], 'assetIds': ['old-image']}
    current = {'ref': ref, 'ranges': [{'field': 'text', 'start': 6, 'end': 14, 'text': 'Current\n'}], 'assetIds': ['current-image']}
    registry = TextAnchors([current, previous])
    return {'s0': ref}, previous, current, registry


def ids(schema):
    return set(schema['properties']['spanId']['enum'])


def test_current_schema_excludes_prior_same_unit_text_and_unprovided_visual_assets():
    refs, previous, current, registry = windows()
    schema = inventory_schema(refs, 'tutorial', registry, current_source=current)
    current_ids = ids(schema['$defs']['currentTextProof'])
    context_ids = ids(schema['$defs']['contextTextProof'])
    assert current_ids == set(TextAnchors([current]).proofs)
    assert context_ids == set(TextAnchors([previous]).proofs)
    assert current_ids.isdisjoint(context_ids)
    visual = schema['$defs']['currentVisualProof']['properties']
    assert visual['ref']['enum'] == ['s0']
    assert visual['assetId']['enum'] == ['current-image']
    for record in ('item', 'context', 'requirement', 'topic'):
        assert schema['$defs'][record]['properties']['proofs'] == {'$ref': '#/$defs/claimProofs'}
    assert schema['$defs']['item']['properties']['contextOrigins']['type'] == 'array'


def wire_inventory(registry, *, current_id, previous_id):
    current = {'type': 'text_span', 'spanId': current_id}
    previous = {'type': 'text_span', 'spanId': previous_id}
    return {'items': [{'origin': deepcopy(previous), 'parent': None, 'contextOrigins': [],
                      'proofs': {'current': current, 'context': [previous]}, 'requirements': []}],
            'sharedContexts': [], 'topics': []}


def test_current_wrapper_decodes_to_existing_canonical_arrays_without_changing_origins():
    refs, previous, current, registry = windows()
    current_id, previous_id = next(iter(TextAnchors([current]).proofs)), next(iter(TextAnchors([previous]).proofs))
    value = wire_inventory(registry, current_id=current_id, previous_id=previous_id)
    before = deepcopy(value)
    decoded = decode_inventory(value, refs, records=[current, previous], known_origins=[registry.proofs[previous_id]],
                               text_anchors=registry, wire_version=4)
    assert decoded['items'][0]['origin'] == registry.proofs[previous_id]
    assert decoded['items'][0]['proofs'] == [registry.proofs[current_id], registry.proofs[previous_id]]
    assert value == before


@pytest.mark.parametrize('damage', ['prior_span', 'wrong_asset', 'missing_current', 'array'])
def test_v4_current_slot_cannot_be_satisfied_by_context_or_missing_evidence(damage):
    refs, previous, current, registry = windows()
    current_id, previous_id = next(iter(TextAnchors([current]).proofs)), next(iter(TextAnchors([previous]).proofs))
    value = wire_inventory(registry, current_id=current_id, previous_id=previous_id)
    claims = value['items'][0]['proofs']
    if damage == 'prior_span':
        claims['current'] = deepcopy(claims['context'][0])
    elif damage == 'wrong_asset':
        claims['current'] = {'type': 'visual_region', 'ref': 's0', 'assetId': 'old-image', 'box': [0, 0, 1, 1]}
    elif damage == 'missing_current':
        claims['current'] = None
    else:
        value['items'][0]['proofs'] = [claims['current']]
    with pytest.raises(ValueError, match='current|Current|claim'):
        decode_inventory(value, refs, records=[current, previous], text_anchors=registry, wire_version=4)


def test_v3_span_array_pending_payload_still_decodes_with_current_anchor_registry():
    refs, previous, current, registry = windows()
    current_id, previous_id = next(iter(TextAnchors([current]).proofs)), next(iter(TextAnchors([previous]).proofs))
    value = wire_inventory(registry, current_id=current_id, previous_id=previous_id)
    claims = value['items'][0]['proofs']
    value['items'][0]['proofs'] = [claims['current'], *claims['context']]
    decoded = decode_inventory(value, refs, records=[current, previous], text_anchors=registry, wire_version=3)
    assert decoded['items'][0]['proofs'] == [registry.proofs[current_id], registry.proofs[previous_id]]


def test_current_window_without_any_original_evidence_cannot_emit_claim_records():
    refs, _, current, _ = windows()
    current.update(ranges=[], assetIds=[])
    schema = inventory_schema(refs, 'tutorial', TextAnchors([current]), current_source=current)
    for collection in ('items', 'sharedContexts', 'topics'):
        assert schema['properties'][collection]['maxItems'] == 0
