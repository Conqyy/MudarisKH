"""Original-evidence checks for supporting material alignment."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.services.source_evidence import SourceEvidence
from src.supporting.contracts import validate_alignment_report
from src.utils.source_context import build_source_plan
from tests.supporting_fixtures import alignment_report, supporting_manifest, supporting_ref
from tests.test_source_context import source_scope


def response(value, *, finish_reason='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content=json.dumps(value, ensure_ascii=False)))])


class LectureRenderer:
    def render_reference(self, user_id, course_id, ref):
        return ['data:image/png;base64,YQ==']


def reader(scope):
    return SourceEvidence(scope, LectureRenderer(), 'owner', 'course', object(), 'fake')


def test_public_original_read_counts_returned_invalid_response_before_parse(monkeypatch):
    scope = source_scope(['A taught definition.'])
    batch = build_source_plan(scope, 'summary')[0]
    calls = []

    def provider(*args, **kwargs):
        calls.append(deepcopy(kwargs['messages']))
        return response({'ok': True}, finish_reason='length')

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    source = reader(scope)
    returned = []
    with pytest.raises(ValueError):
        source.read_original_batch(batch, policy='Check originals.', task={'targetIds': ['r1']},
                                   on_response=lambda: returned.append('returned'))
    assert returned == ['returned']
    assert source.supplied == []
    assert len(calls) == 1


def test_public_original_read_bounds_all_text_and_images(monkeypatch):
    scope = source_scope(['A taught definition.'], visual=True)
    batch = build_source_plan(scope, 'summary')[0]
    delivered = []
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
                        lambda *args, **kwargs: delivered.append(kwargs['messages']) or response({'ok': True}))
    source = reader(scope)
    result, supplied = source.read_original_batch(batch, policy='Read original.', task={'targetIds': ['r1']})
    assert result == {'ok': True}
    assert supplied and source.supplied == supplied
    assert len(delivered) == 1
    assert any(part['type'] == 'image_url' for part in delivered[0][1]['content'])
    with pytest.raises(ValueError, match='(?i)bound|budget|split'):
        source.read_original_batch(batch, policy='x'*24000, task={'targetIds': ['r1']})
    assert len(delivered) == 1


def test_complete_review_needs_exact_supplied_intervals_and_proof_containment():
    report = alignment_report()
    finding = report['alignments'][0]['requirements'][0]
    finding['reviewCoverage'].pop('suppliedEvidence')
    with pytest.raises(ValueError, match='(?i)supplied|ledger|review'):
        validate_alignment_report(report)
    ref = report['scopeSnapshot']['allowedRefs'][0]
    text = report['scopeSnapshot']['manifests'][0]['units'][0]['text']
    finding['reviewCoverage'].update(
        suppliedEvidence=[{'ref': ref, 'ranges': [{'textField': 'text', 'start': 0, 'end': len(text)}], 'assetIds': []}],
        excludedBlankRefs=[], checkState='complete')
    assert validate_alignment_report(report)['alignmentCoverage']['complete'] is True
    finding['reviewCoverage']['suppliedEvidence'][0]['ranges'][0]['start'] = 6
    with pytest.raises(ValueError, match='(?i)proof|supplied|review'):
        validate_alignment_report(report)


class SupportingOriginals:
    def __init__(self, manifest):
        self.manifest = manifest
        self.database = None

    def load_source(self, identity, source_revision=None):
        assert identity == self.manifest['identity']
        assert source_revision in (None, self.manifest['sourceRevision'])
        return deepcopy(self.manifest)

    def read_refs(self, identity, refs):
        assert identity == self.manifest['identity']
        return [deepcopy(next(u for u in self.manifest['units'] if u['unitId'] == ref['unitId'])) for ref in refs]

    def render_reference(self, identity, ref):
        assert identity == self.manifest['identity']
        return ['data:image/png;base64,YQ==']


def one_requirement(manifest, requirement_text):
    ref = supporting_ref(manifest)
    original = manifest['units'][0]['text']
    proof = {'type': 'text_span', 'ref': ref, 'field': 'text', 'start': 0,
             'end': len(original), 'quote': original}
    item = {'id': 'q1', 'parentId': None, 'paperId': None, 'printedLabel': None,
            'itemType': 'teaching_point' if manifest['identity']['kind'] != 'historical_exam' else 'question',
            'text': original, 'sharedContextIds': [], 'choices': [], 'givenData': [], 'printedMarks': None,
            'requirements': [{'id': 'r1', 'text': requirement_text, 'category': 'concept',
                              'supportingSourceRefs': [ref], 'supportingSourceProofs': [proof]}],
            'supportingSourceRefs': [ref], 'supportingSourceProofs': [proof]}
    return {'items': [item], 'sharedContexts': [], 'papers': [], 'topics': [],
            'extractionCoverage': {'unitIds': [u['unitId'] for u in manifest['units']],
                'accountedUnitIds': [u['unitId'] for u in manifest['units']],
                'unresolvedUnitIds': [], 'complete': True}}


def text_proof(ref, text, quote):
    start = text.index(quote)
    return {'type': 'text_span', 'ref': deepcopy(ref), 'field': 'text', 'start': start,
            'end': start + len(quote), 'quote': quote}


def visual_proof(ref, asset_id='page-1', box=None):
    return {'type': 'visual_region', 'ref': deepcopy(ref), 'assetId': asset_id,
            'box': [0.1, 0.1, 0.9, 0.9] if box is None else box}


def request_packet(messages):
    return json.loads(messages[1]['content'][0]['text'])


def test_incidental_first_candidate_does_not_hide_late_original_support(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Trees are decorative in this unrelated example.',
                          'A tree is a connected graph without cycles.'])
    manifest = supporting_manifest('historical_exam', ['Define a tree.'])
    library = SupportingOriginals(manifest)
    candidate = text_proof(scope['allowedRefs'][1], scope['manifests'][0]['units'][1]['text'],
                           'A tree is a connected graph without cycles.')
    source_proof = one_requirement(manifest, 'Define a tree')['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    seen = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage, targets = packet['task']['stage'], packet['task']['targets']
        seen.append((stage, deepcopy(packet), deepcopy(kwargs['messages'])))
        if stage == 'source_check':
            return response({'judgments': [{'targetId': t['id'], 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': ['connected acyclic graph'],
                'explicitTeaching': False, 'reason': 'Original question asks for definition'} for t in targets]})
        if stage == 'verify':
            return response({'judgments': [{'targetId': t['id'], 'verdict': 'support',
                'lectureProofs': [candidate], 'reason': 'Exact definition in original lecture'} for t in targets]})
        evidence = packet['evidence']
        late = any(e['ref']['unitId'] == 'p0002' for e in evidence)
        return response({'judgments': [{'targetId': t['id'], 'verdict': 'support' if late else 'no_support',
            'lectureProofs': [candidate] if late else [],
            'reason': 'Original teaches the definition' if late else 'Incidental mention only'} for t in targets]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    checkpoints = []
    report = SupportingAligner(reader(scope), library).align(manifest['identity'],
        one_requirement(manifest, 'Define a tree'), scope=scope, checkpoint=checkpoints.append)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'lecture_supported'
    assert finding['lectureSupportProofs'] == [candidate]
    assert any(stage == 'search' and any(e['ref']['unitId'] == 'p0001' for e in packet['evidence'])
               for stage, packet, _ in seen)
    assert any(stage == 'search' and any(e['ref']['unitId'] == 'p0002' for e in packet['evidence'])
               for stage, packet, _ in seen)
    assert any(stage == 'verify' and any(e['ref']['unitId'] == 'p0002' for e in packet['evidence'])
               for stage, packet, _ in seen)
    assert checkpoints and report['alignmentCoverage']['complete'] is True


@pytest.mark.parametrize('fail_late', [False, True])
def test_only_complete_selected_original_sweep_authorizes_not_found(monkeypatch, fail_late):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['The lecture covers lists.', 'The later lecture covers arrays.'])
    manifest = supporting_manifest('historical_exam', ['Prove an untaught theorem.'])
    library = SupportingOriginals(manifest)
    inventory = one_requirement(manifest, 'Prove an untaught theorem')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    seen = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        units = {e['ref']['unitId'] for e in packet['evidence']}
        seen.append((stage, units))
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual question'}]})
        if fail_late and 'p0002' in units:
            return response({'judgments': []}, finish_reason='length')
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'no_support',
            'lectureProofs': [], 'reason': 'Different method'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    saved = []
    report = SupportingAligner(reader(scope), library).align(manifest['identity'], inventory,
        scope=scope, checkpoint=saved.append)
    finding = report['alignments'][0]['requirements'][0]
    assert any(stage == 'search' and 'p0002' in units for stage, units in seen)
    if fail_late:
        assert finding['relation'] == 'unverified'
        assert finding['reviewCoverage']['complete'] is False
        assert report['alignmentCoverage']['complete'] is False
        assert saved[-1]['modelCalls'] == len(seen)
    else:
        assert finding['relation'] == 'not_found'
        assert finding['reviewCoverage']['complete'] is True
        assert {r['unitId'] for r in finding['reviewCoverage']['reviewedRefs']} == {'p0001', 'p0002'}


def test_broad_topic_has_independent_result_and_cannot_borrow_question_support(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['A tree is a connected acyclic graph.'])
    manifest = supporting_manifest('historical_exam', ['Define a tree.'])
    inventory = one_requirement(manifest, 'Define a tree')
    original_proof = inventory['items'][0]['supportingSourceProofs'][0]
    inventory['topics'] = [{'id': 't1', 'text': 'Trees solve every graph problem',
        'itemIds': ['q1'], 'requirementIds': ['r1'], 'supportingSourceRefs': [supporting_ref(manifest)],
        'supportingSourceProofs': [original_proof]}]
    lecture_proof = text_proof(scope['allowedRefs'][0], scope['manifests'][0]['units'][0]['text'],
                               'A tree is a connected acyclic graph.')
    seen_targets = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        ids = [t['id'] for t in packet['task']['targets']]
        seen_targets.extend(ids)
        if stage == 'source_check':
            return response({'judgments': [{'targetId': target_id,
                'sourceVerdict': 'established' if target_id == 'r1' else 'not_established',
                'sourceProofs': [original_proof] if target_id == 'r1' else [],
                'queries': [], 'explicitTeaching': False, 'reason': 'Original statement checked'}
                for target_id in ids]})
        return response({'judgments': [{'targetId': target_id,
            'verdict': 'support' if target_id == 'r1' else 'no_support',
            'lectureProofs': [lecture_proof] if target_id == 'r1' else [],
            'reason': 'Definition only'} for target_id in ids]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None)
    assert report['alignments'][0]['status'] == 'covered'
    assert report['topics'][0]['alignment']['relation'] != 'lecture_supported'
    assert report['alignmentCoverage']['topicIds'] == ['t1']
    assert 't1' in seen_targets


def test_inseparable_parent_context_blocks_one_child_but_independent_sibling_is_covered(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['A tree is a connected acyclic graph.'])
    manifest = supporting_manifest('historical_exam', ['Use a Fourier transform. Define a tree.'])
    inventory = one_requirement(manifest, 'Use a Fourier transform')
    parent = inventory['items'][0]
    parent['id'], parent['text'] = 'parent', 'Use a Fourier transform.'
    parent['requirements'][0]['id'] = 'r-parent'
    source_ref = parent['supportingSourceRefs'][0]
    source_proof = parent['supportingSourceProofs'][0]
    context = {'id': 'stem', 'text': 'Use a Fourier transform.',
               'supportingSourceRefs': [source_ref], 'supportingSourceProofs': [source_proof]}
    parent['sharedContextIds'] = ['stem']
    for item_id, text in [('child-a', 'Define a tree with the given transform.'),
                          ('child-b', 'Independently define a tree.')]:
        child = deepcopy(parent)
        child.update(id=item_id, parentId='parent', text=text, sharedContextIds=[], requirements=[
            {'id': 'r-' + item_id, 'text': 'Define a tree', 'category': 'concept',
             'supportingSourceRefs': [source_ref], 'supportingSourceProofs': [source_proof]}])
        inventory['items'].append(child)
    inventory['sharedContexts'] = [context]
    lecture_proof = text_proof(scope['allowedRefs'][0], scope['manifests'][0]['units'][0]['text'],
                               'A tree is a connected acyclic graph.')

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        results = []
        for target in packet['task']['targets']:
            target_id = target['id']
            context_item = target.get('contextForItemId')
            if stage in ('source_check', 'context_verify'):
                result = {'targetId': target_id, 'sourceVerdict': 'established',
                          'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                          'reason': 'Original asks for these tasks'}
                if context_item:
                    result.update(decision='not_required' if context_item == 'child-b' else 'required',
                                  contentKind='academic_claim', methodRequired=True)
            else:
                teaches_tree = target_id in ('r-child-a', 'r-child-b')
                result = {'targetId': target_id,
                          'verdict': 'support' if teaches_tree else 'no_support',
                          'lectureProofs': [lecture_proof] if teaches_tree else [],
                          'reason': 'Only tree definition is taught'}
            results.append(result)
        return response({'judgments': results})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None)
    by_item = {row['itemId']: row for row in report['alignments']}
    assert by_item['child-a']['status'] == 'needs_review'
    assert by_item['child-b']['status'] == 'covered'
    assert any(dep['decision'] == 'required' and not dep['usable']
               for dep in by_item['child-a']['contextDependencies'])
    assert all(dep['decision'] == 'not_required' for dep in by_item['child-b']['contextDependencies'])


@pytest.mark.parametrize('case', ['uncertain_omission', 'misleading_given_method'])
def test_context_needs_independent_certificate_before_omission_or_source_only_use(monkeypatch, case):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['A tree is a connected acyclic graph.'])
    manifest = supporting_manifest('historical_exam', ['Use the Fourier method. Define a tree.'])
    inventory = one_requirement(manifest, 'Define a tree')
    child = inventory['items'][0]
    child['id'], child['requirements'][0]['id'] = 'child', 'r-child'
    source_ref, source_proof = child['supportingSourceRefs'][0], child['supportingSourceProofs'][0]
    parent = deepcopy(child)
    parent.update(id='parent', text='Use the Fourier method.', parentId=None,
                  sharedContextIds=[], requirements=[{'id': 'r-parent', 'text': 'Use the Fourier method',
                    'category': 'method', 'supportingSourceRefs': [source_ref],
                    'supportingSourceProofs': [source_proof]}])
    child['parentId'] = 'parent'
    inventory['items'].insert(0, parent)
    lecture_proof = text_proof(scope['allowedRefs'][0], scope['manifests'][0]['units'][0]['text'],
                               'A tree is a connected acyclic graph.')

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        rows = []
        for target in packet['task']['targets']:
            context = bool(target.get('contextForItemId'))
            if stage in ('source_check', 'context_verify'):
                row = {'targetId': target['id'], 'sourceVerdict':
                       'uncertain' if context and case == 'uncertain_omission' else 'established',
                       'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                       'reason': 'Original context checked'}
                if context:
                    row.update(decision='not_required' if case == 'uncertain_omission' else 'required',
                               contentKind='hypothetical_data', methodRequired=case == 'misleading_given_method')
            else:
                taught = target['id'] == 'r-child'
                row = {'targetId': target['id'], 'verdict': 'support' if taught else 'no_support',
                       'lectureProofs': [lecture_proof] if taught else [],
                       'reason': 'The Fourier method is absent'}
            rows.append(row)
        return response({'judgments': rows})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None)
    child_alignment = next(row for row in report['alignments'] if row['itemId'] == 'child')
    assert child_alignment['status'] == 'needs_review'
    assert child_alignment['contextDependencies'][0]['usable'] is False
    if case == 'uncertain_omission':
        assert child_alignment['contextDependencies'][0]['decision'] == 'unresolved'
        assert report['alignmentCoverage']['complete'] is False
    else:
        assert child_alignment['contextDependencies'][0]['methodRequired'] is True
        assert child_alignment['contextDependencies'][0]['relation'] != 'source_only'


def test_scope_shrink_rechecks_selected_absence_and_keeps_removed_original_separate(monkeypatch):
    from src.supporting.alignment import SupportingAligner
    from src.supporting.contracts import digest
    from src.utils.source_contracts import build_source_manifest, guide_digest

    selected = source_scope(['This lecture teaches lists.'])
    excluded_manifest = build_source_manifest('excluded', 'c'*64, 'pdf', [{
        'unitId': 'p0001', 'kind': 'page', 'position': 1, 'label': 'Page 1',
        'text': 'A tree is a connected acyclic graph.', 'blank': False,
        'needsVisualRead': False, 'warnings': [], 'visualAssets': []}])
    excluded_guide = {'version': 1, 'sourceRevision': excluded_manifest['sourceRevision'],
        'sections': [], 'concepts': [], 'visualReferences': [], 'warnings': [],
        'unitCoverage': deepcopy(excluded_manifest['coverage'])}
    excluded_doc = {'id': 'excluded', 'title': 'Removed lecture',
        'sourceRevision': excluded_manifest['sourceRevision'],
        'guideRevision': guide_digest(excluded_guide), 'guide': excluded_guide}
    whole = deepcopy(selected)
    whole['documents'].append(excluded_doc)
    whole['manifests'].append(excluded_manifest)
    excluded_ref = {'documentId': 'excluded', 'sourceRevision': excluded_manifest['sourceRevision'], 'unitId': 'p0001'}
    whole['allowedRefs'].append(excluded_ref)
    whole['scopeRevision'] = digest([{key: d[key] for key in ('id', 'sourceRevision', 'guideRevision')}
                                     for d in whole['documents']])
    manifest = supporting_manifest('historical_exam', ['Define a tree.'])
    library = SupportingOriginals(manifest)
    inventory = one_requirement(manifest, 'Define a tree')
    source_proof = inventory['items'][0]['supportingSourceProofs'][0]
    late_proof = text_proof(excluded_ref, excluded_manifest['units'][0]['text'],
                            'A tree is a connected acyclic graph.')
    monkeypatch.setattr('src.supporting.alignment.resolve_source_scope', lambda *args: deepcopy(whole))

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        ids = [t['id'] for t in packet['task']['targets']]
        if stage == 'source_check':
            return response({'judgments': [{'targetId': i, 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Original question'} for i in ids]})
        removed = any(e['ref']['documentId'] == 'excluded' for e in packet['evidence'])
        return response({'judgments': [{'targetId': i, 'verdict': 'support' if removed else 'no_support',
            'lectureProofs': [late_proof] if removed else [], 'reason': 'Exact lecture checked'} for i in ids]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    whole_report = SupportingAligner(reader(whole), library).align(manifest['identity'], inventory,
        scope=whole, checkpoint=lambda state: None)
    assert whole_report['alignments'][0]['requirements'][0]['relation'] == 'lecture_supported'
    shrunk = SupportingAligner(reader(selected), library).rescope(manifest['identity'], whole_report,
        scope=selected, checkpoint=lambda state: None)
    finding = shrunk['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'outside_selected_scope'
    assert finding['reviewCoverage']['complete'] is True
    assert {ref['documentId'] for ref in finding['reviewCoverage']['allowedRefs']} == {'selected'}
    assert finding['excludedLectureEvidence']['proofs'] == [late_proof]
    assert set(finding['excludedLectureEvidence']['documents'][0]) == {
        'id', 'sourceRevision', 'guideRevision'}
    assert shrunk['items'] == whole_report['items']


def test_current_explicit_teaching_needs_checked_anchor_and_complete_selected_sweep(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Trees are connected acyclic graphs.', 'Unrelated appendix. ' + 'x' * 9000])
    manifest = supporting_manifest('tutorial', ['The professor adds a red-black tree comparison.'])
    inventory = one_requirement(manifest, 'Compare red-black trees')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    anchor = text_proof(scope['allowedRefs'][0], scope['manifests'][0]['units'][0]['text'],
                        'Trees are connected acyclic graphs.')
    seen = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        unit_ids = {entry['ref']['unitId'] for entry in packet['evidence']}
        seen.append((stage, unit_ids))
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': ['tree comparison'], 'explicitTeaching': True,
                'reason': 'The tutorial explicitly teaches the addition'}]})
        if stage == 'verify':
            return response({'judgments': [{'targetId': 'r1', 'verdict': 'related_anchor',
                'lectureProofs': [anchor], 'reason': 'The selected original teaches the prerequisite'}]})
        anchored = 'p0001' in unit_ids
        return response({'judgments': [{'targetId': 'r1',
            'verdict': 'related_anchor' if anchored else 'no_support',
            'lectureProofs': [anchor] if anchored else [], 'reason': 'Checked selected original'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'related_supplementary'
    assert finding['lectureSupportProofs'] == [anchor]
    assert finding['reviewCoverage']['complete'] is True
    assert any(stage == 'search' and 'p0002' in units for stage, units in seen)


def test_historical_extra_cannot_become_supplementary_and_conflict_keeps_both_originals(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Trees always contain a cycle.'])
    manifest = supporting_manifest('historical_exam', ['Trees never contain a cycle.'])
    inventory = one_requirement(manifest, 'State whether trees contain cycles')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    lecture_proof = text_proof(scope['allowedRefs'][0], scope['manifests'][0]['units'][0]['text'],
                               'Trees always contain a cycle.')

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'The old exam asserts the opposite premise'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'conflict',
            'lectureProofs': [lecture_proof], 'reason': 'The originals contradict'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None
    )['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'conflicting'
    assert finding['relation'] != 'related_supplementary'
    assert finding['supportingSourceProofs'] == [source_proof]
    assert finding['lectureSupportProofs'] == [lecture_proof]


@pytest.mark.parametrize('verifier_accepts', [True, False])
def test_diagram_support_requires_actual_image_and_independent_box_judgment(monkeypatch, verifier_accepts):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Diagram page'], visual=True)
    manifest = supporting_manifest('historical_exam', ['Identify the search-tree rotation.'])
    inventory = one_requirement(manifest, 'Identify the search-tree rotation')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    proof = visual_proof(scope['allowedRefs'][0])
    image_stages = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        if any(part['type'] == 'image_url' for part in kwargs['messages'][1]['content']):
            image_stages.append(stage)
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual exam question'}]})
        if stage == 'verify':
            return response({'judgments': [{'targetId': 'r1',
                'verdict': 'support' if verifier_accepts else 'reject',
                'lectureProofs': [proof] if verifier_accepts else [],
                'reason': 'Exact diagram region checked'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'support',
            'lectureProofs': [proof], 'reason': 'Diagram nominates the rotation'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None
    )['alignments'][0]['requirements'][0]
    assert ('search' in image_stages) and ('verify' in image_stages)
    assert (finding['relation'] == 'lecture_supported') is verifier_accepts


def test_strict_planner_reads_page_asset_even_when_extracted_text_is_blank():
    from src.supporting.contracts import digest
    from src.utils.source_contracts import build_source_manifest, guide_digest

    scope = source_scope([''])
    unit = deepcopy(scope['manifests'][0]['units'][0])
    unit.update(blank=True, needsVisualRead=True, visualReadStatus='blank',
                visualAssets=[{'assetId': 'page-1', 'unitId': 'p0001', 'kind': 'page',
                               'mimeType': 'image/png'}])
    manifest = build_source_manifest('selected', 'a' * 64, 'pdf', [unit])
    guide = deepcopy(scope['documents'][0]['guide'])
    guide['sourceRevision'] = manifest['sourceRevision']
    guide['unitCoverage'] = deepcopy(manifest['coverage'])
    scope['manifests'] = [manifest]
    scope['documents'][0].update(sourceRevision=manifest['sourceRevision'],
                                 guideRevision=guide_digest(guide), guide=guide)
    scope['allowedRefs'] = [{'documentId': 'selected', 'sourceRevision': manifest['sourceRevision'],
                             'unitId': 'p0001'}]
    scope['scopeRevision'] = digest([{key: scope['documents'][0][key]
                                      for key in ('id', 'sourceRevision', 'guideRevision')}])
    ordinary = build_source_plan(scope, 'summary')
    strict = build_source_plan(scope, 'summary', include_blank_assets=True)
    assert not [image for batch in ordinary for entry in batch['evidence'] for image in entry['images']]
    assert [image['asset']['assetId'] for batch in strict for entry in batch['evidence']
            for image in entry['images']] == ['page-1']
    assert all(entry['disposition'] == 'candidate' for batch in strict for entry in batch['evidence'])


def test_malformed_response_spends_one_call_without_review_and_resume_keeps_spent_count(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Lists are taught.'])
    manifest = supporting_manifest('historical_exam', ['Prove an untaught theorem.'])
    inventory = one_requirement(manifest, 'Prove an untaught theorem')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    checkpoints = []
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
                        lambda *args, **kwargs: response({'judgments': []}, finish_reason='length'))
    interrupted = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert interrupted['alignments'][0]['requirements'][0]['relation'] == 'unverified'
    assert checkpoints[-1]['modelCalls'] == 1
    assert checkpoints[-1]['ledgers']['r1'] == []

    observed_before_calls = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        observed_before_calls.append(checkpoints[-1]['modelCalls'])
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual old question'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'no_support',
            'lectureProofs': [], 'reason': 'No selected original support'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    resumed = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append,
        resume=checkpoints[-1], model_call_budget=8)
    assert observed_before_calls[0] == 1
    assert resumed['alignments'][0]['requirements'][0]['relation'] == 'not_found'
    assert checkpoints[-1]['modelCalls'] > 1


def test_transport_failure_does_not_spend_returned_completion_budget(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Lists are taught.'])
    manifest = supporting_manifest('historical_exam', ['Prove an untaught theorem.'])
    checkpoints = []
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry',
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('transport down')))
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], one_requirement(manifest, 'Prove an untaught theorem'),
        scope=scope, checkpoint=checkpoints.append)
    assert report['alignmentCoverage']['complete'] is False
    assert checkpoints[-1]['modelCalls'] == 0


def test_resume_rejects_forged_accepted_ledger(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Lists are taught.'])
    manifest = supporting_manifest('historical_exam', ['Prove an untaught theorem.'])
    inventory = one_requirement(manifest, 'Prove an untaught theorem')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    checkpoints = []

    def provider(*args, **kwargs):
        return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
            'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
            'reason': 'Actual old question'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append,
        model_call_budget=1)
    forged = deepcopy(checkpoints[-1])
    lecture_text = scope['manifests'][0]['units'][0]['text']
    forged['ledgers']['r1'] = [{'ref': deepcopy(scope['allowedRefs'][0]),
                                'ranges': [{'textField': 'text', 'start': 0,
                                            'end': len(lecture_text)}], 'assetIds': []}]
    with pytest.raises(ValueError, match='(?i)checkpoint|ledger|scope|original'):
        SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
            manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None,
            resume=forged, model_call_budget=1)

    for damage in ('past_original_end', 'invented_asset'):
        matching = deepcopy(checkpoints[-1])
        entry = {'ref': deepcopy(scope['allowedRefs'][0]),
            'ranges': [{'textField': 'text', 'start': 0,
                        'end': len(lecture_text) + (1 if damage == 'past_original_end' else 0)}],
            'assetIds': ['invented-page'] if damage == 'invented_asset' else []}
        matching['ledgers']['r1'] = [deepcopy(entry)]
        matching['acceptedReads']['r1'] = [{'suppliedEvidence': [deepcopy(entry)],
                                            'excludedBlankRefs': []}]
        with pytest.raises(ValueError, match='(?i)checkpoint|ledger|scope|original|interval|asset'):
            SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
                manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None,
                resume=matching, model_call_budget=1)


def test_cross_language_support_is_found_by_complete_late_original_sweep(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['An unrelated introduction.', 'الشجرة رسم بياني متصل بلا دورات.'])
    manifest = supporting_manifest('historical_exam', ['Define an acyclic connected graph.'])
    inventory = one_requirement(manifest, 'Define an acyclic connected graph')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    late = text_proof(scope['allowedRefs'][1], scope['manifests'][0]['units'][1]['text'],
                      'الشجرة رسم بياني متصل بلا دورات.')
    seen = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        units = {entry['ref']['unitId'] for entry in packet['evidence']}
        seen.append((stage, units))
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': ['تعريف الشجرة'], 'explicitTeaching': False,
                'reason': 'Actual exam requirement'}]})
        if stage == 'verify':
            return response({'judgments': [{'targetId': 'r1', 'verdict': 'support',
                'lectureProofs': [late], 'reason': 'Arabic original teaches the same definition'}]})
        supported = 'p0002' in units
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'support' if supported else 'no_support',
            'lectureProofs': [late] if supported else [], 'reason': 'Checked original meaning'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None
    )['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'lecture_supported'
    assert any(stage == 'search' and 'p0002' in units for stage, units in seen)


@pytest.mark.parametrize('taught,expected', [(True, 'lecture_supported'), (False, 'not_found')])
def test_new_numeric_example_requires_the_complete_taught_operation(monkeypatch, taught, expected):
    from src.supporting.alignment import SupportingAligner

    lecture = 'Add two quantities by summing their values.' if taught else 'Multiply two quantities.'
    scope = source_scope([lecture])
    manifest = supporting_manifest('historical_exam', ['There are 13 apples and 8 apples. Find the total.'])
    inventory = one_requirement(manifest, 'Calculate 13 + 8')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    proof = text_proof(scope['allowedRefs'][0], lecture, lecture)

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': ['sum quantities'], 'explicitTeaching': False,
                'reason': 'Actual numerical question'}]})
        verdict = 'support' if taught else 'no_support'
        return response({'judgments': [{'targetId': 'r1', 'verdict': verdict,
            'lectureProofs': [proof] if taught else [],
            'reason': 'Every premise and operation checked' if taught else 'Required addition is untaught'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None
    )['alignments'][0]['requirements'][0]
    assert finding['relation'] == expected


def test_unsupported_extracted_paraphrase_and_full_semantic_uncertainty_stay_unverified(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['A tree is a connected acyclic graph.'])
    manifest = supporting_manifest('notes', ['Shopping reminder.'])
    inventory = one_requirement(manifest, 'Define a tree')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    stages = []

    def unsupported_source(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stages.append(packet['task']['stage'])
        return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'not_established',
            'sourceProofs': [], 'queries': [], 'explicitTeaching': False,
            'reason': 'The supporting original does not contain the extracted paraphrase'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', unsupported_source)
    rejected = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None)
    finding = rejected['alignments'][0]['requirements'][0]
    assert stages == ['source_check']
    assert finding['relation'] == 'unverified'
    assert rejected['alignmentCoverage']['complete'] is False

    def uncertain(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': True,
                'reason': 'The note wording itself is established'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'uncertain',
            'lectureProofs': [], 'reason': 'Meaning remains ambiguous after full review'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', uncertain)
    reviewed = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None)
    finding = reviewed['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'unverified'
    assert finding['reviewCoverage']['complete'] is True
    assert finding['reviewCoverage']['checkState'] == 'uncertain'
    assert reviewed['alignmentCoverage']['complete'] is True


def test_many_targets_are_split_by_the_complete_serialized_request_before_provider_call(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Trees are connected graphs.'])
    manifest = supporting_manifest('historical_exam', ['Explain trees.'])
    inventory = one_requirement(manifest, 'Explain trees')
    base = inventory['items'][0]['requirements'][0]
    inventory['items'][0]['requirements'] = [{**deepcopy(base), 'id': f'r{i}',
        'text': f'Explain tree case {i}: ' + ('x' * 1800)} for i in range(16)]
    source_proof = base['supportingSourceProofs'][0]
    lecture_proof = text_proof(scope['allowedRefs'][0], scope['manifests'][0]['units'][0]['text'],
                               'Trees are connected graphs.')
    calls = []

    def provider(*args, **kwargs):
        messages = kwargs['messages']
        packet = request_packet(messages)
        targets = packet['task']['targets']
        calls.append((packet['task']['stage'], [target['id'] for target in targets],
                      len(json.dumps(messages, ensure_ascii=False, separators=(',', ':'))),
                      sum(part['type'] == 'image_url' for part in messages[1]['content'])))
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': target['id'], 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual question'} for target in targets]})
        return response({'judgments': [{'targetId': target['id'], 'verdict': 'support',
            'lectureProofs': [lecture_proof], 'reason': 'Definition checked'} for target in targets]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None,
        model_call_budget=64)
    findings = report['alignments'][0]['requirements']
    assert len(findings) == 16 and all(row['relation'] == 'lecture_supported' for row in findings)
    source_calls = [call for call in calls if call[0] == 'source_check']
    assert len(source_calls) > 1
    assert {target_id for _, ids, _, _ in source_calls for target_id in ids} == {f'r{i}' for i in range(16)}
    assert all(len(ids) < 16 and size <= 24000 and images <= 8 for _, ids, size, images in calls)


def test_invalid_group_judgment_accepts_no_partial_review_ledger(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    scope = source_scope(['Trees are connected graphs.'])
    manifest = supporting_manifest('historical_exam', ['Explain trees.'])
    inventory = one_requirement(manifest, 'Explain trees')
    base = inventory['items'][0]['requirements'][0]
    inventory['items'][0]['requirements'] = [
        {**deepcopy(base), 'id': 'r1'},
        {**deepcopy(base), 'id': 'r2', 'text': 'Classify trees'},
    ]
    source_proof = base['supportingSourceProofs'][0]
    checkpoints = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        targets = packet['task']['targets']
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': target['id'],
                'sourceVerdict': 'established', 'sourceProofs': [source_proof],
                'queries': [], 'explicitTeaching': False, 'reason': 'Actual question'}
                for target in targets]})
        return response({'judgments': [
            {'targetId': 'r1', 'verdict': 'no_support', 'lectureProofs': [],
             'reason': 'Checked without support'},
            {'targetId': 'r2', 'verdict': 'invented', 'lectureProofs': [],
             'reason': 'Invalid response row'},
        ]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    report = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append)
    assert report['alignmentCoverage']['complete'] is False
    assert checkpoints[-1]['ledgers'] == {'r1': [], 'r2': []}
    assert checkpoints[-1]['acceptedReads'] == {'r1': [], 'r2': []}


def test_verified_explicit_exclusion_finishes_selected_sweep_before_outside_scope(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    first = 'Advanced sorting is explicitly outside this course. ' + ('a' * 5000)
    second = 'The remaining lecture discusses queues only. ' + ('b' * 5000)
    scope = source_scope([first, second])
    manifest = supporting_manifest('historical_exam', ['Explain advanced sorting.'])
    inventory = one_requirement(manifest, 'Explain advanced sorting')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    exclusion = text_proof(scope['allowedRefs'][0], first,
                           'Advanced sorting is explicitly outside this course.')
    searched = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        units = {entry['ref']['unitId'] for entry in packet['evidence']}
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual old question'}]})
        if stage == 'verify':
            return response({'judgments': [{'targetId': 'r1', 'verdict': 'explicit_exclusion',
                'lectureProofs': [exclusion], 'reason': 'The selected original excludes this topic'}]})
        searched.append(units)
        excluded = 'p0001' in units
        return response({'judgments': [{'targetId': 'r1',
            'verdict': 'explicit_exclusion' if excluded else 'no_support',
            'lectureProofs': [exclusion] if excluded else [],
            'reason': 'Exact exclusion' if excluded else 'No support'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None
    )['alignments'][0]['requirements'][0]
    assert any('p0002' in units for units in searched)
    assert finding['reviewCoverage']['complete'] is True
    assert finding['relation'] == 'outside_selected_scope'
    assert finding['lectureSupportProofs'] == [exclusion]
    assert 'excludedLectureEvidence' not in finding


def test_deduction_combines_premises_from_separate_original_batches(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    first = 'Premise A: every tree is acyclic. ' + ('a' * 5000)
    second = ('b' * 5000) + ' Premise B: every connected acyclic graph has n minus one edges.'
    scope = source_scope([first, second])
    manifest = supporting_manifest('historical_exam', ['Deduce the edge count of a tree.'])
    inventory = one_requirement(manifest, 'Deduce that a tree on n vertices has n minus one edges')
    inventory['items'][0]['requirements'][0]['category'] = 'deduction'
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    proofs = [text_proof(scope['allowedRefs'][0], first, 'Premise A: every tree is acyclic.'),
              text_proof(scope['allowedRefs'][1], second,
                         'Premise B: every connected acyclic graph has n minus one edges.')]
    joint_verification_units = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        units = {entry['ref']['unitId'] for entry in packet['evidence']}
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual deduction request'}]})
        if stage == 'verify':
            nominated = packet['task']['nominatedProofs']['r1']['lectureProofs']
            if len(nominated) == 2:
                joint_verification_units.append(units)
                return response({'judgments': [{'targetId': 'r1', 'verdict': 'support',
                    'lectureProofs': nominated, 'reason': 'Both premises jointly establish the deduction'}]})
            return response({'judgments': [{'targetId': 'r1', 'verdict': 'reject',
                'lectureProofs': [], 'reason': 'One premise alone is insufficient'}]})
        index = 0 if 'p0001' in units else 1
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'premise',
            'lectureProofs': [proofs[index]], 'reason': f'Premise {index + 1} is taught here'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None
    )['alignments'][0]['requirements'][0]
    assert joint_verification_units == [{'p0001', 'p0002'}]
    assert finding['relation'] == 'lecture_supported'
    assert {json.dumps(proof, sort_keys=True) for proof in finding['lectureSupportProofs']} == {
        json.dumps(proof, sort_keys=True) for proof in proofs}


def test_indivisible_combined_premises_fail_without_provider_verification(monkeypatch):
    from src.supporting.alignment import SupportingAligner
    from src.supporting.contracts import digest
    from src.utils.source_contracts import build_source_manifest, guide_digest

    scope = source_scope([f'Diagram premise {index}' for index in range(9)])
    units = deepcopy(scope['manifests'][0]['units'])
    for index, unit in enumerate(units, 1):
        unit.update(needsVisualRead=True, blank=False, visualReadStatus='readable',
                    visualText=f'Exact diagram premise {index}.',
                    visualAssets=[{'assetId': f'page-{index}', 'unitId': unit['unitId'],
                                   'kind': 'page', 'mimeType': 'image/png'}])
    lecture_manifest = build_source_manifest('selected', 'a' * 64, 'pdf', units)
    guide = deepcopy(scope['documents'][0]['guide'])
    guide['sourceRevision'] = lecture_manifest['sourceRevision']
    guide['unitCoverage'] = deepcopy(lecture_manifest['coverage'])
    scope['manifests'] = [lecture_manifest]
    scope['documents'][0].update(sourceRevision=lecture_manifest['sourceRevision'],
                                 guideRevision=guide_digest(guide), guide=guide)
    scope['allowedRefs'] = [{'documentId': 'selected',
        'sourceRevision': lecture_manifest['sourceRevision'], 'unitId': unit['unitId']}
        for unit in units]
    scope['scopeRevision'] = digest([{key: scope['documents'][0][key]
                                      for key in ('id', 'sourceRevision', 'guideRevision')}])
    manifest = supporting_manifest('historical_exam', ['Combine all nine diagram premises.'])
    inventory = one_requirement(manifest, 'Combine all nine diagram premises')
    inventory['items'][0]['requirements'][0]['category'] = 'deduction'
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    proofs = {ref['unitId']: visual_proof(ref, f'page-{index}')
              for index, ref in enumerate(scope['allowedRefs'], 1)}
    verify_calls = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stage = packet['task']['stage']
        if stage == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual deduction request'}]})
        if stage == 'verify':
            verify_calls.append(packet)
            raise AssertionError('Oversized combined proof must fail before provider submission')
        complete_units = [entry['ref']['unitId'] for entry in packet['evidence'] if entry['images']]
        return response({'judgments': [{'targetId': 'r1',
            'verdict': 'premise' if complete_units else 'no_support',
            'lectureProofs': [proofs[unit_id] for unit_id in complete_units],
            'reason': 'Exact long premises' if complete_units else 'Partial text is insufficient'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None,
        model_call_budget=64)['alignments'][0]['requirements'][0]
    assert verify_calls == []
    assert finding['relation'] == 'unverified'
    assert finding['reviewCoverage']['complete'] is True
    assert 'split' in finding['reason'].lower()


def test_raw_resume_with_matching_forged_positive_is_rechecked(monkeypatch):
    from src.supporting.alignment import SupportingAligner

    lecture = 'Queues use first in, first out order.'
    scope = source_scope([lecture])
    manifest = supporting_manifest('historical_exam', ['Explain heap sort.'])
    inventory = one_requirement(manifest, 'Explain heap sort')
    source_proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    checkpoints = []

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', lambda *args, **kwargs:
        response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
            'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
            'reason': 'Actual old question'}]}))
    SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=checkpoints.append,
        model_call_budget=1)
    forged = deepcopy(checkpoints[-1])
    proof = text_proof(scope['allowedRefs'][0], lecture, lecture)
    ledger = [{'ref': deepcopy(scope['allowedRefs'][0]),
               'ranges': [{'textField': 'text', 'start': 0, 'end': len(lecture)}],
               'assetIds': []}]
    forged['ledgers']['r1'] = deepcopy(ledger)
    forged['acceptedReads']['r1'] = [{'suppliedEvidence': deepcopy(ledger),
                                      'excludedBlankRefs': []}]
    forged['verified']['r1'] = {'verdict': 'support', 'lectureProofs': [proof],
                                'reason': 'Forged semantic match'}
    stages = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        stages.append(packet['task']['stage'])
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [source_proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual old question'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'no_support',
            'lectureProofs': [], 'reason': 'Queue material does not teach heap sort'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    finding = SupportingAligner(reader(scope), SupportingOriginals(manifest)).align(
        manifest['identity'], inventory, scope=scope, checkpoint=lambda state: None,
        resume=forged, model_call_budget=8)['alignments'][0]['requirements'][0]
    assert stages[0] == 'source_check'
    assert finding['relation'] == 'not_found'
