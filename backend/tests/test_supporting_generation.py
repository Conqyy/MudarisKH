"""Checked supporting packets cross the actual generator request boundary."""

import json
import pytest

from src.utils.generation_context import supporting_packet_text


def packet():
    return {'version': 1, 'purpose': 'summary',
        'scopeSnapshot': {'version': 1, 'scopeRevision': 'a' * 64,
                          'foundationRevision': 'b' * 64, 'documents': [], 'allowedRefs': []},
        'snapshot': {'version': 1, 'materials': [{'identity': {'userId': 'u', 'courseId': 'c',
            'kind': 'historical_exam', 'materialId': 'paper'}, 'sourceRevision': 'c' * 64,
            'reportRevision': 'd' * 64, 'analysisId': 'job', 'scopedReportRevision': 'e' * 64}]},
        'academicItems': [{'id': 'q1', 'text': 'EXACT CHECKED QUESTION',
            'requiredContext': [{'value': 'REQUIRED PARENT'}], 'alignment': {'status': 'covered'}}],
        'qualifiedItems': [], 'structuralPapers': [], 'coverage': {'complete': True}}


def test_packet_text_preserves_every_checked_item_or_fails_before_provider():
    checked = packet()
    serialized = supporting_packet_text(checked)
    assert json.loads(serialized) == checked
    checked['academicItems'].append({'id': 'tail', 'text': 'TAIL' * 30000})
    with pytest.raises(ValueError, match='(?i)split|select fewer|budget'):
        supporting_packet_text(checked)


def test_tutor_preserves_model_provenance_for_backend_verification(monkeypatch):
    from types import SimpleNamespace
    from src.agents import tutor_agent
    agent = tutor_agent.AITutorAgent.__new__(tutor_agent.AITutorAgent)
    agent.client, agent.model_id = object(), 'test-model'
    claim = {'path': '/reply', 'authority': 'lecture', 'relation': 'lecture_supported',
             'sourceRefs': [{'documentId': 'doc', 'sourceRevision': 'a' * 64, 'unitId': 'u'}],
             'supportingSourceRefs': [], 'supportingSourceProofs': [], 'lectureAnchorRefs': []}
    result = {'reply': 'A claim', 'sourceRefs': claim['sourceRefs'],
              'supportingSourceRefs': [], 'provenance': [claim]}
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps(result)), finish_reason='stop')])
    monkeypatch.setattr(tutor_agent, 'chat_with_retry', lambda *a, **kw: response)
    assert agent.reply_grounded({'course': {}}, [{'role': 'user', 'content': 'Explain'}],
                                lecture_evidence=None, supporting_context=packet()) == result


@pytest.mark.parametrize('kind', ['exam', 'summary', 'flashcards', 'tutor'])
def test_all_generator_provider_messages_use_only_checked_supporting_data(monkeypatch, kind):
    from src.agents import exam_generator, summary_generator, tutor_agent
    module = tutor_agent if kind == 'tutor' else summary_generator if kind == 'summary' else exam_generator
    agent_type = (tutor_agent.AITutorAgent if kind == 'tutor' else
                  summary_generator.SummaryGeneratorAgent if kind == 'summary' else exam_generator.ExamGeneratorAgent)
    agent = agent_type.__new__(agent_type)
    agent.client, agent.model_id = object(), 'test-model'
    seen = []

    class Captured(Exception): pass

    def capture(*args, **kwargs):
        seen.append(kwargs['messages'])
        raise Captured()

    monkeypatch.setattr(module, 'chat_with_retry', capture)
    checked = packet()
    with pytest.raises(Captured):
        if kind == 'exam':
            agent.compile_enhanced_exam({}, [], '', 'exam', historical_texts=['RAW UNCHECKED'],
                tutorial_texts=['RAW UNCHECKED'], audio_insights=[{'summary': 'RAW UNCHECKED'}],
                supporting_context=checked)
        elif kind == 'summary':
            agent.generate_summary({}, [], historical_texts=['RAW UNCHECKED'],
                tutorial_texts=['RAW UNCHECKED'], audio_insights=[{'summary': 'RAW UNCHECKED'}],
                supporting_context=checked)
        elif kind == 'flashcards':
            agent.generate_flashcards({}, [], historical_texts=['RAW UNCHECKED'],
                tutorial_texts=['RAW UNCHECKED'], audio_insights=[{'summary': 'RAW UNCHECKED'}],
                supporting_context=checked)
        else:
            agent.reply_grounded({'past_exams': [{'extractedText': 'RAW UNCHECKED'}]},
                [{'role': 'user', 'content': 'Help'}], lecture_evidence=None,
                supporting_context=checked)
    assert len(seen) == 1
    sent = json.dumps(seen[0], ensure_ascii=False)
    assert 'EXACT CHECKED QUESTION' in sent and 'REQUIRED PARENT' in sent
    assert checked['snapshot']['materials'][0]['scopedReportRevision'] in sent
    assert 'RAW UNCHECKED' not in sent


@pytest.mark.parametrize('kind', ['summary', 'flashcards'])
def test_structured_retry_reuses_entire_checked_packet(monkeypatch, kind):
    from types import SimpleNamespace
    from src.agents import exam_generator, summary_generator
    module = summary_generator if kind == 'summary' else exam_generator
    agent_type = summary_generator.SummaryGeneratorAgent if kind == 'summary' else exam_generator.ExamGeneratorAgent
    agent = agent_type.__new__(agent_type)
    agent.client, agent.model_id = object(), 'test-model'
    seen = []
    completed = ({'title': 'Trees', 'overview': 'Trees', 'sections': [{
        'heading': 'Trees', 'content': 'Trees have roots.', 'keyPoints': [],
        'examLikelihood': 'high', 'examWeight': 50}], 'keyTerms': [], 'examFocus': []}
        if kind == 'summary' else {'cards': [{'front': 'Trees?', 'back': 'Roots.',
                                             'topic': 'Trees', 'examLikelihood': 'high'}]})
    ref = {'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}
    row = completed if kind == 'summary' else completed['cards'][0]
    paths = (['/overview', '/sections/0/heading', '/sections/0/content']
             if kind == 'summary' else ['/front', '/back', '/topic'])
    row['provenance'] = [{'path': path, 'authority': 'lecture', 'relation': 'lecture_supported',
        'sourceRefs': [ref], 'supportingSourceRefs': [], 'supportingSourceProofs': [],
        'lectureAnchorRefs': []} for path in paths]
    def provider(*args, **kwargs):
        seen.append(json.dumps(kwargs['messages'], ensure_ascii=False))
        content = 'not json' if len(seen) == 1 else json.dumps(completed)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                                        finish_reason='stop')])
    monkeypatch.setattr(module, 'chat_with_retry', provider)
    if kind == 'summary':
        agent.generate_summary({}, [], supporting_context=packet())
    else:
        agent.generate_flashcards({}, [], count=1, supporting_context=packet())
    assert len(seen) == 2
    assert all('EXACT CHECKED QUESTION' in call and 'REQUIRED PARENT' in call for call in seen)


def test_summary_claims_resolve_unique_quotes_in_final_text_and_cover_every_field():
    from src.supporting.verification import SupportingOutputVerifier
    lecture_ref = {'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}

    class Reader:
        scope = {'allowedRefs': [lecture_ref]}
        def validate_refs(self, refs):
            if refs != [lecture_ref]: raise ValueError('Wrong lecture ref')
            return refs
        def verify_rows(self, rows, **kwargs): return rows

    summary = {'overview': 'Trees have nodes.',
        'sections': [{'heading': 'Trees', 'content': 'A root has children.',
                      'keyPoints': ['Leaves have no children.'], 'sourceRefs': [lecture_ref]}],
        'keyTerms': [{'term': 'Root', 'definition': 'First node.'}],
        'examFocus': ['Trace the tree.'], 'sourceRefs': [lecture_ref]}
    fields = ['/overview', '/sections/0/heading', '/sections/0/content',
              '/sections/0/keyPoints/0', '/keyTerms/0/term',
              '/keyTerms/0/definition', '/examFocus/0']
    summary['provenance'] = [{'path': path, 'authority': 'lecture',
                              'relation': 'lecture_supported', 'sourceRefs': [lecture_ref],
                              'supportingSourceRefs': [], 'supportingSourceProofs': [],
                              'lectureAnchorRefs': []} for path in fields]
    incomplete = json.loads(json.dumps(summary))
    incomplete['provenance'].pop()
    result = SupportingOutputVerifier(Reader(), None).verify_rows([summary], packet=packet(), purpose='summary')[0]
    assert result['provenance'][0]['start'] == 0
    assert result['provenance'][0]['end'] == len(summary['overview'])
    assert 'quote' not in result['provenance'][0]
    assert result['sections'][0]['sourceRefs'] == [lecture_ref]
    assert result['keyTerms'][0]['sourceRefs'] == [lecture_ref]
    with pytest.raises(ValueError, match='(?i)provenance|cover|academic'):
        SupportingOutputVerifier(Reader(), None).verify_rows([incomplete], packet=packet(), purpose='summary')


def test_ambiguous_model_quote_cannot_select_a_claim_occurrence():
    from src.supporting.verification import SupportingOutputVerifier
    lecture_ref = {'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}
    class Reader:
        scope = {'allowedRefs': [lecture_ref]}
        def validate_refs(self, refs): return refs
        def verify_rows(self, rows, **kwargs): return rows
    card = {'front': 'tree tree', 'back': 'answer', 'topic': 'tree', 'sourceRefs': [lecture_ref],
            'provenance': [{'path': '/front', 'quote': 'tree', 'authority': 'lecture',
                            'relation': 'lecture_supported', 'sourceRefs': [lecture_ref],
                            'supportingSourceRefs': [], 'supportingSourceProofs': [],
                            'lectureAnchorRefs': []}]}
    with pytest.raises(ValueError, match='(?i)quote|ambiguous'):
        SupportingOutputVerifier(Reader(), None).verify_rows([card], packet=packet(), purpose='flashcards')


def test_supplementary_proof_must_belong_to_checked_scoped_report():
    from src.supporting.verification import SupportingOutputVerifier
    lecture_ref = {'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}
    supporting_ref = {'kind': 'historical_exam', 'materialId': 'paper',
                      'sourceRevision': 'c' * 64, 'unitId': 'u1'}
    allowed = {'type': 'text_span', 'ref': supporting_ref, 'field': 'text',
               'start': 0, 'end': 7, 'quote': 'Checked'}
    forged = {**allowed, 'start': 8, 'end': 14, 'quote': 'FORGED'}
    lecture_proof = {'type': 'text_span', 'ref': lecture_ref, 'field': 'text',
                     'start': 0, 'end': 7, 'quote': 'Lecture'}

    class Reader:
        scope = {'scopeRevision': 'a' * 64, 'allowedRefs': [lecture_ref], 'manifests': [{'documentId': 'lecture',
            'sourceRevision': 'f' * 64, 'units': [{'unitId': 'u1', 'kind': 'paragraph',
            'position': 1, 'label': 'p1', 'text': 'Lecture covers trees.', 'visualText': '',
            'visualAssets': []}]}]}
        def validate_refs(self, refs): return refs
        def verify_rows(self, rows, **kwargs): return rows
        def original_batch_fits(self, batch, *, policy, task): return True
        def read_original_batch(self, batch, *, policy, task): return {'supported': True, 'anchored': True}, []

    class Library:
        def read_refs(self, identity, refs):
            return [{'unitId': 'u1', 'text': 'Checked FORGED source', 'visualText': '', 'visualAssets': []}]
        def load_report(self, identity, revision):
            return {'sourceRevision': 'c' * 64, 'scopeSnapshot': {'scopeRevision': 'a' * 64},
                    'items': [], 'alignments': [{'requirements': [{'supportingSourceProofs': [allowed],
                        'lectureSupportProofs': [lecture_proof]}]}], 'sharedContexts': [], 'topics': []}

    checked = packet()
    checked['academicItems'][0]['alignment'] = {'requirements': [{'supportingSourceProofs': [allowed],
        'lectureSupportProofs': [lecture_proof]}]}
    card = {'front': 'Trees', 'back': 'Professor explained trees.', 'topic': 'Trees',
            'sourceRefs': [lecture_ref], 'supportingSourceRefs': [supporting_ref]}
    lecture = lambda path: {'path': path, 'authority': 'lecture', 'relation': 'lecture_supported',
        'sourceRefs': [lecture_ref], 'supportingSourceRefs': [],
        'supportingSourceProofs': [], 'lectureAnchorRefs': []}
    supplement = {'path': '/back', 'authority': 'supplementary',
        'relation': 'related_supplementary', 'sourceRefs': [],
        'supportingSourceRefs': [supporting_ref], 'supportingSourceProofs': [forged],
        'lectureAnchorRefs': [lecture_ref]}
    card['provenance'] = [lecture('/front'), supplement, lecture('/topic')]
    with pytest.raises(ValueError, match='(?i)report|checked|proof'):
        SupportingOutputVerifier(Reader(), Library()).verify_rows([card], packet=checked, purpose='flashcards')
    checked['academicItems'][0]['relation'] = 'lecture_supported'
    checked['academicItems'][0]['materialIdentity'] = checked['snapshot']['materials'][0]['identity']
    checked['academicItems'][0]['supportingSourceProofs'] = [allowed]
    card['provenance'][1]['supportingSourceProofs'] = [allowed]
    with pytest.raises(ValueError, match='(?i)relation|alignment'):
        SupportingOutputVerifier(Reader(), Library()).verify_rows([card], packet=checked, purpose='flashcards')
    card['provenance'][1]['relation'] = 'lecture_supported'
    class ContraryReader(Reader):
        def read_original_batch(self, batch, *, policy, task):
            return {'supported': False, 'anchored': True}, []
    with pytest.raises(ValueError, match='(?i)original|verified'):
        SupportingOutputVerifier(ContraryReader(), Library()).verify_rows([card],
                                                                          packet=checked, purpose='flashcards')
    card['provenance'][1]['sourceRefs'] = [{'documentId': 'unrelated',
        'sourceRevision': 'e' * 64, 'unitId': 'u1'}]
    card['sourceRefs'].append(card['provenance'][1]['sourceRefs'][0])
    with pytest.raises(ValueError, match='(?i)anchor|citation'):
        SupportingOutputVerifier(Reader(), Library()).verify_rows([card],
                                                                  packet=checked, purpose='flashcards')
    card['provenance'][1]['sourceRefs'] = []
    card['sourceRefs'] = [lecture_ref]
    wrong_pair = json.loads(json.dumps(checked))
    wrong_pair['academicItems'][0]['alignment']['requirements'][0]['lectureSupportProofs'] = []
    wrong_pair['academicItems'][0]['alignment']['requirements'].append({
        'supportingSourceProofs': [forged], 'lectureSupportProofs': [lecture_proof]})
    with pytest.raises(ValueError, match='(?i)anchor|proof'):
        SupportingOutputVerifier(Reader(), Library()).verify_rows([card],
                                                                  packet=wrong_pair, purpose='flashcards')


def test_api_compiler_receives_original_selections_and_selected_lecture_scope(monkeypatch):
    from types import SimpleNamespace
    from src import api
    from src.supporting import context, alignment
    calls = []
    class Compiler:
        def __init__(self, repository, library, aligner): pass
        def compile(self, **kwargs):
            calls.append(kwargs)
            return packet()
    monkeypatch.setattr(context, 'SupportingContextCompiler', Compiler)
    monkeypatch.setattr(alignment, 'SupportingAligner', lambda reader, library: object())
    reader = SimpleNamespace(scope={'scopeRevision': 'a' * 64})
    result = api._compile_supporting_context(reader, 'u', 'c',
        historical_ids=['paper'], audio_ids=[], tutorial_ids=None,
        purpose='summary')
    assert result['snapshot'] == packet()['snapshot']
    assert calls == [{'user_id': 'u', 'course_id': 'c', 'scope': reader.scope,
                      'selected': {'historical_ids': ['paper'], 'audio_ids': [], 'tutorial_ids': None},
                      'purpose': 'summary', 'discussion_query': None}]


def test_exam_blueprint_unknown_formats_leave_only_known_type_counts_fixed():
    from src.utils.ai_contracts import validate_exam_contract
    tex = r'\begin{document}\textbf{Question 1} A \textbf{Question 2} B \end{document}'
    blueprint = {'totalQuestions': 2, 'unknownQuestionCount': 1,
                 'questionTypes': [{'type': 'mcq', 'count': 1}]}
    questions = {'q1': {'question_type': 'mcq', 'max_score': 1, 'correct_answer': 'A'},
                 'q2': {'question_type': 'written', 'max_score': 1, 'criteria': 'B'}}
    assert validate_exam_contract(tex, {'questions': questions}, blueprint=blueprint)
    questions['q1'] = {'question_type': 'written', 'max_score': 1, 'criteria': 'A'}
    with pytest.raises(ValueError, match='(?i)mix|type'):
        validate_exam_contract(tex, {'questions': questions}, blueprint=blueprint)


def test_saved_question_identity_keeps_per_question_supporting_refs():
    from src.services.source_evidence import saved_question_identity
    tex = r'\begin{document}\textbf{Question 1} Explain trees.\end{document}'
    supporting = {'kind': 'historical_exam', 'materialId': 'past',
                  'sourceRevision': 'a' * 64, 'unitId': 'u1'}
    rubrics = {'questions': {'q1': {'question_type': 'written', 'max_score': 2,
                                   'criteria': 'Explain a root', 'sourceRefs': [],
                                   'supportingSourceRefs': [supporting]}}}
    assert saved_question_identity(tex, rubrics)['questions'][0]['supportingSourceRefs'] == [supporting]


def test_student_notes_are_framed_as_reports_in_analysis_and_pdf():
    from src import api
    framed = api._frame_notes('The professor promised eight marks.')
    assert 'student-reported' in framed.lower()
    assert 'first-hand exam hint' not in framed.lower()
    pdf = api._audio_to_latex({'title': 'Notes', 'sourceType': 'notes',
        'insights': {'summary': 'Eight marks were promised.',
                     'examHints': [{'hint': 'Eight marks for trees.',
                                    'confidence': 0.9, 'source': 'Eight marks'}]}})
    assert 'Student-reported notes' in pdf
    assert 'Student-reported exam hints' in pdf
    assert 'Lecture analysis' not in pdf


def test_managed_notes_pdf_without_legacy_insights_points_to_report(monkeypatch):
    from types import SimpleNamespace
    from src import api
    row = {'userId': 'u', 'courseId': 'c', 'sourceType': 'notes',
           'supportingAnalysis': {'state': 'completed'}, 'insights': None}
    monkeypatch.setattr(api, 'db_client', SimpleNamespace(get_audio_recording=lambda *a: row))
    with pytest.raises(api.HTTPException) as exc:
        api.get_audio_pdf('note', uid='u')
    assert exc.value.status_code == 409
    assert 'report' in exc.value.detail.lower()
    row['supportingAnalysis'] = None
    with pytest.raises(api.HTTPException) as legacy:
        api.get_audio_pdf('note', uid='u')
    assert 'retry' in legacy.value.detail.lower()


def test_unanchored_qualified_tutor_claim_requires_explicit_scope_warning():
    from src.supporting.verification import SupportingOutputVerifier
    ref = {'kind': 'historical_exam', 'materialId': 'paper',
           'sourceRevision': 'c' * 64, 'unitId': 'u1'}
    proof = {'type': 'text_span', 'ref': ref, 'field': 'text',
             'start': 0, 'end': 5, 'quote': 'Trees'}
    reply = {'reply': 'Trees have roots.', 'sourceRefs': [], 'supportingSourceRefs': [ref],
             'provenance': [{'path': '/reply', 'authority': 'supplementary',
                'relation': 'outside_selected_scope', 'sourceRefs': [],
                'supportingSourceRefs': [ref], 'supportingSourceProofs': [proof],
                'lectureAnchorRefs': []}]}
    checked = packet()
    checked['qualifiedItems'] = [{'relation': 'outside_selected_scope',
        'materialIdentity': checked['snapshot']['materials'][0]['identity'],
        'supportingSourceProofs': [proof]}]
    class Reader:
        def validate_refs(self, refs): return refs
    with pytest.raises(ValueError, match='(?i)scope|qualified'):
        SupportingOutputVerifier(Reader(), None).verify_tutor_reply(reply, packet=checked)


def test_public_exam_projects_only_safe_supporting_identity_and_citations():
    from src import api
    ref = {'kind': 'historical_exam', 'materialId': 'paper',
           'sourceRevision': 'c' * 64, 'unitId': 'u1'}
    source = packet()['snapshot']['materials'][0]
    exam = {'userId': 'u', 'courseId': 'c', 'texContent': 'Question',
            'questionStructure': [{'id': 'q1', 'text': 'Question',
                                   'supportingSourceRefs': [ref]}],
            'sharedSupportingSourceRefs': [ref],
            'supportingSnapshot': {'version': 1, 'materials': [source]},
            'rubrics': {'secret': 'private'}, 'provenance': [{'supportingSourceProofs': ['private']}]}
    public = api._public_exam(exam)
    assert public['questionStructure'][0]['supportingSourceRefs'] == [ref]
    assert public['sharedSupportingSourceRefs'] == [ref]
    assert public['supportingSnapshot']['materials'][0]['identity'] == {
        'kind': 'historical_exam', 'materialId': 'paper'}
    assert 'analysisId' not in str(public)
    assert 'rubrics' not in public and 'provenance' not in public


def test_summary_pruning_rebases_selectors_without_reassigning_claims():
    from src.supporting.verification import rebase_summary_provenance
    before = {'overview': 'Trees', 'sections': [
        {'heading': 'Drop', 'content': 'Wrong', 'keyPoints': []},
        {'heading': 'Keep', 'content': 'Grounded', 'keyPoints': ['Point']}],
        'keyTerms': [], 'examFocus': [], 'provenance': [
            {'path': '/overview'}, {'path': '/sections/0/heading'},
            {'path': '/sections/1/heading'}, {'path': '/sections/1/content'},
            {'path': '/sections/1/keyPoints/0'}]}
    after = json.loads(json.dumps(before))
    after['sections'] = [after['sections'][1]]
    rebase_summary_provenance(before, after)
    assert [row['path'] for row in after['provenance']] == [
        '/overview', '/sections/0/heading', '/sections/0/content',
        '/sections/0/keyPoints/0']


def test_social_tutor_reply_with_selected_supporting_uses_nonacademic_check():
    from src.supporting.verification import SupportingOutputVerifier
    seen = []
    class Reader:
        def verify_nonacademic_reply(self, reply): seen.append(reply)
    reply = {'reply': 'Happy to help.', 'sourceRefs': [],
             'supportingSourceRefs': [], 'provenance': []}
    assert SupportingOutputVerifier(Reader(), None).verify_tutor_reply(reply, packet=packet()) == reply
    assert seen == ['Happy to help.']


def test_summary_root_citations_cover_overview_while_section_keeps_own_refs():
    from src.supporting.verification import SupportingOutputVerifier
    first = {'documentId': 'one', 'sourceRevision': 'a' * 64, 'unitId': 'u1'}
    second = {'documentId': 'two', 'sourceRevision': 'b' * 64, 'unitId': 'u2'}
    class Reader:
        def validate_refs(self, refs): return refs
        def verify_rows(self, rows, **kwargs): return rows
    def claim(path, ref):
        return {'path': path, 'authority': 'lecture', 'relation': 'lecture_supported',
                'sourceRefs': [ref], 'supportingSourceRefs': [],
                'supportingSourceProofs': [], 'lectureAnchorRefs': []}
    row = {'overview': 'First', 'sections': [{'heading': 'Second', 'content': 'Second.',
            'keyPoints': [], 'sourceRefs': [second]}], 'keyTerms': [], 'examFocus': [],
           'sourceRefs': [first], 'provenance': [claim('/overview', first),
              claim('/sections/0/heading', second), claim('/sections/0/content', second)]}
    checked = SupportingOutputVerifier(Reader(), None).verify_rows([row], packet=packet(), purpose='summary')[0]
    assert checked['sourceRefs'] == [first]
    assert checked['sections'][0]['sourceRefs'] == [second]


def test_exam_shared_and_question_citations_remain_distinct():
    from src.supporting.verification import SupportingOutputVerifier
    first = {'documentId': 'one', 'sourceRevision': 'a' * 64, 'unitId': 'u1'}
    second = {'documentId': 'two', 'sourceRevision': 'b' * 64, 'unitId': 'u2'}
    class Reader:
        def validate_refs(self, refs): return refs
        def verify_rows(self, rows, **kwargs): return rows
    def claim(path, ref):
        return {'path': path, 'authority': 'lecture', 'relation': 'lecture_supported',
                'sourceRefs': [ref], 'supportingSourceRefs': [],
                'supportingSourceProofs': [], 'lectureAnchorRefs': []}
    tex = r'\begin{document}Preface.\textbf{Question 1} Explain trees.\end{document}'
    rubric = {'sharedSourceRefs': [first], 'questions': {'q1': {
        'question_type': 'written', 'max_score': 2, 'criteria': 'Root and leaves.',
        'sourceRefs': [second]}}, 'provenance': [claim('/sharedContext', first),
        claim('/questions/q1/text', second), claim('/questions/q1/criteria', second)]}
    checked = SupportingOutputVerifier(Reader(), None).verify_exam(tex, rubric, packet=packet())
    assert checked['sharedSourceRefs'] == [first]
    assert checked['questions']['q1']['sourceRefs'] == [second]
