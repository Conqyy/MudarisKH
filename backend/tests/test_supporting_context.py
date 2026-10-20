"""Checked supporting packets preserve original evidence and selection intent."""
from copy import deepcopy

import pytest

from src.supporting.context import SupportingContextCompiler, historical_projection
from src.supporting.contracts import aggregate_item_alignment, digest
from src.supporting.alignment_evidence import context_components
from src.utils.exam_blueprint import build_exam_blueprint
from tests.supporting_fixtures import alignment_report, supporting_manifest


class CourseRows:
    def __init__(self, rows):
        self.rows = rows

    def get_course_historical_exams(self, course_id, user_id=None):
        return [deepcopy(row) for row in self.rows if row['kind'] == 'historical_exam']

    def get_course_tutorials(self, course_id, user_id=None):
        return [deepcopy(row) for row in self.rows if row['kind'] == 'tutorial']

    def get_course_audio_recordings(self, course_id, user_id=None):
        return [deepcopy(row) for row in self.rows if row['kind'] in ('audio', 'notes')]


class CheckedRepository:
    def __init__(self, rows, reports=None):
        self.database = CourseRows(rows)
        self.rows = rows
        self.reports = reports or {}
        self.cache = {}
        self.scoped_revisions = {}

    def get_owned(self, identity):
        for row in self.rows:
            if (row['id'] == identity['materialId'] and row['kind'] == identity['kind']
                    and row['userId'] == identity['userId'] and row['courseId'] == identity['courseId']):
                return deepcopy(row)
        raise ValueError('Supporting material is unavailable')

    def assert_snapshot(self, snapshot, *, scope_revision=None):
        for entry in snapshot['materials']:
            row = self.get_owned(entry['identity'])
            for field in ('sourceRevision', 'reportRevision', 'analysisId'):
                assert row['supportingAnalysis'][field] == entry[field]

    def _key(self, identity, expected, **fields):
        return digest({'identity': identity, 'expected': expected, **fields})

    def get_scoped_cache(self, identity, expected, **fields):
        return self.cache.get(self._key(identity, expected, **fields))

    def save_scoped_cache(self, identity, expected, *, scoped_report_revision, **fields):
        self.cache[self._key(identity, expected, **fields)] = scoped_report_revision
        self.scoped_revisions[scoped_report_revision] = fields['scope_revision']

    def get_version(self, identity, kind, revision):
        assert kind == 'report'
        baseline = self.reports[identity['materialId']]
        scope_revision = baseline['scopeSnapshot']['scopeRevision']
        if revision in self.scoped_revisions:
            scope_revision = self.scoped_revisions[revision]
        row = self.get_owned(identity)
        return {'versionKind': 'report', 'revision': revision, 'state': 'adopted',
                'coverageComplete': True, 'sourceRevision': row['supportingAnalysis']['sourceRevision'],
                'scopeRevision': scope_revision, 'foundationRevision': row['processingJob']['foundationRevision']}


class CheckedLibrary:
    def __init__(self, reports):
        self.reports = reports
        self.scoped_reports = {}

    def load_source(self, identity, source_revision=None):
        manifest = supporting_manifest(identity['kind'])
        manifest['identity'] = identity
        manifest['sourceRevision'] = source_revision
        return manifest

    def load_report(self, identity, report_revision=None):
        return deepcopy(self.scoped_reports.get(report_revision, self.reports[identity['materialId']]))

    def save_scoped_report(self, identity, expected, report):
        revision = digest({'foundationRevision': 'f'*64, 'report': report})
        self.scoped_reports[revision] = deepcopy(report)
        return {'versionKind': 'report', 'revision': revision, 'state': 'adopted',
                'coverageComplete': True, 'sourceRevision': expected['sourceRevision'],
                'scopeRevision': report['scopeSnapshot']['scopeRevision'], 'foundationRevision': 'f'*64}


def _setup(kind='historical_exam', *, status='completed'):
    report = alignment_report(kind)
    material_id = {'historical_exam': 'past', 'tutorial': 'tutorial',
                   'notes': 'note', 'audio': 'audio'}[kind]
    report['items'][0]['text'] = 'Explain trees in the original question.'
    report['items'][0]['supportingSourceRefs'][0]['materialId'] = material_id
    report['items'][0]['supportingSourceProofs'][0]['ref']['materialId'] = material_id
    report['items'][0]['requirements'][0]['supportingSourceRefs'][0]['materialId'] = material_id
    report['alignments'][0]['requirements'][0]['supportingSourceProofs'][0]['ref']['materialId'] = material_id
    report['scopeSnapshot']['foundationRevision'] = 'f'*64
    report['scopeSnapshot']['scopeRevision'] = digest([
        {key: document[key] for key in ('id', 'sourceRevision', 'guideRevision')}
        for document in report['scopeSnapshot']['documents']])
    for alignment in report['alignments']:
        for finding in alignment['requirements']:
            finding['reviewCoverage']['scopeRevision'] = report['scopeSnapshot']['scopeRevision']
        for dependency in alignment.get('contextDependencies', []):
            dependency['reviewCoverage']['scopeRevision'] = report['scopeSnapshot']['scopeRevision']
    identity = {'userId': 'owner', 'courseId': 'course', 'kind': kind, 'materialId': material_id}
    row = {'id': material_id, 'kind': kind, 'userId': 'owner', 'courseId': 'course',
           'sourceType': 'notes' if kind == 'notes' else 'file', 'status': status,
           'originalDigest': 'a'*64,
           'processingJob': {'id': 'job', 'stage': status, 'sourceDigest': 'a'*64,
                             'foundationRevision': 'f'*64},
           'supportingAnalysis': {'version': 1, 'state': status, 'sourceRevision': report['sourceRevision'],
                                  'reportRevision': 'b'*64, 'analysisId': 'job'}}
    return identity, row, report


def _compiler(*entries):
    rows = [entry[1] for entry in entries]
    reports = {entry[0]['materialId']: entry[2] for entry in entries}
    return SupportingContextCompiler(CheckedRepository(rows, reports), CheckedLibrary(reports), None)


class RescopeAligner:
    def __init__(self):
        self.calls = []

    def rescope(self, identity, baseline, *, scope, checkpoint):
        self.calls.append(identity['kind'])
        report = deepcopy(baseline)
        report['scopeSnapshot'] = deepcopy(scope)
        return report


def _scope(report):
    return deepcopy(report['scopeSnapshot'])


def _second_scope(report):
    scope = _scope(report)
    document = deepcopy(scope['documents'][0])
    document['id'] = 'selected2'
    scope['documents'].append(document)
    scope['allowedRefs'].extend({**ref, 'documentId': 'selected2'} for ref in deepcopy(scope['allowedRefs']))
    scope['scopeRevision'] = digest([
        {key: document[key] for key in ('id', 'sourceRevision', 'guideRevision')}
        for document in scope['documents']])
    return scope


def _selected(**kwargs):
    return {'historical_ids': [], 'audio_ids': [], 'tutorial_ids': []} | kwargs


def test_explicit_empty_selection_returns_no_supporting_evidence():
    entry = _setup()
    packet = _compiler(entry).compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
                                      selected=_selected(), purpose='exam')
    assert packet['academicItems'] == []
    assert packet['qualifiedItems'] == []
    assert packet['structuralPapers'] == []
    assert packet['snapshot']['materials'] == []


def test_original_question_reaches_all_four_purposes_with_snapshot():
    entry = _setup()
    compiler = _compiler(entry)
    for purpose in ('summary', 'exam', 'flashcards', 'tutor'):
        packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
                                  selected=_selected(historical_ids=['past']), purpose=purpose)
        assert 'Explain trees in the original question.' in [item['text'] for item in packet['academicItems']]
        assert packet['qualifiedItems'] == []
        assert packet['snapshot']['materials'][0] == {
            'identity': entry[0], 'sourceRevision': entry[2]['sourceRevision'],
            'reportRevision': 'b'*64, 'analysisId': 'job', 'scopedReportRevision': 'b'*64}
        assert 'manifests' not in packet['scopeSnapshot']
        assert all('guide' not in document for document in packet['scopeSnapshot']['documents'])


def test_none_selects_unready_owned_row_and_fails_while_empty_list_deselects_it():
    entry = _setup(status='queued')
    compiler = _compiler(entry)
    with pytest.raises(ValueError, match='(?i)unavailable|ready|upgrade'):
        compiler.compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
                         selected=_selected(historical_ids=None), purpose='summary')
    packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
                              selected=_selected(), purpose='summary')
    assert packet['snapshot']['materials'] == []


def test_foreign_or_missing_explicit_id_fails_and_duplicate_owned_id_counts_once():
    entry = _setup()
    compiler = _compiler(entry)
    for missing in ('foreign', 'missing'):
        with pytest.raises(ValueError, match='(?i)unavailable'):
            compiler.compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
                selected=_selected(historical_ids=[missing]), purpose='summary')
    packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(entry[2]),
        selected=_selected(historical_ids=['past', 'past']), purpose='summary')
    assert len(packet['snapshot']['materials']) == 1
    assert len(packet['academicItems']) == 1


def test_notes_are_student_attributed_and_supplementary_only_in_summary_and_tutor():
    identity, row, report = _setup('notes')
    item = report['items'][0]
    item['itemType'] = 'teaching_point'
    finding = report['alignments'][0]['requirements'][0]
    finding['relation'] = 'related_supplementary'
    report['alignments'][0] = aggregate_item_alignment([finding], item_id=item['id'])
    compiler = _compiler((identity, row, report))
    for purpose in ('summary', 'tutor'):
        packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
            selected=_selected(audio_ids=['note']), purpose=purpose)
        assert packet['academicItems'][0]['sourceType'] == 'notes'
        assert packet['academicItems'][0]['attribution'] == 'student-reported notes'
        assert packet['academicItems'][0]['relation'] == 'related_supplementary'
    for purpose in ('exam', 'flashcards'):
        packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
            selected=_selected(audio_ids=['note']), purpose=purpose)
        assert packet['academicItems'] == []


def test_selected_chapter_rescopes_every_kind_and_reuses_only_same_baseline_cache():
    entries = [_setup('historical_exam'), _setup('tutorial'), _setup('notes')]
    reports = {entry[0]['materialId']: entry[2] for entry in entries}
    repository = CheckedRepository([entry[1] for entry in entries], reports)
    library = CheckedLibrary(reports)
    aligner = RescopeAligner()
    compiler = SupportingContextCompiler(repository, library, aligner)
    scope = _second_scope(entries[0][2])
    selection = _selected(historical_ids=['past'], tutorial_ids=['tutorial'], audio_ids=['note'])
    first = compiler.compile(user_id='owner', course_id='course', scope=scope,
                             selected=selection, purpose='summary')
    assert sorted(aligner.calls) == ['historical_exam', 'notes', 'tutorial']
    assert {entry['identity']['kind'] for entry in first['snapshot']['materials']} == {
        'historical_exam', 'tutorial', 'notes'}
    assert all(entry['scopedReportRevision'] != entry['reportRevision'] for entry in first['snapshot']['materials'])
    compiler.compile(user_id='owner', course_id='course', scope=scope, selected=selection, purpose='exam')
    assert len(aligner.calls) == 3
    repository.rows[0]['processingJob']['id'] = 'retry-job'
    repository.rows[0]['supportingAnalysis']['analysisId'] = 'retry-job'
    compiler.compile(user_id='owner', course_id='course', scope=scope, selected=selection, purpose='exam')
    assert aligner.calls.count('historical_exam') == 2


@pytest.mark.parametrize('change', ('document_id', 'source_revision', 'guide_revision',
                                   'guide_content', 'title', 'allowed_ref', 'foundation'))
def test_same_revision_altered_scope_cannot_relabel_baseline_report(change):
    entry = _setup()
    scope = _scope(entry[2])
    if change == 'document_id': scope['documents'][0]['id'] = 'forged'
    elif change == 'source_revision': scope['documents'][0]['sourceRevision'] = 'c'*64
    elif change == 'guide_revision': scope['documents'][0]['guideRevision'] = 'c'*64
    elif change == 'guide_content': scope['documents'][0]['guide']['sections'][0]['label'] = 'Forged'
    elif change == 'title': scope['documents'][0]['title'] = 'Forged'
    elif change == 'allowed_ref': scope['allowedRefs'][0]['unitId'] = 'forged'
    elif change == 'foundation': scope['foundationRevision'] = 'c'*64
    with pytest.raises(ValueError, match='(?i)scope|foundation|ready'):
        _compiler(entry).compile(user_id='owner', course_id='course', scope=scope,
            selected=_selected(historical_ids=['past']), purpose='exam')


def test_cached_scope_checks_full_identity_and_returns_adopted_ref_order():
    entry = _setup()
    reports = {entry[0]['materialId']: entry[2]}
    compiler = SupportingContextCompiler(CheckedRepository([entry[1]], reports), CheckedLibrary(reports), RescopeAligner())
    scope = _second_scope(entry[2])
    selected = _selected(historical_ids=['past'])
    packet = compiler.compile(user_id='owner', course_id='course', scope=scope,
                              selected=selected, purpose='exam')
    assert packet['scopeSnapshot']['allowedRefs'] == scope['allowedRefs']
    reordered = deepcopy(scope)
    reordered['allowedRefs'].reverse()
    packet = compiler.compile(user_id='owner', course_id='course', scope=reordered,
                              selected=selected, purpose='exam')
    assert packet['scopeSnapshot']['allowedRefs'] == scope['allowedRefs']
    forged = deepcopy(scope)
    forged['documents'].reverse()
    with pytest.raises(ValueError, match='(?i)scope'):
        compiler.compile(user_id='owner', course_id='course', scope=forged,
                         selected=selected, purpose='exam')
    forged = deepcopy(scope)
    forged['allowedRefs'][1]['documentId'] = 'forged'
    with pytest.raises(ValueError, match='(?i)scope'):
        compiler.compile(user_id='owner', course_id='course', scope=forged,
                         selected=selected, purpose='exam')


def test_rescoped_report_cannot_relabel_different_selected_metadata():
    entry = _setup()
    reports = {entry[0]['materialId']: entry[2]}

    class AlteringAligner(RescopeAligner):
        def rescope(self, identity, baseline, *, scope, checkpoint):
            report = super().rescope(identity, baseline, scope=scope, checkpoint=checkpoint)
            report['scopeSnapshot']['documents'][0]['title'] = 'Forged report title'
            return report

    compiler = SupportingContextCompiler(CheckedRepository([entry[1]], reports),
                                         CheckedLibrary(reports), AlteringAligner())
    with pytest.raises(ValueError, match='(?i)scope'):
        compiler.compile(user_id='owner', course_id='course', scope=_second_scope(entry[2]),
                         selected=_selected(historical_ids=['past']), purpose='exam')
    assert compiler.repository.cache == {}


def test_unready_later_selection_blocks_all_scoped_alignment_work():
    historical = _setup('historical_exam')
    tutorial = _setup('tutorial', status='queued')
    reports = {historical[0]['materialId']: historical[2], tutorial[0]['materialId']: tutorial[2]}
    repository = CheckedRepository([historical[1], tutorial[1]], reports)
    library = CheckedLibrary(reports)
    aligner = RescopeAligner()
    scope = _second_scope(historical[2])
    compiler = SupportingContextCompiler(repository, library, aligner)
    with pytest.raises(ValueError, match='(?i)ready|upgrade'):
        compiler.compile(user_id='owner', course_id='course', scope=scope,
            selected=_selected(historical_ids=['past'], tutorial_ids=['tutorial']), purpose='summary')
    assert aligner.calls == []


def test_unknown_question_formats_keep_original_paper_count_without_invented_type():
    paper = {'paperId': 'p', 'examType': 'Final', 'totalQuestions': 8, 'totalMarks': None,
             'questionTypes': [], 'unknownQuestionTypeIds': ['q1'],
             'topicWeights': [{'topic': 'Trees', 'questionCount': 1}]}
    result = build_exam_blueprint([{'sourceId': 'past', 'analysisVersion': 3, 'papers': [paper]}])
    assert result['totalQuestions'] == 8
    assert result['questionTypes'] == []
    assert result['topicWeights'][0]['topic'] == 'Trees'
    assert result['evidence']['sources'][0]['totalMarks'] is None


def test_required_unsupported_shared_context_blocks_child_but_verified_omission_keeps_sibling():
    identity, row, report = _setup()
    parent = report['items'][0]
    parent['id'], parent['text'] = 'parent', 'Answer any three using an untaught theorem.'
    parent['sharedContextIds'] = ['stem']
    parent['supportingSourceProofs'] = deepcopy(report['alignments'][0]['requirements'][0]['supportingSourceProofs'])
    shared = {'id': 'stem', 'text': 'Use the untaught theorem.',
              'supportingSourceRefs': deepcopy(parent['supportingSourceRefs']),
              'supportingSourceProofs': deepcopy(parent['supportingSourceProofs'])}
    children = []
    for item_id in ('dependent', 'independent'):
        child = deepcopy(parent)
        child.update(id=item_id, parentId='parent', itemType='subpart',
                     text=f'Explain trees: {item_id}', sharedContextIds=[])
        children.append(child)
    report['items'] = [parent, *children]
    report['sharedContexts'] = [shared]
    components = context_components(report['items'], report['sharedContexts'])
    finding = report['alignments'][0]['requirements'][0]

    def dependency(component, decision):
        settled = {'sourceProofs': deepcopy(component['supportingSourceProofs']),
                   'decision': decision, 'contentKind': 'academic_claim',
                   'methodRequired': True, 'reason': 'Independently checked original component'}
        return {key: deepcopy(component[key]) for key in ('ownerType', 'ownerId', 'field', 'index', 'contentDigest')} | {
            'componentId': component['id'], 'supportingSourceProofs': deepcopy(component['supportingSourceProofs']),
            'decision': decision, 'contentKind': 'academic_claim', 'methodRequired': True,
            'verification': settled, 'relation': 'not_found' if decision == 'required' else 'not_applicable',
            'lectureSupportProofs': [], 'reviewCoverage': deepcopy(finding['reviewCoverage']), 'usable': False}

    alignments = []
    for item in report['items']:
        decision = 'required' if item['id'] == 'dependent' else 'not_required'
        dependencies = [dependency(component, decision) for component in components[item['id']]]
        alignments.append(aggregate_item_alignment([finding], item_id=item['id'], context_dependencies=dependencies))
    report['alignments'] = alignments
    report['papers'][0]['questionIds'] = ['parent']
    report['topics'] = [{'id': 'parent-topic', 'text': 'Unsafe parent vote', 'itemIds': ['parent'],
                         'requirementIds': ['r1'], 'alignment': {'relation': 'lecture_supported',
                         'originRequirementIds': ['r1']}}]
    report['alignmentCoverage'].update(itemIds=[i['id'] for i in report['items']],
                                        checkedItemIds=[i['id'] for i in report['items']])
    packet = _compiler((identity, row, report)).compile(user_id='owner', course_id='course',
        scope=_scope(report), selected=_selected(historical_ids=['past']), purpose='exam')
    assert [item['id'] for item in packet['academicItems']] == ['independent']
    assert packet['academicItems'][0]['text'] == 'Explain trees: independent'
    assert packet['academicItems'][0]['requiredContext'] == []
    assert packet['structuralPapers'][0]['topics'] == []
    assert historical_projection(packet)[0]['papers'][0]['topicWeights'] == []


def test_projection_normalizes_verified_topics_per_paper_and_preserves_structure():
    def paper(source, paper_id, count, topics, known_type):
        questions = []
        topic_rows = []
        for number, label in enumerate(topics):
            item_id = f'{paper_id}-{number}'
            requirement_id = f'{item_id}-r'
            questions.append({'id': item_id, 'parentId': None, 'paperId': paper_id,
                'text': f'Original {label} question', 'requirements': [{'id': requirement_id}],
                'alignment': {'status': 'covered', 'requirements': [{'requirementId': requirement_id,
                    'relation': 'lecture_supported'}]}, 'materialIdentity': {'materialId': source,
                    'kind': 'historical_exam'}, 'sourceType': 'historical_exam'})
            topic_rows.append({'id': f'{item_id}-topic', 'text': label, 'itemIds': [item_id],
                'requirementIds': [requirement_id], 'alignment': {'relation': 'lecture_supported',
                    'originRequirementIds': [requirement_id]}})
        structure = {'paperId': paper_id, 'examType': 'Final', 'totalQuestions': count,
            'totalMarks': None, 'questionIds': [q['id'] for q in questions],
            'questionTypes': [{'type': known_type, 'count': count}] if known_type else [],
            'unknownQuestionTypeIds': [] if known_type else [q['id'] for q in questions]}
        return questions, {'materialIdentity': {'materialId': source, 'kind': 'historical_exam'},
                           'paper': structure, 'topics': topic_rows, 'eligibleItemIds': [q['id'] for q in questions]}

    a, a_struct = paper('a', 'p1', 2, ['Decision Trees', 'Graphs'], 'mcq')
    b, b_struct = paper('b', 'p2', 10, ['decision trees'], None)
    packet = {'academicItems': a+b, 'structuralPapers': [a_struct, b_struct]}
    projected = historical_projection(packet)
    blueprint = build_exam_blueprint(projected)
    assert blueprint == build_exam_blueprint(historical_projection({**packet,
        'academicItems': list(reversed(packet['academicItems'])),
        'structuralPapers': list(reversed(packet['structuralPapers']))}))
    assert {row['topic']: row['weight'] for row in blueprint['topicWeights']} == {
        'Decision Trees': .75, 'Graphs': .25}
    assert blueprint['evidence']['paperCount'] == 2
    assert any(source['unknownQuestionTypeIds'] for source in blueprint['evidence']['sources'])


def test_only_explicit_tutor_conflict_discussion_receives_qualified_original():
    identity, row, report = _setup()
    finding = report['alignments'][0]['requirements'][0]
    finding['relation'] = 'conflicting'
    report['alignments'][0] = aggregate_item_alignment([finding], item_id='q1')
    compiler = _compiler((identity, row, report))
    ordinary = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
        selected=_selected(historical_ids=['past']), purpose='tutor', discussion_query='Help me study trees')
    requested = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
        selected=_selected(historical_ids=['past']), purpose='tutor',
        discussion_query='Discuss the conflict in this past question')
    assert ordinary['qualifiedItems'] == []
    assert requested['academicItems'] == []
    assert requested['qualifiedItems'][0]['text'] == 'Explain trees in the original question.'
    assert requested['qualifiedItems'][0]['relation'] == 'conflicting'
    assert requested['qualifiedItems'][0]['supportingSourceProofs'] == report['items'][0]['supportingSourceProofs']
    assert requested['qualifiedItems'][0]['scopeRevision'] == report['scopeSnapshot']['scopeRevision']
    arabic = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
        selected=_selected(historical_ids=['past']), purpose='tutor',
        discussion_query='ناقش التعارض في السؤال السابق')
    assert arabic['qualifiedItems'][0]['relation'] == 'conflicting'
    for query in ('Is this question contradicted by the lecture?',
                  'هل يتعارض هذا السؤال مع المحاضرة؟'):
        direct = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
            selected=_selected(historical_ids=['past']), purpose='tutor', discussion_query=query)
        assert direct['qualifiedItems'][0]['relation'] == 'conflicting'
    for query in ('What is a contradiction in general?', 'هل تعرف معنى التناقض؟'):
        general = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
            selected=_selected(historical_ids=['past']), purpose='tutor', discussion_query=query)
        assert general['qualifiedItems'] == []
    for purpose in ('summary', 'exam', 'flashcards'):
        packet = compiler.compile(user_id='owner', course_id='course', scope=_scope(report),
            selected=_selected(historical_ids=['past']), purpose=purpose,
            discussion_query='Discuss the conflict')
        assert packet['qualifiedItems'] == []


def test_projection_omits_unchecked_style_prose_from_excluded_questions():
    packet = {'academicItems': [], 'structuralPapers': [{
        'materialIdentity': {'kind': 'historical_exam', 'materialId': 'past'},
        'paper': {'paperId': 'p1', 'examType': 'Final', 'totalQuestions': 1, 'totalMarks': None,
                  'questionIds': ['excluded'], 'questionTypes': [{'type': 'written', 'count': 1,
                      'style': 'Use an untaught method from the excluded question'}],
                  'unknownQuestionTypeIds': []},
        'topics': [], 'eligibleItemIds': []}]}
    projected = historical_projection(packet)
    paper = projected[0]['papers'][0]
    assert paper['totalQuestions'] == 1
    assert paper['questionTypes'] == [{'type': 'written', 'count': 1}]
    assert build_exam_blueprint(projected)['styles'] == []


def test_compiled_structural_paper_does_not_expose_unchecked_style_prose():
    identity, row, report = _setup()
    report['papers'][0]['questionTypes'] = [{'type': 'written', 'count': 1,
        'questionIds': ['q1'], 'style': 'Apply a method never taught in lectures'}]
    packet = _compiler((identity, row, report)).compile(user_id='owner', course_id='course',
        scope=_scope(report), selected=_selected(historical_ids=['past']), purpose='summary')
    assert packet['structuralPapers'][0]['paper']['questionTypes'] == [
        {'type': 'written', 'count': 1, 'questionIds': ['q1']}]


def test_unchecked_topic_wording_stays_out_of_structural_packet():
    identity, row, report = _setup()
    report['topics'] = [{'id': 't1', 'text': 'Untaught theorem to copy', 'itemIds': ['q1'],
        'requirementIds': ['r1'], 'alignment': {'relation': 'not_found',
            'originRequirementIds': ['r1']}}]
    packet = _compiler((identity, row, report)).compile(user_id='owner', course_id='course',
        scope=_scope(report), selected=_selected(historical_ids=['past']), purpose='exam')
    assert packet['structuralPapers'][0]['topics'] == []
