"""Deterministic complete plans and exact evidence-bound citations."""
from copy import deepcopy
import json

import pytest

from src.utils.source_contracts import build_source_manifest, guide_digest


def source_scope(texts, visual=False):
    units = []
    for i, text in enumerate(texts, 1):
        unit = {'unitId': f'p{i:04d}', 'kind': 'page', 'position': i, 'label': f'Page {i}',
                'text': text, 'blank': not text, 'needsVisualRead': False, 'warnings': [], 'visualAssets': []}
        if visual and i == (len(texts) if visual == 'last' else 1):
            unit.update(needsVisualRead=True, blank=False, visualReadStatus='readable',
                        visualText='رسم يوضح أَشجار البحث. Café search trees.',
                        visualAssets=[{'assetId': f'page-{i}', 'unitId': f'p{i:04d}', 'kind': 'page', 'mimeType': 'image/png'}])
        units.append(unit)
    manifest = build_source_manifest('selected', 'a'*64, 'pdf', units)
    guide = {'version': 1, 'sourceRevision': manifest['sourceRevision'],
             'sections': [{'label': 'Only guide heading', 'purpose': 'Navigation', 'unitIds': ['p0001']}],
             'concepts': [], 'visualReferences': [], 'warnings': [], 'unitCoverage': deepcopy(manifest['coverage'])}
    refs = [{'documentId': 'selected', 'sourceRevision': manifest['sourceRevision'], 'unitId': u['unitId']} for u in units]
    return {'documents': [{'id': 'selected', 'title': 'Lecture', 'sourceRevision': manifest['sourceRevision'],
                           'guideRevision': guide_digest(guide), 'guide': guide}],
            'manifests': [manifest], 'allowedRefs': refs, 'scopeRevision': 'b'*64}


def plan(scope, purpose='summary', **kwargs):
    from src.utils.source_context import build_source_plan
    return build_source_plan(scope, purpose, **kwargs)


def evidence_text(batches):
    return ''.join(r['text'] for b in batches for e in b['evidence'] for r in e['ranges'])


@pytest.mark.parametrize('purpose', ['summary', 'exam', 'flashcards'])
def test_broad_plans_cover_all_long_ranges_and_blank_units_without_claiming_execution(purpose):
    text = 'First lesson. ' + 'x'*48000 + ' A late requested fact.'
    scope = source_scope([text, '', 'Academic idea omitted from guide.'], visual=True)
    batches = plan(scope, purpose, text_budget=4000, image_budget=1)
    assert batches == plan(scope, purpose, text_budget=4000, image_budget=1)
    assert all(len(json.dumps(b, ensure_ascii=False, sort_keys=True, separators=(',', ':'))) <= 4000 for b in batches)
    all_refs = [e['ref'] for b in batches for e in b['evidence']]
    assert {r['unitId'] for r in all_refs} == {'p0001', 'p0002', 'p0003'}
    for unit in scope['manifests'][0]['units']:
        for field in ('text', 'visualText'):
            ranges = [r for b in batches for e in b['evidence'] if e['ref']['unitId'] == unit['unitId']
                      for r in e['ranges'] if r['textField'] == field]
            assert ''.join(r['text'] for r in ranges) == unit.get(field, '')
            assert all(r['text'] == unit[field][r['start']:r['end']] for r in ranges)
            assert all(a['end'] == b['start'] for a, b in zip(ranges, ranges[1:]))
    for b in batches:
        assert b['coverage']['state'] == 'planned'
        assert b['coverage']['processedRefs'] == []
        assert b['coverage']['complete'] is False
    blank = [e for b in batches for e in b['evidence'] if e['ref']['unitId'] == 'p0002']
    assert len(blank) == 1 and blank[0]['disposition'] == 'excluded_blank'
    images = [image for b in batches for e in b['evidence'] for image in e['images']]
    assert len(images) == 1
    assert images[0]['asset'] == scope['manifests'][0]['units'][0]['visualAssets'][0]
    assert images[0]['ref'] == scope['allowedRefs'][0]


@pytest.mark.parametrize('query,fact', [('اشجار البحث', 'أَشجار البحث'), ('CAFÉ trees', 'Café search trees')])
def test_focused_unicode_ranking_finds_late_native_and_visual_facts(query, fact):
    scope = source_scope(['irrelevant '*9000, fact + ' are explained here.'], visual=True)
    batches = plan(scope, 'focused', query=query, text_budget=2500)
    assert fact in evidence_text(batches)
    assert all(b['coverage']['mode'] == 'partial' and not b['coverage']['complete'] for b in batches)
    assert 'Only guide heading' not in evidence_text(batches)


def test_focused_finds_fact_inside_late_long_unit_not_only_first_chunk():
    fact = 'rare quasar resonance explanation'
    scope = source_scope(['irrelevant '*20000 + fact])
    assert fact in evidence_text(plan(scope, 'focused', query='quasar resonance', text_budget=2500))


def test_unselected_source_never_enters_plan():
    scope = source_scope(['chosen content'])
    assert {e['ref']['documentId'] for b in plan(scope) for e in b['evidence']} == {'selected'}


@pytest.mark.parametrize('budget', [0, -1, True, 200])
def test_indivisible_or_invalid_budget_fails_with_selection_split_guidance(budget):
    with pytest.raises(ValueError, match='[Ss]elect|[Ss]plit|budget'):
        plan(source_scope(['fact']), text_budget=budget)


def test_exact_citations_reject_unsupplied_stale_invented_foreign_and_blank_refs():
    from src.utils.source_context import validate_source_refs
    scope = source_scope(['fact', 'second fact', ''])
    supplied = plan(scope, 'focused', query='fact', text_budget=1800)[0]['evidence']
    ref = supplied[0]['ref']
    assert validate_source_refs([ref, ref], scope, supplied) == [ref]
    invalid = [{**ref, 'sourceRevision': 'c'*64}, {**ref, 'documentId': 'foreign'},
               {**ref, 'unitId': 'p0999'}, {**ref, 'extra': 'invalid'}, scope['allowedRefs'][2]]
    for citation in invalid:
        with pytest.raises(ValueError): validate_source_refs([citation], scope, supplied)
    with pytest.raises(ValueError): validate_source_refs([ref], scope, [])
    forged = deepcopy(supplied)
    forged[0]['ranges'][0]['text'] = 'made up evidence'
    with pytest.raises(ValueError): validate_source_refs([ref], scope, forged)


def test_plan_limits_reject_before_returning_successful_truncation():
    scope = source_scope(['x'*600000])
    with pytest.raises(ValueError, match='128.*[Ss]elect|128.*[Ss]plit'):
        plan(scope, text_budget=2000)
    # DOCX supports many ordered blocks; this is a planning limit, not an extraction cap.
    from src.utils.source_context import MAX_SOURCE_PLAN_UNITS
    scope = source_scope(['x'])
    units = [{**scope['manifests'][0]['units'][0], 'unitId': f'b{i:04d}', 'kind': 'block', 'position': i}
             for i in range(1, MAX_SOURCE_PLAN_UNITS + 2)]
    manifest = build_source_manifest('selected', 'a'*64, 'docx', units)
    scope['manifests'] = [manifest]
    scope['allowedRefs'] = [{'documentId': 'selected', 'sourceRevision': manifest['sourceRevision'], 'unitId': u['unitId']} for u in units]
    with pytest.raises(ValueError, match='3201.*3200.*[Ss]elect|3201.*3200.*[Ss]plit'):
        plan(scope)


def test_admin_text_is_planned_as_candidate_never_excluded_by_guide_omission():
    batches = plan(source_scope(['Academic lecture', 'Office hours: Sunday.']))
    assert 'Office hours: Sunday.' in evidence_text(batches)
    assert all(e['disposition'] == 'candidate' for b in batches for e in b['evidence'])


def test_original_images_require_successful_supply_and_exact_locator():
    from src.utils.source_context import validate_source_refs
    scope = source_scope(['fact'], visual=True)
    images = [e for b in plan(scope) for e in b['evidence'] if e['images']]
    ref = scope['allowedRefs'][0]
    with pytest.raises(ValueError): validate_source_refs([ref], scope, images)
    images[0]['images'][0]['supplied'] = True
    assert validate_source_refs([ref], scope, images) == [ref]
    images[0]['images'][0]['asset']['assetId'] = 'invented'
    with pytest.raises(ValueError): validate_source_refs([ref], scope, images)


def test_bundle_formatter_preserves_budget_accounting_and_unicode():
    from src.utils.generation_context import source_bundle_text
    bundle = plan(source_scope(['أَشجار البحث']), text_budget=1800)[0]
    text = source_bundle_text(bundle)
    assert json.loads(text) == bundle and len(text) <= 1800
    assert 'أَشجار' in text


def test_tiny_focused_budget_does_not_trim_away_early_query_hit():
    scope = source_scope(['quasar resonance ' + 'filler '*5000])
    assert 'quasar resonance' in evidence_text(plan(scope, 'focused', query='quasar resonance', text_budget=1500))


def test_repeated_query_hits_do_not_make_focused_context_indivisible():
    scope = source_scope(['trees '*600])
    assert 'trees' in evidence_text(plan(scope, 'focused', query='trees', text_budget=1200))


def test_many_images_are_batched_completely_and_zero_budget_fails_honestly():
    scope = source_scope(['Charts are explained.'], visual=True)
    unit = scope['manifests'][0]['units'][0]
    unit['visualAssets'] = [{**unit['visualAssets'][0], 'assetId': f'image-{i}'} for i in range(11)]
    manifest = build_source_manifest('selected', 'a'*64, 'pdf', [unit])
    scope['manifests'] = [manifest]
    scope['allowedRefs'][0]['sourceRevision'] = manifest['sourceRevision']
    batches = plan(scope, image_budget=2)
    images = [im for b in batches for e in b['evidence'] for im in e['images']]
    assert [im['assetIndex'] for im in images] == list(range(11))
    assert all(sum(len(e['images']) for e in b['evidence']) <= 2 for b in batches)
    with pytest.raises(ValueError, match='[Ss]elect|[Ss]plit'):
        plan(scope, image_budget=0)


def test_blank_only_plan_has_no_citable_evidence():
    from src.utils.source_context import validate_source_refs
    scope = source_scope([''])
    batches = plan(scope)
    assert batches[0]['coverage']['plannedExcludedRefs'] == scope['allowedRefs']
    with pytest.raises(ValueError): validate_source_refs(scope['allowedRefs'], scope, batches[0]['evidence'])
