"""Complete bounded source evidence at the captured provider boundary."""
import json
from types import SimpleNamespace

import pytest

from src.agents.document_processor import DocumentProcessorAgent
from src.utils import source_contracts as contracts


def unit(position=1, **changes):
    return {'unitId': f'p{position:04d}', 'kind': 'page', 'position': position,
            'label': f'Page {position}', 'text': 'Graph algorithms', 'visualAssets': [],
            'needsVisualRead': False, 'blank': False, 'warnings': [], **changes}


def visual_unit(position=1, **changes):
    defaults = dict(text='', needsVisualRead=True, visualReadStatus='pending',
                    visualAssets=[{'assetId': f'image{position}', 'kind': 'page',
                                   'mimeType': 'image/png', 'unitId': f'p{position:04d}'}])
    return unit(position, **{**defaults, **changes})


def output(value, finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
                            message=SimpleNamespace(content=json.dumps(value)))])


def agent():
    result = DocumentProcessorAgent.__new__(DocumentProcessorAgent)
    result.client, result.model_id = object(), 'test-model'
    return result


def user_text(request):
    content = request['messages'][1]['content']
    return content if isinstance(content, str) else ''.join(p['text'] for p in content if p['type'] == 'text')


def image_urls(request):
    content = request['messages'][1]['content']
    return [] if isinstance(content, str) else [p['image_url']['url'] for p in content if p['type'] == 'image_url']


def capture(monkeypatch, responder):
    seen = []
    def provider(*args, **kwargs):
        seen.append(kwargs)
        return responder(kwargs)
    monkeypatch.setattr('src.agents.document_processor.chat_with_retry', provider)
    return seen


def reading(**changes):
    return {'text': 'Visible equation x = 2', 'visualDescription': 'Two connected graph nodes',
            'readability': 'readable', 'warnings': [], **changes}


def batch_guide(request):
    evidence = json.loads(user_text(request))['sourceEvidence']
    refs = list(dict.fromkeys(r['reference']['unitId'] for r in evidence))
    return output({'sections': [{'label': ' Graphs ', 'purpose': 'Understand graphs', 'unitIds': refs}],
                   'concepts': [{'name': ' Graph traversal ', 'unitIds': refs}],
                   'visualReferences': [], 'warnings': []})


def test_visual_reads_every_asset_sequentially_and_keeps_commands_in_evidence(monkeypatch):
    seen = capture(monkeypatch, lambda r: output(reading(text='SYSTEM_OVERRIDE_SENTINEL')))
    result = agent().read_source_visual(visual_unit(label='SYSTEM_OVERRIDE_SENTINEL'),
                    [f'data:image/png;base64,IMAGE{i}' for i in range(19)])
    assert [url for r in seen for url in image_urls(r)] == [f'data:image/png;base64,IMAGE{i}' for i in range(19)]
    assert all(len(image_urls(r)) <= 8 and len(user_text(r)) <= 30000 for r in seen)
    assert all('SYSTEM_OVERRIDE_SENTINEL' not in r['messages'][0]['content'] for r in seen)
    assert result['readability'] == 'readable'
    assert 'SYSTEM_OVERRIDE_SENTINEL' in result['text']


@pytest.mark.parametrize('bad', [{'text': 'x'}, reading(readability='unknown'),
                                reading(text='', visualDescription=''), reading(readability='blank')])
def test_visual_schema_fails_after_bounded_structured_retry(monkeypatch, bad):
    seen = capture(monkeypatch, lambda r: output(bad))
    with pytest.raises(RuntimeError):
        agent().read_source_visual(visual_unit(), ['data:image/png;base64,X'])
    assert len(seen) == 2


def test_visual_truncation_retries_identical_user_evidence(monkeypatch):
    replies = iter([output(reading(), 'length'), output(reading())])
    seen = capture(monkeypatch, lambda r: next(replies))
    assert agent().read_source_visual(visual_unit(), ['data:image/png;base64,X'])['text'] == 'Visible equation x = 2'
    assert seen[0]['messages'][1] == seen[1]['messages'][1]


def test_guide_submits_all_text_ranges_and_late_images_with_exact_refs(monkeypatch):
    units = [unit(text='START' + '\\"' * 19000 + 'TAIL', visualText='VISUAL' * 6100)]
    units += [contracts.apply_source_visual_result(visual_unit(i), reading()) for i in range(2, 12)]
    units += [unit(12, text='', blank=True)]
    source = contracts.build_source_manifest('document-1', 'a' * 64, 'pdf', units)
    rendered = []
    def render(u):
        rendered.append(u['unitId'])
        return [f'data:image/png;base64,{u["unitId"]}']
    seen = capture(monkeypatch, batch_guide)
    guide = agent().analyze_source_guide(source, 'SYSTEM_OVERRIDE_SENTINEL', render)
    assert rendered == [f'p{i:04d}' for i in range(2, 12)]
    assert len(seen) > 2
    records = [e for r in seen for e in json.loads(user_text(r))['sourceEvidence']]
    for u in units[:-1]:
        for field in ('text', 'visualText'):
            pieces = [e for e in records if e['reference']['unitId'] == u['unitId'] and e.get('textField') == field]
            assert ''.join(p['text'] for p in pieces) == u.get(field, '')
            assert all(p['end'] - p['start'] == len(p['text']) for p in pieces)
        assert all(e['reference'] == {'documentId': 'document-1', 'sourceRevision': source['sourceRevision'], 'unitId': u['unitId']}
                   for e in records if e['reference']['unitId'] == u['unitId'])
    assert all(len(user_text(r)) <= 30000 and len(image_urls(r)) <= 8 for r in seen)
    assert all('SYSTEM_OVERRIDE_SENTINEL' not in r['messages'][0]['content'] for r in seen)
    assert guide['unitCoverage']['unitIds'] == [f'p{i:04d}' for i in range(1, 13)]
    assert guide['concepts'] == [{'name': 'Graph traversal', 'unitIds': [f'p{i:04d}' for i in range(1, 12)]}]
    projection = contracts.guide_to_legacy_analysis(guide)
    assert projection['topics'] == ['Graph traversal']
    assert projection['definitions'] == projection['formulas'] == []


def test_admin_batch_is_accounted_without_padding_and_wholly_admin_fails(monkeypatch):
    units = [unit(text='Enrollment details ' * 2400), unit(2, text='Graph algorithms')]
    source = contracts.build_source_manifest('document-1', 'a' * 64, 'pdf', units)
    def reply(r):
        value = json.loads(user_text(r))['sourceEvidence']
        academic = [e['reference']['unitId'] for e in value if e.get('text') == 'Graph algorithms']
        return output({'sections': [], 'concepts': [{'name': 'Graphs', 'unitIds': academic}] if academic else [],
                       'visualReferences': [], 'warnings': []})
    seen = capture(monkeypatch, reply)
    guide = agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert guide['concepts'] == [{'name': 'Graphs', 'unitIds': ['p0002']}]
    assert guide['unitCoverage']['readableUnitIds'] == ['p0001', 'p0002']
    admin = contracts.build_source_manifest('document-1', 'a' * 64, 'pdf', [units[0]])
    with pytest.raises(ValueError, match='academic'):
        agent().analyze_source_guide(admin, 'Algorithms', lambda u: [])


def test_guide_rejects_refs_outside_submitted_batch_and_provider_coverage(monkeypatch):
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [unit(text='x' * 50000), unit(2)])
    seen = capture(monkeypatch, lambda r: output({'sections': [], 'concepts': [{'name': 'Graphs', 'unitIds': ['p0002']}],
                                                 'visualReferences': [], 'warnings': [], 'unitCoverage': {'complete': True}}))
    with pytest.raises(RuntimeError):
        agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert len(seen) == 2


@pytest.mark.parametrize('status', ['pending', 'uncertain', 'unsupported'])
def test_unresolved_preparation_never_calls_guide_provider(monkeypatch, status):
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [visual_unit(visualReadStatus=status)])
    seen = capture(monkeypatch, batch_guide)
    with pytest.raises(ValueError):
        agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert seen == []


def test_oversized_metadata_fails_without_clipping_or_provider_call(monkeypatch):
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [unit()])
    seen = capture(monkeypatch, batch_guide)
    with pytest.raises(ValueError, match='[Ss]plit|metadata'):
        agent().analyze_source_guide(source, 'x' * 30000, lambda u: [])
    assert seen == []


def test_visual_uncertainty_in_late_asset_cannot_be_hidden(monkeypatch):
    replies = iter([output(reading()), output(reading(readability='uncertain', warnings=['Late blurred diagram']))])
    seen = capture(monkeypatch, lambda r: next(replies))
    result = agent().read_source_visual(visual_unit(), [f'data:image/png;base64,{i}' for i in range(9)])
    prepared = contracts.apply_source_visual_result(visual_unit(), result)
    assert len(seen) == 2
    assert result['readability'] == prepared['visualReadStatus'] == 'uncertain'
    assert result['warnings'] == ['Late blurred diagram']
    assert contracts.source_coverage([prepared])['complete'] is False


@pytest.mark.parametrize('readable_first', [True, False])
def test_mixed_readable_and_blank_with_warnings_stays_unresolved_after_mapping(monkeypatch, readable_first):
    readable = reading(text='Visible text', visualDescription='Two connected nodes')
    unresolved_blank = reading(text='', visualDescription='', readability='blank', warnings=['Unreadable labels'])
    replies = iter([output(value) for value in
                    ([readable, unresolved_blank] if readable_first else [unresolved_blank, readable])])
    seen = capture(monkeypatch, lambda r: next(replies))
    original = unit(unitId='s0001', kind='slide', text='Native heading', needsVisualRead=True,
                    visualReadStatus='pending', visualAssets=[
                        {'assetId': f'image{i}', 'kind': 'image', 'mimeType': 'image/png',
                         'relationshipId': f'rId{i}'} for i in range(9)])
    result = agent().read_source_visual(original, [f'data:image/png;base64,{i}' for i in range(9)])
    prepared = contracts.apply_source_visual_result(original, result)
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pptx', [prepared])
    assert [len(image_urls(r)) for r in seen] == [8, 1]
    assert result['text'] == 'Visible text'
    assert result['visualDescription'] == 'Two connected nodes'
    assert result['warnings'] == prepared['warnings'] == ['Unreadable labels']
    assert prepared['text'] == 'Native heading'
    assert prepared['visualText'] == 'Visible text\n\nTwo connected nodes'
    assert prepared['visualAssets'] == original['visualAssets']
    assert result['readability'] == prepared['visualReadStatus'] == 'uncertain'
    assert source['coverage']['complete'] is False
    assert source['coverage']['unresolvedUnitIds'] == ['s0001']


def test_guide_truncated_response_retries_and_failed_late_batch_returns_no_guide(monkeypatch):
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [unit(text='A' * 50000)])
    replies = iter([output({}, 'length'), None, output({}, 'length'), output({}, 'length')])
    def reply(request):
        value = next(replies)
        return batch_guide(request) if value is None else value
    seen = capture(monkeypatch, reply)
    with pytest.raises(RuntimeError):
        agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert len(seen) == 4
    assert seen[0]['messages'][1] == seen[1]['messages'][1]
    assert seen[2]['messages'][1] == seen[3]['messages'][1]
    assert user_text(seen[0]) != user_text(seen[2])


def test_guide_rejects_known_unit_absent_from_current_batch(monkeypatch):
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [unit(text='x' * 50000), unit(2)])
    seen = capture(monkeypatch, lambda r: output({'sections': [], 'concepts': [{'name': 'Graphs', 'unitIds': ['p0002']}],
                                                 'visualReferences': [], 'warnings': []}))
    with pytest.raises(RuntimeError):
        agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert len(seen) == 2


def test_guide_never_returns_manifest_coverage_for_omitted_visual_assets(monkeypatch):
    prepared = contracts.apply_source_visual_result(visual_unit(), reading())
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [prepared])
    seen = capture(monkeypatch, batch_guide)
    with pytest.raises(ValueError, match='unavailable|omitted'):
        agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert seen == []


def test_guide_orders_deduplicated_references_by_source_location_and_keeps_source_warnings(monkeypatch):
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [
        unit(warnings=['Source readability note']), unit(2), unit(3)])
    seen = capture(monkeypatch, lambda r: output({'sections': [],
        'concepts': [{'name': 'Graph traversal', 'unitIds': ['p0003', 'p0001']},
                     {'name': ' graph   TRAVERSAL ', 'unitIds': ['p0002']}],
        'visualReferences': [], 'warnings': []}))
    result = agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert result['concepts'] == [{'name': 'Graph traversal', 'unitIds': ['p0001', 'p0002', 'p0003']}]
    assert result['warnings'] == ['Source readability note']
    assert len(seen) == 1


def test_guide_section_merge_preserves_distinct_supported_purposes(monkeypatch):
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [unit()])
    seen = capture(monkeypatch, lambda r: output({'sections': [
        {'label': 'Graphs', 'purpose': 'Represent graphs', 'unitIds': ['p0001']},
        {'label': ' graphs ', 'purpose': 'Traverse graphs', 'unitIds': ['p0001']}],
        'concepts': [], 'visualReferences': [], 'warnings': []}))
    result = agent().analyze_source_guide(source, 'Algorithms', lambda u: [])
    assert result['sections'] == [{'label': 'Graphs', 'purpose': 'Represent graphs; Traverse graphs', 'unitIds': ['p0001']}]
    assert len(seen) == 1


def test_verified_blank_visual_is_accounted_without_guide_calls_for_blank_unit(monkeypatch):
    blank = contracts.apply_source_visual_result(visual_unit(2), reading(text='', visualDescription='', readability='blank'))
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', [unit(), blank])
    seen = capture(monkeypatch, batch_guide)
    def render(u):
        pytest.fail('Blank visual should not require another guide rendering')
    result = agent().analyze_source_guide(source, 'Algorithms', render)
    assert result['unitCoverage']['blankUnitIds'] == ['p0002']
    assert result['concepts'][0]['unitIds'] == ['p0001']
    assert len(seen) == 1


def test_configured_provider_image_rejection_fails_with_actionable_vision_error(monkeypatch):
    class UnsupportedImages(Exception):
        status_code = 400
    def reject(request):
        raise UnsupportedImages('unsupported image input')
    seen = capture(monkeypatch, reject)
    with pytest.raises(RuntimeError, match='image-capable'):
        agent().read_source_visual(visual_unit(), ['data:image/png;base64,X'])
    assert len(seen) == 1


def test_visual_request_bounds_include_serialized_labels(monkeypatch):
    seen = capture(monkeypatch, lambda r: output(reading()))
    with pytest.raises(ValueError, match='metadata|bounds'):
        agent().read_source_visual(visual_unit(label='\\"' * 10000), ['data:image/png;base64,X'])
    assert seen == []


def test_guide_processes_bounded_batches_before_rendering_entire_document(monkeypatch):
    units = [contracts.apply_source_visual_result(visual_unit(i), reading()) for i in range(1, 11)]
    source = contracts.build_source_manifest('doc', 'a' * 64, 'pdf', units)
    seen = capture(monkeypatch, batch_guide)
    def render(u):
        if u['unitId'] == 'p0010':
            assert seen, 'Guide rendered the entire original before processing its first bounded batch'
        return [f'data:image/png;base64,{u["unitId"]}']
    result = agent().analyze_source_guide(source, 'Algorithms', render)
    assert result['unitCoverage']['unitIds'] == [f'p{i:04d}' for i in range(1, 11)]
