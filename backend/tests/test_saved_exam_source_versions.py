"""Saved outputs keep their original evidence independently of current authorization."""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_document_library import library, pdf_bytes
from tests.test_source_foundation_api import source_api, complete
from tests.test_document_pipeline import pipeline, Processor
from tests.foundation_fixtures import stub_source_provider
from src.services.source_evidence import saved_question_identity

TEX = r"""\documentclass{article}
\newcommand{\given}{2}
\begin{document}
Use the given constant.
\textbf{Question 1} [3 marks]
Compute $\given+2$. Options: A: 3; B: 4.
\end{document}"""


@pytest.fixture
def saved(source_api, library, monkeypatch):
    api, db = source_api, library.database
    doc = complete(library)
    confirm(api)
    from src.agents.exam_generator import ExamGeneratorAgent
    agent = ExamGeneratorAgent.__new__(ExamGeneratorAgent)
    agent.client, agent.model_id = object(), 'stub'
    monkeypatch.setattr(api, 'ai_agent', agent)
    stub_source_provider(monkeypatch)
    reader = api._source_reader('c', 'u', agent)
    scope = reader.snapshot()
    refs = scope['allowedRefs']
    rubrics = {'sharedSourceRefs': refs, 'questions': {'q1': {
        'question_type': 'mcq', 'max_score': 3, 'correct_answer': 'B',
        'explanation': '2+2=4', 'sourceRefs': refs}}}
    identity = saved_question_identity(TEX, rubrics)
    exam = {'examId': 'saved', 'texContent': TEX, 'rubrics': rubrics, 'totalMarks': 3,
            'sourceScope': scope, 'questionStructure': identity['questions'],
            'questionIdentity': identity, 'sharedSourceRefs': refs,
            'foundationRevision': api.get_course_foundation('c', uid='u')['revision']}
    eid = db.save_exam_flat('u', 'c', exam)
    monkeypatch.setattr('src.utils.pdf_response.pdf_file_response', lambda path, name: {'pdf': path})
    monkeypatch.setattr('src.utils.pdf_response.cleanup_temp_pdf', lambda path: None)
    return api, library, doc, eid, db.get_exam(eid)


def confirm(api):
    state = api.get_course_foundation('c', uid='u')
    api.confirm_course_foundation('c', api.FoundationConfirmRequest(revision=state['revision']), uid='u')


def test_unicode_answer_fallback_probe_serve_and_cache_use_same_engine(saved, monkeypatch):
    api, library, doc, eid, exam = saved
    exam['texContent'] = TEX.replace('Use the given constant.', 'استخدم الثابت مع x ≤ 2.')
    exam['texContent'] = exam['texContent'].replace('Compute $\\given+2$. Options: A: 3; B: 4.', 'ما هو الذكاء الاصطناعي؟')
    exam['rubrics']['questions']['q1'].update(question_type='written', criteria='محاكاة الذكاء البشري')
    identity = saved_question_identity(exam['texContent'], exam['rubrics'])
    exam.update(questionIdentity=identity, questionStructure=identity['questions'])
    library.database.update_exam(eid, exam)
    item = {'questionId': 'q1', 'question': identity['questions'][0]['text'],
            'answer': 'محاكاة الذكاء البشري', 'explanation': 'مثال مع α ≤ 2', 'sourceRefs': exam['sharedSourceRefs']}
    monkeypatch.setattr(api.ai_agent, 'generate_answer_pairs', lambda *a, **kw: [deepcopy(item)])
    compiled = []
    def compiler(tex, name, engine='pdflatex'):
        compiled.append((tex, engine))
        if 'Model Answers' not in tex:
            return None  # Force the structured, identity-checked fallback.
        return 'pdf' if engine == 'xelatex' and r'\usepackage{fontspec}' in tex else None
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', compiler)
    assert api.get_exam_answer_key_pdf(eid, uid='u') == {'pdf': 'pdf'}
    stored = library.database.get_exam(eid)
    assert stored['questionIdentity'] == exam['questionIdentity']
    assert stored['rubrics'] == exam['rubrics']
    assert stored['questionStructure'] == exam['questionStructure']
    assert 'ما هو الذكاء الاصطناعي؟' in stored['answerKeyTex']
    assert item['answer'] in stored['answerKeyTex']
    assert 'استخدم الثابت' in stored['answerKeyTex']
    assert [engine for tex, engine in compiled if 'Model Answers' in tex] == ['xelatex', 'xelatex']
    monkeypatch.setattr(api.ai_agent, 'generate_answer_pairs', lambda *a, **kw: pytest.fail('cached key regenerated'))
    assert api.get_exam_answer_key_pdf(eid, uid='u') == {'pdf': 'pdf'}
    assert compiled[-1] == (stored['answerKeyTex'], 'xelatex')


def test_answer_renderer_preserves_literal_code_and_renders_arabic_and_math():
    from src.agents.exam_generator import ExamGeneratorAgent
    from src.utils.compile_pdf import validate_tex_source
    items = [{'question': 'ما هو الذكاء الاصطناعي؟',
              'answer': 'if (x_1 <= 2) {\n  return "مرحبا"; // α ≤ ∞\n}',
              'explanation': r'Literal \input{private} is text, not a command.'}]
    original = deepcopy(items)
    tex = ExamGeneratorAgent._answers_to_latex(items, 'unicode')
    validate_tex_source(tex)
    assert items == original
    assert r'\textarabic{' in tex
    assert 'مرحبا' in tex
    assert r'\alpha' in tex and r'\leq' in tex and r'\infty' in tex
    assert r'\textbackslash{}input\{private\}' in tex
    assert r'\tracinglostchars=3' in tex


def test_answer_and_shared_code_preserve_indentation_blank_lines_and_repeated_spaces():
    import json
    from src.agents.exam_generator import ExamGeneratorAgent
    from src.utils.compile_pdf import validate_tex_source
    code = 'for i in range(3):\n    total  += i\n\n\treturn "مرحبا"'
    tex = ExamGeneratorAgent._answers_to_latex(
        [{'question': 'Keep the code.', 'answer': code}], 'spaces', shared_context=json.dumps([code]))
    validate_tex_source(tex)
    assert tex.count(r'\hphantom{~~~~}') == 4
    assert tex.count(r'\hphantom{~~}') == 2
    assert tex.count(r'\mbox{}') == 2
    assert tex.count('total') == 2 and tex.count('مرحبا') == 2


def test_multiline_answer_starts_below_label_with_one_shared_code_margin():
    from src.agents.exam_generator import ExamGeneratorAgent
    tex = ExamGeneratorAgent._answers_to_latex([
        {'question': 'Code?', 'answer': 'if x:\n    return x'},
        {'question': 'Value?', 'answer': '2'},
    ], 'code-layout')
    assert r'\textbf{Answer:}\par\smallskip {\ttfamily if x:' in tex
    assert r'\textbf{Answer:}~ 2' in tex


def replace(api, library, doc):
    raw = pdf_bytes('REPLACEMENT SENTINEL teaches unrelated content')
    db = library.database
    db.upload_file_to_storage(raw, 'documents/u/c/replaced.pdf', 'u')
    db.update_document(doc, {'storagePath': 'documents/u/c/replaced.pdf', 'originalDigest': sha256(raw).hexdigest()})
    db.start_document_job('u', 'c', doc, source_digest=sha256(raw).hexdigest())
    assert pipeline(library, Processor()).run(doc)
    confirm(api)


def test_restore_old_scope_and_guide_after_replacement(saved):
    api, library, doc, _, exam = saved
    replace(api, library, doc)
    restored = api._load_saved_exam_evidence(exam, 'u')
    assert restored['reader'].snapshot() == exam['sourceScope']
    assert 'Complete lecture about limits' in str(restored['reader'].scope['manifests'])
    assert 'REPLACEMENT SENTINEL' not in str(restored['reader'].scope)


@pytest.mark.parametrize('damage', ['original', 'manifest', 'guide', 'scope', 'refs', 'question', 'shared'])
def test_bad_saved_provenance_rejects_before_provider(saved, monkeypatch, damage):
    api, library, doc, eid, exam = saved
    if damage in ('original', 'manifest'):
        version = library.database.get_document(doc)['sourceVersions'][exam['sourceScope']['documents'][0]['sourceRevision']]
        library.database.delete_file_from_storage(version[damage + 'Path'], 'u')
    elif damage == 'guide':
        exam['sourceScope']['documents'][0]['guide']['concepts'][0]['name'] = 'tampered'
    elif damage == 'scope':
        exam['sourceScope'] = None
    elif damage == 'refs':
        exam['sourceScope']['allowedRefs'][0]['unitId'] = 'p0002'
    elif damage == 'question':
        exam['texContent'] = TEX.replace('A: 3', 'A: 9')
    else:
        exam['sharedSourceRefs'] = []
    library.database.update_exam(eid, exam)
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a: None)
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', lambda *a, **k: pytest.fail('provider before validation'))
    monkeypatch.setattr(api.ai_agent, 'repair_latex', lambda *a, **k: pytest.fail('repair before validation'))
    with pytest.raises(api.HTTPException) as error:
        api.get_exam_pdf(eid, uid='u')
    assert error.value.status_code == 409
    assert 'restore' in str(error.value.detail).lower() and 'regenerate' in str(error.value.detail).lower()


@pytest.mark.parametrize('mutation', ['layout', 'option', 'macro', 'instruction', 'marks', 'hidden'])
def test_repair_preserves_saved_payload_and_rubric(saved, monkeypatch, mutation):
    api, library, doc, eid, exam = saved
    replace(api, library, doc)
    changes = {'layout': TEX.replace('\\begin{document}', '\\usepackage{amsmath}\n\\begin{document}'),
               'option': TEX.replace('A: 3', 'A: 8'), 'macro': TEX.replace('{2}', '{9}'),
               'instruction': TEX.replace('given constant', 'different constant'),
               'marks': TEX.replace('3 marks', '4 marks'),
               'hidden': TEX + '<secret-rubrics>{"questions":{}}</secret-rubrics>'}
    seen = []
    def repair(tex, *, lecture_evidence):
        seen.append(lecture_evidence)
        assert tex == TEX
        return changes[mutation]
    monkeypatch.setattr(api.ai_agent, 'repair_latex', repair)
    attempts = iter([None, 'pdf'])
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda tex, name: next(attempts))
    if mutation == 'layout':
        assert api.get_exam_pdf(eid, uid='u') == {'pdf': 'pdf'}
        result = library.database.get_exam(eid)
        assert result['rubrics'] == exam['rubrics']
        assert result['questionStructure'] == exam['questionStructure']
        assert result['sourceScope'] == exam['sourceScope']
        assert result['foundationRevision'] == exam['foundationRevision']
        assert result['questionIdentity']['sharedContext'] == exam['questionIdentity']['sharedContext']
    else:
        with pytest.raises(api.HTTPException) as error:
            api.get_exam_pdf(eid, uid='u')
        assert error.value.status_code == 422
        assert library.database.get_exam(eid)['texContent'] == TEX
    assert seen and 'REPLACEMENT SENTINEL' not in str(seen)


@pytest.mark.parametrize('kind', ['pdf', 'cached', 'deterministic'])
def test_saved_complete_reads_work_while_locked_without_provider(saved, monkeypatch, kind):
    api, library, doc, eid, exam = saved
    library.database.start_document_job('u', 'c', doc, source_digest=library.database.get_document(doc)['originalDigest'])
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', lambda *a, **k: pytest.fail('cached read invoked provider'))
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a: 'pdf')
    if kind == 'cached':
        # The compatibility cache is available even for legacy missing scope.
        exam.pop('sourceScope')
        exam.update(answerKeyTex='legacy key', answerKeyQuestionCount=1)
        library.database.update_exam(eid, {'sourceScope': None, **exam})
    call = api.get_exam_pdf if kind == 'pdf' else api.get_exam_answer_key_pdf
    assert call(eid, uid='u') == {'pdf': 'pdf'}


def test_legacy_detail_is_read_only_and_projects_safe_fields(saved, monkeypatch):
    api, library, _, eid, exam = saved
    library.database.update_exam(eid, {'sourceScope': None, 'questionStructure': [],
        'sourceVersions': {'secret': 'private/path'}, 'solutionPath': 'private/path',
        'answerKeyTex': 'secret answers', 'texContent': TEX + '<secret-rubrics>hidden</secret-rubrics>'})
    monkeypatch.setattr(api.ai_agent, 'generate_rubrics_from_tex', lambda *a, **k: pytest.fail('detail invoked provider'))
    result = api.get_exam_detail(eid, uid='u')['exam']
    assert result['texContent'] == TEX
    assert 'private/path' not in str(result) and 'secret answers' not in str(result) and 'hidden' not in str(result)


@pytest.mark.parametrize('change', ['texContent', 'rubrics', 'sourceScope', 'sharedSourceRefs'])
def test_atomic_exam_fence_rejects_changed_inputs(saved, change):
    from src.database.firebase_client import saved_exam_revision, DataConflict
    _, library, _, eid, exam = saved
    revision = saved_exam_revision(exam)
    library.database.update_exam(eid, {change: 'concurrent change'})
    with pytest.raises(DataConflict):
        library.database.update_exam(eid, {'answerKeyTex': 'stale'}, expected_exam_revision=revision)
    assert 'answerKeyTex' not in library.database.get_exam(eid)


@pytest.mark.parametrize('damage', [None, 'id', 'question', 'answer', 'refs', 'count'])
def test_answer_pairs_require_exact_saved_mapping_and_authoritative_answers(saved, monkeypatch, damage):
    api, library, doc, eid, exam = saved
    replace(api, library, doc)
    items = [{'questionId': 'q1', 'question': exam['questionStructure'][0]['text'],
              'answer': 'B', 'explanation': '2+2=4', 'sourceRefs': exam['sharedSourceRefs']}]
    if damage == 'id': items[0]['questionId'] = 'q2'
    if damage == 'question': items[0]['question'] = 'A different question with the same number'
    if damage == 'answer': items[0]['answer'] = 'A'
    if damage == 'refs': items[0]['sourceRefs'] = [{'documentId': doc, 'sourceRevision': library.database.get_document(doc)['sourceRevision'], 'unitId': 'p0001'}]
    if damage == 'count': items *= 2
    def pairs(tex, name, *, lecture_evidence):
        assert tex == TEX
        assert 'REPLACEMENT SENTINEL' not in str(lecture_evidence)
        assert lecture_evidence['savedQuestions'] == exam['questionStructure']
        return items
    monkeypatch.setattr(api.ai_agent, 'generate_answer_pairs', pairs)
    monkeypatch.setattr(api.ai_agent, 'generate_answer_key', lambda *a, **k: pytest.fail('unmapped rich key used'))
    monkeypatch.setattr('src.utils.pdf_response.check_tex_compiles', lambda *a, **kw: True)
    # Original rubric document fails, while separately rendered verified pairs compile.
    attempts = iter([None, 'pdf'])
    monkeypatch.setattr(api, '_compile_answer_tex', lambda *a: next(attempts))
    if damage:
        with pytest.raises(api.HTTPException) as error:
            api.get_exam_answer_key_pdf(eid, uid='u')
        assert error.value.status_code == 422
        assert 'answerKeyTex' not in library.database.get_exam(eid)
    else:
        assert api.get_exam_answer_key_pdf(eid, uid='u') == {'pdf': 'pdf'}
        stored = library.database.get_exam(eid)
        assert stored['answerKeyIdentity']['questionIds'] == ['q1']
        assert stored['rubrics'] == exam['rubrics'] and stored['sourceScope'] == exam['sourceScope']
        assert stored['answerKeyIdentity']['sourceRefs'] == [{'questionId': 'q1', 'sourceRefs': exam['sharedSourceRefs']}]


@pytest.mark.parametrize('race', ['saved', 'foundation', 'deleted'])
def test_pdf_publication_rejects_race_after_last_api_check(saved, monkeypatch, race):
    api, library, doc, eid, exam = saved
    db = library.database
    monkeypatch.setattr(api.ai_agent, 'repair_latex', lambda *a, **k: TEX.replace('\\begin{document}', '\\usepackage{amsmath}\n\\begin{document}'))
    attempts = iter([None, 'pdf'])
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a: next(attempts))
    update = db.update_exam
    def race_update(identity, data, **kwargs):
        if race == 'saved': update(eid, {'texContent': TEX.replace('A: 3', 'A: 7')})
        elif race == 'deleted': db.delete_exam(eid)
        else: db.start_document_job('u', 'c', doc, source_digest=db.get_document(doc)['originalDigest'])
        return update(identity, data, **kwargs)
    monkeypatch.setattr(db, 'update_exam', race_update)
    from src.database.firebase_client import DataConflict
    with pytest.raises(DataConflict):
        api.get_exam_pdf(eid, uid='u')
    assert db.get_exam(eid).get('pdfStatus') != 'ready'


def test_new_cache_is_invalidated_by_same_count_question_change(saved, monkeypatch):
    api, library, _, eid, exam = saved
    compiled = []
    monkeypatch.setattr(api, '_compile_answer_tex', lambda tex, name: compiled.append(tex) or 'pdf')
    assert api.get_exam_answer_key_pdf(eid, uid='u') == {'pdf': 'pdf'}
    assert library.database.get_exam(eid).get('answerKeyIdentity')
    changed_tex = TEX.replace('A: 3', 'A: 7')
    identity = saved_question_identity(changed_tex, exam['rubrics'])
    library.database.update_exam(eid, {'texContent': changed_tex, 'questionIdentity': identity,
                                      'questionStructure': identity['questions']})
    compiled.clear()
    api.get_exam_answer_key_pdf(eid, uid='u')
    assert len(compiled) == 1 and 'A: 7' in compiled[0]


@pytest.mark.parametrize('path, visible', [('solutions/u/c/exam.pdf', True),
    ('documents/u/c/private.pdf', False), ('solutions/v/c/exam.pdf', False),
    ('C:/private/exam.pdf', False), ('https://cloud/private.pdf', False)])
def test_detail_preserves_only_owned_relative_solution_locator(saved, path, visible):
    api, library, _, eid, _ = saved
    library.database.update_exam(eid, {'solutionPath': path})
    detail = api.get_exam_detail(eid, uid='u')['exam']
    assert detail.get('solutionPath') == (path if visible else None)


@pytest.mark.parametrize('damage', ['tex', 'mapping', 'rubric', 'shared', 'scope'])
def test_cache_rejects_changed_identity_or_mapping(saved, monkeypatch, damage):
    api, library, _, eid, exam = saved
    monkeypatch.setattr(api, '_compile_answer_tex', lambda *a: 'pdf')
    api.get_exam_answer_key_pdf(eid, uid='u')
    stored = library.database.get_exam(eid)
    if damage == 'tex': stored['answerKeyTex'] += 'changed'
    elif damage == 'mapping': stored['answerKeyIdentity']['sourceRefs'][0]['sourceRefs'] = []
    elif damage == 'rubric': stored['rubrics']['questions']['q1']['correct_answer'] = 'A'
    elif damage == 'shared': stored['texContent'] = TEX.replace('{2}', '{9}')
    else: stored['sourceScope']['scopeRevision'] = 'b' * 64
    assert api._cached_answer_key(stored, 1) == ''


def test_malformed_cache_mapping_fails_closed(saved, monkeypatch):
    api, library, _, eid, _ = saved
    monkeypatch.setattr(api, '_compile_answer_tex', lambda *a: 'pdf')
    api.get_exam_answer_key_pdf(eid, uid='u')
    stored = library.database.get_exam(eid)
    stored['answerKeyIdentity']['sourceRefs'].append('not a mapping')
    assert api._cached_answer_key(stored, 1) == ''


def test_saved_source_pdf_compiles_exact_saved_tex_without_rewriting(saved, monkeypatch):
    api, _, _, eid, _ = saved
    compiled = []
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda tex, name: compiled.append(tex) or 'pdf')
    api.get_exam_pdf(eid, uid='u')
    assert compiled == [TEX]


@pytest.mark.parametrize('locked', [False, True])
def test_legacy_missing_scope_uncached_ai_is_actionable_without_provider(saved, monkeypatch, locked):
    api, library, doc, eid, _ = saved
    library.database.update_exam(eid, {'sourceScope': None, 'rubrics': {}})
    if locked:
        library.database.start_document_job('u', 'c', doc, source_digest=library.database.get_document(doc)['originalDigest'])
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', lambda *a, **k: pytest.fail('legacy provider call'))
    with pytest.raises(api.HTTPException) as error:
        api.get_exam_answer_key_pdf(eid, uid='u')
    assert error.value.status_code == 409 and 'regenerate' in error.value.detail.lower()


@pytest.mark.parametrize('race', ['saved', 'foundation'])
def test_answer_publication_fences_after_last_api_check(saved, monkeypatch, race):
    api, library, doc, eid, exam = saved
    db = library.database
    items = [{'questionId': 'q1', 'question': exam['questionStructure'][0]['text'],
              'answer': 'B', 'explanation': '2+2=4', 'sourceRefs': exam['sharedSourceRefs']}]
    monkeypatch.setattr(api.ai_agent, 'generate_answer_pairs', lambda *a, **k: items)
    monkeypatch.setattr('src.utils.pdf_response.check_tex_compiles', lambda *a, **kw: True)
    attempts = iter([None, 'pdf'])
    monkeypatch.setattr(api, '_compile_answer_tex', lambda *a: next(attempts))
    cleaned = []
    monkeypatch.setattr('src.utils.pdf_response.cleanup_temp_pdf', cleaned.append)
    update = db.update_exam
    def late(identity, data, **kwargs):
        if race == 'saved': update(eid, {'sharedSourceRefs': []})
        else: db.start_document_job('u', 'c', doc, source_digest=db.get_document(doc)['originalDigest'])
        return update(identity, data, **kwargs)
    monkeypatch.setattr(db, 'update_exam', late)
    from src.database.firebase_client import DataConflict
    with pytest.raises(DataConflict): api.get_exam_answer_key_pdf(eid, uid='u')
    assert 'answerKeyTex' not in db.get_exam(eid) and cleaned == ['pdf']


def test_saved_shared_context_is_verified_with_original_images_before_repair(saved, monkeypatch):
    import json
    import pymupdf
    api, library, doc, eid, exam = saved
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.draw_rect((40, 40, 200, 200))
        raw = pdf.tobytes()
    db = library.database
    db.upload_file_to_storage(raw, 'documents/u/c/diagram.pdf', 'u')
    db.update_document(doc, {'storagePath': 'documents/u/c/diagram.pdf', 'originalDigest': sha256(raw).hexdigest()})
    db.start_document_job('u', 'c', doc, source_digest=sha256(raw).hexdigest())
    assert pipeline(library, Processor()).run(doc)
    confirm(api)
    scope = api._source_reader('c', 'u', api.ai_agent).snapshot()
    exam['sourceScope'] = scope
    exam['rubrics']['sharedSourceRefs'] = exam['sharedSourceRefs'] = scope['allowedRefs']
    exam['rubrics']['questions']['q1']['sourceRefs'] = scope['allowedRefs']
    exam['questionIdentity'] = saved_question_identity(TEX, exam['rubrics'])
    exam['questionStructure'] = exam['questionIdentity']['questions']
    db.update_exam(eid, exam)
    seen = []
    def provider(client, **kwargs):
        packet = json.loads(kwargs['messages'][1]['content'][0]['text'])
        policy = kwargs['messages'][0]['content']
        if 'supportedSpans' in policy:
            seen.append(packet)
            assert 'given' in packet['task']['text']
            assert any(p.get('type') == 'image_url' for p in kwargs['messages'][1]['content'])
            result = {'supportedSpans': []}
        else:
            refs = [row['ref'] for row in packet['evidence']]
            result = {'facts': [{'text': 'limits', 'sourceRefs': refs}], 'administrativeRefs': []}
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(result)))])
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a: None)
    monkeypatch.setattr(api.ai_agent, 'repair_latex', lambda *a, **k: pytest.fail('unsupported shared context reached repair'))
    with pytest.raises(api.HTTPException) as error: api.get_exam_pdf(eid, uid='u')
    assert error.value.status_code == 422 and seen
