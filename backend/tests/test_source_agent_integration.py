"""Original evidence is submitted, not inferred from guide labels or model ledgers."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from .test_source_context import source_scope


def response(value):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(value)))])


class Library:
    def __init__(self, scope): self.scope = scope
    def render_reference(self, owner, course, ref):
        unit = next(u for m in self.scope['manifests'] for u in m['units'] if u['unitId'] == ref['unitId'])
        return [f'data:image/png;base64,image{i}' for i, _ in enumerate(unit['visualAssets'])]


def test_broad_executor_accounts_every_range_blank_and_exact_rendered_asset(monkeypatch):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['ORIGINAL_FORMULA = n(n+1)/2. ' + 'academic text '*2000, '', 'Late original fact.'], visual=True)
    captured = []
    def provider(client, **kwargs):
        captured.append(kwargs['messages'])
        packet = json.loads(kwargs['messages'][1]['content'][0]['text'])
        refs = [e['ref'] for e in packet['evidence'] if e['disposition'] != 'excluded_blank']
        return response({'facts': [{'text': 'Academic fact', 'sourceRefs': refs}] if refs else [], 'administrativeRefs': []})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model', text_budget=5000)
    packet = reader.prepare('summary')
    assert len(captured) > 1
    submitted = [json.loads(messages[1]['content'][0]['text']) for messages in captured]
    for source in submitted:
        assert 'Only guide heading' in json.dumps(source['guide'])
    original = ''.join(r['text'] for p in submitted for e in p['evidence'] for r in e['ranges'] if r['textField'] == 'text')
    assert original == ''.join(u['text'] for u in scope['manifests'][0]['units'])
    assert any(part.get('image_url', {}).get('url') == 'data:image/png;base64,image0'
               for messages in captured for part in messages[1]['content'])
    assert reader.coverage()['complete'] is True
    assert reader.coverage()['excludedRefs'] == [scope['allowedRefs'][1]]
    assert reader.validate_refs([scope['allowedRefs'][0]]) == [scope['allowedRefs'][0]]
    json.dumps(packet)  # No callbacks, clients, private paths or service objects.
    assert 'ORIGINAL_FORMULA' in json.dumps(packet)
    assert 'ORIGINAL_FORMULA' not in ''.join(m[0]['content'] for m in captured)


def test_failed_provider_cannot_claim_successful_coverage_or_supply(monkeypatch):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['first '*2000, 'last original'], visual=True)
    def failed(*args, **kwargs): raise RuntimeError('provider unavailable')
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', failed)
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model', text_budget=4000)
    with pytest.raises(RuntimeError): reader.prepare('exam')
    assert reader.coverage()['complete'] is False
    with pytest.raises(ValueError): reader.validate_refs([scope['allowedRefs'][0]])


def test_model_supplied_ledger_and_wrong_image_count_are_not_authority(monkeypatch):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['formula'], visual=True)
    library = Library(scope)
    library.render_reference = lambda *args: []
    calls = []
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', lambda *args, **kwargs: calls.append(kwargs))
    reader = SourceEvidence(scope, library, 'u', 'c', object(), 'model')
    with pytest.raises(ValueError, match='image|asset'): reader.prepare('flashcards')
    assert calls == []
    assert reader.coverage()['complete'] is False


def packet():
    from src.utils.source_context import build_source_plan
    scope = source_scope(['ORIGINAL_FORMULA = n(n+1)/2.'], visual=True)
    result = build_source_plan(scope, 'exam')[0]
    result['guide'] = scope['documents']
    result['imageParts'] = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,ORIGINAL'}}]
    return result


@pytest.mark.parametrize('kind', ['audio', 'tutorial', 'historical', 'summary', 'cards', 'exam', 'tutor', 'pairs', 'rubrics', 'repair', 'answer'])
def test_each_agent_receives_original_formula_guide_and_image_in_user_content(monkeypatch, kind):
    from src.agents.audio_intelligence import AudioIntelligenceAgent
    from src.agents.document_processor import DocumentProcessorAgent
    from src.agents.historical_exam_analyzer import HistoricalExamAnalyzer
    from src.agents.summary_generator import SummaryGeneratorAgent
    from src.agents.exam_generator import ExamGeneratorAgent
    from src.agents.tutor_agent import AITutorAgent
    evidence = packet()
    ref = evidence['evidence'][0]['ref']
    rubrics = {'questions': {'q1': {'question_type': 'written', 'max_score': 5, 'criteria': 'n(n+1)/2', 'sourceRefs': [ref]}}}
    tex = r'\documentclass{article}\begin{document}\textbf{Question 1} [5 marks] Compute the sum.\end{document}'
    values = {
        'audio': {'chapterMapping': [], 'examHints': [], 'keyEmphasis': [{'topic': 'Sum', 'quote': 'verbatim', 'emphasisLevel': 'high'}], 'summary': 'Sum'},
        'tutorial': {'topics': ['Sum'], 'problems': [{'label': '1', 'statement': 'Compute n=5'}], 'formulas': [], 'skills': [], 'problemCount': 1},
        'historical': {'topicWeights': [{'topic': 'Sum', 'weight': 1.0, 'questionCount': 1}],
            'questionTypes': [{'type': 'written', 'count': 1, 'percentage': 100.0}],
            'difficultyDistribution': [{'level': 'medium', 'percentage': 100.0}],
            'gradingBlueprint': 'Five marks', 'patterns': [], 'totalQuestions': 1},
        'summary': {'title': 'Sum', 'overview': 'Sum', 'sections': [{'heading': 'Sum', 'content': 'n(n+1)/2', 'keyPoints': [], 'examLikelihood': 'low', 'examWeight': 0, 'sourceRefs': [ref]}], 'keyTerms': [], 'examFocus': []},
        'cards': {'cards': [{'front': 'Sum?', 'back': 'n(n+1)/2', 'topic': 'Sum', 'examLikelihood': 'low', 'sourceRefs': [ref]}]},
        'tutor': {'reply': 'n(n+1)/2', 'sourceRefs': [ref]},
        'pairs': {'items': [{'questionId': 'q1', 'question': 'Compute the sum.', 'answer': 'n(n+1)/2', 'explanation': '', 'sourceRefs': [ref]}]},
        'rubrics': rubrics,
    }
    types = {'audio': AudioIntelligenceAgent, 'tutorial': DocumentProcessorAgent, 'historical': HistoricalExamAnalyzer,
             'summary': SummaryGeneratorAgent, 'tutor': AITutorAgent}
    cls = types.get(kind, ExamGeneratorAgent)
    agent = cls.__new__(cls); agent.client = object(); agent.model_id = 'model'
    seen = []
    def provider(*args, **kwargs):
        seen.append(kwargs)
        if kind in ('exam', 'repair', 'answer'):
            raw = tex + '<secret-rubrics>' + json.dumps(rubrics) + '</secret-rubrics>' if kind == 'exam' else tex
            if kind == 'answer': raw = r'\textbf{Question 1} Compute the sum.\textbf{Answer:} n(n+1)/2'
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=raw))])
        return response(values[kind])
    monkeypatch.setattr(cls.__module__ + '.chat_with_retry', provider)
    kwargs = {'lecture_evidence': evidence}
    if kind == 'audio': result = agent.analyze_transcript('verbatim', 'Course', **kwargs)
    elif kind == 'tutorial': result = agent.analyze_tutorial('Exercise sum n=5', 'Course', **kwargs)
    elif kind == 'historical': result = agent.analyze_exam('Question 1 [5 marks]', 'Course', **kwargs)
    elif kind == 'summary': result = agent.generate_summary({}, [], **kwargs)
    elif kind == 'cards': result = agent.generate_flashcards({}, [], count=1, **kwargs)
    elif kind == 'exam': result = agent.compile_enhanced_exam({}, [], '', 'e', total_marks=5, **kwargs)
    elif kind == 'tutor': result = agent.reply_grounded({'course': {}}, [{'role': 'user', 'content': 'Explain sum'}], **kwargs)
    elif kind == 'pairs': result = agent.generate_answer_pairs(tex, 'e', **kwargs)
    elif kind == 'rubrics': result = agent.generate_rubrics_from_tex(tex, 'e', **kwargs)
    elif kind == 'repair': result = agent.repair_latex(tex, **kwargs)
    else: result = agent.generate_answer_key(tex, 'e', **kwargs)
    user = json.dumps([m['content'] for call in seen for m in call['messages'] if m['role'] == 'user'])
    system = json.dumps([m['content'] for call in seen for m in call['messages'] if m['role'] == 'system'])
    assert 'ORIGINAL_FORMULA' in user and 'Only guide heading' in user
    assert 'data:image/png;base64,ORIGINAL' in user
    assert 'ORIGINAL_FORMULA' not in system and 'Only guide heading' not in system
    if kind == 'pairs': assert result[0]['sourceRefs'] == [ref] and result[0]['questionId'] == 'q1'
    if kind == 'tutor': assert result == values[kind]


@pytest.mark.parametrize('unsupported_late_claim', [False, True])
def test_verification_unions_exact_supported_spans_across_original_batches(monkeypatch, unsupported_late_claim):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['First claim is taught. ' + 'x '*3000, 'Second claim is taught.'])
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model', text_budget=4500)
    def provider(client, **kwargs):
        packet = json.loads(kwargs['messages'][1]['content'][0]['text'])
        originals = ' '.join(r['text'] for e in packet['evidence'] for r in e['ranges'])
        if 'Read EVERY' in kwargs['messages'][0]['content']:
            refs = [e['ref'] for e in packet['evidence'] if e['ranges']]
            return response({'facts': [{'text': 'Academic fact', 'sourceRefs': refs}], 'administrativeRefs': []})
        target = packet['task']['text']
        spans = []
        for fact in ('First claim is taught.', 'Second claim is taught.'):
            if fact in originals and fact in target:
                start = target.index(fact)
                spans.append({'start': start, 'end': start+len(fact), 'text': fact, 'reason': 'The original states this fact.'})
        return response({'supportedSpans': spans})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    reader.prepare('summary')
    text = 'First claim is taught. Second claim is taught.' + (' Unsupported late claim.' if unsupported_late_claim else '')
    rows = [{'content': text, 'sourceRefs': scope['allowedRefs']}]
    if unsupported_late_claim:
        with pytest.raises(ValueError, match='verif|support'): reader.verify_rows(rows)
    else:
        assert reader.verify_rows(rows)[0]['content'] == text


@pytest.mark.parametrize('kind', ['mcq', 'true_false'])
def test_intentional_false_alternatives_are_verified_as_tasks_not_true_assertions(monkeypatch, kind):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['A triangle has three sides.'])
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model')
    policies = []
    def provider(client, **kwargs):
        policy = kwargs['messages'][0]['content']; policies.append(policy)
        packet = json.loads(kwargs['messages'][1]['content'][0]['text'])
        if 'Read EVERY' in policy:
            return response({'facts': [{'text': 'Three sides.', 'sourceRefs': scope['allowedRefs']}], 'administrativeRefs': []})
        assert 'NOT that every alternative is true' in policy
        text = packet['task']['text']
        return response({'supportedSpans': [{'start': 0, 'end': len(text), 'text': text, 'reason': 'The question tests triangles; the correct answer is three.'}]})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    reader.prepare('exam')
    row = {'question_type': kind, 'question': 'Choose: A triangle has three sides / four sides.',
           'correct_answer': 'Three sides', 'sourceRefs': scope['allowedRefs']}
    assert reader.verify_rows([row]) == [row]


def test_later_batch_failure_does_not_mark_partially_submitted_unit_processed(monkeypatch):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['long source '*2500])
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model', text_budget=4500)
    calls = []
    def provider(client, **kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise RuntimeError('late provider failure')
        return response({'facts': [{'text': 'Fact', 'sourceRefs': scope['allowedRefs']}], 'administrativeRefs': []})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    with pytest.raises(RuntimeError): reader.prepare('summary')
    assert reader.coverage()['successfulBatchCount'] == 1
    assert reader.coverage()['processedRefs'] == []
    assert reader.coverage()['complete'] is False


@pytest.mark.parametrize('valid', [True, False])
def test_late_diagram_is_read_and_reread_for_final_claim_verification(monkeypatch, valid):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['Early course unit. '*200, 'Middle course unit. '*200, 'Late diagram of search trees.'], visual='last')
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model', text_budget=6000)
    visual_calls = []
    def provider(client, **kwargs):
        policy = kwargs['messages'][0]['content']
        parts = kwargs['messages'][1]['content']; data = json.loads(parts[0]['text'])
        images = [p for p in parts if p['type'] == 'image_url']
        if images: visual_calls.append(policy)
        if 'Read EVERY' in policy:
            return response({'facts': [{'text': 'Original fact', 'sourceRefs': [e['ref']]} for e in data['evidence'] if e['ranges']], 'administrativeRefs': []})
        target = data['task']['text']
        return response({'supportedSpans': [{'start': 0, 'end': len(target), 'text': target, 'reason': 'Visible original diagram'}] if valid and images else []})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    packet = reader.prepare('summary')
    assert any('Read EVERY' in p for p in visual_calls)
    assert 'p0003' in str(packet['evidence'])  # synthesis has relevant windows beyond the first batch
    row = {'content': 'The diagram shows search trees.' if valid else 'The diagram proves unsupported theorem.', 'sourceRefs': [scope['allowedRefs'][-1]]}
    if valid:
        assert reader.verify_rows([row]) == [row]
    else:
        with pytest.raises(ValueError, match='verified'): reader.verify_rows([row])
    assert any('Verify the target' in p for p in visual_calls)


@pytest.mark.parametrize('valid', [True, False])
def test_exam_shared_diagram_refs_are_reread_for_question_interpretation(monkeypatch, valid):
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['Compute the tree depth.', 'The diagram shows a tree of depth two.'], visual='last')
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model')
    observed = []
    def provider(client, **kwargs):
        parts = kwargs['messages'][1]['content']; data = json.loads(parts[0]['text'])
        if 'supportedSpans' not in kwargs['messages'][0]['content']:
            return response({'facts': [{'text': 'Tree', 'sourceRefs': scope['allowedRefs']}], 'administrativeRefs': []})
        task = data['task']; observed.append((task, parts, data))
        assert data['guide']
        # Both the standalone shared claim and its use by the question require
        # the actual cited diagram, not merely the shared generated description.
        images = [p for p in parts if p['type'] == 'image_url']
        target = task['text']
        return response({'supportedSpans': [{'start': 0, 'end': len(target), 'text': target,
            'reason': 'Depth two is visible in the original diagram.'}] if valid and images else []})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    reader.prepare('exam')
    tex = (r'\begin{document}The shared tree has depth two.'
           r'\textbf{Question 1} [5 marks] Give the shared tree depth.\end{document}')
    rubrics = {'sharedSourceRefs': [scope['allowedRefs'][-1]], 'questions': {'q1': {
        'question_type': 'written', 'max_score': 5, 'criteria': 'Two.', 'sourceRefs': [scope['allowedRefs'][0]]}}}
    if valid:
        reader.verify_exam(tex, rubrics)
        assert rubrics['questions']['q1']['sourceRefs'] == scope['allowedRefs']
        assert any('question' in task['row'] for task, _, _ in observed)
    else:
        with pytest.raises(ValueError, match='verified'):
            reader.verify_exam(tex, rubrics)
    assert all(any(p['type'] == 'image_url' for p in parts) for _, parts, _ in observed)


def test_merged_analysis_keeps_one_compact_scope_snapshot_for_all_papers():
    from src.services.source_evidence import SourceEvidence
    scope = source_scope(['Original course material.'])
    reader = SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'model')
    analysis = {'totalQuestions': 9, 'papers': [{'paperId': 'p1', 'totalQuestions': 3}, {'paperId': 'p2', 'totalQuestions': 6}]}
    result = reader.tag_analysis(analysis)
    assert result['sourceScope']['allowedRefs'] == scope['allowedRefs']
    assert result['papers'] == analysis['papers']


@pytest.mark.parametrize('change', ['macro', 'instruction', 'introduced_macro', 'nested_package'])
def test_repair_preserves_shared_macros_instructions_and_data(change):
    from src.services.source_evidence import validate_exam_repair
    tex = '\\documentclass{article}\n\\newcommand{\\constant}{5}\n\\begin{document}\nUse x=5 in every question.\n\\textbf{Question 1} [5 marks] Compute x.\n\\end{document}'
    changed = {
        'macro': tex.replace(r'\constant}{5}', r'\constant}{6}'),
        'instruction': tex.replace('Use x=5', 'Use x=6'),
        'introduced_macro': tex.replace(r'\begin{document}', '\\newcommand{\\hidden}{6}\n\\begin{document}'),
        'nested_package': tex.replace(r'\constant}{5}', '\\constant}{\n\\usepackage{amsmath}\n5}'),
    }[change]
    rubrics = {'questions': {'q1': {'question_type': 'written', 'max_score': 5, 'criteria': '5', 'sourceRefs': []}}}
    with pytest.raises(ValueError, match='shared|context|preserv'):
        validate_exam_repair(tex, changed, rubrics)


def test_repair_allows_explicit_harmless_package_and_layout_fixes():
    from src.services.source_evidence import validate_exam_repair
    tex = '\\documentclass{article}\n\\newcommand{\\constant}{5}\n\\begin{document}\nUse x=5.\n\\textbf{Question 1} [5 marks] Compute x.\n\\end{document}'
    repaired = tex.replace(r'\documentclass{article}', '\\documentclass[12pt]{article}\n\\usepackage{amsmath,amssymb}\n\\setlength{\\parindent}{0pt}')
    rubrics = {'questions': {'q1': {'question_type': 'written', 'max_score': 5, 'sourceRefs': []}}}
    assert validate_exam_repair(tex, repaired, rubrics) == repaired
