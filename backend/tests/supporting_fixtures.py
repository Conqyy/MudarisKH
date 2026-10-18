"""Synthetic, service-free supporting evidence fixtures."""
from copy import deepcopy
from src.supporting.contracts import supporting_revision, source_coverage, aggregate_item_alignment
from tests.test_source_context import source_scope


def supporting_manifest(kind='historical_exam', texts=None):
    texts = ['Explain trees'] if texts is None else texts
    units = [{'unitId': f'u{i}', 'position': i, 'kind': 'transcript' if kind == 'audio' else 'notes' if kind == 'notes' else 'page',
              'text': text, 'visualText': '', 'visualAssets': [],
              'disposition': 'readable' if text else 'blank', 'timing': None} for i, text in enumerate(texts, 1)]
    return {'version': 1, 'identity': {'userId': 'owner', 'courseId': 'course', 'kind': kind, 'materialId': 'material'},
            'originalDigest': 'a'*64, 'extractorVersion': 1,
            'sourceRevision': supporting_revision('a'*64, units),
            'fileType': 'notes' if kind == 'notes' else 'audio' if kind == 'audio' else 'pdf',
            'units': units, 'coverage': source_coverage(units)}


def supporting_ref(manifest, index=0):
    return {k: manifest['identity'][k] for k in ('kind', 'materialId')} | {
        'sourceRevision': manifest['sourceRevision'], 'unitId': manifest['units'][index]['unitId']}


def requirement_alignment(relation, *, requirement_id, complete=True):
    scope = source_scope(['Trees are connected graphs.'])
    lecture_ref = scope['allowedRefs'][0]
    lecture_text = scope['manifests'][0]['units'][0]['text']
    source_ref = supporting_ref(supporting_manifest())
    return {'requirementId': requirement_id, 'relation': relation, 'reason': 'Checked original evidence',
            'lectureAnchorRefs': [lecture_ref] if relation in ('lecture_supported', 'related_supplementary', 'conflicting') else [],
            'lectureSupportProofs': [{'type': 'text_span', 'ref': lecture_ref, 'field': 'text', 'start': 0,
                                      'end': 5, 'quote': 'Trees'}] if relation in (
                                          'lecture_supported', 'related_supplementary', 'conflicting') else [],
            'supportingSourceProofs': [{'type': 'text_span', 'ref': source_ref, 'field': 'text', 'start': 0, 'end': 7, 'quote': 'Explain'}],
            'reviewCoverage': {'scopeRevision': scope['scopeRevision'], 'allowedRefs': deepcopy(scope['allowedRefs']),
                               'reviewedRefs': deepcopy(scope['allowedRefs']) if complete else [],
                               'unresolvedRefs': [] if complete else deepcopy(scope['allowedRefs']), 'complete': complete,
                               'suppliedEvidence': [{'ref': deepcopy(lecture_ref), 'ranges': [
                                   {'textField': 'text', 'start': 0, 'end': len(lecture_text)}], 'assetIds': []}] if complete else [],
                               'excludedBlankRefs': [],
                               'checkState': 'uncertain' if relation == 'unverified' and complete else
                                   'pending' if relation == 'unverified' else 'complete'}}


def alignment_report(kind='historical_exam', relation='lecture_supported'):
    manifest = supporting_manifest(kind)
    ref = supporting_ref(manifest)
    requirement = {'id': 'r1', 'text': 'Explain a tree', 'category': 'concept', 'supportingSourceRefs': [ref]}
    finding = requirement_alignment(relation, requirement_id='r1')
    finding['supportingSourceProofs'][0]['ref'] = ref
    item = {'id': 'q1', 'parentId': None, 'paperId': 'paper1' if kind == 'historical_exam' else None,
            'printedLabel': '1', 'itemType': 'question', 'text': 'Explain trees', 'sharedContextIds': [],
            'choices': [], 'givenData': [], 'printedMarks': None, 'requirements': [requirement], 'supportingSourceRefs': [ref]}
    item['supportingSourceProofs'] = deepcopy(finding['supportingSourceProofs'])
    return {'version': 1, 'alignmentVersion': 1, 'sourceRevision': manifest['sourceRevision'],
            'scopeSnapshot': source_scope(['Trees are connected graphs.']),
            'extractionCoverage': {'unitIds': ['u1'], 'accountedUnitIds': ['u1'], 'unresolvedUnitIds': [], 'complete': True},
            'alignmentCoverage': {'itemIds': ['q1'], 'checkedItemIds': ['q1'], 'unresolvedItemIds': [],
                                  'topicIds': [], 'checkedTopicIds': [], 'unresolvedTopicIds': [], 'complete': True},
            'items': [item], 'alignments': [aggregate_item_alignment([finding], item_id='q1')],
            'sharedContexts': [], 'topics': [],
            'papers': [{'paperId': 'paper1', 'title': 'Final', 'unitIds': ['u1'], 'questionIds': ['q1'],
                        'totalQuestions': 1, 'totalMarks': None}] if kind == 'historical_exam' else []}
