"""Every original image must carry its role and exact locator next to it."""
from copy import deepcopy
import json

import pytest

from src.supporting.contracts import canonical_bytes, MAX_TEXT_PER_CALL
from src.supporting.extraction_source import request_messages


def image(uri):
    return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + uri}}


def envelope(*, lecture=True):
    source = {'kind': 'tutorial', 'materialId': 't', 'sourceRevision': 'a' * 64, 'unitId': 'p0002'}
    previous = {**source, 'unitId': 'p0001'}
    packet = {'source': {'ref': 's0', 'assetIds': ['p0002-page'], 'ranges': []},
              'previous': {'ref': 's1', 'assetIds': ['p0001-page'], 'ranges': []},
              'sourceReferences': {'s0': source, 's1': previous}, 'lectureNavigation': {}}
    if lecture:
        packet['lectureNavigation'] = {'evidence': [{'images': [{'assetIndex': 0,
            'asset': {'assetId': 'cover-page'},
            'ref': {'documentId': 'lecture', 'sourceRevision': 'b' * 64, 'unitId': 'p0001'}}]}]}
    return packet


@pytest.mark.parametrize('lecture', [False, True])
def test_each_source_image_has_adjacent_role_and_exact_asset_mapping(lecture):
    packet = envelope(lecture=lecture)
    parts = [image('previous'), image('current')] + ([image('lecture')] if lecture else [])
    before = deepcopy((packet, parts))
    content = request_messages('policy', packet, parts)[1]['content']
    assert json.loads(content[0]['text']) == packet
    assert [part for part in content if part['type'] == 'image_url'] == parts
    assert len(content) == 1 + 2 * len(parts)
    roles = ['PREVIOUS_CONTEXT_ONLY', 'CURRENT_SOURCE'] + (['LECTURE_NAVIGATION_ONLY'] if lecture else [])
    assets = ['p0001-page', 'p0002-page'] + (['cover-page'] if lecture else [])
    for index, (role, asset) in enumerate(zip(roles, assets)):
        caption = json.loads(content[1 + index * 2]['text'])
        assert caption['imageRole'] == role
        assert caption['assetId'] == asset
        if index < 2:
            assert caption['sourceReference'] == ('s1' if index == 0 else 's0')
        else:
            assert caption['sourceReference']['documentId'] == 'lecture'
        assert content[2 + index * 2] == parts[index]
    assert 'classify' in json.loads(content[1]['text'])['instruction']
    assert 'inventory' in json.loads(content[3]['text'])['instruction']
    if lecture:
        assert 'classify' in json.loads(content[5]['text'])['instruction']
    assert (packet, parts) == before


@pytest.mark.parametrize('count', [0, 1, 3])
def test_request_rejects_missing_or_extra_images_instead_of_mislabeling_them(count):
    with pytest.raises(ValueError, match='image.*count|count.*image'):
        request_messages('policy', envelope(lecture=False), [image(str(i)) for i in range(count)])


def test_text_bound_counts_captions_and_reserved_schema_bytes():
    from src.supporting.extraction_source import image_caption_size
    packet = envelope()
    parts = [image('previous'), image('current'), image('lecture')]
    policy = 'policy'
    base = len(policy) + len(canonical_bytes(packet).decode('utf-8'))
    caption_size = image_caption_size(packet)
    assert caption_size > 0
    schema_size = MAX_TEXT_PER_CALL - base - caption_size
    messages = request_messages(policy, packet, parts, schema_size=schema_size)
    text_size = len(messages[0]['content']) + sum(len(p['text']) for p in messages[1]['content'] if p['type'] == 'text')
    assert text_size + schema_size == MAX_TEXT_PER_CALL
    with pytest.raises(ValueError, match='bounds'):
        request_messages(policy, packet, parts, schema_size=schema_size + 1)


def test_even_labeled_images_cannot_exceed_the_eight_image_limit():
    packet = envelope(lecture=False)
    packet['previous'] = None
    packet['source']['assetIds'] = [f'asset-{index}' for index in range(9)]
    with pytest.raises(ValueError, match='bounds'):
        request_messages('policy', packet, [image(str(index)) for index in range(9)])


def test_actual_extraction_labels_supporting_and_lecture_images_within_full_schema_budget():
    from types import SimpleNamespace
    from src.services.source_evidence import SourceEvidence
    from .test_source_context import source_scope
    from .test_supporting_extraction import extractor, pdf, proof, item, page, Provider

    raw = pdf(['Question 1: Explain trees', 'Question 2: Compare graphs'])
    manifest = extractor().prepare_pages(
        {'userId': 'u', 'courseId': 'c', 'kind': 'tutorial', 'materialId': 'm'}, raw, 'pdf')
    scope = source_scope(['Algorithms: lecture cover, for navigation'], visual=True)
    library = SimpleNamespace(render_reference=lambda *args: ['data:image/png;base64,lecture-cover'])
    reader = SourceEvidence(scope, library, 'u', 'c', None, 'never-call-model')
    before = deepcopy((reader.scope, reader.guide, reader.text_budget, reader.image_budget))
    provider = Provider({f'p{number:04d}': page([item(proof(manifest, number), f'Question {number}')])
                         for number in (1, 2)})
    result = extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader,
        render=lambda unit: ['data:image/png;base64,supporting-' + unit['unitId']], checkpoint=lambda state: None)
    assert result['extractionCoverage']['complete']
    assert len(provider.calls) == 4
    for index, call in enumerate(provider.calls):
        content = call['messages'][1]['content']
        paired = list(zip(content[1::2], content[2::2]))
        roles = [json.loads(caption['text'])['imageRole'] for caption, _ in paired]
        assert roles == (['PREVIOUS_CONTEXT_ONLY'] if index % 2 else []) + ['CURRENT_SOURCE', 'LECTURE_NAVIGATION_ONLY']
        assert paired[-1][1]['image_url']['url'].endswith('lecture-cover')
        assert paired[-2][1]['image_url']['url'].endswith(f'supporting-p{index % 2 + 1:04d}')
        size = len(call['messages'][0]['content']) + sum(len(part['text']) for part in content if part['type'] == 'text')
        size += len(canonical_bytes(call['response_format']['json_schema']['schema']).decode('utf-8'))
        assert size <= MAX_TEXT_PER_CALL
    assert (reader.scope, reader.guide, reader.text_budget, reader.image_budget) == before
    assert reader.supplied == []
