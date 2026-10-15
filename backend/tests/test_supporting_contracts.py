"""Contracts reject unsupported certainty without changing original evidence."""
from copy import deepcopy
import pytest
from src.supporting.contracts import (
    validate_supporting_manifest, validate_alignment_report, aggregate_item_alignment,
    supporting_revision, validate_source_proof, source_coverage,
)
from tests.supporting_fixtures import supporting_manifest, supporting_ref, requirement_alignment, alignment_report


def test_one_supported_requirement_cannot_cover_another():
    rows = [requirement_alignment('lecture_supported', requirement_id='r1'),
            requirement_alignment('unverified', requirement_id='r2')]
    result = aggregate_item_alignment(rows, item_id='q1')
    assert result['status'] == 'partly_covered'
    assert result['unresolvedRequirementIds'] == ['r2']
    assert result['requirements'] == rows


@pytest.mark.parametrize('relations,status', [(['lecture_supported'], 'covered'), (['not_found'], 'not_covered'),
    (['unverified'], 'needs_review'), (['conflicting'], 'needs_review'), (['related_supplementary'], 'needs_review'),
    (['lecture_supported', 'conflicting'], 'partly_covered'), ([], 'nonacademic')])
def test_parent_status_is_bounded_by_each_requirement(relations, status):
    rows = [requirement_alignment(r, requirement_id=f'r{i}') for i, r in enumerate(relations)]
    assert aggregate_item_alignment(rows, item_id='q')['status'] == status


@pytest.mark.parametrize('kind', ['historical_exam', 'tutorial', 'audio', 'notes'])
def test_manifest_roundtrip_preserves_source_type_and_null_timing(kind):
    manifest = supporting_manifest(kind)
    checked = validate_supporting_manifest(manifest)
    assert checked == manifest and checked is not manifest
    assert checked['units'][0]['timing'] is None
    checked['units'][0]['text'] = 'mutation'
    assert manifest['units'][0]['text'] == 'Explain trees'


@pytest.mark.parametrize('change', ['text', 'timing'])
def test_transcript_revision_includes_extraction_and_real_timing(change):
    manifest = supporting_manifest('audio')
    units = deepcopy(manifest['units'])
    units[0][change] = 'Different transcript' if change == 'text' else {'startSeconds': 3, 'endSeconds': 9}
    assert supporting_revision(manifest['originalDigest'], units) != manifest['sourceRevision']


@pytest.mark.parametrize('damage', ['duplicate', 'revision', 'notes_time', 'coverage', 'nan_time', 'blank_content'])
def test_manifest_rejects_bad_identity_timing_and_forged_coverage(damage):
    value = supporting_manifest('notes' if damage == 'notes_time' else 'audio')
    if damage == 'duplicate': value['units'].append(deepcopy(value['units'][0]))
    if damage == 'revision': value['sourceRevision'] = 'b'*64
    if damage == 'notes_time': value['units'][0]['timing'] = {'startSeconds': 0, 'endSeconds': 1}
    if damage == 'coverage': value['coverage']['unresolvedUnitIds'] = ['missing']
    if damage == 'nan_time': value['units'][0]['timing'] = {'startSeconds': float('nan'), 'endSeconds': 1}
    if damage == 'blank_content': value['units'][0]['disposition'] = 'blank'
    with pytest.raises(ValueError): validate_supporting_manifest(value)


def test_audio_has_no_page_count_limit_but_pdf_does():
    audio = supporting_manifest('audio', ['teaching']*161)
    assert len(validate_supporting_manifest(audio)['units']) == 161
    with pytest.raises(ValueError): validate_supporting_manifest(supporting_manifest('historical_exam', ['q']*161))


def test_report_preserves_unknown_marks_and_independent_coverage():
    report = alignment_report(relation='unverified')
    checked = validate_alignment_report(report)
    assert checked['items'][0]['printedMarks'] is None
    assert checked['extractionCoverage']['complete'] is True
    assert checked['alignmentCoverage']['complete'] is True
    assert checked['alignments'][0]['status'] == 'needs_review'


@pytest.mark.parametrize('relation', ['not_found', 'outside_selected_scope'])
def test_negative_finding_cannot_claim_incomplete_review(relation):
    finding = requirement_alignment(relation, requirement_id='r1', complete=False)
    with pytest.raises(ValueError): aggregate_item_alignment([finding], item_id='q1')


@pytest.mark.parametrize('damage', ['duplicate', 'nan_marks', 'no_ref', 'wrong_revision', 'wrong_material',
    'fake_complete', 'wrong_aggregate', 'dangling_parent', 'dangling_context', 'historical_supplementary', 'no_lecture_proof'])
def test_report_rejects_untrustworthy_evidence(damage):
    report = alignment_report()
    if damage == 'duplicate': report['items'].append(deepcopy(report['items'][0]))
    if damage == 'nan_marks': report['items'][0]['printedMarks'] = float('inf')
    if damage == 'no_ref': report['items'][0]['supportingSourceRefs'] = []
    if damage == 'wrong_revision': report['items'][0]['supportingSourceRefs'][0]['sourceRevision'] = 'c'*64
    if damage == 'wrong_material': report['alignments'][0]['requirements'][0]['supportingSourceProofs'][0]['ref']['materialId'] = 'foreign'
    if damage == 'fake_complete': report['alignmentCoverage']['checkedItemIds'] = []
    if damage == 'wrong_aggregate': report['alignments'][0]['status'] = 'not_covered'
    if damage == 'dangling_parent': report['items'][0]['parentId'] = 'missing'
    if damage == 'dangling_context': report['items'][0]['sharedContextIds'] = ['missing']
    if damage == 'historical_supplementary': report = alignment_report(relation='related_supplementary')
    if damage == 'no_lecture_proof': report['alignments'][0]['requirements'][0]['lectureSupportProofs'] = []
    with pytest.raises(ValueError): validate_alignment_report(report)


def test_proof_checks_exact_unicode_span_against_original():
    manifest = supporting_manifest('notes', ['شجرة Café'])
    ref = supporting_ref(manifest)
    proof = {'type': 'text_span', 'ref': ref, 'field': 'text', 'start': 0, 'end': 4, 'quote': 'شجرة'}
    assert validate_source_proof(proof, ref=ref, unit=manifest['units'][0]) == proof
    with pytest.raises(ValueError): validate_source_proof({**proof, 'quote': 'tree'}, ref=ref, unit=manifest['units'][0])
    with pytest.raises(ValueError): validate_source_proof({**proof, 'ref': {**ref, 'unitId': 'other'}}, ref=ref, unit=manifest['units'][0])


@pytest.mark.parametrize('box', [[0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, float('nan'), 1], [1, 1, 0, 0]])
def test_visual_proofs_reject_invalid_regions(box):
    manifest = supporting_manifest()
    unit, ref = manifest['units'][0], supporting_ref(manifest)
    unit['visualAssets'] = [{'assetId': 'image', 'kind': 'page', 'mimeType': 'image/png'}]
    proof = {'type': 'visual_region', 'ref': ref, 'assetId': 'image', 'box': box}
    with pytest.raises(ValueError): validate_source_proof(proof, ref=ref, unit=unit)


def test_visual_proof_requires_actual_asset_not_fabricated_quote():
    manifest = supporting_manifest()
    unit, ref = manifest['units'][0], supporting_ref(manifest)
    proof = {'type': 'visual_region', 'ref': ref, 'assetId': 'image', 'box': [0, 0, 1, 1]}
    with pytest.raises(ValueError): validate_source_proof(proof, ref=ref, unit=unit)
    unit['visualAssets'] = [{'assetId': 'image', 'kind': 'page', 'mimeType': 'image/png'}]
    assert validate_source_proof(proof, ref=ref, unit=unit) == proof


def test_historical_projection_v3_retains_paper_validation():
    from src.utils.ai_contracts import validate_analysis
    from tests.test_historical_papers import analysis
    data = analysis()
    data.update(analysisVersion=3, paperCount=2, collectionQuestionCount=4,
                papers=[dict(analysis(), paperId='p1', startPage=1, endPage=2),
                        dict(analysis(), paperId='p2', startPage=3, endPage=4)])
    assert validate_analysis('historical', data)['analysisVersion'] == 3
    data['papers'][1]['paperId'] = 'p1'
    with pytest.raises(ValueError): validate_analysis('historical', data)


def test_academic_item_cannot_become_nonacademic_by_omitting_requirements():
    report = alignment_report()
    report['items'][0]['requirements'] = []
    report['alignments'][0] = aggregate_item_alignment([], item_id='q1')
    with pytest.raises(ValueError): validate_alignment_report(report)


def test_parent_alignment_includes_unresolved_child_requirements():
    report = alignment_report()
    child = deepcopy(report['items'][0])
    child.update(id='q1a', parentId='q1', itemType='subpart')
    child['requirements'][0]['id'] = 'r2'
    report['items'].append(child)
    finding = requirement_alignment('unverified', requirement_id='r2')
    report['alignments'].append(aggregate_item_alignment([finding], item_id='q1a'))
    report['alignmentCoverage']['itemIds'].append('q1a')
    report['alignmentCoverage']['checkedItemIds'].append('q1a')
    with pytest.raises(ValueError): validate_alignment_report(report)
    report['alignments'][0] = aggregate_item_alignment([report['alignments'][0]['requirements'][0], finding], item_id='q1')
    assert validate_alignment_report(report)['alignments'][0]['status'] == 'partly_covered'


def test_outside_scope_requires_positive_evidence_not_just_failed_search():
    report = alignment_report(relation='outside_selected_scope')
    with pytest.raises(ValueError): validate_alignment_report(report)


def test_readable_unit_requires_actual_content_or_visual_asset():
    manifest = supporting_manifest(texts=[''])
    manifest['units'][0]['disposition'] = 'readable'
    manifest['coverage'] = source_coverage(manifest['units'])
    manifest['sourceRevision'] = supporting_revision(manifest['originalDigest'], manifest['units'])
    with pytest.raises(ValueError): validate_supporting_manifest(manifest)
