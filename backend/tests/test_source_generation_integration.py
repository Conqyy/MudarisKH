"""Source-first publication authorization survives the last-read/write race."""
from copy import deepcopy

import pytest

from src.database.firebase_client import DataConflict
from src.utils.course_foundation import build_foundation_status
from .test_atomic_data import database, cloud_database


def material_row():
    return {'id': 'lecture', 'userId': 'u', 'courseId': 'c', 'originalDigest': 'a'*64,
            'sourceRevision': 'b'*64, 'guideRevision': 'c'*64,
            'status': 'completed', 'preparationStatus': 'completed', 'guideStatus': 'completed',
            'processingJob': {'id': 'old', 'stage': 'completed'}}


def put(db, collection, identity, row):
    if db.use_local:
        data = db._read_local_db()
        data.setdefault(collection, {})[identity] = deepcopy(row)
        db._write_local_db(data)
    else:
        db.db.rows[f'{collection}/{identity}'] = deepcopy(row)


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
@pytest.mark.parametrize('change', ['retry', 'addition', 'deletion', 'stage'])
@pytest.mark.parametrize('write', ['summary', 'exam', 'cards', 'new_chat', 'append', 'update', 'rubric'])
def test_stale_confirmation_reinsertion_cannot_authorize_any_ai_write(request, backend, change, write):
    db = request.getfixturevalue(backend)
    row = material_row()
    put(db, 'documents', 'lecture', row)
    revision = build_foundation_status([row])['revision']
    db.confirm_document_foundation('u', 'c', revision)
    exam = db.save_exam_flat('u', 'c', {'texContent': 'original'})
    # Work completed and the final API readiness reload succeeded before this race.
    if change == 'retry':
        put(db, 'documents', 'lecture', {**row, 'processingJob': {'id': 'new', 'stage': 'completed'}})
    elif change == 'stage':
        put(db, 'documents', 'lecture', {**row, 'guideStatus': 'processing'})
    elif change == 'addition':
        put(db, 'documents', 'second', {**row, 'id': 'second'})
    else:
        if db.use_local:
            data = db._read_local_db(); del data['documents']['lecture']; db._write_local_db(data)
        else:
            del db.db.rows['documents/lecture']
    # Legacy in-flight confirmation may still reinsert the old private revision.
    db.confirm_document_foundation('u', 'c', revision)
    kwargs = {'expected_foundation_revision': revision}
    with pytest.raises(DataConflict, match='[Ff]oundation|[Ll]ecture'):
        if write == 'summary': db.save_summary('u', 'c', {'title': 'late'}, **kwargs)
        elif write == 'exam': db.save_exam_flat('u', 'c', {'title': 'late'}, **kwargs)
        elif write == 'cards': db.save_flashcard_set('u', 'c', {'title': 'late'}, **kwargs)
        elif write == 'new_chat': db.save_tutor_chat('u', 'c', {'messages': []}, **kwargs)
        elif write == 'append': db.append_tutor_messages('u', 'c', 'chat', [], [
            {'role': 'user', 'content': 'q'}, {'role': 'assistant', 'content': 'a'}], 1, **kwargs)
        elif write == 'update': db.update_exam(exam, {'texContent': 'late'}, **kwargs)
        else: db.save_secret_rubrics('u', 'c', 'exam', {'questions': {}}, **kwargs)
    assert db.get_exam(exam)['texContent'] == 'original'
    assert db.get_course_summaries('c', user_id='u') == []
    assert db.get_tutor_chat('chat')['messages'] == []


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
def test_new_confirmation_rejects_changed_material_snapshot(request, backend):
    db = request.getfixturevalue(backend)
    row = material_row()
    put(db, 'documents', 'lecture', row)
    revision = build_foundation_status([row])['revision']
    put(db, 'documents', 'lecture', {**row, 'processingJob': {'id': 'new'}})
    with pytest.raises(DataConflict):
        db.confirm_document_foundation('u', 'c', revision, require_current_documents=True)
    assert db.get_document_foundation('u', 'c') == {}


@pytest.fixture
def source_api(monkeypatch, api_module):
    from unittest.mock import MagicMock
    from tests.foundation_fixtures import confirm_lecture_foundation, lecture_document
    from tests.test_source_agent_integration import response
    import json
    db = MagicMock()
    docs = confirm_lecture_foundation(db, [lecture_document(topic='ORIGINAL_FORMULA = n(n+1)/2')])
    docs[0]['analysis'] = {'topics': [], 'definitions': [], 'formulas': []}
    from src.services.document_library import DocumentLibrary
    from src.utils.source_context import resolve_source_scope
    scope = resolve_source_scope(db, DocumentLibrary(db), 'owner', 'course', None)
    db.get_course_intelligence.return_value = {
        'source_scope': scope, 'document_analyses': [], 'historical_analyses': [],
        'source_ids': {'document_ids': ['doc']}, 'counts': {'documents': 1}}
    db.get_tutor_resources.return_value = {'documents': []}
    db.save_tutor_chat.return_value = 'chat'
    monkeypatch.setattr(api_module, 'db_client', db)
    for name in ('ai_agent', 'summary_agent', 'tutor_agent', 'audio_agent', 'hist_analyzer', 'doc_processor'):
        agent = MagicMock(); agent.model_id = 'fake'
        monkeypatch.setattr(api_module, name, agent)
    captured = []
    def provider(client, **kwargs):
        captured.append(kwargs)
        data = json.loads(kwargs['messages'][1]['content'][0]['text'])
        if 'supportedSpans' in kwargs['messages'][0]['content']:
            text = data['task']['text']
            return response({'supportedSpans': [{'start': 0, 'end': len(text), 'text': text, 'reason': 'Original teaches sum.'}]})
        refs = [e['ref'] for e in data['evidence'] if e['ranges']]
        return response({'facts': [{'text': 'n(n+1)/2', 'sourceRefs': refs}], 'administrativeRefs': []})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    return api_module, db, docs, scope, captured


@pytest.mark.parametrize('kind', ['summary', 'cards', 'exam'])
def test_api_sources_do_not_require_rich_analysis_and_save_validated_provenance(source_api, monkeypatch, kind):
    api, db, docs, scope, calls = source_api
    refs = scope['allowedRefs']
    if kind == 'summary':
        api.summary_agent.generate_summary.return_value = {'title': 'Sum', 'overview': 'Sum',
            'sections': [{'heading': 'Sum', 'content': 'n(n+1)/2', 'sourceRefs': refs}], 'keyTerms': [], 'examFocus': []}
        result = api.generate_summary_endpoint(api.SummaryGenerateRequest(course_id='course', user_id='owner'), uid='owner')
        generated, saved = api.summary_agent.generate_summary, db.save_summary
        assert len(result['sections']) == 1
    elif kind == 'cards':
        api.ai_agent.generate_flashcards.return_value = [{'front': 'Sum?', 'back': 'n(n+1)/2', 'sourceRefs': refs}]
        api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(course_id='course', user_id='owner', count=1), uid='owner')
        generated, saved = api.ai_agent.generate_flashcards, db.save_flashcard_set
    else:
        tex = r'\begin{document}\textbf{Question 1:} [5 marks] Compute sum.\end{document}'
        rubrics = {'questions': {'q1': {'question_type': 'written', 'max_score': 5, 'criteria': 'n(n+1)/2', 'sourceRefs': refs}}}
        api.ai_agent.compile_enhanced_exam.return_value = tex
        api.ai_agent.extract_and_save_exam_metadata.return_value = {'cleaned_tex': tex, 'rubrics': rubrics}
        api.ai_agent.repair_latex.return_value = tex
        monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a, **kw: None)
        result = api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(course_id='course', user_id='owner', total_marks=5), uid='owner')
        generated, saved = api.ai_agent.compile_enhanced_exam, db.save_exam_flat
        assert result['question_structure'][0]['sourceRefs'] == refs
        assert 'Compute sum' in result['question_structure'][0]['text']
        assert saved.call_args.args[2]['questionIdentity']['questionRevision']
        assert db.save_secret_rubrics.call_args.kwargs['expected_foundation_revision']
    packet = generated.call_args.kwargs['lecture_evidence']
    assert packet['guide'] and 'ORIGINAL_FORMULA' in str(packet['evidence'])
    record = saved.call_args.args[2]
    assert record['sourceScope']['allowedRefs'] == refs
    assert record['sourceScope']['documents'][0]['guide'] == docs[0]['guide']
    assert record['sourceCoverage']['complete'] is True
    assert saved.call_args.kwargs['expected_foundation_revision'] == record['foundationRevision']
    assert calls


def test_tutor_fallback_stores_separate_provenance_and_reloads_exact_history(source_api):
    api, db, docs, scope, calls = source_api
    refs = scope['allowedRefs']
    api.tutor_agent.reply_grounded.return_value = {'reply': 'n(n+1)/2', 'sourceRefs': refs}
    request = api.TutorChatRequest(course_id='course', user_id='owner', document_ids=[],
                                   messages=[{'role': 'user', 'content': 'Explain sum'}])
    result = api.tutor_chat(request, uid='owner')
    assert result['sourceRefs'] == refs
    record = db.save_tutor_chat.call_args.args[2]
    assert record['sourceTurns'][0]['messageIndex'] == 1
    assert record['sourceTurns'][0]['sourceRefs'] == refs
    assert record['messages'] == [*request.messages, {'role': 'assistant', 'content': 'n(n+1)/2'}]
    db.get_tutor_chat.return_value = {**record, 'id': 'chat', 'userId': 'owner', 'courseId': 'course'}
    detail = api.get_tutor_chat_detail('chat', uid='owner')['chat']
    assert detail['sourceTurns'] == record['sourceTurns']
    request.chat_id = 'chat'
    request.messages = [*record['messages'], {'role': 'user', 'content': 'Explain again'}]
    api.tutor_chat(request, uid='owner')
    assert db.append_tutor_messages.call_args.kwargs['source_turn']['messageIndex'] == 3
    assert db.append_tutor_messages.call_args.args[3] == record['messages']
    assert db.append_tutor_messages.call_args.kwargs['expected_foundation_revision']


def test_notes_analysis_has_originals_and_fenced_publication_without_changing_professor_quote(source_api):
    api, db, docs, scope, calls = source_api
    quote = 'The sum formula is worth 8 marks.'
    api.audio_agent.analyze_transcript.return_value = {'summary': quote,
        'chapterMapping': [], 'examHints': [{'hint': 'Sum: 8 marks', 'source': quote}],
        'keyEmphasis': [{'topic': 'Sum', 'quote': quote, 'emphasisLevel': 'high'}]}
    api.upload_lecture_notes(api.LectureNotesRequest(course_id='course', user_id='owner', notes=quote), uid='owner')
    assert api.audio_agent.analyze_transcript.call_args.kwargs['lecture_evidence']['guide']
    completed = [c for c in db.update_audio_recording.call_args_list if c.args[1].get('status') == 'completed']
    assert completed[0].kwargs['expected_foundation_revision']
    assert completed[0].args[1]['insights']['keyEmphasis'][0]['quote'] == quote
    assert completed[0].args[1]['insights']['examHints'][0]['source'] == quote
    assert completed[0].args[1]['insights']['keyEmphasis'][0]['lectureRefs'] == []


def test_invalid_selected_citation_cannot_be_saved(source_api):
    api, db, docs, scope, calls = source_api
    api.ai_agent.generate_flashcards.return_value = [{'front': 'Sum?', 'back': 'n(n+1)/2',
        'sourceRefs': [{**scope['allowedRefs'][0], 'documentId': 'unselected'}]}]
    with pytest.raises(api.HTTPException) as exc:
        api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(course_id='course', user_id='owner', count=1), uid='owner')
    assert exc.value.status_code == 422
    db.save_flashcard_set.assert_not_called()


def test_tutor_social_reply_has_no_invented_citation(source_api, monkeypatch):
    api, db, docs, scope, calls = source_api
    from tests.foundation_fixtures import stub_source_provider
    from tests.test_source_agent_integration import response
    stub_source_provider(monkeypatch)
    import src.services.source_evidence as module
    original = module.chat_with_retry
    def provider(client, **kwargs):
        if 'nonAcademic' in kwargs['messages'][0]['content']:
            return response({'nonAcademic': True, 'reason': 'Only a social acknowledgement.'})
        return original(client, **kwargs)
    monkeypatch.setattr(module, 'chat_with_retry', provider)
    api.tutor_agent.reply_grounded.return_value = {'reply': 'Happy to help.', 'sourceRefs': []}
    result = api.tutor_chat(api.TutorChatRequest(course_id='course', user_id='owner',
        messages=[{'role': 'user', 'content': 'Thanks'}]), uid='owner')
    assert result['sourceRefs'] == []


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
@pytest.mark.parametrize('kind', ['cards', 'new_chat', 'append'])
def test_api_last_reload_cannot_authorize_publication_after_retry_and_old_reconfirmation(request, backend, kind, monkeypatch, api_module):
    from unittest.mock import MagicMock
    from tests.test_source_context import source_scope
    from tests.test_source_agent_integration import Library
    from tests.foundation_fixtures import stub_source_provider
    from src.services.source_evidence import SourceEvidence
    api, db = api_module, request.getfixturevalue(backend)
    row = material_row(); put(db, 'documents', 'lecture', row)
    revision = build_foundation_status([row])['revision']
    db.confirm_document_foundation('u', 'c', revision)
    scope = source_scope(['The sum is n(n+1)/2.'])
    refs = scope['allowedRefs']
    def readiness(*args, **kwargs):
        assert build_foundation_status([row])['revision'] == revision
        return {'revision': revision, 'course': {'title': 'Sum'}, 'documents': [{'id': 'lecture'}]}
    monkeypatch.setattr(api, '_require_document_foundation', readiness)
    monkeypatch.setattr(api, 'db_client', db)
    monkeypatch.setattr(api, '_source_reader', lambda *a: SourceEvidence(scope, Library(scope), 'u', 'c', object(), 'fake'))
    monkeypatch.setattr(db, 'get_course_intelligence', lambda *a, **k: {'source_scope': scope})
    monkeypatch.setattr(db, 'get_tutor_resources', lambda *a, **k: {'documents': [{'id': 'lecture'}]})
    stub_source_provider(monkeypatch)
    exam, tutor = MagicMock(), MagicMock()
    exam.generate_flashcards.return_value = [{'front': 'Sum?', 'back': 'n(n+1)/2', 'sourceRefs': refs}]
    tutor.reply_grounded.return_value = {'reply': 'n(n+1)/2', 'sourceRefs': refs}
    monkeypatch.setattr(api, 'ai_agent', exam); monkeypatch.setattr(api, 'tutor_agent', tutor)
    method = {'cards': 'save_flashcard_set', 'new_chat': 'save_tutor_chat', 'append': 'append_tutor_messages'}[kind]
    save = getattr(db, method)
    def raced(*args, **kwargs):
        put(db, 'documents', 'lecture', {**row, 'processingJob': {'id': 'retry', 'stage': 'completed'}})
        db.confirm_document_foundation('u', 'c', revision)  # old in-flight confirmation reinserts
        return save(*args, **kwargs)
    monkeypatch.setattr(db, method, raced)
    with pytest.raises((DataConflict, api.HTTPException)) as exc:
        if kind == 'cards':
            api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(course_id='c', user_id='u', count=1), uid='u')
        else:
            api.tutor_chat(api.TutorChatRequest(course_id='c', user_id='u', chat_id='chat' if kind == 'append' else '',
                messages=[{'role': 'user', 'content': 'Sum?'}]), uid='u')
    if isinstance(exc.value, api.HTTPException):
        assert exc.value.status_code == 409
    assert db.get_course_flashcard_sets('c', user_id='u') == []
    assert db.get_tutor_chat('chat')['messages'] == []


@pytest.mark.parametrize('kind', ['tutorial', 'historical', 'audio_job', 'audio_retry'])
def test_supporting_api_calls_supply_guide_original_and_atomic_publication(source_api, monkeypatch, kind):
    import asyncio
    from fastapi import UploadFile
    from io import BytesIO
    api, db, docs, scope, calls = source_api
    text = 'The original sum formula is n(n+1)/2 and is worth five marks.'
    if kind in ('tutorial', 'historical'):
        agent = api.doc_processor if kind == 'tutorial' else api.hist_analyzer
        agent.extract_text.return_value = text
        agent.extract_exam_text.return_value = text
        agent.analyze_tutorial.return_value = {'topics': [], 'problems': [], 'problemCount': 2, 'formulas': [], 'skills': []}
        agent.analyze_pdf.return_value = {'papers': [], 'topicWeights': [], 'totalQuestions': 12, 'gradingBlueprint': '5 marks each'}
        monkeypatch.setattr('src.utils.pdf_extract.pdf_to_image_uris', lambda *a: [])
        upload = UploadFile(filename='source.docx' if kind == 'tutorial' else 'source.pdf', file=BytesIO(b'synthetic'))
        if kind == 'tutorial':
            result = asyncio.run(api.upload_tutorial(upload, 'owner', 'course', title='Tutorial', uid='owner'))
            generate, update = agent.analyze_tutorial, db.update_tutorial
            assert result['analysis']['problemCount'] == 2
        else:
            result = asyncio.run(api.upload_historical_exam(upload, 'owner', 'course', title='Past', uid='owner'))
            generate, update = agent.analyze_pdf, db.update_historical_exam
            assert result['analysis']['totalQuestions'] == 12
            assert result['analysis']['gradingBlueprint'] == '5 marks each'
    else:
        db.get_audio_recording.return_value = {'id': 'recording', 'userId': 'owner', 'courseId': 'course', 'transcript': text}
        db.audio_job_exists.return_value = True
        api.audio_agent.analyze_transcript.return_value = {'summary': text, 'examHints': [], 'chapterMapping': [], 'keyEmphasis': []}
        if kind == 'audio_job':
            assert api._run_audio_pipeline('recording', 'course') is True
        else:
            assert api.reanalyze_audio_recording('recording', uid='owner')['status'] == 'success'
        generate, update = api.audio_agent.analyze_transcript, db.update_audio_recording
    packet = generate.call_args.kwargs['lecture_evidence']
    assert packet['guide'] and 'ORIGINAL_FORMULA' in str(packet['evidence'])
    completed = [c for c in update.call_args_list if c.args[1].get('status') == 'completed']
    assert len(completed) == 1
    assert completed[0].kwargs['expected_foundation_revision']


@pytest.mark.parametrize('change', ['macro', 'instruction', 'harmless'])
def test_generation_repair_cannot_change_shared_semantics(source_api, monkeypatch, tmp_path, change):
    from hashlib import sha256
    api, db, docs, scope, calls = source_api
    tex = '\\documentclass{article}\n\\newcommand{\\constant}{5}\n\\begin{document}\nUse x=5.\n\\textbf{Question 1} [5 marks] Compute x.\n\\end{document}'
    repaired = {'macro': tex.replace(r'\constant}{5}', r'\constant}{6}'),
                'instruction': tex.replace('Use x=5', 'Use x=6'),
                'harmless': tex.replace(r'\documentclass{article}', '\\documentclass[12pt]{article}\n\\usepackage{amsmath}') }[change]
    rubrics = {'questions': {'q1': {'question_type': 'written', 'max_score': 5, 'criteria': '5', 'sourceRefs': scope['allowedRefs']}}}
    api.ai_agent.compile_enhanced_exam.return_value = tex
    api.ai_agent.extract_and_save_exam_metadata.return_value = {'cleaned_tex': tex, 'rubrics': rubrics}
    api.ai_agent.repair_latex.return_value = repaired
    compiled = []
    pdf = tmp_path / 'result.pdf'; pdf.write_bytes(b'synthetic compiled PDF')
    def compile_tex(value, *args):
        compiled.append(value)
        return None if len(compiled) == 1 else str(pdf)
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', compile_tex)
    monkeypatch.setattr('src.utils.pdf_response.cleanup_temp_pdf', lambda *args: None)
    result = api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(course_id='course', user_id='owner', total_marks=5), uid='owner')
    saved = db.save_exam_flat.call_args.args[2]
    assert result['has_pdf'] is (change == 'harmless')
    assert saved['texContent'] == (repaired if change == 'harmless' else tex)
    assert saved['questionIdentity']['texRevision'] == sha256(saved['texContent'].encode()).hexdigest()
    assert len(compiled) == (2 if change == 'harmless' else 1)


@pytest.mark.parametrize('case', ['preface', 'macro', 'shared_data', 'macro_rubric_mismatch', 'valid', 'layout_only'])
def test_exam_shared_context_is_verified_before_publication(source_api, monkeypatch, case):
    """Semantic stub sees only actual provider inputs; omitted shared text used to pass."""
    import json
    from fastapi import HTTPException
    from tests.test_source_agent_integration import response
    api, db, docs, scope, calls = source_api
    shared = {
        'preface': 'Recall: the sum is n^2.',
        'macro': r'\newcommand{\formula}{n^2}',
        'shared_data': 'For every question use sum = n^2.',
        'macro_rubric_mismatch': 'Recall: the sum is n(n+1)/2.',
        'valid': 'Recall: the sum is n(n+1)/2.',
        'layout_only': r'\begin{center}Practice Exam --- Student: Example Name\end{center}',
    }[case]
    macro = shared if case == 'macro' else r'\newcommand{\formula}{n(n+1)/2}'
    preface = '' if case == 'macro' else shared
    tex = ('\\documentclass{article}\n\\usepackage{amsmath}\n' + macro +
           '\n\\begin{document}\n' + preface +
           '\n\\textbf{Question 1} [5 marks] State the sum represented by $\\formula$.\n\\end{document}')
    if case == 'macro_rubric_mismatch':
        tex = tex.replace('State the sum', 'State twice the sum')
    refs = scope['allowedRefs']
    rubrics = {'questions': {'q1': {'question_type': 'written', 'max_score': 5,
                                   'criteria': 'n(n+1)/2', 'sourceRefs': refs}}}
    api.ai_agent.compile_enhanced_exam.return_value = tex
    api.ai_agent.extract_and_save_exam_metadata.return_value = {'cleaned_tex': tex, 'rubrics': rubrics}
    api.ai_agent.repair_latex.return_value = tex
    monkeypatch.setattr('src.utils.pdf_response.compile_temp_pdf', lambda *a, **kw: None)
    judgments = []
    def provider(client, **kwargs):
        data = json.loads(kwargs['messages'][1]['content'][0]['text'])
        if 'supportedSpans' not in kwargs['messages'][0]['content']:
            return response({'facts': [{'text': 'n(n+1)/2', 'sourceRefs': refs}], 'administrativeRefs': []})
        task = data['task']; judgments.append(task)
        target = task['text']
        # The actual original teaches the sum formula, never n^2. A macro's value
        # must also reach the question check so its rubric can be interpreted.
        if 'n^2' in target or 'n^2' in task.get('sharedContext', ''):
            return response({'contradicted': True, 'supportedSpans': []})
        if 'State twice the sum' in target and 'n(n+1)/2' in task.get('sharedContext', ''):
            # Shared definition itself is true; the answer is wrong only after
            # resolving the macro and the task together.
            return response({'contradicted': True, 'supportedSpans': []})
        return response({'supportedSpans': [{'start': 0, 'end': len(target), 'text': target,
                                             'reason': 'Original sum formula; header/layout is nonacademic.'}]})
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
    request = api.EnhancedExamGenerateRequest(course_id='course', user_id='owner', total_marks=5)
    if case in ('preface', 'macro', 'shared_data', 'macro_rubric_mismatch'):
        with pytest.raises(HTTPException) as error:
            api.generate_enhanced_exam_endpoint(request, uid='owner')
        assert error.value.status_code == 422
        db.save_exam_flat.assert_not_called()
        db.save_secret_rubrics.assert_not_called()
        if case == 'macro_rubric_mismatch':
            assert any('question' in j['row'] for j in judgments)
    else:
        api.generate_enhanced_exam_endpoint(request, uid='owner')
        question_checks = [j for j in judgments if 'question' in j['row']]
        shared_checks = [j for j in judgments if 'sharedContext' in j['row']]
        assert question_checks and shared_checks
        assert all(macro in '\n'.join(json.loads(j['sharedContext'])) and
                   preface in '\n'.join(json.loads(j['sharedContext'])) for j in question_checks)
        assert shared in '\n'.join(json.loads(shared_checks[0]['text']))
        saved = db.save_exam_flat.call_args.args[2]
        assert saved['sharedSourceRefs'] == refs
        assert saved['rubrics']['sharedSourceRefs'] == refs
        assert saved['questionIdentity']['sharedContext']['sourceRefs'] == refs
        assert saved['questionIdentity']['sharedContext']['revision']
