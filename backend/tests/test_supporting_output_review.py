"""Supporting-aware output retains joint semantics and closed academic coverage."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.services.source_evidence import SourceEvidence
from src.supporting.verification import SupportingOutputVerifier
from tests.test_source_agent_integration import Library, response
from tests.test_source_context import source_scope
from tests.test_supporting_generation import packet


def lecture_claim(path, refs):
    return {'path': path, 'authority': 'lecture', 'relation': 'lecture_supported',
            'sourceRefs': deepcopy(refs), 'supportingSourceRefs': [],
            'supportingSourceProofs': [], 'lectureAnchorRefs': []}


def original_reader(monkeypatch, texts, judge):
    scope = source_scope(texts)
    calls = []
    def provider(client, **kwargs):
        data = json.loads(kwargs['messages'][1]['content'][0]['text'])
        if 'supportedSpans' in kwargs['messages'][0]['content']:
            calls.append(deepcopy(data))
            task = data['task']
            text = task['text']
            good = judge(task, data['evidence'])
            return response({'supportedSpans': [{'start': 0, 'end': len(text),
                'text': text, 'reason': 'Controlled original evidence judgment'}] if good else []})
        refs = [entry['ref'] for entry in data['evidence'] if entry['ranges']]
        return response({'facts': [{'text': 'Controlled lecture fact', 'sourceRefs': refs}],
                         'administrativeRefs': []})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'fake')
    reader.prepare('exam')
    return reader, calls


def exam(refs, *, written=False):
    body = ('Explain the graph edge rule.' if written else
            'Which value is twice 2? A: 3. B: 4.')
    tex = r'\begin{document}\textbf{Question 1} ' + body + r' [2 marks]\end{document}'
    grading = {'criteria': 'Explain graph edges.'} if written else {'correct_answer': 'B'}
    rubric = {'sharedSourceRefs': refs, 'questions': {'q1': {
        'question_type': 'written' if written else 'mcq', 'max_score': 2,
        **grading, 'sourceRefs': refs}}, 'provenance': [
            lecture_claim('/sharedContext', refs), lecture_claim('/questions/q1/text', refs),
            lecture_claim('/questions/q1/' + ('criteria' if written else 'correct_answer'), refs)]}
    return tex, rubric


@pytest.mark.parametrize('saved', [False, True])
@pytest.mark.parametrize('written', [False, True])
def test_selected_supporting_exam_rejects_answer_or_criterion_for_another_question(monkeypatch, saved, written):
    # The old per-field path accepts each plausible fragment independently.
    def judge(task, evidence):
        row = task['row']
        if 'question' not in row: return True
        return row.get('criteria') == 'Explain graph edges.' if written else row.get('correct_answer') == 'B'
    reader, calls = original_reader(monkeypatch, ['Doubling 2 gives 4. Graph edges connect nodes.'], judge)
    tex, rubric = exam(reader.scope['allowedRefs'], written=written)
    verifier = SupportingOutputVerifier(reader, None)
    if saved:
        verifier.verify_exam(tex, rubric, packet=packet())
    rubric['questions']['q1'].update({'criteria': 'Explain wrong edges.'} if written else {'correct_answer': 'A'})
    with pytest.raises(ValueError, match='(?i)verif|provenance|support'):
        verifier.verify_exam(tex, rubric, packet=packet(), saved=saved)


def test_selected_supporting_exam_joint_check_reads_independently_cited_shared_original(monkeypatch):
    def judge(task, evidence):
        row = task['row']
        if 'question' not in row: return True
        return ({entry['ref']['unitId'] for entry in evidence} == {'p0001', 'p0002'}
                and any(r'\newcommand{\factor}{2}' in part for part in json.loads(task['sharedContext']))
                and row.get('correct_answer') == 'B')
    reader, calls = original_reader(monkeypatch,
        ['The shared multiplier is two.', 'Multiplying two by two gives four.'], judge)
    first, second = reader.scope['allowedRefs']
    tex, rubric = exam([second])
    tex = tex.replace(r'\begin{document}', r'\newcommand{\factor}{2}\begin{document}')
    rubric['sharedSourceRefs'] = [first]
    rubric['provenance'][0] = lecture_claim('/sharedContext', [first])
    SupportingOutputVerifier(reader, None).verify_exam(tex, rubric, packet=packet())
    joint = [data for data in calls if 'question' in data['task']['row']]
    assert joint, 'No semantic judgment received a complete question and its grading key'
    assert rubric['sharedSourceRefs'] == [first]
    assert rubric['questions']['q1']['sourceRefs'] == [second]


def supporting_claim(path, lecture_ref, supporting_ref, proof):
    return {'path': path, 'authority': 'supplementary', 'relation': 'lecture_supported',
        'sourceRefs': [], 'supportingSourceRefs': [supporting_ref],
        'supportingSourceProofs': [proof], 'lectureAnchorRefs': [lecture_ref]}


@pytest.mark.parametrize('purpose', ['exam', 'flashcards'])
@pytest.mark.parametrize('untaught', [True, False])
def test_supporting_proof_requires_taught_operation_but_allows_hypothetical_givens(monkeypatch, purpose, untaught):
    reader, calls = original_reader(monkeypatch, ['A tree has nodes. Tree edges equal nodes minus one.'],
        lambda task, evidence: 'UNTaught operation' not in task['text'])
    lecture_ref = reader.scope['allowedRefs'][0]
    checked = packet()
    checked['scopeSnapshot']['scopeRevision'] = reader.scope['scopeRevision']
    supporting_ref = {'kind': 'historical_exam', 'materialId': 'paper',
                      'sourceRevision': 'c' * 64, 'unitId': 'u1'}
    original = ('Trees. UNTaught operation requires an extra method.' if untaught else
                'Trees. In this hypothetical example there are seven nodes.')
    proof = {'type': 'text_span', 'ref': supporting_ref, 'field': 'text',
             'start': 0, 'end': len(original), 'quote': original}
    anchor = {'type': 'text_span', 'ref': lecture_ref, 'field': 'text',
              'start': 0, 'end': 6, 'quote': 'A tree'}
    finding = {'relation': 'lecture_supported', 'supportingSourceProofs': [proof],
               'lectureSupportProofs': [anchor]}
    checked['academicItems'] = [{'materialIdentity': checked['snapshot']['materials'][0]['identity'],
        'supportingSourceProofs': [proof], 'alignment': {'requirements': [finding]}}]
    class SupportingLibrary:
        def read_refs(self, identity, refs):
            return [{'unitId': 'u1', 'text': original, 'visualText': '', 'visualAssets': []}]
        def load_report(self, identity, revision):
            return {'sourceRevision': 'c' * 64,
                'scopeSnapshot': {'scopeRevision': reader.scope['scopeRevision']},
                'items': checked['academicItems']}
    # Independent supplement verification honestly succeeds: the extra method is
    # in the original, and its topic has a real related lecture anchor.
    supporting_tasks = []
    def supporting_judgment(batch, *, policy, task):
        supporting_tasks.append(deepcopy(task))
        return {'supported': True, 'anchored': True}, []
    monkeypatch.setattr(reader, 'read_original_batch', supporting_judgment)
    verifier = SupportingOutputVerifier(reader, SupportingLibrary())
    prompt = ('Perform the UNTaught operation on a tree.' if untaught else
              'In a hypothetical tree of seven nodes, find its edge count.')
    answer = ('Apply the UNTaught operation.' if untaught else
              'The taught rule gives seven minus one, so there are six edges.')
    if purpose == 'exam':
        tex, rubric = exam([lecture_ref], written=True)
        tex = tex.replace('Explain the graph edge rule.', prompt)
        rubric['questions']['q1'].update(criteria=answer, sourceRefs=[],
                                         supportingSourceRefs=[supporting_ref])
        rubric['provenance'][1:] = [supporting_claim('/questions/q1/' + field,
            lecture_ref, supporting_ref, proof) for field in ('text', 'criteria')]
        action = lambda: verifier.verify_exam(tex, rubric, packet=checked)
    else:
        card = {'front': prompt, 'back': answer,
            'topic': 'Trees', 'sourceRefs': [], 'supportingSourceRefs': [supporting_ref],
            'provenance': [supporting_claim('/' + field, lecture_ref, supporting_ref, proof)
                           for field in ('front', 'back', 'topic')]}
        action = lambda: verifier.verify_rows([card], packet=checked, purpose='flashcards')
    if untaught:
        with pytest.raises(ValueError, match='(?i)verif|lecture|support'):
            action()
    else:
        action()
    assert supporting_tasks
    assert all('academicContext' in task for task in supporting_tasks)
    joint = [data for data in calls if 'question' in data['task']['row'] or 'front' in data['task']['row']]
    assert joint


def generated(purpose):
    ref = {'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}
    if purpose == 'flashcards':
        row = {'front': 'Root?', 'back': 'First node.', 'topic': 'Trees', 'examLikelihood': 'high',
            'sourceRefs': [ref], 'supportingSourceRefs': [], 'provenance': [
                lecture_claim('/' + field, [ref]) for field in ('front', 'back', 'topic')]}
        return {'cards': [row]}
    return {'title': 'Trees', 'overview': 'Trees have nodes.', 'sections': [{
        'heading': 'Roots', 'content': 'A root is the first node.', 'keyPoints': [],
        'examLikelihood': 'high', 'examWeight': 100, 'sourceRefs': [ref]}],
        'keyTerms': [{'term': 'Root', 'definition': 'First node.', 'sourceRefs': [ref]}],
        'examFocus': [], 'sourceRefs': [ref], 'supportingSourceRefs': [], 'provenance': [
            lecture_claim(path, [ref]) for path in ('/overview', '/sections/0/heading',
                '/sections/0/content', '/keyTerms/0/term', '/keyTerms/0/definition')]}


@pytest.mark.parametrize('target', ['card', 'section', 'term', 'rubric'])
def test_verifier_rejects_retained_extra_academic_fields(target):
    class Reader:
        def validate_refs(self, refs): return refs
        def verify_rows(self, rows, **kwargs): return rows
    verifier = SupportingOutputVerifier(Reader(), None)
    if target == 'rubric':
        tex, rubric = exam([{'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}])
        rubric['questions']['q1']['workedExample'] = 'UNTaught academic assertion'
        action = lambda: verifier.verify_exam(tex, rubric, packet=packet())
    else:
        purpose = 'flashcards' if target == 'card' else 'summary'
        data = generated(purpose)
        row = data['cards'][0] if target == 'card' else data
        nested = row if target == 'card' else row['sections' if target == 'section' else 'keyTerms'][0]
        nested['explanation'] = 'UNTaught academic assertion'
        action = lambda: verifier.verify_rows([row], packet=packet(), purpose=purpose)
    with pytest.raises(ValueError, match='(?i)field|extra|unsupported|academic'):
        action()


@pytest.mark.parametrize('kind', ['summary', 'flashcards'])
@pytest.mark.parametrize('invalid', ['extra', 'section_extra', 'selector', 'citation', 'offset', 'proof'])
def test_structured_generation_retries_malformed_provenance_and_unchecked_fields(monkeypatch, kind, invalid):
    from src.agents import exam_generator, summary_generator
    module = summary_generator if kind == 'summary' else exam_generator
    cls = summary_generator.SummaryGeneratorAgent if kind == 'summary' else exam_generator.ExamGeneratorAgent
    agent = cls.__new__(cls)
    agent.client, agent.model_id = object(), 'fake'
    valid = generated(kind)
    bad = deepcopy(valid)
    row = bad if kind == 'summary' else bad['cards'][0]
    claim = row['provenance'][0]
    if invalid == 'extra':
        (row['keyTerms'][0] if kind == 'summary' else row)['explanation'] = 'UNTaught assertion'
    elif invalid == 'section_extra':
        (row['sections'][0] if kind == 'summary' else row)['workedExample'] = 'UNTaught assertion'
    elif invalid == 'selector': claim['path'] = '/broken~escape'
    elif invalid == 'citation': claim['sourceRefs'][0]['privatePath'] = 'private'
    elif invalid == 'offset': claim['start'], claim['end'] = 0, 2
    elif invalid == 'proof': claim['supportingSourceProofs'] = [{'type': 'text_span', 'ref': {}, 'quote': 'bad'}]
    returned = iter([bad, valid])
    monkeypatch.setattr(module, 'chat_with_retry', lambda *a, **kw: response(next(returned)))
    result = (agent.generate_summary({}, [], supporting_context=packet()) if kind == 'summary'
              else agent.generate_flashcards({}, [], count=1, supporting_context=packet()))
    assert result == (valid if kind == 'summary' else valid['cards'])


def test_supporting_exam_generator_rejects_unchecked_rubric_extras_during_parse(monkeypatch):
    from src.agents import exam_generator
    tex, rubric = exam([{'documentId': 'lecture', 'sourceRevision': 'f' * 64, 'unitId': 'u1'}])
    rubric['questions']['q1']['workedExample'] = 'UNTaught assertion'
    raw = tex + '<secret-rubrics>' + json.dumps(rubric) + '</secret-rubrics>'
    agent = exam_generator.ExamGeneratorAgent.__new__(exam_generator.ExamGeneratorAgent)
    agent.client, agent.model_id = object(), 'fake'
    monkeypatch.setattr(exam_generator, 'chat_with_retry', lambda *a, **kw: SimpleNamespace(
        choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=raw))]))
    with pytest.raises(ValueError, match='(?i)field|extra|unsupported'):
        agent.compile_enhanced_exam({}, [], '', 'generated', supporting_context=packet())


def test_no_packet_legacy_generator_preserves_existing_optional_fields(monkeypatch):
    from src.agents import exam_generator
    data = generated('flashcards')
    data['cards'][0]['explanation'] = 'Legacy optional explanation'
    data['cards'][0].pop('provenance')
    agent = exam_generator.ExamGeneratorAgent.__new__(exam_generator.ExamGeneratorAgent)
    agent.client, agent.model_id = object(), 'fake'
    monkeypatch.setattr(exam_generator, 'chat_with_retry', lambda *a, **kw: response(data))
    assert agent.generate_flashcards({}, [], count=1) == data['cards']
