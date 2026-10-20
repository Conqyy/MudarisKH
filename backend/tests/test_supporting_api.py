"""Authenticated supporting reads expose compact, exact versioned projections."""
from copy import deepcopy
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest


def _auth(monkeypatch, api):
    api.app.dependency_overrides[api.require_uid] = lambda: "owner"
    monkeypatch.setattr(api, "_require_course", lambda course_id, uid, allow_deleting=False: {"id": course_id, "userId": uid})


def test_supporting_status_has_only_public_progress_fields(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    api.supporting_library = MagicMock()
    api.supporting_library.public_status.return_value = {
        "materialId": "m", "kind": "tutorial", "status": "processing", "stage": "extracting",
        "progress": {"completedUnits": 2, "totalUnits": 4, "completedRequirements": 0, "totalRequirements": None},
        "sourceRevision": None, "reportRevision": None, "scopeRevision": None,
        "coverage": None, "legacy": False, "stale": False, "errorMessage": None,
    }
    api.db_client.get_tutorial.return_value = {"id": "m", "userId": "owner", "courseId": "course"}
    with TestClient(api.app) as client:
        response = client.get("/api/supporting/tutorial/m/status?course_id=course")
    assert response.status_code == 200
    assert response.json()["progress"] == {
        "completedUnits": 2, "totalUnits": 4,
        "completedRequirements": 0, "totalRequirements": None,
    }
    assert "cursor" not in response.json() and "analysisId" not in response.json()
    api.app.dependency_overrides.clear()


def test_source_echoes_complete_typed_reference(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    revision = "a" * 64
    api.db_client.get_tutorial.return_value = {"id": "m", "userId": "owner", "courseId": "course"}
    api.supporting_library = MagicMock()
    api.supporting_library.read_refs.return_value = [{
        "unitId": "p0001", "position": 1, "kind": "page", "text": "proof",
        "visualText": "", "visualAssets": [], "disposition": "readable", "timing": None,
    }]
    with TestClient(api.app) as client:
        response = client.get(f"/api/supporting/tutorial/m/source?course_id=course&revision={revision}&unit_id=p0001")
    assert response.status_code == 200
    assert response.json()["ref"] == {
        "kind": "tutorial", "materialId": "m", "sourceRevision": revision, "unitId": "p0001",
    }
    api.app.dependency_overrides.clear()


def test_pdf_source_exposes_verified_original_page_locator(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    api.db_client.get_historical_exam.return_value = {
        'id': 'm', 'userId': 'owner', 'courseId': 'course'}
    api.supporting_library = MagicMock()
    api.supporting_library.read_refs.return_value = [{
        'unitId': 'p0007', 'position': 7, 'kind': 'page', 'text': '',
        'visualText': '', 'visualAssets': [], 'disposition': 'readable', 'timing': None}]
    api.supporting_library.load_source.return_value = {'fileType': 'pdf'}
    with TestClient(api.app) as client:
        response = client.get('/api/supporting/historical_exam/m/source?course_id=course&revision=' +
                              'a'*64 + '&unit_id=p0007')
    assert response.status_code == 200
    assert response.json()['originalPage'] == 7
    api.app.dependency_overrides.clear()


def test_legacy_worker_failure_update_requests_atomic_legacy_fence(api_module, monkeypatch):
    api = api_module
    api.db_client.get_audio_recording.return_value = {
        'id': 'm', 'userId': 'owner', 'courseId': 'course'}
    api.db_client.audio_job_exists.return_value = True
    monkeypatch.setattr(api, '_require_document_foundation', lambda *args: (_ for _ in ()).throw(
        api.HTTPException(status_code=409, detail='locked')))
    assert api._run_audio_pipeline('m', 'course') is False
    assert api.db_client.update_audio_recording.call_args.kwargs['expected_legacy_audio'] is True


def test_report_page_requires_owned_exact_revision_and_caps_limit(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    api.db_client.get_historical_exam.return_value = {"id": "m", "userId": "owner", "courseId": "course"}
    api.supporting_library = MagicMock()
    api.supporting_library.report_page.side_effect = ValueError("Exact supporting version is unavailable")
    with TestClient(api.app) as client:
        foreign = client.get("/api/supporting/historical_exam/m/report?course_id=course&revision=" + "f" * 64)
        oversized = client.get("/api/supporting/historical_exam/m/report?course_id=course&revision=" + "a" * 64 + "&limit=101")
    assert foreign.status_code == 404
    assert oversized.status_code == 422
    api.app.dependency_overrides.clear()


def test_original_read_returns_exact_adopted_bytes_without_current_foundation(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    revision = "a" * 64
    api.db_client.get_tutorial.return_value = {
        "id": "m", "userId": "owner", "courseId": "course"}
    api.supporting_library = MagicMock()
    api.supporting_library.load_source.return_value = {"fileType": "pdf"}
    api.supporting_library.original_bytes.return_value = b"%PDF-1.4 exact adopted bytes"
    with TestClient(api.app) as client:
        response = client.get(
            f"/api/supporting/tutorial/m/original?course_id=course&revision={revision}")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 exact adopted bytes"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers['content-disposition'].startswith('inline;')
    api.supporting_library.original_bytes.assert_called_once_with({
        "userId": "owner", "courseId": "course", "kind": "tutorial", "materialId": "m"}, revision)
    api.app.dependency_overrides.clear()


@pytest.mark.parametrize('kind,file_type,body,mime,extension', [
    ('historical_exam', 'image', b'\xff\xd8\xff\xe0' + b'jpeg', 'image/jpeg', '.jpg'),
    ('audio', 'audio', b'RIFF\x04\x00\x00\x00WAVEfmt ', 'audio/wav', '.wav'),
    ('audio', 'audio', b'unknown exact bytes', 'application/octet-stream', '.bin'),
])
def test_original_read_labels_verified_bytes_honestly(api_module, monkeypatch, kind, file_type,
                                                      body, mime, extension):
    api = api_module
    _auth(monkeypatch, api)
    row = {'id': 'm', 'userId': 'owner', 'courseId': 'course', 'audioExt': 'mp3'}
    getter = api.db_client.get_historical_exam if kind == 'historical_exam' else api.db_client.get_audio_recording
    getter.return_value = row
    api.supporting_library = MagicMock()
    api.supporting_library.load_source.return_value = {'fileType': file_type}
    api.supporting_library.original_bytes.return_value = body
    with TestClient(api.app) as client:
        response = client.get('/api/supporting/' + kind + '/m/original?course_id=course&revision=' + 'a'*64)
    assert response.status_code == 200
    assert response.content == body and response.headers['content-type'] == mime
    assert response.headers['content-disposition'].endswith(f'm{extension}"')
    if mime.startswith(('image/', 'audio/')):
        assert response.headers['content-disposition'].startswith('inline;')
    api.app.dependency_overrides.clear()


def test_managed_list_projection_does_not_expose_private_row_fields(api_module, monkeypatch):
    api = api_module
    monkeypatch.setattr(api, "_require_course", lambda course_id, uid: {
        "id": course_id, "userId": uid})
    monkeypatch.setattr(api.db_client, "get_course_tutorials", lambda course_id, user_id=None: [{
        "id": "m", "userId": "owner", "courseId": "course", "title": "Practice",
        "storagePath": "tutorials/owner/course/private.pdf", "fileUrl": "private://url",
        "processingJob": {"claimToken": "secret"}, "supportingAnalysis": {"version": 1},
    }])
    api.supporting_library = MagicMock()
    api.supporting_library.public_status.return_value = {
        "materialId": "m", "kind": "tutorial", "status": "processing", "stage": "extracting",
        "progress": {"completedUnits": 1, "totalUnits": 2,
            "completedRequirements": 0, "totalRequirements": None},
        "sourceRevision": None, "reportRevision": None, "scopeRevision": None,
        "coverage": None, "legacy": False, "stale": False, "errorMessage": None,
    }
    result = api.get_course_tutorials("course", uid="owner")["tutorials"][0]
    assert result["title"] == "Practice"
    assert "storagePath" not in result and "fileUrl" not in result
    assert "processingJob" not in result and "supportingAnalysis" not in result


@pytest.mark.parametrize('route,method,kind', [
    ('/api/historical-exams/course', 'get_course_historical_exams', 'historical_exam'),
    ('/api/tutorials/course', 'get_course_tutorials', 'tutorial'),
    ('/api/audio/course', 'get_course_audio_recordings', 'audio'),
])
def test_compact_lists_preserve_safe_identity_and_job_aliases(api_module, monkeypatch, route, method, kind):
    api = api_module
    _auth(monkeypatch, api)
    getter = {'historical_exam': 'get_course_historical_exams',
              'tutorial': 'get_course_tutorials', 'audio': 'get_course_audio_recordings'}[kind]
    monkeypatch.setattr(api.db_client, getter, lambda course_id, user_id=None: [{
        'id': 'm', 'userId': 'owner', 'courseId': 'course', 'title': 'Saved',
        'processingJob': {'id': 'opaque-job', 'claimToken': 'secret'},
        'supportingAnalysis': {'version': 1}, 'storagePath': 'private/path',
        'analysis': {'private': 'large'}, 'insights': {'private': 'large'},
    }])
    api.supporting_library = MagicMock()
    api.supporting_library.public_status.return_value = {
        'materialId': 'm', 'kind': kind, 'jobId': 'opaque-job', 'status': 'processing',
        'stage': 'extracting', 'progress': {}, 'sourceRevision': None,
        'reportRevision': None, 'scopeRevision': None, 'coverage': None,
        'legacy': False, 'stale': False, 'errorMessage': None}
    with TestClient(api.app) as client:
        response = client.get(route)
    assert response.status_code == 200
    item = next(value for value in response.json().values() if isinstance(value, list))[0]
    assert (item['id'], item['courseId'], item['materialId'], item['jobId']) == (
        'm', 'course', 'm', 'opaque-job')
    assert not {'storagePath', 'analysis', 'insights', 'processingJob', 'claimToken'} & set(item)
    api.app.dependency_overrides.clear()


@pytest.mark.parametrize('kind,getter,payload', [
    ('historical_exam', 'get_historical_exam', {'analysis': {'topicWeights': [{'topic': 'Trees'}]}}),
    ('tutorial', 'get_tutorial', {'analysis': {'problems': [{'text': 'Explain trees'}]}}),
    ('notes', 'get_audio_recording', {'insights': {'keyEmphasis': [{'quote': 'The lecturer said trees matter'}]},
                                      'transcript': '  The lecturer said trees matter  ', 'sourceType': 'notes'}),
])
def test_legacy_analysis_is_owned_readable_when_foundation_locked(api_module, monkeypatch, kind, getter, payload):
    api = api_module
    _auth(monkeypatch, api)
    row = {'id': 'm', 'userId': 'owner', 'courseId': 'course', 'title': 'Saved',
           'storagePath': 'private/path', 'processingJob': {'claimToken': 'secret'}, **payload}
    monkeypatch.setattr(api.db_client, getter, lambda material_id: row)
    api.supporting_repository = MagicMock()
    api.supporting_repository.get_owned.side_effect = lambda identity: row.copy()
    monkeypatch.setattr(api, '_require_document_foundation', lambda *args: (_ for _ in ()).throw(
        AssertionError('saved legacy reads must not require current foundation')))
    with TestClient(api.app) as client:
        response = client.get(f'/api/supporting/{kind}/m/legacy-analysis?course_id=course')
        wrong_course = client.get(f'/api/supporting/{kind}/m/legacy-analysis?course_id=other')
        row['userId'] = 'other'
        foreign = client.get(f'/api/supporting/{kind}/m/legacy-analysis?course_id=course')
    assert response.status_code == 200
    body = response.json()
    assert body['legacy'] is True and body['verified'] is False
    assert body['id'] == body['materialId'] == 'm' and body['courseId'] == 'course'
    assert body['title'] == 'Saved'
    for field, value in payload.items():
        assert body[field] == value
    assert not {'storagePath', 'processingJob', 'claimToken', 'userId'} & set(body)
    assert wrong_course.status_code == 404 and foreign.status_code == 404
    api.app.dependency_overrides.clear()


def test_legacy_analysis_drops_nested_internal_paths_and_claims(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    api.db_client.get_tutorial.return_value = {
        'id': 'm', 'userId': 'owner', 'courseId': 'course',
        'analysis': {'topic': 'Trees', 'storagePath': 'private/path',
                     'nested': [{'claimToken': 'secret', 'jobId': 'private-old-job', 'text': 'Keep'}]}}
    api.supporting_repository = MagicMock()
    api.supporting_repository.get_owned.return_value = api.db_client.get_tutorial.return_value
    with TestClient(api.app) as client:
        response = client.get('/api/supporting/tutorial/m/legacy-analysis?course_id=course')
    assert response.status_code == 200
    assert response.json()['analysis'] == {'topic': 'Trees', 'nested': [{'text': 'Keep'}]}
    api.app.dependency_overrides.clear()


def test_legacy_analysis_rejects_row_replaced_after_owned_lookup(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    api.db_client.get_tutorial.return_value = {'id': 'm', 'userId': 'owner', 'courseId': 'course'}
    api.supporting_repository = MagicMock()
    api.supporting_repository.get_owned.side_effect = api.DataConflict('material changed')
    with TestClient(api.app) as client:
        response = client.get('/api/supporting/tutorial/m/legacy-analysis?course_id=course')
    assert response.status_code == 404
    api.app.dependency_overrides.clear()


def test_prepare_returns_accepted_job_metadata(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    api.db_client.get_audio_recording.return_value = {
        "id": "m", "userId": "owner", "courseId": "course", "sourceType": "notes",
    }
    api.supporting_workflow = MagicMock()
    api.supporting_workflow.prepare.return_value = {
        "materialId": "m", "kind": "notes", "status": "queued", "stage": "queued",
        "progress": {"completedUnits": 0, "totalUnits": None, "completedRequirements": 0, "totalRequirements": None},
        "sourceRevision": None, "reportRevision": None, "scopeRevision": None,
        "coverage": None, "legacy": False, "stale": False, "errorMessage": None,
    }
    api._supporting_runner = MagicMock()
    with TestClient(api.app) as client:
        response = client.post("/api/supporting/notes/m/prepare?course_id=course")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    api.app.dependency_overrides.clear()


def test_default_all_selection_surfaces_legacy_instead_of_filtering_it(api_module, monkeypatch):
    api = api_module
    api.supporting_workflow = MagicMock()
    api._supporting_runner = MagicMock()
    monkeypatch.setattr(api.db_client, "get_course_historical_exams", lambda course_id, user_id=None: [
        {"id": "legacy", "userId": "owner", "courseId": "course", "status": "completed",
         "storagePath": "historical_exams/owner/course/original.pdf"},
    ])
    monkeypatch.setattr(api.db_client, "get_course_tutorials", lambda course_id, user_id=None: [])
    monkeypatch.setattr(api.db_client, "get_course_audio_recordings", lambda course_id, user_id=None: [])
    with pytest.raises(api.HTTPException) as exc:
        api._require_selected_supporting_ready("course", "owner",
            historical_exam_ids=None, tutorial_ids=[], audio_ids=[])
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "supporting_upgrade_required"
    assert exc.value.detail["materials"][0]["materialId"] == "legacy"
    assert exc.value.detail["materials"][0]["queued"] is True
    api.supporting_workflow.prepare.assert_called_once_with({
        "userId": "owner", "courseId": "course", "kind": "historical_exam",
        "materialId": "legacy"}, retry=True)


def test_explicit_empty_selection_supplies_no_supporting_material(api_module, monkeypatch):
    api = api_module
    monkeypatch.setattr(api.db_client, "get_course_historical_exams", lambda course_id, user_id=None: [
        {"id": "legacy", "userId": "owner", "courseId": "course", "status": "completed"},
    ])
    monkeypatch.setattr(api.db_client, "get_course_tutorials", lambda course_id, user_id=None: [])
    monkeypatch.setattr(api.db_client, "get_course_audio_recordings", lambda course_id, user_id=None: [])
    assert api._require_selected_supporting_ready("course", "owner",
        historical_exam_ids=[], tutorial_ids=[], audio_ids=[]) is None


def test_completed_material_from_old_foundation_is_requeued_and_rejected(api_module, monkeypatch):
    api = api_module
    row = {"id": "old", "userId": "owner", "courseId": "course", "status": "completed",
        "storagePath": "tutorials/owner/course/original.pdf", "originalDigest": "d" * 64,
        "processingJob": {"foundationRevision": "a" * 64},
        "supportingAnalysis": {"version": 1, "state": "completed",
            "sourceRevision": "s" * 64, "reportRevision": "r" * 64}}
    monkeypatch.setattr(api.db_client, "get_course_historical_exams", lambda course_id, user_id=None: [])
    monkeypatch.setattr(api.db_client, "get_course_tutorials", lambda course_id, user_id=None: [row])
    monkeypatch.setattr(api.db_client, "get_course_audio_recordings", lambda course_id, user_id=None: [])
    api.supporting_workflow = MagicMock()
    api._supporting_runner = MagicMock()
    with pytest.raises(api.HTTPException) as exc:
        api._require_selected_supporting_ready("course", "owner", foundation_revision="b" * 64,
            historical_exam_ids=[], tutorial_ids=None, audio_ids=[])
    assert exc.value.status_code == 409
    assert exc.value.detail["materials"] == [{
        "materialId": "old", "kind": "tutorial", "status": "completed",
        "legacy": False, "queued": True, "guidance": "Retry, upgrade, or deselect this material"}]
    api.supporting_workflow.prepare.assert_called_once_with({
        "userId": "owner", "courseId": "course", "kind": "tutorial", "materialId": "old"}, retry=True)


def test_ambiguous_queue_response_preserves_adopted_unique_upload(api_module, monkeypatch):
    api = api_module
    identity = {"userId": "owner", "courseId": "course", "kind": "tutorial", "materialId": "m"}
    repository = MagicMock()
    repository.queue.side_effect = RuntimeError("transport lost after commit")
    api.supporting_repository = repository
    api._supporting_runner = MagicMock()
    deleted = []
    monkeypatch.setattr(api.db_client, "upload_file_to_storage", lambda body, path, user_id: "private")
    monkeypatch.setattr(api.db_client, "delete_file_from_storage", lambda path, user_id: deleted.append(path))

    from src.supporting.contracts import digest
    input_revision = digest({"identity": identity,
        "sourceDigest": __import__("hashlib").sha256(b"bytes").hexdigest(),
        "storagePath": "tutorials/owner/course/unique.pdf", "sourceUrl": None,
        "fileType": "pdf", "sourceType": None})
    repository.get_owned.return_value = {"storagePath": "tutorials/owner/course/unique.pdf",
        "processingJob": {"id": "job", "inputRevision": input_revision}}
    accepted = api._queue_supporting_acceptance(identity, "f" * 64,
        {"title": "Tutorial", "fileType": "pdf"}, original_bytes=b"bytes",
        storage_path="tutorials/owner/course/unique.pdf")
    assert accepted["jobId"] == "job"
    assert deleted == []


def test_unverifiable_queue_response_preserves_unique_upload(api_module, monkeypatch):
    api = api_module
    identity = {"userId": "owner", "courseId": "course", "kind": "tutorial", "materialId": "m"}
    repository = MagicMock()
    repository.queue.side_effect = RuntimeError("transport lost after commit")
    repository.get_owned.side_effect = RuntimeError("read transport unavailable")
    api.supporting_repository = repository
    api._supporting_runner = MagicMock()
    deleted = []
    monkeypatch.setattr(api.db_client, "upload_file_to_storage", lambda body, path, user_id: "private")
    monkeypatch.setattr(api.db_client, "delete_file_from_storage", lambda path, user_id: deleted.append(path))
    with pytest.raises(RuntimeError, match="transport"):
        api._queue_supporting_acceptance(identity, "f" * 64,
            {"title": "Tutorial", "fileType": "pdf"}, original_bytes=b"bytes",
            storage_path="tutorials/owner/course/unique.pdf")
    assert deleted == []


def test_confirmed_queue_rejection_compensates_unique_upload(api_module, monkeypatch):
    api = api_module
    identity = {"userId": "owner", "courseId": "course", "kind": "tutorial", "materialId": "m"}
    repository = MagicMock()
    repository.queue.side_effect = api.DataConflict("queue rejected")
    repository.get_owned.side_effect = api.DataConflict("material absent")
    api.supporting_repository = repository
    deleted = []
    monkeypatch.setattr(api.db_client, "upload_file_to_storage", lambda body, path, user_id: "private")
    monkeypatch.setattr(api.db_client, "delete_file_from_storage", lambda path, user_id: deleted.append(path))
    with pytest.raises(api.DataConflict, match="queue rejected"):
        api._queue_supporting_acceptance(identity, "f" * 64,
            {"title": "Tutorial", "fileType": "pdf"}, original_bytes=b"bytes",
            storage_path="tutorials/owner/course/unique.pdf")
    assert deleted == ["tutorials/owner/course/unique.pdf"]


def test_upload_returns_202_with_legacy_alias_and_job_identity(api_module, monkeypatch):
    api = api_module
    _auth(monkeypatch, api)
    monkeypatch.setattr(api, "_require_document_foundation", lambda course_id, uid: {
        "revision": "f" * 64, "course": {"id": course_id}, "document_insights": []})
    monkeypatch.setattr(api.db_client, "upload_file_to_storage", lambda body, path, user_id: "private")
    api.supporting_repository = MagicMock()
    api.supporting_repository.queue.return_value = {"id": "job"}
    api._supporting_runner = MagicMock()
    with TestClient(api.app) as client:
        response = client.post("/api/historical-exams/upload", headers={"Authorization": "Bearer token"},
            data={"user_id": "forged", "course_id": "course", "title": "Past"},
            files={"file": ("past.pdf", b"%PDF synthetic", "application/pdf")})
    assert response.status_code == 202
    body = response.json()
    assert body["exam_id"] == body["materialId"]
    assert body["identity"]["userId"] == "owner" and body["jobId"] == "job"
    api.app.dependency_overrides.clear()
