"""Blank lecture units count only through deterministic original validation."""
from copy import deepcopy

import pytest

from src.supporting.alignment import SupportingAligner
from src.supporting.contracts import digest
from src.utils.source_context import build_source_plan
from src.utils.source_contracts import build_source_manifest, guide_digest
from tests.supporting_fixtures import supporting_manifest
from tests.test_source_context import source_scope
from tests.test_supporting_alignment import (
    SupportingOriginals, one_requirement, reader, request_packet, response,
)


def _fixture(scope, monkeypatch):
    manifest = supporting_manifest('historical_exam', ['Prove an untaught theorem.'])
    inventory = one_requirement(manifest, 'Prove an untaught theorem')
    proof = inventory['items'][0]['requirements'][0]['supportingSourceProofs'][0]
    calls = []

    def provider(*args, **kwargs):
        packet = request_packet(kwargs['messages'])
        calls.append(deepcopy(packet))
        if packet['task']['stage'] == 'source_check':
            return response({'judgments': [{'targetId': 'r1', 'sourceVerdict': 'established',
                'sourceProofs': [proof], 'queries': [], 'explicitTeaching': False,
                'reason': 'Actual supporting question'}]})
        return response({'judgments': [{'targetId': 'r1', 'verdict': 'no_support',
            'lectureProofs': [], 'reason': 'Different academic material'}]})

    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    return manifest, inventory, SupportingOriginals(manifest), calls


def test_blank_only_final_batch_completes_sweep_without_provider_call(monkeypatch):
    scope = source_scope(['The lecture covers lists.'] * 13 + [''])
    batches = build_source_plan(scope, 'summary', text_budget=8000, image_budget=4,
                                include_blank_assets=True)
    assert all(row['disposition'] == 'excluded_blank' for row in batches[-1]['evidence'])
    manifest, inventory, library, calls = _fixture(scope, monkeypatch)
    saved = []
    report = SupportingAligner(reader(scope), library).align(manifest['identity'], inventory,
        scope=scope, checkpoint=saved.append)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'not_found'
    assert finding['reviewCoverage']['complete'] is True
    assert finding['reviewCoverage']['excludedBlankRefs'] == [scope['allowedRefs'][-1]]
    assert all(any(row['disposition'] != 'excluded_blank' for row in call['evidence'])
               for call in calls)
    assert saved[-1]['modelCalls'] == len(calls)
    # An owned checkpoint with deterministic blank coverage still restores and
    # validates exactly; no fabricated provider response is needed for the blank.
    library.load_checkpoint = lambda identity, revision: deepcopy(saved[-1])
    resumed = SupportingAligner(reader(scope), library).align(manifest['identity'], inventory,
        scope=scope, checkpoint=lambda _: None, resume_revision='a' * 64)
    assert resumed['alignments'][0]['requirements'][0]['relation'] == 'not_found'


@pytest.mark.parametrize('corruption', ['hidden_text', 'unexpected_range', 'foreign_ref'])
def test_blank_flag_cannot_hide_original_content_or_invent_coverage(monkeypatch, corruption):
    scope = source_scope(['The lecture covers lists.'])
    manifest, inventory, library, calls = _fixture(scope, monkeypatch)
    original_plan = build_source_plan

    def forged_plan(*args, **kwargs):
        result = original_plan(*args, **kwargs)
        if args[1] == 'summary':
            result = deepcopy(result)
            for batch in result:
                for entry in batch['evidence']:
                    entry['disposition'] = 'excluded_blank'
                    if corruption != 'unexpected_range':
                        entry['ranges'] = []
                    if corruption == 'foreign_ref':
                        entry['ref']['unitId'] = 'foreign'
        return result

    monkeypatch.setattr('src.supporting.alignment.build_source_plan', forged_plan)
    saved = []
    report = SupportingAligner(reader(scope), library).align(manifest['identity'], inventory,
        scope=scope, checkpoint=saved.append)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'unverified'
    assert finding['reviewCoverage']['complete'] is False
    assert finding['reviewCoverage']['excludedBlankRefs'] == []
    assert not any(call['task']['stage'] == 'search' for call in calls)
    assert 'blank' in (saved[-1]['error'] or '').lower()


def test_excluded_blank_original_does_not_invalidate_completed_selected_absence(monkeypatch):
    selected = source_scope(['The lecture covers lists.'])
    excluded_manifest = build_source_manifest('excluded', 'c' * 64, 'pdf', [{
        'unitId': 'p0001', 'kind': 'page', 'position': 1, 'label': 'Page 1',
        'text': '', 'blank': True, 'needsVisualRead': False, 'warnings': [], 'visualAssets': []}])
    excluded_guide = {'version': 1, 'sourceRevision': excluded_manifest['sourceRevision'],
        'sections': [], 'concepts': [], 'visualReferences': [], 'warnings': [],
        'unitCoverage': deepcopy(excluded_manifest['coverage'])}
    excluded_document = {'id': 'excluded', 'title': 'Removed lecture',
        'sourceRevision': excluded_manifest['sourceRevision'],
        'guideRevision': guide_digest(excluded_guide), 'guide': excluded_guide}
    whole = deepcopy(selected)
    whole['documents'].append(excluded_document)
    whole['manifests'].append(excluded_manifest)
    whole['allowedRefs'].append({'documentId': 'excluded',
        'sourceRevision': excluded_manifest['sourceRevision'], 'unitId': 'p0001'})
    whole['scopeRevision'] = digest([{key: document[key] for key in
        ('id', 'sourceRevision', 'guideRevision')} for document in whole['documents']])
    monkeypatch.setattr('src.supporting.alignment.resolve_source_scope', lambda *args: deepcopy(whole))
    manifest, inventory, library, calls = _fixture(selected, monkeypatch)
    saved = []
    report = SupportingAligner(reader(selected), library).align(manifest['identity'], inventory,
        scope=selected, checkpoint=saved.append)
    finding = report['alignments'][0]['requirements'][0]
    assert finding['relation'] == 'not_found'
    assert report['alignmentCoverage']['complete'] is True
    assert finding['reviewCoverage']['allowedRefs'] == selected['allowedRefs']
    assert finding['reviewCoverage']['excludedBlankRefs'] == []
    assert 'excludedLectureEvidence' not in finding
    assert saved[-1]['failedReads'] == {}
    assert saved[-1]['error'] is None
    assert saved[-1]['modelCalls'] == len(calls)
    assert all(entry['ref']['documentId'] != 'excluded'
               for call in calls for entry in call['evidence'])
