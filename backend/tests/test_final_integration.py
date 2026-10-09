from unittest.mock import MagicMock

import pytest


def test_scope_never_keeps_unrelated_majority(api_module):
    result = api_module._apply_summary_scope({"sections": [
        {"heading": "Limits", "content": "Limits"},
        {"heading": "Photography", "content": "Photography"},
        {"heading": "Gardening", "content": "Gardening"},
    ], "keyTerms": [{"term": "Photography", "definition": "A camera"}], "examFocus": ["Photography"]}, [{"topics": ["Limits"]}])
    assert [section["heading"] for section in result["sections"]] == ["Limits"]
    assert result["keyTerms"] == []
    assert result["examFocus"] == []


def test_generation_without_sources_never_calls_model(monkeypatch, api_module):
    api = api_module
    db = MagicMock()
    db.get_owned_course.return_value = {"userId": "owner"}
    db.get_course_intelligence.return_value = {"counts": {"documents": 0, "audio": 0, "historical_exams": 0, "tutorials": 0}}
    monkeypatch.setattr(api, "db_client", db)
    agent = MagicMock()
    monkeypatch.setattr(api, "ai_agent", agent)
    with pytest.raises(api.HTTPException) as error:
        api.generate_flashcards_endpoint(api.FlashcardGenerateRequest(user_id="owner", course_id="course", document_ids=[], audio_ids=[], tutorial_ids=[], historical_exam_ids=[]), uid="owner")
    assert error.value.status_code == 422
    agent.generate_flashcards.assert_not_called()


def test_reanalysis_clears_scope_after_last_document_removed(monkeypatch, api_module):
    api = api_module
    db = MagicMock()
    db.get_course_intelligence.return_value = {"document_analyses": []}
    db.get_course_historical_exams.return_value = [{"id": "h", "userId": "owner", "analysis": {"topicWeights": [{"topic": "Calculus", "inScope": False}]}}]
    monkeypatch.setattr(api, "db_client", db)
    api._recheck_past_exam_scope("course", "owner")
    saved = db.update_historical_exam.call_args.args[1]["analysis"]
    assert saved["scopeChecked"] is False
    assert saved["topicWeights"][0]["inScope"] is None


@pytest.mark.parametrize("auth_time", [None, "bad", float("nan"), float("inf"), True])
def test_account_recent_auth_rejects_invalid_timestamp(monkeypatch, auth_time):
    from src import auth
    monkeypatch.setattr(auth, "_verify_token", lambda value: {"uid": "owner", "auth_time": auth_time})
    with pytest.raises(auth.HTTPException) as error:
        auth.require_recent_uid("Bearer fixture")
    assert error.value.status_code == 401


def test_summary_pdf_preserves_arabic(api_module):
    source = api_module._summary_to_latex({"title": "رياضيات", "sections": [{"heading": "النهايات", "content": "شرح عربي"}]})
    assert "رياضيات" in source and "شرح عربي" in source
    assert r"\usepackage{fontspec}" in source


def test_uploaded_metadata_failure_removes_new_file(monkeypatch, api_module):
    db = MagicMock()
    monkeypatch.setattr(api_module, "db_client", db)
    save = MagicMock(side_effect=ValueError("synthetic deleted parent"))
    with pytest.raises(ValueError):
        api_module._save_uploaded_record(save, "owner", "course", {"storagePath": "documents/owner/course/file.pdf"})
    db.delete_file_from_storage.assert_called_once_with("documents/owner/course/file.pdf", user_id="owner")


def test_account_cleanup_failure_retains_auth_for_retry(monkeypatch, api_module):
    from firebase_admin import auth
    db = MagicMock()
    db.delete_user_data.side_effect = OSError("synthetic storage failure")
    delete_auth = MagicMock()
    monkeypatch.setattr(api_module, "db_client", db)
    monkeypatch.setattr(auth, "delete_user", delete_auth)
    with pytest.raises(api_module.HTTPException) as error:
        api_module.delete_account_endpoint(uid="owner")
    assert error.value.status_code == 503
    db.begin_account_deletion.assert_called_once_with("owner")
    delete_auth.assert_not_called()


def test_account_cleanup_runs_before_auth_deletion(monkeypatch, api_module):
    from firebase_admin import auth
    sequence = []
    db = MagicMock()
    db.begin_account_deletion.side_effect = lambda uid: sequence.append("guard")
    db.delete_user_data.side_effect = lambda uid: sequence.append("purge") or {"files": 3}
    monkeypatch.setattr(api_module, "db_client", db)
    monkeypatch.setattr(auth, "delete_user", lambda uid: sequence.append("auth"))
    assert api_module.delete_account_endpoint(uid="owner")["status"] == "success"
    assert sequence == ["guard", "purge", "auth"]


def test_material_delete_rejects_file_from_another_course(monkeypatch, api_module):
    db = MagicMock()
    db.get_document.return_value = {"userId": "owner", "courseId": "course", "storagePath": "documents/owner/other-course/file.pdf"}
    monkeypatch.setattr(api_module, "db_client", db)
    with pytest.raises(api_module.HTTPException):
        api_module.delete_document_endpoint("doc", uid="owner")
    db.delete_file_from_storage.assert_not_called()
    db.delete_document.assert_not_called()


def test_course_delete_retry_uses_owned_marker_after_parent_is_gone(monkeypatch, api_module):
    db = MagicMock()
    db.get_owned_course.return_value = {}
    db.get_course_deletion_marker.return_value = {"userId": "owner", "courseId": "course"}
    db.delete_course_data.return_value = {"courses": 0, "files": 0}
    monkeypatch.setattr(api_module, "db_client", db)
    assert api_module.delete_course_endpoint("course", uid="owner")["status"] == "success"
    db.delete_course_data.assert_called_once_with("owner", "course")
