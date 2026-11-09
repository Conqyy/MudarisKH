from copy import deepcopy
import re

import pytest

from src.supporting.text_anchors import TextAnchors


REF = {'kind': 'tutorial', 'materialId': 'm', 'sourceRevision': 'a' * 64, 'unitId': 'p0001'}


def record(text='Chapter 1\n\n1. Explain trees.\n2. Compare graphs.\n', start=0):
    return {'ref': deepcopy(REF), 'ranges': [{'field': 'text', 'start': start,
        'end': start + len(text), 'text': text}], 'assetIds': []}


def test_annotations_preserve_every_original_character_and_restore_exact_proofs():
    source = record()
    before = deepcopy(source)
    registry = TextAnchors([source])
    annotated = registry.annotate([source])[0]
    marked = annotated['ranges'][0]['text']
    assert marked != source['ranges'][0]['text']
    assert re.sub(r'\[/?t_[0-9a-f]{16}\]', '', marked) == source['ranges'][0]['text']
    assert source == before
    for anchor_id, proof in registry.proofs.items():
        assert registry.decode({'type': 'text_span', 'spanId': anchor_id}) == proof
        assert source['ranges'][0]['text'][proof['start']:proof['end']] == proof['quote']
        assert registry.encode(proof) == {'type': 'text_span', 'spanId': anchor_id}


def test_anchor_ids_bind_exact_whitespace_location_revision_and_are_order_independent():
    source = record('A\n\nB\n', 50)
    other = record('Other source\n')
    other['ref']['unitId'] = 'p0002'
    first = TextAnchors([source, other])
    reordered = TextAnchors([other, source])
    assert first.proofs == reordered.proofs
    changed = deepcopy(source)
    changed['ref']['sourceRevision'] = 'b' * 64
    assert not set(TextAnchors([changed]).proofs) & set(first.proofs)
    assert all(proof['end'] - proof['start'] == len(proof['quote']) for proof in first.proofs.values())


@pytest.mark.parametrize('value', [
    {'type': 'text_span', 'spanId': 'foreign'},
    {'type': 'text_span', 'spanId': None},
    {'type': 'visual_region', 'spanId': 'foreign'},
    {'type': 'text_span', 'spanId': 'foreign', 'ref': REF},
])
def test_unknown_or_forged_ids_are_rejected(value):
    with pytest.raises(ValueError):
        TextAnchors([record()]).decode(value)


def test_copied_proof_is_detached_and_exact_prior_origin_can_be_registered():
    source = record()
    old = {'type': 'text_span', 'ref': {**REF, 'unitId': 'p0000'}, 'field': 'text',
           'start': 12, 'end': 25, 'quote': 'Prior origin\n'}
    registry = TextAnchors([source], known_origins=[old])
    wire = registry.encode(old)
    restored = registry.decode(wire)
    assert restored == old
    restored['quote'] = 'mutated'
    assert registry.decode(wire) == old
    assert wire['spanId'] not in registry.annotate([source])[0]['ranges'][0]['text']


def test_visual_only_source_has_no_invalid_empty_enum_and_bounds_are_checked():
    registry = TextAnchors([{'ref': REF, 'ranges': [], 'assetIds': ['a1']}])
    assert registry.schema() is None
    invalid = record()
    invalid['ranges'][0]['end'] += 1
    with pytest.raises(ValueError, match='range'):
        TextAnchors([invalid])


def test_known_anchor_overlapping_lines_is_visible_without_duplicating_original_text():
    source = record('Heading\n\nQuestion across\nmultiple lines.\n')
    quote = 'Question across\nmultiple lines.'
    start = source['ranges'][0]['text'].index(quote)
    known = {'type': 'text_span', 'ref': REF, 'field': 'text', 'start': start,
             'end': start + len(quote), 'quote': quote}
    registry = TextAnchors([source], known_origins=[known])
    marked = registry.annotate([source])[0]['ranges'][0]['text']
    assert '[' + registry.encode(known)['spanId'] + ']' in marked
    assert re.sub(r'\[/?t_[0-9a-f]{16}\]', '', marked) == source['ranges'][0]['text']


@pytest.mark.parametrize('text', [
    '1. Define a process. 2. Define a thread.',
    '(a) Define a process. (b) Define a thread.',
    'أ) عرّف العملية. ب) عرّف الخيط.',
])
def test_same_line_numbered_items_have_distinct_exact_origins(text):
    source = record(text)
    registry = TextAnchors([source])
    assert len(registry.proofs) == 2
    proofs = list(registry.proofs.values())
    assert proofs[0]['start'] != proofs[1]['start']
    assert ''.join(proof['quote'] for proof in proofs) == text
    assert re.sub(r'\[/?t_[0-9a-f]{16}\]', '', registry.annotate([source])[0]['ranges'][0]['text']) == text
