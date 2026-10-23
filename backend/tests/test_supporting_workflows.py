"""Durable supporting work survives saturation, restart, and stale claims."""
from concurrent.futures import Future
from copy import deepcopy
from types import SimpleNamespace
import threading
from unittest.mock import MagicMock

import pytest

from src.supporting.jobs import SupportingJobRunner
from src.supporting.workflows import SupportingWorkflow
from tests.test_supporting_job_storage import identity as stored_identity, repository
from tests.test_document_job_storage import job_db
from tests.test_atomic_data import database, cloud_database
from src.database.firebase_client import FirebaseClient
from src.supporting.library import SupportingLibrary


IDENTITY = {
    "userId": "u",
    "courseId": "c",
    "kind": "historical_exam",
    "materialId": "m",
}


class InlineExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, function, *args):
        self.calls.append((function, args))
        return Future()

    def shutdown(self, **kwargs):
        return None


def test_runner_saturation_leaves_durable_identity_recoverable():
    pending = [deepcopy(IDENTITY), {**IDENTITY, "materialId": "later"}]

    class Repository:
        def pending(self, *, now_ms, limit=100):
            return deepcopy(pending[:limit])

    executor = InlineExecutor()
    runner = SupportingJobRunner(Repository(), lambda identity: True,
                                 max_workers=1, max_pending=1, executor=executor)
    assert runner.submit(IDENTITY) is True
    assert runner.submit(pending[1]) is False
    runner.recover()
    assert len(executor.calls) == 1


def test_runner_executes_blocking_work_off_the_caller_thread():
    caller = threading.get_ident()
    finished, observed = threading.Event(), []

    def run_job(identity):
        observed.append(threading.get_ident())
        finished.set()

    runner = SupportingJobRunner(MagicMock(), run_job, max_workers=1, max_pending=1)
    try:
        assert runner.submit(IDENTITY) is True
        assert finished.wait(2)
    finally:
        runner.close()
    assert observed and observed[0] != caller


def test_checkpoint_persists_call_count_before_detached_checkpoint():
    events = []

    class Repository:
        def checkpoint(self, identity, job, *, changes, now_ms):
            events.append(("count", deepcopy(changes)))
            return True

    class Library:
        repository = Repository()

        def save_checkpoint(self, identity, job, state):
            events.append(("save", deepcopy(state)))
            return {"revision": "a" * 64}

    workflow = SupportingWorkflow(Repository(), Library(), object(), object(), lambda identity: None)
    workflow._persist_checkpoint(IDENTITY, {"id": "job"}, "aligning", {"modelCalls": 7})
    assert events[0] == ("count", {"stage": "aligning", "modelCalls": 7})
    assert events[1][0] == "save"


def test_crash_after_count_before_checkpoint_never_undercounts():
    class Repository:
        def __init__(self):
            self.calls = 4

        def checkpoint(self, identity, job, *, changes, now_ms):
            self.calls = changes["modelCalls"]
            return True

    class Library:
        def save_checkpoint(self, identity, job, state):
            raise RuntimeError("synthetic storage interruption")

    repository = Repository()
    workflow = SupportingWorkflow(repository, Library(), object(), object(), lambda identity: None)
    with pytest.raises(RuntimeError, match="storage interruption"):
        workflow._persist_checkpoint(IDENTITY, {"id": "job"}, "aligning", {"modelCalls": 5})
    assert repository.calls == 5


def test_alignment_checkpoint_keeps_separate_inventory_revision():
    changes = []

    class Repository:
        def checkpoint(self, identity, job, *, changes: dict, now_ms):
            globals_changes = deepcopy(changes)
            changes_log.append(globals_changes)
            return True

    changes_log = changes
    class Library:
        def save_checkpoint(self, identity, job, state):
            return {"revision": "b" * 64}

    workflow = SupportingWorkflow(Repository(), Library(), object(), object(), lambda identity: None)
    workflow._persist_checkpoint(IDENTITY, {"id": "job"}, "aligning", {"modelCalls": 2},
                                 inventory_revision="c" * 64)
    assert changes[-1]["inventoryRevision"] == "c" * 64
    assert changes[-1]["checkpointRevision"] == "b" * 64


def test_crash_after_direct_alignment_checkpoint_retains_inventory_pointer():
    row = {"processingJob": {"inventoryRevision": "c" * 64}}

    class Repository:
        calls = 0
        def checkpoint(self, identity, job, *, changes, now_ms):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic crash after adoption")
            row["processingJob"].update(deepcopy(changes))
            return True

    class Library:
        def save_checkpoint(self, identity, job, state):
            row["processingJob"]["checkpointRevision"] = "b" * 64
            return {"revision": "b" * 64}

    workflow = SupportingWorkflow(Repository(), Library(), object(), object(), lambda identity: None)
    with pytest.raises(RuntimeError, match="after adoption"):
        workflow._persist_checkpoint(IDENTITY, {"id": "job"}, "aligning",
            {"stage": "align", "modelCalls": 5}, inventory_revision="c" * 64)
    assert row["processingJob"]["checkpointRevision"] == "b" * 64
    assert row["processingJob"]["inventoryRevision"] == "c" * 64


def test_inventory_checkpoint_must_match_current_prepared_source():
    inventory = {"items": []}
    state = {"phase": "inventory", "sourceRevision": "a" * 64,
        "inventoryDigest": __import__("src.supporting.contracts", fromlist=["digest"]).digest(inventory),
        "inventory": inventory}
    library = SimpleNamespace(load_checkpoint=lambda identity, revision: deepcopy(state))
    workflow = SupportingWorkflow(MagicMock(), library, object(), object(), lambda identity: None)
    with pytest.raises(ValueError, match="source"):
        workflow._load_inventory(IDENTITY, "c" * 64, "b" * 64)


def test_prepare_rejects_unready_foundation_before_any_provider_call():
    class Repository:
        def get_owned(self, identity):
            return {"userId": "u", "courseId": "c", "originalDigest": "d" * 64}

        def queue(self, *args, **kwargs):
            raise AssertionError("unready material must not queue")

    called = []

    def reader_factory(identity):
        called.append(identity)
        raise ValueError("lecture foundation is not ready")

    workflow = SupportingWorkflow(Repository(), object(), object(), object(), reader_factory)
    with pytest.raises(ValueError, match="foundation"):
        workflow.prepare(IDENTITY)
    assert called == [IDENTITY]


def test_prepare_upgrades_legacy_notes_from_exact_retained_text():
    repository = MagicMock()
    repository.get_owned.return_value = {
        "userId": "u", "courseId": "c", "sourceType": "notes",
        "storagePath": "", "transcript": "  exact legacy notes  ",
    }
    repository.queue.return_value = {"id": "job"}
    reader = SimpleNamespace(scope={"foundationRevision": "f" * 64})
    workflow = SupportingWorkflow(repository, object(), object(), object(), lambda identity: reader)
    identity = {**IDENTITY, "kind": "notes"}
    accepted = workflow.prepare(identity)
    queued = repository.queue.call_args.kwargs
    assert accepted["status"] == "queued"
    assert queued["source_digest"] == __import__("hashlib").sha256(
        b"  exact legacy notes  ").hexdigest()


def test_prepare_hashes_owned_legacy_original_before_queueing(tmp_path):
    original = tmp_path / "legacy.pdf"
    original.write_bytes(b"%PDF exact legacy bytes")
    database = MagicMock()
    database.download_file_from_storage.return_value = original
    repository = MagicMock(database=database)
    repository.get_owned.return_value = {
        "userId": "u", "courseId": "c",
        "storagePath": "historical_exams/u/c/legacy.pdf",
    }
    repository.queue.return_value = {"id": "job"}
    reader = SimpleNamespace(scope={"foundationRevision": "f" * 64})
    workflow = SupportingWorkflow(repository, object(), object(), object(), lambda identity: reader)
    workflow.prepare(IDENTITY)
    assert repository.queue.call_args.kwargs["source_digest"] == __import__("hashlib").sha256(
        b"%PDF exact legacy bytes").hexdigest()
    database.download_file_from_storage.assert_called_once_with(
        "historical_exams/u/c/legacy.pdf", "u")


def test_legacy_historical_original_infers_missing_file_type():
    extractor = MagicMock()
    extractor.prepare_pages.return_value = {"sourceRevision": "s" * 64}
    workflow = SupportingWorkflow(MagicMock(), MagicMock(), extractor, object(), lambda identity: None)
    workflow._manifest(IDENTITY, {
        "storagePath": "historical_exams/u/c/unique_old-exam.pdf"},
        {"sourceDigest": "d" * 64}, b"%PDF")
    extractor.prepare_pages.assert_called_once_with(IDENTITY, b"%PDF", "pdf")


def test_repository_persists_configured_budget(repository):
    job = repository.queue(stored_identity(), input_revision="b" * 64,
        source_digest="a" * 64, foundation_revision=repository.test_foundation_revision,
        now_ms=10, initial_data={"title": "Source"}, model_call_budget=7)
    assert job["modelCallBudget"] == 7
    assert repository.get_owned(stored_identity())["processingJob"]["modelCallBudget"] == 7


def test_legacy_audio_recovery_excludes_managed_supporting_rows():
    database = SimpleNamespace(is_course_deleting=lambda course_id: False,
                               get_owned_course=lambda user_id, course_id: {"id": course_id})
    assert FirebaseClient._recoverable_audio_job(database, {
        "userId": "u", "courseId": "c", "status": "queued",
        "supportingAnalysis": {"version": 1, "state": "queued"},
    }) is False


def test_legacy_audio_worker_cannot_publish_managed_row(api_module, monkeypatch):
    api = api_module
    api.db_client.get_audio_recording.return_value = {
        "id": "managed", "courseId": "c", "supportingAnalysis": {"version": 1, "state": "queued"}}
    legacy = MagicMock()
    monkeypatch.setattr(api, "_run_audio_pipeline", legacy)
    api._run_saved_audio_job("managed")
    legacy.assert_not_called()


def test_public_status_reports_real_unit_and_requirement_progress(monkeypatch):
    row = {
        "supportingAnalysis": {"version": 1, "state": "completed", "sourceRevision": "a" * 64,
            "reportRevision": "b" * 64, "scopeRevision": "c" * 64, "analysisId": "private"},
        "processingJob": {"id": "opaque-job", "stage": "completed", "cursor": {"units": 9},
                          "extractionRevision": "e" * 64},
        "error": None,
    }
    library = SupportingLibrary(SimpleNamespace(get_owned=lambda identity: deepcopy(row), database=None))
    monkeypatch.setattr(library, "load_source", lambda identity, revision=None: {
        "units": [{"unitId": "u1"}, {"unitId": "u2"}],
        "coverage": {"complete": True, "unitIds": ["u1", "u2"], "unresolvedUnitIds": []},
    })
    monkeypatch.setattr(library, "load_report", lambda identity, revision=None: {
        "items": [{"requirements": [{"id": "r1"}, {"id": "r2"}]}],
        "alignments": [{"itemId": "q1", "unresolvedRequirementIds": []}],
        "topics": [{"id": "t1"}],
        "extractionCoverage": {"complete": True, "unitIds": ["u1", "u2"], "unresolvedUnitIds": []},
        "alignmentCoverage": {"complete": True, "checkedItemIds": ["q1"], "unresolvedItemIds": [], "topicIds": ["t1"],
            "checkedTopicIds": ["t1"], "unresolvedTopicIds": []},
    })
    status = library.public_status(IDENTITY)
    assert set(status) == {"materialId", "kind", "jobId", "status", "stage", "progress", "sourceRevision",
                           "reportRevision", "scopeRevision", "coverage", "legacy", "stale", "errorMessage"}
    assert status['jobId'] == 'opaque-job'
    assert status["progress"] == {"completedUnits": 2, "totalUnits": 2,
                                  "completedRequirements": 3, "totalRequirements": 3}


def test_public_status_marks_old_foundation_report_stale():
    row = {
        "supportingAnalysis": {"version": 1, "state": "completed"},
        "processingJob": {"stage": "completed", "foundationRevision": "a" * 64},
    }
    database = SimpleNamespace(get_document_foundation=lambda user_id, course_id: {
        "revision": "b" * 64})
    library = SupportingLibrary(SimpleNamespace(
        get_owned=lambda identity: deepcopy(row), database=database))
    assert library.public_status(IDENTITY)["stale"] is True


def test_public_status_marks_legacy_worker_state_as_upgrade_required():
    row = {"status": "queued", "processingJob": {"stage": "queued"}}
    library = SupportingLibrary(SimpleNamespace(
        get_owned=lambda identity: deepcopy(row), database=None))
    status = library.public_status(IDENTITY)
    assert status["status"] == "legacy"
    assert status["stage"] == "upgrade_required"
    assert status["legacy"] is True


def test_report_page_does_not_leak_unpaged_topics_or_papers(monkeypatch):
    library = SupportingLibrary(SimpleNamespace(database=None))
    monkeypatch.setattr(library, "load_report", lambda identity, revision: {
        "items": [{"id": "q1", "paperId": "p1", "sharedContextIds": []},
                  {"id": "q2", "paperId": "p2", "sharedContextIds": []}],
        "alignments": [{"itemId": "q1"}, {"itemId": "q2"}], "sharedContexts": [],
        "papers": [{"paperId": "p1"}, {"paperId": "p2"}],
        "topics": [{"id": "t1", "itemIds": ["q1"]}, {"id": "t2", "itemIds": ["q2"]}],
        "scopeSnapshot": {}, "extractionCoverage": {}, "alignmentCoverage": {},
    })
    page = library.report_page(IDENTITY, report_revision="a" * 64, offset=0, limit=1)
    assert page["papers"] == [{"paperId": "p1"}]
    assert page["topics"] == [{"id": "t1", "itemIds": ["q1"]}]


def test_run_prepares_extracts_aligns_and_publishes_with_one_budget(monkeypatch, tmp_path):
    original = b"one page"
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(original)
    foundation = "f" * 64
    handle = {"id": "1" * 32, "claimToken": "2" * 32, "inputRevision": "3" * 64,
              "sourceDigest": __import__("hashlib").sha256(original).hexdigest(),
              "foundationRevision": foundation}

    class Repository:
        database = SimpleNamespace(
            download_file_from_storage=lambda path, user_id: source_path,
            get_owned_course=lambda user_id, course_id: {"title": "Algorithms"},
        )

        def __init__(self):
            self.row = {"userId": "u", "courseId": "c", "storagePath": "historical_exams/u/c/source.pdf",
                        "fileType": "pdf", "originalDigest": handle["sourceDigest"],
                        "processingJob": {**handle, "stage": "queued", "modelCalls": 0,
                                          "modelCallBudget": 9, "leaseUntil": 0}}
            self.changes = []

        def get_owned(self, identity): return deepcopy(self.row)
        def claim(self, identity, job_id, *, worker_id, now_ms): return deepcopy(handle)
        def checkpoint(self, identity, job, *, changes, now_ms):
            self.changes.append(deepcopy(changes))
            self.row["processingJob"].update(changes)
            return True

    manifest = {"identity": deepcopy(IDENTITY), "sourceRevision": "4" * 64,
                "originalDigest": handle["sourceDigest"], "fileType": "pdf", "units": [],
                "coverage": {"complete": True, "unitIds": [], "unresolvedUnitIds": []}}
    inventory = {"items": [], "sharedContexts": [], "papers": [], "topics": [],
                 "extractionCoverage": {"complete": True, "unitIds": [], "unresolvedUnitIds": []}}

    class Extractor:
        def prepare_pages(self, identity, body, file_type): return deepcopy(manifest)
        def extract(self, manifest, **kwargs):
            kwargs["checkpoint"]({"stage": "complete", "modelCalls": 2})
            return deepcopy(inventory)

    class Library:
        def __init__(self): self.saved_report = None; self.saved = {}
        def save_source(self, identity, job, body, value): return {"revision": value["sourceRevision"]}
        def save_checkpoint(self, identity, job, state):
            revision = __import__("hashlib").sha256(repr(state).encode()).hexdigest()
            self.saved[revision] = deepcopy(state)
            return {"revision": revision}
        def load_checkpoint(self, identity, revision): return deepcopy(self.saved[revision])
        def render_reference(self, identity, ref): return []
        def save_report(self, identity, job, report): self.saved_report = deepcopy(report); return {"revision": "5" * 64}

    class Aligner:
        def __init__(self, reader, library): pass
        def align(self, identity, inventory, **kwargs):
            assert kwargs["model_calls"] == 2 and kwargs["model_call_budget"] == 9
            kwargs["checkpoint"]({"stage": "align", "modelCalls": 3})
            return {"report": True}

    repository, library = Repository(), Library()
    reader = SimpleNamespace(scope={"foundationRevision": foundation, "allowedRefs": ["owned"]})
    monkeypatch.setattr("src.supporting.workflows.SupportingAligner", Aligner)
    workflow = SupportingWorkflow(repository, library, Extractor(), object(), lambda identity: reader)
    assert workflow.run(IDENTITY) is True
    assert library.saved_report == {"report": True}
    assert any(change.get("inventoryRevision") for change in repository.changes)
    assert repository.row["processingJob"]["modelCalls"] == 3


def test_url_capture_is_bound_once_and_retry_reuses_preserved_bytes(api_module, monkeypatch, tmp_path):
    captured = tmp_path / "captured.mp3"
    captured.write_bytes(b"version-one-audio")
    downloads = []
    monkeypatch.setattr(api_module, "_download_url_audio_to_mp3",
                        lambda url, directory: (downloads.append(url) or str(captured), "Title"))

    class Database:
        def __init__(self): self.objects = {}
        def upload_file_to_storage(self, body, path, user_id, require_remote=False): self.objects[path] = bytes(body)
        def download_file_from_storage(self, path, user_id):
            output = tmp_path / ("saved-" + str(len(self.objects[path])))
            output.write_bytes(self.objects[path])
            return output

    class Repository:
        def __init__(self): self.database = Database(); self.row = None
        def reserve(self, identity, job, *, paths, now_ms): return True
        def bind_capture(self, identity, job, *, path, source_digest, now_ms):
            self.row = {"sourceUrl": "https://example.test/audio", "storagePath": path,
                        "originalDigest": source_digest}
            return {**job, "sourceDigest": source_digest}
        def get_owned(self, identity): return deepcopy(self.row)

    repository = Repository()
    workflow = SupportingWorkflow(repository, object(), object(), object(), lambda identity: None)
    job = {"id": "1" * 32, "claimToken": "2" * 32, "sourceDigest": None,
           "foundationRevision": "3" * 64}
    body, row, bound = workflow._read_original({**IDENTITY, "kind": "audio"},
        {"sourceUrl": "https://example.test/audio", "storagePath": "", "originalDigest": None}, job)
    assert body == b"version-one-audio" and len(downloads) == 1
    captured.write_bytes(b"changed-remote-audio")
    retried, _, _ = workflow._read_original({**IDENTITY, "kind": "audio"}, row, bound)
    assert retried == b"version-one-audio" and len(downloads) == 1


def test_missing_capture_and_legacy_text_cannot_invent_audio_provenance(tmp_path):
    class Database:
        def download_file_from_storage(self, path, user_id):
            missing = tmp_path / "missing.mp3"
            missing.write_bytes(b"wrong bytes")
            return missing
    repository = SimpleNamespace(database=Database())
    workflow = SupportingWorkflow(repository, object(), object(), object(), lambda identity: None)
    job = {"sourceDigest": "a" * 64}
    with pytest.raises(ValueError, match="missing or corrupt"):
        workflow._read_original({**IDENTITY, "kind": "audio"},
            {"storagePath": "audio/u/c/captured.mp3", "originalDigest": "a" * 64}, job)
    with pytest.raises(ValueError, match="re-upload"):
        workflow._read_original({**IDENTITY, "kind": "audio"},
            {"storagePath": "", "transcript": "legacy words", "originalDigest": "a" * 64}, job)

