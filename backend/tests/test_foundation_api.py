import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile
from io import BytesIO
from tests.foundation_fixtures import lecture_document, install_source_artifacts


ANALYSIS = {'topics': ['AI'], 'definitions': [], 'formulas': [], 'chapterMapping': [],
            'diagrams': [], 'codeSnippets': [], 'workedExamples': [], 'keyConceptCount': 1}


@pytest.fixture
def foundation_db(monkeypatch, api_module):
    db = MagicMock()
    course = {'id': 'course', 'userId': 'owner', 'title': 'AI'}
    db.get_owned_course.return_value = course
    db.get_course_documents.return_value = []
    db.get_course_intelligence.return_value = {'document_analyses': [ANALYSIS]}
    db.get_document_foundation.return_value = {}
    def confirm(owner, course_id, revision):
        db.get_document_foundation.return_value = {'userId': owner, 'courseId': course_id, 'revision': revision}
        return True
    db.confirm_document_foundation.side_effect = confirm
    monkeypatch.setattr(api_module, 'db_client', db)
    monkeypatch.setattr(api_module, 'ai_agent', MagicMock())
    monkeypatch.setattr(api_module, 'summary_agent', MagicMock())
    monkeypatch.setattr(api_module, 'audio_agent', MagicMock())
    monkeypatch.setattr(api_module, 'tutor_agent', MagicMock())
    monkeypatch.setattr(api_module, 'hist_analyzer', MagicMock())
    monkeypatch.setattr(api_module, 'doc_processor', MagicMock())
    return db


@pytest.mark.parametrize('kind', ['past', 'tutorial', 'audio', 'notes', 'url', 'exam', 'summary', 'flashcards', 'tutor'])
def test_blocked_workflows_reject_before_upload_model_or_save(api_module, foundation_db, monkeypatch, kind):
    api, db = api_module, foundation_db
    upload = UploadFile(filename='input.pdf', file=BytesIO(b'fake'))
    upload.read = AsyncMock(side_effect=[b'fake', b''])
    spawn = MagicMock()
    monkeypatch.setattr(api, '_spawn_audio_job', spawn)
    with pytest.raises(api.HTTPException) as error:
        if kind == 'past':
            asyncio.run(api.upload_historical_exam(upload, 'owner', 'course', title='Past', uid='owner'))
        elif kind == 'tutorial':
            asyncio.run(api.upload_tutorial(upload, 'owner', 'course', title='Tutorial', uid='owner'))
        elif kind == 'audio':
            asyncio.run(api.upload_audio(upload, 'owner', 'course', title='Audio', lecture_id='', uid='owner'))
        elif kind == 'notes':
            api.upload_lecture_notes(api.LectureNotesRequest(user_id='owner', course_id='course', notes='The professor discussed AI agents and search.'), uid='owner')
        elif kind == 'url':
            api.upload_audio_from_url(api.AudioUrlRequest(user_id='owner', course_id='course', video_url='https://www.youtube.com/watch?v=demo'), uid='owner')
        elif kind == 'exam':
            api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(user_id='owner', course_id='course'), uid='owner')
        elif kind == 'summary':
            api.generate_summary_endpoint(api.SummaryGenerateRequest(user_id='owner', course_id='course'), uid='owner')
        elif kind == 'flashcards':
            api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(user_id='owner', course_id='course'), uid='owner')
        else:
            api.tutor_chat(api.TutorChatRequest(user_id='owner', course_id='course', messages=[{'role': 'user', 'content': 'Explain AI'}]), uid='owner')
    assert error.value.status_code == 409
    assert 'document' in str(error.value.detail).lower()
    upload.read.assert_not_called()
    db.upload_file_to_storage.assert_not_called()
    db.save_audio_recording.assert_not_called()
    db.save_exam_flat.assert_not_called()
    db.save_summary.assert_not_called()
    db.save_flashcard_set.assert_not_called()
    api.ai_agent.compile_enhanced_exam.assert_not_called()
    api.summary_agent.generate_summary.assert_not_called()
    api.audio_agent.analyze_transcript.assert_not_called()
    api.tutor_agent.reply.assert_not_called()
    spawn.assert_not_called()


def ready_documents(db):
    docs = [lecture_document(topic='AI', title='Introduction to AI', analysis=ANALYSIS)]
    install_source_artifacts(db, docs)
    return docs


def test_confirmation_requires_all_documents_and_current_revision(api_module, foundation_db):
    api, db = api_module, foundation_db
    docs = ready_documents(db)
    initial = api.get_course_foundation('course', uid='owner')
    assert initial['state'] == 'confirmation_required'
    assert initial['ready'] is False
    docs.append({**docs[0], 'id': 'pending', 'status': 'processing'})
    with pytest.raises(api.HTTPException) as error:
        api.confirm_course_foundation('course', api.FoundationConfirmRequest(revision=initial['revision']), uid='owner')
    assert error.value.status_code == 409
    db.confirm_document_foundation.assert_not_called()
    docs.pop()
    confirmed = api.confirm_course_foundation('course', api.FoundationConfirmRequest(revision=initial['revision']), uid='owner')
    assert confirmed['ready'] is True
    docs[0]['guideRevision'] = 'b' * 64
    assert api.get_course_foundation('course', uid='owner')['ready'] is False


def test_foundation_never_uses_documents_from_another_course_or_owner(api_module, foundation_db):
    api, db = api_module, foundation_db
    docs = ready_documents(db)
    db.get_course_documents.return_value = [{**docs[0], 'userId': 'other'}, {**docs[0], 'courseId': 'other'}]
    assert api.get_course_foundation('course', uid='owner')['state'] == 'missing'


def test_generation_rejects_empty_lecture_selection_even_with_supporting_sources(api_module, foundation_db):
    api, db = api_module, foundation_db
    ready_documents(db)
    initial = api.get_course_foundation('course', uid='owner')
    api.confirm_course_foundation('course', api.FoundationConfirmRequest(revision=initial['revision']), uid='owner')
    db.get_course_intelligence.return_value = {'historical_analyses': [{'topics': ['AI']}], 'document_analyses': []}
    with pytest.raises(api.HTTPException) as error:
        api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(user_id='owner', course_id='course', document_ids=[]), uid='owner')
    assert error.value.status_code == 422
    api.ai_agent.generate_flashcards.assert_not_called()


def test_generation_cannot_save_after_foundation_changes(api_module, foundation_db):
    api, db = api_module, foundation_db
    docs = ready_documents(db)
    initial = api.get_course_foundation('course', uid='owner')
    api.confirm_course_foundation('course', api.FoundationConfirmRequest(revision=initial['revision']), uid='owner')
    def generate(**kwargs):
        docs[0]['status'] = 'analyzing'
        return [{'front': 'AI?', 'back': 'Intelligent agents', 'topic': 'AI'}]
    api.ai_agent.generate_flashcards.side_effect = generate
    with pytest.raises(api.HTTPException) as error:
        api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(user_id='owner', course_id='course'), uid='owner')
    assert error.value.status_code == 409
    db.save_flashcard_set.assert_not_called()


def test_queued_audio_does_not_transcribe_without_ready_foundation(api_module, foundation_db):
    api, db = api_module, foundation_db
    db.get_audio_recording.return_value = {'id': 'rec', 'userId': 'owner', 'courseId': 'course'}
    db.audio_job_exists.return_value = True
    assert api._run_audio_pipeline('rec', 'course', file_bytes=b'fake', audio_ext='mp3') is False
    api.audio_agent.transcribe_audio.assert_not_called()
    api.audio_agent.analyze_transcript.assert_not_called()
    assert not any(call.args[1].get('status') == 'completed' for call in db.update_audio_recording.call_args_list)


def test_audio_analysis_uses_documents_but_cannot_complete_after_they_change(api_module, foundation_db):
    api, db = api_module, foundation_db
    docs = ready_documents(db)
    initial = api.get_course_foundation('course', uid='owner')
    api.confirm_course_foundation('course', api.FoundationConfirmRequest(revision=initial['revision']), uid='owner')
    db.get_audio_recording.return_value = {'id': 'rec', 'userId': 'owner', 'courseId': 'course',
                                         'transcript': 'The professor discussed search methods.'}
    db.audio_job_exists.return_value = True
    def analyze(*args, **kwargs):
        docs[0]['status'] = 'analyzing'
        return {'summary': 'Search methods'}
    api.audio_agent.analyze_transcript.side_effect = analyze
    assert api._run_audio_pipeline('rec', 'course') is False
    api.audio_agent.analyze_transcript.assert_called_once()
    assert api.audio_agent.analyze_transcript.call_args.kwargs['document_insights'][0]['topics'] == ['AI']
    assert not any(call.args[1].get('status') == 'completed' for call in db.update_audio_recording.call_args_list)


def test_uncached_answers_cannot_bypass_document_foundation(api_module, foundation_db, monkeypatch):
    api, db = api_module, foundation_db
    db.get_exam.return_value = {'userId': 'owner', 'courseId': 'course', 'texContent': 'exam',
                               'questionStructure': [{'id': 'q1'}]}
    answers = MagicMock(return_value='answers')
    monkeypatch.setattr(api, '_make_compilable_answer_key', answers)
    monkeypatch.setattr(api, '_compile_answer_tex', lambda *a: None)
    with pytest.raises(api.HTTPException) as error:
        api.get_exam_answer_key_pdf('exam', uid='owner')
    assert error.value.status_code == 409
    answers.assert_not_called()


def test_saved_exam_detail_remains_readable_without_triggering_ai_rescue(api_module, foundation_db):
    api, db = api_module, foundation_db
    db.get_exam.return_value = {'userId': 'owner', 'courseId': 'course', 'texContent': 'saved exam',
                               'questionStructure': [], 'rubrics': {'private': 'answer'}}
    result = api.get_exam_detail('exam', uid='owner')
    assert result['exam']['texContent'] == 'saved exam'
    assert 'rubrics' not in result['exam']
    api.ai_agent.generate_rubrics_from_tex.assert_not_called()


def test_foundation_failure_identifies_the_document_that_can_be_retried(api_module, foundation_db):
    api, db = api_module, foundation_db
    docs = ready_documents(db)
    docs[0]['guide'] = {'concepts': ['AI']}
    status = api.get_course_foundation('course', uid='owner')
    assert status['state'] == 'failed'
    assert status['failedDocumentIds'] == ['doc']
