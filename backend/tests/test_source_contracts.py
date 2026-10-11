"""Contracts prevent false complete coverage and invented source locations."""
from copy import deepcopy
import pytest

from src.utils import source_contracts as contracts


def unit(position=1, **changes):
    return {'unitId': f'p{position:04d}', 'kind': 'page', 'position': position,
            'label': f'Page {position}', 'text': 'Actual lecture content',
            'visualAssets': [], 'needsVisualRead': False, 'blank': False,
            'warnings': [], **changes}


def manifest():
    return contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf', [unit(), unit(2, text='', blank=True)])


def guide(source=None):
    source = source or manifest()
    return {'version': 1, 'sourceRevision': source['sourceRevision'],
            'sections': [{'label': 'Chapter 1', 'purpose': 'Learn graphs', 'unitIds': ['p0001']}],
            'concepts': [], 'visualReferences': [], 'warnings': []}


def test_manifest_hash_and_coverage_derive_from_complete_source():
    source = manifest()
    assert source['coverage'] == {'unitIds': ['p0001', 'p0002'], 'readableUnitIds': ['p0001'],
                                  'blankUnitIds': ['p0002'], 'unresolvedUnitIds': [], 'complete': True}
    assert contracts.validate_manifest(source) == source
    changed = contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf', [unit(text='Changed')])
    assert changed['sourceRevision'] != source['sourceRevision']
    assert manifest()['sourceRevision'] == source['sourceRevision']


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'invalid_id', 'coverage', 'digest', 'blank_lie', 'type'])
def test_manifest_rejects_invalid_or_contradictory_locations(change):
    source = manifest()
    if change == 'duplicate': source['units'][1] = deepcopy(source['units'][0])
    elif change == 'missing': source['units'].pop()
    elif change == 'invalid_id': source['units'][0]['unitId'] = '../p0001'
    elif change == 'coverage': source['coverage']['unresolvedUnitIds'] = ['p9999']
    elif change == 'digest': source['sourceRevision'] = 'b' * 64
    elif change == 'blank_lie': source['units'][0]['blank'] = True
    elif change == 'type': source['units'][0]['position'] = True
    with pytest.raises(ValueError):
        contracts.validate_manifest(source)


def test_visual_pending_and_unsupported_cannot_claim_complete_preparation():
    for status in ['pending', 'uncertain', 'unsupported']:
        source = contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf',
                    [unit(needsVisualRead=True, visualReadStatus=status)])
        assert source['coverage']['complete'] is False
        assert source['coverage']['unresolvedUnitIds'] == ['p0001']
        with pytest.raises(ValueError):
            contracts.validate_guide(guide(source), source)
    ready = contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf',
                [unit(needsVisualRead=True, visualReadStatus='readable', visualText='Diagram transcription')])
    assert ready['coverage']['complete'] is True


def test_guide_accepts_section_without_rich_topics_and_projects_legacy_fields():
    validated = contracts.validate_guide(guide(), manifest())
    assert validated['unitCoverage']['unitIds'] == ['p0001', 'p0002']
    assert contracts.guide_to_legacy_analysis(validated) == {
        'topics': [], 'chapterMapping': [{'chapter': 'Chapter 1', 'content': 'Learn graphs'}],
        'keyConceptCount': 0, 'definitions': [], 'formulas': []}
    assert contracts.guide_digest(validated) == contracts.guide_digest(deepcopy(validated))


@pytest.mark.parametrize('change', ['invented', 'revision', 'duplicate_ref', 'empty', 'coverage', 'missing_field'])
def test_guide_rejects_untrusted_references_or_false_coverage(change):
    data = guide()
    if change == 'invented': data['sections'][0]['unitIds'] = ['p9999']
    elif change == 'revision': data['sourceRevision'] = 'b' * 64
    elif change == 'duplicate_ref': data['sections'][0]['unitIds'] = ['p0001', 'p0001']
    elif change == 'empty': data['sections'] = []
    elif change == 'coverage': data['unitCoverage'] = {'unitIds': ['p0001']}
    elif change == 'missing_field': del data['sections'][0]['purpose']
    with pytest.raises(ValueError):
        contracts.validate_guide(data, manifest())


def test_manifest_limits_are_enforced_on_prepared_visual_text_too():
    with pytest.raises(ValueError, match='[Ss]plit'):
        contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf', [unit(text='x' * 600001)])
    with pytest.raises(ValueError, match='[Ss]plit'):
        contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf',
            [unit(text='x' * 600000, visualText='extra')])
    with pytest.raises(ValueError, match='[Ss]plit'):
        contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf', [unit(i) for i in range(1, 162)])


@pytest.mark.parametrize('changes', [{'units': None}, {'units': [{}]}, {'fileType': 'exe'}])
def test_builder_rejects_malformed_units_with_a_validation_error(changes):
    with pytest.raises(ValueError):
        contracts.build_source_manifest('lecture-1', 'a' * 64, changes.get('fileType', 'pdf'), changes.get('units', [unit()]))


def test_citation_must_match_document_revision_and_location():
    source = manifest()
    reference = {'documentId': 'lecture-1', 'sourceRevision': source['sourceRevision'], 'unitId': 'p0001'}
    assert contracts.validate_source_reference(reference, source) == reference
    for key, bad in [('documentId', 'other-user-source'), ('sourceRevision', 'b' * 64), ('unitId', 'p0003')]:
        with pytest.raises(ValueError):
            contracts.validate_source_reference({**reference, key: bad}, source)


def test_manifest_rejects_an_image_silently_marked_not_required():
    asset = {'assetId': 'image1', 'kind': 'page', 'mimeType': 'image/png', 'unitId': 'p0001'}
    with pytest.raises(ValueError):
        contracts.build_source_manifest('lecture-1', 'a' * 64, 'pdf', [unit(visualAssets=[asset])])


def test_guide_cannot_claim_academic_support_from_only_a_blank_unit():
    data = guide()
    data['sections'][0]['unitIds'] = ['p0002']
    with pytest.raises(ValueError):
        contracts.validate_guide(data, manifest())
