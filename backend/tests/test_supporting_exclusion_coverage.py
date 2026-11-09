"""Whole-window exclusion retains exact original evidence instead of an empty label."""
from copy import deepcopy

import pytest

from src.supporting.contracts import source_coverage, supporting_revision
from src.supporting.extraction_inventory import ExclusionCoverageError, validate_response
from src.supporting.extraction_source import source_plan
from tests.supporting_fixtures import supporting_manifest


def fixture(text='Course title\nAdministrative information', *, visual=False):
    manifest = supporting_manifest('tutorial', [text])
    if visual:
        manifest['units'][0]['visualAssets'] = [{'assetId': 'page-image', 'kind': 'page',
                                               'mimeType': 'image/png'}]
        manifest['units'][0]['disposition'] = 'readable'
        manifest['sourceRevision'] = supporting_revision(manifest['originalDigest'], manifest['units'])
        manifest['coverage'] = source_coverage(manifest['units'])
    return manifest, source_plan(manifest, 0)[0]


def response(*, role='cover', disposition='nonacademic', records=(), contexts=()):
    return {'pageRole': role, 'disposition': disposition, 'paper': None,
            'items': list(records), 'sharedContexts': list(contexts), 'topics': []}


def text_proof(source, start=None, end=None):
    span = source['ranges'][0]
    start = span['start'] if start is None else start
    end = span['end'] if end is None else end
    return {'type': 'text_span', 'ref': source['ref'], 'field': span['field'],
            'start': start, 'end': end,
            'quote': span['text'][start - span['start']:end - span['start']]}


def image_proof(source, box=None):
    return {'type': 'visual_region', 'ref': source['ref'], 'assetId': source['assetIds'][0],
            'box': [0, 0, 1, 1] if box is None else box}


def nonacademic(proofs, *, text='Retained original administrative content'):
    return {'origin': proofs[0], 'itemType': 'nonacademic', 'text': text,
            'parent': None, 'printedLabel': None, 'printedMarks': None, 'questionType': None,
            'choices': [], 'givenData': [], 'contextOrigins': [], 'requirements': [], 'proofs': proofs}


@pytest.mark.parametrize('role,disposition', [
    ('cover', 'nonacademic'), ('cover', 'readable'), ('answer_key', 'readable'),
    ('other', 'nonacademic'), ('blank', 'blank')])
def test_visible_original_cannot_disappear_under_an_empty_exclusion_label(role, disposition):
    manifest, source = fixture('Question: What does fork() return?')
    with pytest.raises(ExclusionCoverageError, match='exclusion|blank'):
        validate_response(response(role=role, disposition=disposition), manifest, source, None, [])


@pytest.mark.parametrize('role,disposition', [
    ('cover', 'nonacademic'), ('cover', 'readable'), ('answer_key', 'readable'),
    ('other', 'nonacademic')])
def test_legitimate_exclusion_retains_all_text_without_academic_requirements(role, disposition):
    manifest, source = fixture()
    value = response(role=role, disposition=disposition,
                     records=[nonacademic([text_proof(source)])])
    accepted = validate_response(value, manifest, source, None, [])
    assert accepted['items'][0]['requirements'] == []
    assert accepted['items'][0]['proofs'] == [text_proof(source)]


def test_heading_only_proof_cannot_exclude_unaccounted_content():
    manifest, source = fixture('Course title\nOriginal content that also needs a decision')
    value = response(records=[nonacademic([text_proof(source, end=12)])])
    with pytest.raises(ExclusionCoverageError, match='exclusion'):
        validate_response(value, manifest, source, None, [])


def test_exact_fragments_can_account_for_text_with_blank_spacing_between_them():
    manifest, source = fixture('Title\n\nDetails\t\n')
    value = response(records=[nonacademic([text_proof(source, 0, 5), text_proof(source, 7, 14)])])
    assert validate_response(value, manifest, source, None, []) == value


def test_retained_context_can_account_for_a_legitimate_cover():
    manifest, source = fixture()
    value = response(contexts=[{'origin': text_proof(source), 'text': source['ranges'][0]['text'],
                                'proofs': [text_proof(source)]}])
    assert validate_response(value, manifest, source, None, []) == value


@pytest.mark.parametrize('damage', ['bare_empty', 'missing_image', 'partial_image'])
def test_exclusion_accounts_for_current_original_image_as_well_as_text(damage):
    manifest, source = fixture(visual=True)
    proofs = [text_proof(source)]
    if damage == 'partial_image':
        proofs.append(image_proof(source, [0, 0, 1, .25]))
    records = [] if damage == 'bare_empty' else [nonacademic(proofs)]
    with pytest.raises(ExclusionCoverageError, match='exclusion'):
        validate_response(response(records=records), manifest, source, None, [])


@pytest.mark.parametrize('role,disposition', [('cover', 'nonacademic'), ('blank', 'blank')])
def test_scanned_cover_or_blank_image_can_be_explicitly_retained(role, disposition):
    manifest, source = fixture('', visual=True)
    value = response(role=role, disposition=disposition,
                     records=[nonacademic([image_proof(source)])])
    assert validate_response(value, manifest, source, None, []) == value


def test_truly_empty_source_may_have_an_empty_blank_inventory():
    manifest, source = fixture('')
    value = response(role='blank', disposition='blank')
    assert validate_response(value, manifest, source, None, []) == value


def test_previous_window_evidence_cannot_fill_a_current_window_exclusion_gap():
    manifest, source = fixture('Prior header\nCurrent information')
    previous = deepcopy(source)
    previous['ranges'] = [{'field': 'text', 'start': 0, 'end': 12, 'text': 'Prior header'}]
    source['ranges'] = [{'field': 'text', 'start': 13, 'end': 32, 'text': 'Current information'}]
    value = response(records=[nonacademic([text_proof(previous), text_proof(source, 13, 20)])])
    with pytest.raises(ExclusionCoverageError, match='exclusion'):
        validate_response(value, manifest, source, previous, [])


@pytest.mark.parametrize('discarded_passes', [('extract',), ('extract', 'reconcile')])
def test_legacy_empty_exclusion_rewinds_both_passes_without_repeating_valid_prefix(discarded_passes):
    from src.utils.document_sources import render_source_unit
    from tests.test_supporting_extraction import (Provider, extractor, item, page, pdf,
                                                   proof, reader, run)

    raw = pdf(['Question 1: Explain trees', 'Question 2: Explain graphs'])
    def rows(manifest):
        return {f'p{number:04d}': page([item(proof(manifest, number), f'Question {number}')])
                for number in (1, 2)}
    _, _, manifest, states = run(raw, kind='tutorial', rows=rows)
    legacy = deepcopy(states[-1])
    spent = legacy['modelCalls']
    prefix = {phase: deepcopy(legacy['responses'][phase]['0']) for phase in ('extract', 'reconcile')}
    for phase in discarded_passes:
        legacy['responses'][phase]['1'] = response()
    provider, recovered = Provider(rows(manifest)), []
    result = extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
        render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']),
        checkpoint=recovered.append, resume=legacy)
    assert result['extractionCoverage']['complete'] is True
    assert len(result['items']) == 2
    assert len(provider.calls) == 2
    assert recovered[-1]['modelCalls'] == spent + 2
    assert {phase: recovered[-1]['responses'][phase]['0'] for phase in prefix} == prefix
    assert all(recovered[-1]['responses'][phase]['1']['items'] for phase in prefix)


def test_exclusion_recovery_does_not_grandfather_a_forged_original_proof():
    from src.utils.document_sources import render_source_unit
    from tests.test_supporting_extraction import (Provider, extractor, item, page, pdf,
                                                   proof, reader, run)

    raw = pdf(['Question 1: Explain trees', 'Question 2: Explain graphs'])
    _, _, manifest, states = run(raw, kind='tutorial', rows=lambda source: {
        f'p{number:04d}': page([item(proof(source, number))]) for number in (1, 2)})
    legacy = deepcopy(states[-1])
    legacy['responses']['extract']['1'] = response()
    legacy['responses']['extract']['0']['items'][0]['proofs'][0]['quote'] = 'Forged text'
    provider = Provider({})
    with pytest.raises(ValueError):
        extractor(provider).extract(manifest, course_title='Algorithms', lecture_reader=reader(),
            render=lambda unit: render_source_unit(raw, 'pdf', unit['unitId']),
            checkpoint=lambda state: None, resume=legacy)
    assert provider.calls == []
