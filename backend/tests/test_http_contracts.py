from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_current_api_starts_and_protects_deletion(monkeypatch, api_module):
    api = api_module
    db = MagicMock()
    db.get_pending_audio_jobs.return_value = []
    monkeypatch.setattr(api, "db_client", db)
    with TestClient(api.app) as client:
        assert client.get("/").status_code == 200
        assert client.delete("/api/account").status_code == 401
        assert client.delete("/api/courses/course").status_code == 401
        assert client.get("/api/files/serve?path=documents/owner/course/a.pdf").status_code == 401
    db.delete_user_data.assert_not_called()
    db.delete_course_data.assert_not_called()


def test_http_deletion_uses_verified_owner_and_recent_auth(monkeypatch, api_module):
    import time
    from firebase_admin import auth
    api = api_module
    db = MagicMock()
    db.get_pending_audio_jobs.return_value = []
    db.get_owned_course.return_value = {"id": "course", "userId": "owner"}
    db.delete_course_data.return_value = {"documents": 2}
    db.delete_user_data.return_value = {"courses": 1}
    monkeypatch.setattr(api, "db_client", db)
    monkeypatch.setattr(auth, "verify_id_token", lambda token, check_revoked: {"uid": "owner", "auth_time": time.time() - (600 if token == "old" else 0)})
    delete_user = MagicMock()
    monkeypatch.setattr(auth, "delete_user", delete_user)
    with TestClient(api.app) as client:
        assert client.delete("/api/account", headers={"Authorization": "Bearer old"}).status_code == 401
        assert client.delete("/api/courses/course", headers={"Authorization": "Bearer recent"}).status_code == 200
        assert client.delete("/api/account", headers={"Authorization": "Bearer recent"}).status_code == 200
    db.delete_course_data.assert_called_once_with("owner", "course")
    db.delete_user_data.assert_called_once_with("owner")
    delete_user.assert_called_once_with("owner")
