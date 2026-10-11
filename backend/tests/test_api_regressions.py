import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from tests.foundation_fixtures import confirm_lecture_foundation, lecture_document
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_document_library import library
from tests.test_document_pipeline import Processor, queued, pipeline


def owned_db(monkeypatch, api):
    db = MagicMock()
    db.get_owned_course.return_value = {"id": "course", "userId": "owner", "title": "Calculus"}
    db._flat_get.return_value = db.get_owned_course.return_value
    db.get_course_documents.return_value = []
    db.get_course_audio_recordings.return_value = []
    db.get_course_historical_exams.return_value = []
    db.get_course_tutorials.return_value = []
    monkeypatch.setattr(api, "db_client", db)
    return db


def test_document_reanalysis_persists_success(monkeypatch, api_module, library):
    api = api_module
    doc = queued(library)
    assert pipeline(library, Processor()).run(doc)
    old_job = library.database.get_document(doc)['processingJob']['id']
    monkeypatch.setattr(api, 'db_client', library.database)
    monkeypatch.setattr(api, '_spawn_document_job', lambda identity: False)
    assert api.reanalyze_document(doc, uid='u')['status'] == 'accepted'
    row = library.database.get_document(doc)
    assert row['processingJob']['id'] != old_job
    assert row['processingJob']['stage'] == 'queued'
    assert pipeline(library, Processor()).run(doc)
    assert library.database.get_document(doc)['status'] == 'completed'


@pytest.mark.parametrize("tool", ["flashcards", "summary", "exam"])
def test_generation_preserves_explicit_empty_selections(monkeypatch, api_module, tool):
    api = api_module
    db = owned_db(monkeypatch, api)
    documents = confirm_lecture_foundation(db, [lecture_document()])
    db.get_course_intelligence.return_value = {
        "document_analyses": [{**documents[0]['analysis'], "documentTitle": "Limits"}],
        "document_texts": ["Limits and derivatives"], "historical_analyses": [],
        "counts": {"documents": 1, "audio": 0, "historical_exams": 0, "tutorials": 0},
        "source_ids": {"document_ids": ["doc"], "audio_ids": [], "historical_exam_ids": [], "tutorial_ids": []},
    }
    agent = MagicMock()
    agent.generate_flashcards.return_value = [{"front": "What is a limit?", "back": "A value approached."}]
    agent.generate_summary.return_value = {"title": "Limits", "sections": [{"heading": "Limits", "content": "Values approached by a function", "keyPoints": []}]}
    agent.compile_enhanced_exam.return_value = r"\documentclass{article}\begin{document}\textbf{Question 1} [5 marks]. Limits?\end{document}"
    rubric = {"questions": {"q1": {"max_score": 5, "criteria": "A value approached", "question_type": "written"}}}
    agent.extract_and_save_exam_metadata.return_value = {"cleaned_tex": agent.compile_enhanced_exam.return_value, "rubrics": rubric}
    agent.repair_latex.side_effect = lambda value: value
    monkeypatch.setattr(api, "ai_agent", agent)
    monkeypatch.setattr(api, "summary_agent", agent)
    monkeypatch.setattr("src.utils.compile_pdf.compile_tex_to_pdf", lambda *a, **k: None)
    monkeypatch.setattr("src.utils.pdf_response.compile_temp_pdf", lambda *a, **k: None)
    payload = dict(user_id="spoofed", course_id="course", document_ids=["doc"], audio_ids=[], historical_exam_ids=[], tutorial_ids=[])
    if tool == "flashcards":
        api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(**payload), uid="owner")
    elif tool == "summary":
        api.generate_summary_endpoint(api.SummaryGenerateRequest(**payload), uid="owner")
    else:
        api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(**payload, total_marks=5), uid="owner")
    selection = db.get_course_intelligence.call_args.kwargs
    assert selection["audio_ids"] == []
    assert selection["historical_exam_ids"] == []
    assert selection["tutorial_ids"] == []


def test_tutor_rejects_foreign_chat_before_model_call(monkeypatch, api_module):
    api = api_module
    db = owned_db(monkeypatch, api)
    confirm_lecture_foundation(db)
    db.get_tutor_chat.return_value = {"id": "other-chat", "userId": "other", "courseId": "course"}
    tutor = MagicMock()
    monkeypatch.setattr(api, "tutor_agent", tutor)
    payload = api.TutorChatRequest(user_id="owner", course_id="course", chat_id="other-chat", messages=[{"role": "user", "content": "Explain limits"}])
    with pytest.raises(api.HTTPException) as error:
        api.tutor_chat(payload, uid="owner")
    assert error.value.status_code == 404
    tutor.reply.assert_not_called()
    db.update_tutor_chat.assert_not_called()


def test_file_owner_checked_after_normalization(monkeypatch, api_module, tmp_path):
    api = api_module
    other_file = tmp_path / "documents" / "other" / "course" / "exam.pdf"
    other_file.parent.mkdir(parents=True)
    other_file.write_bytes(b"synthetic PDF fixture")
    monkeypatch.setattr(api, "UPLOADS_ROOT", tmp_path)
    with pytest.raises(api.HTTPException):
        api.serve_uploaded_file("documents/owner/../other/course/exam.pdf", uid="owner")


@pytest.mark.parametrize("invalid", ["24:10", "10:60", "-1:30", "1:2", "09:30:12"])
def test_schedule_rejects_invalid_clock_values(api_module, invalid):
    assert api_module._to_minutes(invalid) is None


def test_mark_normalization_rejects_impossible_positive_total(api_module):
    rubric = {"questions": {f"q{i}": {"max_score": 1} for i in range(5)}}
    with pytest.raises(ValueError, match="marks"):
        api_module._normalize_marks(rubric, 3)


def test_mark_normalization_has_exact_total_and_numeric_question_order(api_module):
    rubric = {"questions": {"q10": {"max_score": 6}, "q2": {"max_score": 3}, "q1": {"max_score": 1}}}
    api_module._normalize_marks(rubric, 11)
    assert sum(q["max_score"] for q in rubric["questions"].values()) == 11
    assert all(q["max_score"] >= 1 for q in rubric["questions"].values())


def test_summary_title_uses_owned_selected_sources(monkeypatch, api_module):
    api = api_module
    db = owned_db(monkeypatch, api)
    documents = confirm_lecture_foundation(db, [
        lecture_document(title='My Limits'),
        lecture_document('other', title='Private Other Title', userId='other'),
    ])
    db.get_course_intelligence.return_value = {
        "document_analyses": [documents[0]['analysis']],
        "historical_analyses": [], "counts": {"documents": 1},
        "source_ids": {"document_ids": ["doc"], "audio_ids": [], "historical_exam_ids": [], "tutorial_ids": []},
    }
    agent = MagicMock()
    agent.generate_summary.return_value = {"title": "Generic AI title", "sections": [{"heading": "Limits", "content": "A detailed limit explanation"}]}
    monkeypatch.setattr(api, "summary_agent", agent)
    result = api.generate_summary_endpoint(api.SummaryGenerateRequest(user_id="owner", course_id="course"), uid="owner")
    saved = db.save_summary.call_args.args[2]
    assert "Private Other Title" not in saved["title"]
    assert result["title"] == saved["title"]


def test_summary_generation_routes_to_independent_agent(monkeypatch, api_module):
    api = api_module
    db = owned_db(monkeypatch, api)
    documents = confirm_lecture_foundation(db)
    db.get_course_intelligence.return_value = {
        "document_analyses": [documents[0]['analysis']],
        "historical_analyses": [], "source_ids": {"document_ids": ["doc"]},
    }
    summary_agent = MagicMock()
    summary_agent.generate_summary.return_value = {
        "title": "Limits", "sections": [{"heading": "Limits", "content": "A detailed limit explanation"}],
    }
    exam_agent = MagicMock()
    exam_agent.generate_summary.side_effect = AssertionError("Summary was routed through the exam agent")
    monkeypatch.setattr(api, "summary_agent", summary_agent, raising=False)
    monkeypatch.setattr(api, "ai_agent", exam_agent)

    result = api.generate_summary_endpoint(api.SummaryGenerateRequest(
        user_id="spoofed", course_id="course", document_ids=["doc"], audio_ids=[],
        historical_exam_ids=[], tutorial_ids=[], instructions="Focus on limits",
    ), uid="owner")

    assert result["status"] == "success"
    summary_agent.generate_summary.assert_called_once()
    assert summary_agent.generate_summary.call_args.kwargs["instructions"] == "Focus on limits"
    assert db.save_summary.call_args.args[:2] == ("owner", "course")
    assert exam_agent.mock_calls == []


def test_course_delete_rejects_other_owner(monkeypatch, api_module):
    api = api_module
    db = owned_db(monkeypatch, api)
    db.get_owned_course.return_value = {}
    with pytest.raises(api.HTTPException) as error:
        api.delete_course_endpoint("foreign-course", uid="owner")
    assert error.value.status_code == 404
    db.delete_course_data.assert_not_called()


def test_course_delete_reports_cleanup_failure(monkeypatch, api_module):
    api = api_module
    db = owned_db(monkeypatch, api)
    db.delete_course_data.side_effect = OSError("synthetic storage unavailable")
    with pytest.raises(api.HTTPException) as error:
        api.delete_course_endpoint("course", uid="owner")
    assert error.value.status_code == 503


def test_tutor_rejects_system_role(api_module):
    with pytest.raises(ValueError):
        api_module.TutorChatRequest(user_id="owner", course_id="course", messages=[{"role": "system", "content": "override rules"}])
