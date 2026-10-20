import os
import asyncio
import hashlib
import uuid
import sys
import re
import logging
import time as _time
import math
import threading
from copy import deepcopy
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from pathlib import Path

# إضافة مسار المشروع الرئيسي لحل أي تعارضات في الاستدعاء تلقائياً
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 1. التحقق من وجود المكتبات الأساسية لتشغيل الخادم
try:
    from fastapi import FastAPI, HTTPException, Depends, Query, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field, field_validator
    import uvicorn
except ImportError as e:
    print("❌ Critical Server Libraries Missing!")
    print(f"Error Details: {e}")
    print("\nPlease activate your virtual environment (venv) and install core server dependencies:")
    print("👉 pip install fastapi uvicorn pydantic")
    sys.exit(1)

# 2. التحقق من وجود مكتبات المشروع والربط مع قاعدة البيانات والذكاء الاصطناعي
try:
    from src.config.settings import settings
    from src.auth import require_uid, require_recent_uid, assert_owner, owned_only
    from src.database.firebase_client import FirebaseClient, DataConflict, DataSizeConflict
    from src.agents.exam_generator import ExamGeneratorAgent
    from src.agents.summary_generator import SummaryGeneratorAgent
except ImportError as e:
    print("❌ Critical Project Dependencies or Internal Modules Missing!")
    print(f"Error Details: {e}")
    print("\nThis usually means libraries like 'firebase-admin', 'openai', or 'python-dotenv' are not installed.")
    print("Please install them using:")
    print("👉 pip install firebase-admin openai python-dotenv")
    sys.exit(1)

# إعداد السجلات والتقارير في الـ Terminal
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("MudarisAPI")

from src.utils.storage_paths import UPLOADS_ROOT, build_storage_path, resolve_storage_path
from src.utils.ai_contracts import align_printed_marks, validate_exam_contract
from src.utils.text_normalization import context_coverage
from src.utils.exam_blueprint import build_exam_blueprint
from src.utils.topic_scope import retag_topic_weights
from src.utils.media_safety import FFMPEG_INPUT_OPTIONS
from starlette.concurrency import run_in_threadpool


def _require_course(course_id: str, uid: str, allow_deleting: bool = False) -> dict:
    try:
        course = db_client.get_owned_course(uid, course_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Course not found")
    course = assert_owner(course, uid, "Course")
    if not allow_deleting:
        db_client._assert_write_allowed(uid, course_id)
    return course


def _load_document_foundation(course_id: str, uid: str) -> dict:
    from src.utils.course_foundation import build_foundation_status, hydrate_document_source
    course = _require_course(course_id, uid)
    documents = [row for row in owned_only(db_client.get_course_documents(course_id, user_id=uid), uid)
                 if row.get('courseId') == course_id]
    confirmation = db_client.get_document_foundation(uid, course_id)
    confirmed_revision = confirmation.get('revision', '') if isinstance(confirmation, dict) else ''
    documents = [hydrate_document_source(db_client, row) for row in documents]
    status = build_foundation_status(documents, confirmed_revision)
    return {**status, 'documents': documents, 'course': course,
            'document_insights': [{**row.get('analysis', {}), 'documentTitle': row.get('title', '')}
                                  for row in documents if isinstance(row.get('analysis'), dict)]}


def _require_document_foundation(course_id: str, uid: str, expected_revision: str = None) -> dict:
    foundation = _load_document_foundation(course_id, uid)
    if not foundation['ready']:
        raise HTTPException(status_code=409, detail=foundation['message'])
    if expected_revision is not None and foundation['revision'] != expected_revision:
        raise HTTPException(status_code=409, detail='Lecture documents changed during processing. Confirm all documents again and retry.')
    return foundation


def _public_foundation(foundation: dict) -> dict:
    return {key: foundation[key] for key in ('ready', 'state', 'revision', 'documentCount',
            'completedCount', 'pendingCount', 'failedCount', 'message', 'failedDocumentIds', 'failedStages')}


def _require_lecture(lecture_id: str, course_id: str, uid: str) -> None:
    if not lecture_id:
        return
    from src.utils.storage_paths import validate_component
    try:
        validate_component(lecture_id, "lecture ID")
        lecture = assert_owner(db_client._flat_get("lectures", lecture_id), uid, "Lecture")
    except ValueError:
        raise HTTPException(status_code=404, detail="Lecture not found")
    if lecture.get("courseId") != course_id:
        raise HTTPException(status_code=404, detail="Lecture not found")


def _save_uploaded_record(save, user_id, course_id, data):
    """Compensate file creation when metadata cannot be committed."""
    try:
        return save(user_id, course_id, data)
    except Exception:
        path = data.get("storagePath")
        if path:
            try:
                db_client.delete_file_from_storage(path, user_id=user_id)
            except Exception:
                logger.exception("Upload rollback failed; lifecycle cleanup will retry this file")
        raise


def _queue_supporting_acceptance(identity, foundation_revision, initial_data, *,
                                 original_bytes=None, storage_path=None, source_digest=None):
    """Persist a unique original, then atomically create its compact row and job."""
    initial_data = deepcopy(initial_data)
    if original_bytes is not None:
        if not storage_path:
            raise ValueError('An uploaded original needs a private storage path')
        source_digest = hashlib.sha256(original_bytes).hexdigest()
        initial_data['storagePath'] = storage_path
        initial_data['fileUrl'] = db_client.upload_file_to_storage(
            original_bytes, storage_path, identity['userId'])
    input_revision = __import__('src.supporting.contracts', fromlist=['digest']).digest({
        'identity': identity, 'sourceDigest': source_digest, 'storagePath': storage_path,
        'sourceUrl': initial_data.get('sourceUrl'), 'fileType': initial_data.get('fileType'),
        'sourceType': initial_data.get('sourceType')})
    try:
        job = supporting_repository.queue(identity, input_revision=input_revision,
            source_digest=source_digest, foundation_revision=foundation_revision,
            now_ms=int(_time.time() * 1000), initial_data=initial_data,
            model_call_budget=settings.SUPPORTING_MODEL_CALL_BUDGET)
    except Exception as queue_error:
        try:
            adopted = supporting_repository.get_owned(identity)
        except DataConflict:
            adopted = {}
        except Exception:
            # The queue write may have committed even though both transports
            # failed. Keep the unique bytes so the durable row can recover.
            raise
        current = (adopted or {}).get('processingJob') or {}
        committed = (current.get('inputRevision') == input_revision
                     and ((adopted or {}).get('storagePath') or None) == storage_path)
        if storage_path and not committed:
            try:
                db_client.delete_file_from_storage(storage_path, identity['userId'])
            except Exception:
                logger.exception('Supporting upload compensation failed; preserved object needs cleanup')
        if not committed:
            raise queue_error
        job = current
    _supporting_runner.submit(identity)
    return {
        'materialId': identity['materialId'], 'kind': identity['kind'],
        'status': 'queued', 'stage': 'queued',
        'progress': {'completedUnits': 0, 'totalUnits': None,
                     'completedRequirements': 0, 'totalRequirements': None},
        'sourceRevision': None, 'reportRevision': None, 'scopeRevision': None,
        'coverage': None, 'legacy': False, 'stale': False, 'errorMessage': None,
        'originalDigest': source_digest, 'identity': deepcopy(identity), 'jobId': job['id'],
    }


def _require_record_storage(row: dict, uid: str, category: str) -> None:
    path = row.get("storagePath")
    if not path:
        return
    try:
        resolve_storage_path(path, uid, root=UPLOADS_ROOT)
        parts = path.split("/")
        if parts[0] != category or parts[2] != row.get("courseId"):
            raise ValueError("Storage association changed")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="This file's course association is invalid. Cleanup was stopped.") from exc


def _source_summary(intelligence: dict) -> dict:
    ids = intelligence.get("source_ids", {})
    return {
        "documentIds": ids.get("document_ids", []),
        "audioIds": ids.get("audio_ids", []),
        "historicalExamIds": ids.get("historical_exam_ids", []),
        "tutorialIds": ids.get("tutorial_ids", []),
    }


def _require_sources(intelligence: dict, supplemental_text: str = "", require_documents: bool = False) -> None:
    source_scope = intelligence.get('source_scope')
    if require_documents and not (source_scope.get('allowedRefs') if source_scope is not None else intelligence.get('document_analyses')):
        raise HTTPException(status_code=422, detail='Select at least one analyzed lecture document for the study scope.')
    if source_scope and source_scope.get('allowedRefs'):
        return
    groups = ("document_analyses", "audio_insights", "historical_analyses", "tutorial_analyses",
              "document_texts", "historical_texts", "tutorial_texts")
    if not supplemental_text.strip() and not any(intelligence.get(key) for key in groups):
        raise HTTPException(status_code=422, detail="Select at least one successfully analyzed source before generating.")


def _source_reader(course_id, uid, agent, document_ids=None):
    """Resolve owned originals for this request; never retain execution on an agent."""
    from src.services.document_library import DocumentLibrary
    from src.services.source_evidence import SourceEvidence
    from src.utils.source_context import resolve_source_scope
    library = DocumentLibrary(db_client)
    try:
        scope = resolve_source_scope(db_client, library, uid, course_id, document_ids)
        if not scope['allowedRefs']:
            raise ValueError('Select at least one ready lecture document.')
        return SourceEvidence(scope, library, uid, course_id, agent.client, agent.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='Selected lecture originals are unavailable. Select ready documents and retry.') from exc


def _source_prepare(reader, purpose, query=''):
    try:
        return reader.prepare(purpose, query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _source_verify(reader, rows):
    try:
        return reader.verify_rows(rows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


_SAVED_SOURCE_UNAVAILABLE = ('The saved exam\'s exact original sources or identity are unavailable. '
                             'Restore the original source versions, or regenerate the exam from confirmed documents.')


def _load_saved_exam_evidence(exam: dict, uid: str) -> dict:
    """No provider work: restore original provenance, independently of today's foundation."""
    from src.services.document_library import DocumentLibrary
    from src.services.source_evidence import SourceEvidence, saved_question_identity
    from src.database.firebase_client import saved_exam_revision
    assert_owner(exam, uid, 'Exam')
    _require_course(exam.get('courseId', ''), uid)
    try:
        library = DocumentLibrary(db_client)
        scope = library.restore_scope(uid, exam['courseId'], exam.get('sourceScope'))
        rubrics = deepcopy(exam.get('rubrics', {}))
        validate_exam_contract(exam['texContent'], rubrics, total_marks=exam.get('totalMarks'), blueprint=exam.get('examBlueprint'))
        identity = saved_question_identity(exam['texContent'], rubrics)
        if (identity != exam.get('questionIdentity') or identity['questions'] != exam.get('questionStructure')
                or rubrics.get('sharedSourceRefs') != exam.get('sharedSourceRefs')):
            raise ValueError('Saved question or shared context identity changed')
        for refs in [rubrics.get('sharedSourceRefs'), *[q['sourceRefs'] for q in identity['questions']]]:
            if not isinstance(refs, list) or not refs or any(ref not in scope['allowedRefs'] for ref in refs):
                raise ValueError('Saved citations are outside the saved scope')
        reader = SourceEvidence(scope, library, uid, exam['courseId'], ai_agent.client, ai_agent.model_id)
        return {'reader': reader, 'identity': identity, 'revision': saved_exam_revision(exam)}
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=409, detail=_SAVED_SOURCE_UNAVAILABLE) from exc


def _verify_saved_exam(reader, exam):
    rubrics = reader.verify_exam(exam['texContent'], deepcopy(exam['rubrics']))
    if rubrics != exam['rubrics']:
        raise ValueError('Verification cannot rewrite authoritative saved rubrics or shared references')


def _publish_saved_exam(doc_id, exam, changes, uid, foundation_revision=None):
    from src.database.firebase_client import saved_exam_revision
    assert_owner(db_client.get_exam(doc_id), uid, 'Exam')
    if foundation_revision is not None:
        _require_document_foundation(exam['courseId'], uid, foundation_revision)
    db_client.update_exam(doc_id, changes, expected_exam_revision=saved_exam_revision(exam),
                          expected_foundation_revision=foundation_revision)


async def _read_upload(file, limit: int = 100 * 1024 * 1024) -> bytes:
    """Bound file buffering even when a request omits Content-Length."""
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="This file exceeds the upload size limit.")
        chunks.append(chunk)
    if not size:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    return b"".join(chunks)


def _upload_path(uid: str, course_id: str, category: str, filename: str) -> str:
    import uuid
    try:
        # Validate the original name before adding the collision-free prefix.
        from src.utils.storage_paths import validate_component
        name = validate_component(filename or "upload", "filename")
        return build_storage_path(uid, course_id, category, f"{uuid.uuid4().hex}_{name}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename or course ID.")

# تهيئة تطبيق FastAPI
@asynccontextmanager
async def _lifespan(application):
    await run_in_threadpool(_recover_audio_jobs)
    await run_in_threadpool(_recover_document_jobs)
    await run_in_threadpool(_recover_supporting_jobs)
    async def recover_documents():
        while True:
            await asyncio.sleep(10)
            await run_in_threadpool(_recover_document_jobs)
            await run_in_threadpool(_recover_supporting_jobs)
    recovery = asyncio.create_task(recover_documents())
    try:
        yield
    finally:
        recovery.cancel()
        try:
            await recovery
        except asyncio.CancelledError:
            pass
        await run_in_threadpool(_close_document_jobs)
        await run_in_threadpool(_close_audio_jobs)
        await run_in_threadpool(_close_supporting_jobs)


app = FastAPI(
    title="Mudaris AI Examination Core API",
    description="Backend Grading & Exam Generation Engine for Imam University",
    version="1.0.0",
    lifespan=_lifespan,
)

# CORS: the frontend only ever runs on localhost now, so that is the single
# allowed origin. No "*" default: a wildcard would let any page on the internet
# call this API from a signed-in visitor's browser.
app.add_middleware(
    CORSMiddleware,
    # Dev servers take whatever port is free (.claude/launch.json autoPort),
    # so match localhost on any port instead of pinning 3000.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    # No cross-origin cookies are used (auth rides in headers), so credentials
    # stay off. That also avoids "*" + credentials, which makes the preflight
    # echo back whatever origin asked.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DataConflict)
async def _data_conflict_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": "The account, course, or conversation changed. Reload before retrying."})


@app.exception_handler(DataSizeConflict)
async def _data_size_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=413, content={"detail": "This material is too large to save safely. Split it into smaller parts."})


# Keep exception details in backend logs and return a generic retry message.
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc):
    import traceback
    from fastapi.responses import JSONResponse
    logger.error(
        f"Unhandled error on {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "The operation could not be completed. Please retry."},
    )

# تهيئة عملاء الاتصال بقاعدة البيانات والذكاء الاصطناعي - نقوم هنا بتمرير كائن الإعدادات المورد من الـ Canvas
db_client = FirebaseClient(settings)
ai_agent = ExamGeneratorAgent()
summary_agent = SummaryGeneratorAgent()


@app.get('/api/courses/{course_id}/foundation')
def get_course_foundation(course_id: str, uid: str = Depends(require_uid)):
    return _public_foundation(_load_document_foundation(course_id, uid))


class FoundationConfirmRequest(BaseModel):
    revision: str = Field(min_length=1, max_length=128)


@app.post('/api/courses/{course_id}/foundation/confirm')
def confirm_course_foundation(course_id: str, payload: FoundationConfirmRequest, uid: str = Depends(require_uid)):
    foundation = _load_document_foundation(course_id, uid)
    if foundation['state'] not in ('confirmation_required', 'ready') or foundation['revision'] != payload.revision:
        raise HTTPException(status_code=409, detail='Upload all lecture documents and finish their analysis before confirming. Refresh and retry if the documents changed.')
    if db_client.confirm_document_foundation(uid, course_id, payload.revision, require_current_documents=True) is False:
        raise HTTPException(status_code=404, detail='Course not found')
    confirmed = _require_document_foundation(course_id, uid, payload.revision)
    return _public_foundation(confirmed)

# تعريف هيكلية البيانات المتوقعة من صفحة الـ HTML عند إرسال الإجابات
@app.get("/")
def read_root():
    return {
        "status": "Online",
        "system": "Mudaris Exam Engine",
        "university": "Imam Mohammad Ibn Saud Islamic University",
        "api_docs": "/docs"
    }


@app.delete("/api/courses/{course_id}")
def delete_course_endpoint(course_id: str, uid: str = Depends(require_uid)):
    try:
        _require_course(course_id, uid, allow_deleting=True)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        try:
            marker = db_client.get_course_deletion_marker(course_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Course not found")
        assert_owner(marker, uid, "Course")
    try:
        counts = db_client.delete_course_data(uid, course_id)
    except Exception:
        logger.exception("Course cleanup failed")
        raise HTTPException(status_code=503, detail="Course cleanup is incomplete. Please retry before leaving this page.")
    return {"status": "success", "deleted": course_id, "counts": counts}


@app.delete("/api/account")
def delete_account_endpoint(uid: str = Depends(require_recent_uid)):
    try:
        db_client.begin_account_deletion(uid)
        counts = db_client.delete_user_data(uid)
        from firebase_admin import auth as firebase_auth
        firebase_auth.delete_user(uid)
    except Exception:
        logger.exception("Account cleanup failed")
        raise HTTPException(status_code=503, detail="Account cleanup is incomplete. Please retry while signed in.")
    return {"status": "success", "counts": counts}

# ──────────────────────────────────────────────────
# Model 1: Document Processor
# ──────────────────────────────────────────────────

from src.agents.document_processor import DocumentProcessorAgent
doc_processor = DocumentProcessorAgent()

try:
    from fastapi import UploadFile, File, Form
    from fastapi.responses import FileResponse
except ImportError:
    pass

ALLOWED_DOC_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def _recheck_past_exam_scope(course_id: str, user_id: str = None):
    """Re-tag every past exam's topics as in/out of the CURRENT course (using the
    Historical Exam Analyzer's scope logic). Cheap — pure string match, no LLM
    call. Called when the course's documents change so the analyzer's scope
    decision stays current even if a past exam was uploaded before the lectures."""
    try:
        intel = db_client.get_course_intelligence(course_id, user_id=user_id)
        if intel.get("source_scope") is not None:
            return  # Re-evaluate against selected originals during new work.
        doc_insights = intel.get("document_analyses", [])
        past_exams = db_client.get_course_historical_exams(course_id, user_id=user_id)
        if user_id:
            past_exams = owned_only(past_exams, user_id)
        for h in past_exams:
            analysis = h.get("analysis") or {}
            if not analysis.get("topicWeights"):
                continue
            hist_analyzer.tag_topic_scope(analysis, doc_insights)
            db_client.update_historical_exam(h.get("id"), {"analysis": analysis})
    except Exception as e:
        logger.warning(f"Past-exam scope re-check failed for course {course_id}: {e}")


@app.post("/api/documents/upload", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    title: str = Form(""),
    lecture_id: str = Form(""), uid: str = Depends(require_uid),):
    user_id = uid  # the token decides the owner, not the form field
    course = _require_course(course_id, uid)
    _require_lecture(lecture_id, course_id, uid)
    import time as _time

    content_type = file.content_type or ""
    file_type = ALLOWED_DOC_TYPES.get(content_type)
    if not file_type:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        file_type = {"pdf": "pdf", "pptx": "pptx", "docx": "docx"}.get(ext)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    file_bytes = await _read_upload(file)
    file_size = len(file_bytes)
    doc_title = title or (file.filename or "Untitled Document")

    existing_docs = owned_only(db_client.get_course_documents(course_id, user_id=uid), uid)
    for ed in existing_docs:
        if ed.get("title") == doc_title or (file.filename and file.filename in ed.get("storagePath", "")):
            raise HTTPException(
                status_code=409,
                detail=f"A document named '{doc_title}' has already been uploaded to this course."
            )

    storage_path = _upload_path(uid, course_id, "documents", file.filename)
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path, user_id=uid, require_remote=True)

    doc_data = {
        "title": doc_title,
        "fileType": file_type,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "status": "processing",
        "preparationStatus": "pending", "guideStatus": "pending",
        "originalDigest": hashlib.sha256(file_bytes).hexdigest(),
        "uploadedAt": int(_time.time() * 1000),
    }
    if lecture_id:
        doc_data["lectureId"] = lecture_id

    doc_data['processingJob'] = {
        'id': uuid.uuid4().hex, 'kind': 'prepare', 'sourceDigest': doc_data['originalDigest'],
        'claimToken': None, 'leaseUntil': 0, 'stage': 'queued', 'cursor': None,
    }
    doc_data.update({'preparationError': None, 'guideError': None})
    doc_id = _save_uploaded_record(db_client.save_document, user_id, course_id, doc_data)
    try:
        _spawn_document_job(doc_id)
    except Exception:
        logger.warning('Document scheduling deferred to durable recovery')
    return {'status': 'accepted', 'document_id': doc_id, 'title': doc_title, 'file_type': file_type,
            'preparationStatus': 'pending', 'guideStatus': 'pending'}


def _public_document(row):
    fields = ('id', 'userId', 'courseId', 'lectureId', 'title', 'fileType', 'fileSize',
              'status', 'uploadedAt', 'processedAt', 'preparationStatus', 'guideStatus',
              'preparationError', 'guideError', 'unitCount', 'sourceRevision', 'guideRevision', 'guide', 'analysis')
    result = {key: row[key] for key in fields if key in row}
    job = row.get('processingJob')
    result['processingStage'] = job.get('stage') if isinstance(job, dict) else None
    return result


def _owned_source_document(doc_id, uid):
    row = assert_owner(db_client.get_document(doc_id), uid, 'Document')
    _require_course(row.get('courseId'), uid)
    return row


@app.get('/api/documents/{course_id}')
def get_course_documents(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    docs = owned_only(db_client.get_course_documents(course_id, user_id=uid), uid)
    return {'status': 'success', 'documents': [_public_document(row) for row in docs if row.get('courseId') == course_id]}


@app.get('/api/documents/detail/{doc_id}')
def get_document_detail(doc_id: str, uid: str = Depends(require_uid)):
    return {'status': 'success', 'document': _public_document(_owned_source_document(doc_id, uid))}


def _queue_document_preparation(doc_id, uid):
    doc = _owned_source_document(doc_id, uid)
    digest = doc.get('originalDigest')
    if not digest:
        # Legacy migration is explicit. Only digest discovery precedes the claim;
        # all extraction and provider work is performed by the claimed worker.
        _require_record_storage(doc, uid, 'documents')
        try:
            source = db_client.download_file_from_storage(doc.get('storagePath'), uid)
            digest_state, size = hashlib.sha256(), 0
            with source.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail='This original exceeds the upload limit. Split it and upload again.')
                    digest_state.update(chunk)
            if not size:
                raise HTTPException(status_code=422, detail='The saved original is empty. Upload it again.')
        except (ValueError, FileNotFoundError):
            raise HTTPException(status_code=422, detail='The saved original is unavailable. Upload it again.')
        current = _owned_source_document(doc_id, uid)
        _require_record_storage(current, uid, 'documents')
        if any(current.get(key) != doc.get(key) for key in ('courseId', 'storagePath', 'fileType', 'originalDigest')):
            raise HTTPException(status_code=409, detail='The original changed during preparation. Reload and retry.')
        if current.get('status') == 'deleting':
            raise HTTPException(status_code=409, detail='This document is being deleted.')
        digest = digest_state.hexdigest()
    db_client.start_document_job(uid, doc['courseId'], doc_id, source_digest=digest, force_guide=True)
    try:
        _spawn_document_job(doc_id)
    except Exception:
        logger.warning('Document scheduling deferred to durable recovery')
    return {'status': 'accepted', 'document_id': doc_id}


@app.post('/api/documents/{doc_id}/prepare', status_code=202)
def prepare_document(doc_id: str, uid: str = Depends(require_uid)):
    return _queue_document_preparation(doc_id, uid)


@app.post('/api/documents/{doc_id}/reanalyze', status_code=202)
def reanalyze_document(doc_id: str, uid: str = Depends(require_uid)):
    return _queue_document_preparation(doc_id, uid)


@app.get('/api/documents/{doc_id}/original')
def get_document_original(doc_id: str, uid: str = Depends(require_uid)):
    from fastapi.responses import Response
    row = _owned_source_document(doc_id, uid)
    if row.get('status') == 'deleting':
        raise HTTPException(status_code=409, detail='This document is being deleted.')
    _require_record_storage(row, uid, 'documents')
    media_types = {'pdf': 'application/pdf',
                   'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                   'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}
    file_type = row.get('fileType')
    if file_type not in media_types or not row.get('storagePath'):
        raise HTTPException(status_code=404, detail='The saved original is unavailable.')
    try:
        path = db_client.download_file_from_storage(row['storagePath'], uid)
        with path.open('rb') as stream:
            original = stream.read(100 * 1024 * 1024 + 1)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail='The saved original is unavailable.')
    if len(original) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='This original exceeds the supported file size.')
    current = _owned_source_document(doc_id, uid)
    _require_record_storage(current, uid, 'documents')
    if (current.get('status') == 'deleting' or any(current.get(key) != row.get(key)
            for key in ('courseId', 'storagePath', 'fileType', 'originalDigest'))):
        raise HTTPException(status_code=409, detail='The original changed. Reload and retry.')
    if row.get('originalDigest') and hashlib.sha256(original).hexdigest() != row['originalDigest']:
        raise HTTPException(status_code=409, detail='The saved original is corrupt. Restore or replace it.')
    return Response(content=original, media_type=media_types[file_type], headers={
        'Content-Disposition': f'inline; filename="document.{file_type}"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@app.get('/api/documents/{doc_id}/sources')
def get_document_sources(doc_id: str, uid: str = Depends(require_uid)):
    from src.utils.course_foundation import hydrate_document_source
    row = _owned_source_document(doc_id, uid)
    hydrated = hydrate_document_source(db_client, row)
    result = _public_document(row)
    manifest = hydrated.get('_sourceManifest')
    result['available'] = hydrated['_sourceArtifactsValid']
    if manifest:
        result.update({'coverage': manifest['coverage'], 'warnings': manifest['warnings'],
                       'units': [{key: unit[key] for key in ('unitId', 'kind', 'position', 'label', 'blank', 'warnings')}
                                 for unit in manifest['units']]})
    return {'status': 'success', 'source': result}


@app.get('/api/documents/{doc_id}/sources/{unit_id}')
def get_document_source_unit(doc_id: str, unit_id: str, source_revision: str, uid: str = Depends(require_uid)):
    from src.services.document_library import DocumentLibrary
    row = _owned_source_document(doc_id, uid)
    library = DocumentLibrary(db_client)
    ref = {'documentId': doc_id, 'sourceRevision': source_revision, 'unitId': unit_id}
    try:
        unit = library.load_units(uid, row['courseId'], [ref])[0]
        images = library.render_reference(uid, row['courseId'], ref)
    except (ValueError, FileNotFoundError):
        # Recheck ownership so an ownership/deletion race remains indistinguishable
        # from an inaccessible document, rather than revealing historical versions.
        _owned_source_document(doc_id, uid)
        raise HTTPException(status_code=409, detail='That exact source version is unavailable. Restore the original version or regenerate the saved output.')
    public = {key: unit[key] for key in ('documentId', 'sourceRevision', 'unitId', 'kind', 'position',
              'label', 'text', 'blank', 'warnings')}
    public['visualText'] = unit.get('visualText', '')
    return {'status': 'success', 'unit': public, 'images': images}


@app.delete('/api/documents/{doc_id}')
def delete_document_endpoint(doc_id: str, uid: str = Depends(require_uid)):
    doc = _owned_source_document(doc_id, uid)
    _require_record_storage(doc, uid, 'documents')
    try:
        db_client.delete_document_data(uid, doc_id)
    except (DataConflict, DataSizeConflict):
        raise
    except Exception:
        raise HTTPException(status_code=503, detail='File cleanup failed. Please retry.')
    _recheck_past_exam_scope(doc.get('courseId', ''), uid)
    return {'status': 'success', 'deleted': doc_id}


@app.delete("/api/audio/{rec_id}")
def delete_audio_endpoint(rec_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_audio_recording(rec_id), uid, "Recording")
    rec = db_client._flat_get("audio_recordings", rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    _require_record_storage(rec, uid, "audio")
    storage_path = rec.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path, user_id=uid)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
            raise HTTPException(status_code=503, detail="File cleanup failed. Please retry.")
    db_client.delete_audio_recording(rec_id)
    logger.info(f"Audio recording {rec_id} deleted.")
    return {"status": "success", "deleted": rec_id}


@app.delete("/api/historical-exams/{exam_id}")
def delete_historical_exam_endpoint(exam_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_historical_exam(exam_id), uid, "Exam")
    exam = db_client._flat_get("historical_exams", exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Historical exam not found")
    _require_record_storage(exam, uid, "historical_exams")
    storage_path = exam.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path, user_id=uid)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
            raise HTTPException(status_code=503, detail="File cleanup failed. Please retry.")
    db_client.delete_historical_exam(exam_id)
    logger.info(f"Historical exam {exam_id} deleted.")
    return {"status": "success", "deleted": exam_id}


@app.delete("/api/exams/{doc_id}")
def delete_generated_exam_endpoint(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    try:
        db_client.delete_exam_data(uid, doc_id)
    except Exception:
        logger.exception("Exam cleanup failed")
        raise HTTPException(status_code=503, detail="Exam cleanup failed. Please retry.")
    logger.info(f"Generated exam {doc_id} deleted.")
    return {"status": "success", "deleted": doc_id}


@app.get("/api/files/serve")
def serve_uploaded_file(path: str, uid: str = Depends(require_uid)):
    # `path` comes from the caller, so it has to be contained inside
    # UPLOADS_ROOT before anything is read: pathlib lets an absolute value
    # replace the root outright ("/proc/self/environ" -> the process env, which
    # holds the API keys and the service-account JSON), and ".." segments walk
    # out of it. Resolve the join, then re-check where it landed.
    try:
        file_path = resolve_storage_path(path, uid, root=UPLOADS_ROOT)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")
    # Upload paths are built as "{kind}/{user_id}/{course_id}/{file}" by the
    # upload endpoints, so the second segment names the owner. Containment
    # alone would still hand one student another student's lecture PDF.
    # is_file() rather than exists(), so directories aren't handed to
    # FileResponse. The detail deliberately omits the resolved path, which
    # would leak the server's filesystem layout.
    if not file_path.is_file():
        try:
            file_path = db_client.download_file_from_storage(path, uid)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except Exception:
            logger.exception("Private file download failed")
            raise HTTPException(status_code=503, detail="The file could not be loaded. Please retry.")
    content_types = {
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".txt": "text/plain",
    }
    ct = content_types.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        str(file_path), media_type=ct, content_disposition_type="inline"
    )


# ──────────────────────────────────────────────────
# Model 3: Historical Exam Analyzer
# ──────────────────────────────────────────────────

from src.agents.historical_exam_analyzer import HistoricalExamAnalyzer
hist_analyzer = HistoricalExamAnalyzer()


def _ensure_historical_paper_analysis(course_id: str, uid: str, selected_ids: list, document_insights: list,
                                     foundation_revision: str = None, *, lecture_evidence=None, source_reader=None) -> bool:
    """Upgrade selected legacy files from their saved originals before predicting.

    A flat legacy question count could describe a merged collection. It is never
    silently used as one paper's format. Successful rescans are cached; failures
    retain the old source and remain retryable.
    """
    if not selected_ids:
        return False
    from src.utils.ai_contracts import validate_analysis
    from src.utils.pdf_extract import image_to_image_uri
    rows = {row['id']: row for row in owned_only(db_client.get_course_historical_exams(course_id, user_id=uid), uid)
            if row.get('courseId') == course_id}
    changed = False
    for source_id in dict.fromkeys(selected_ids):
        row = assert_owner(rows.get(source_id), uid, 'Past exam')
        analysis = row.get('analysis') or {}
        if analysis.get('analysisVersion') == 2:
            try:
                validate_analysis('historical', analysis)
                continue
            except ValueError:
                pass
        if not row.get('storagePath'):
            raise HTTPException(status_code=422, detail='A selected past exam needs its original file to identify individual papers. Re-upload that file before generating.')
        _require_record_storage(row, uid, 'historical_exams')
        course = _require_course(course_id, uid)
        evidence_kwargs = {'lecture_evidence': lecture_evidence} if lecture_evidence is not None else {}
        try:
            path = db_client.download_file_from_storage(row['storagePath'], uid)
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError('Past-exam source exceeds the size limit')
            file_bytes = path.read_bytes()
            if row['storagePath'].lower().endswith('.pdf'):
                analysis = hist_analyzer.analyze_pdf(file_bytes, course.get('title', course_id), document_insights=document_insights, **evidence_kwargs)
            else:
                analysis = hist_analyzer.analyze_exam('', course.get('title', course_id),
                    image_uris=[image_to_image_uri(file_bytes)], document_insights=document_insights, **evidence_kwargs)
            validate_analysis('historical', analysis)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=422, detail='A selected past-exam original is unavailable. Re-upload it to predict from its individual papers.') from exc
        except (ValueError, RuntimeError) as exc:
            logger.warning('Historical paper rescan failed: %s', type(exc).__name__)
            raise HTTPException(status_code=422, detail='Individual papers could not be identified reliably. Retry, or upload the papers separately.') from exc
        _require_course(course_id, uid)
        if foundation_revision is not None:
            _require_document_foundation(course_id, uid, foundation_revision)
        latest = assert_owner(db_client.get_historical_exam(source_id), uid, 'Past exam')
        if latest.get('courseId') != course_id or latest.get('storagePath') != row.get('storagePath'):
            raise HTTPException(status_code=409, detail='A selected past exam changed during analysis. Select the sources again and retry.')
        if source_reader is not None:
            analysis = source_reader.tag_analysis(analysis)
        db_client.update_historical_exam(source_id, {'analysis': analysis, 'processedAt': int(_time.time() * 1000),
                                                    'foundationRevision': foundation_revision},
                                        expected_foundation_revision=foundation_revision)
        changed = True
    return changed

@app.post("/api/historical-exams/upload", status_code=202)
async def upload_historical_exam(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    title: str = Form(""), uid: str = Depends(require_uid),):
    user_id = uid  # the token decides the owner, not the form field
    foundation = await run_in_threadpool(_require_document_foundation, course_id, uid)
    import time as _time

    content_type = file.content_type or ""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    _IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "bmp", "gif"}
    is_pdf = content_type == "application/pdf" or ext == "pdf"
    is_image = content_type.startswith("image/") or ext in _IMAGE_EXTS
    if not (is_pdf or is_image):
        raise HTTPException(
            status_code=400,
            detail="Past exams must be a PDF or an image (photo).",
        )

    file_bytes = await _read_upload(file)
    file_size = len(file_bytes)
    exam_title = title or (file.filename or "Untitled Exam")

    exam_id = 'historical_exams_' + uuid.uuid4().hex
    storage_path = _upload_path(uid, course_id, "historical_exams", file.filename)
    accepted = await run_in_threadpool(_queue_supporting_acceptance,
        {'userId': uid, 'courseId': course_id, 'kind': 'historical_exam', 'materialId': exam_id},
        foundation['revision'], {'title': exam_title, 'fileType': 'pdf' if is_pdf else 'image',
        'fileSize': file_size, 'uploadedAt': int(_time.time() * 1000)},
        original_bytes=file_bytes, storage_path=storage_path)
    return {**accepted, 'exam_id': exam_id, 'title': exam_title}


@app.get("/api/historical-exams/{course_id}")
def get_course_historical_exams(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    exams = owned_only(db_client.get_course_historical_exams(course_id, user_id=uid), uid)
    exams = [_supporting_projection(row, 'historical_exam') for row in exams if row.get('courseId') == course_id]
    return {"status": "success", "historical_exams": exams}


# ──────────────────────────────────────────────────
# Tutorials — ungraded practice problems (ideas only, no marks/format)
# ──────────────────────────────────────────────────

@app.post("/api/tutorials/upload", status_code=202)
async def upload_tutorial(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    title: str = Form(""), uid: str = Depends(require_uid),):
    """Upload a tutorial / practice sheet (PDF, PPTX, DOCX). We analyze it for
    TOPICS and worked-problem IDEAS only — it never contributes grading weight
    or exam format (those come from past exams). Reuses the document analyzer."""
    user_id = uid  # the token decides the owner, not the form field
    foundation = await run_in_threadpool(_require_document_foundation, course_id, uid)
    import time as _time

    content_type = file.content_type or ""
    file_type = ALLOWED_DOC_TYPES.get(content_type)
    if not file_type:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        file_type = {"pdf": "pdf", "pptx": "pptx", "docx": "docx"}.get(ext)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    file_bytes = await _read_upload(file)
    file_size = len(file_bytes)
    tut_title = title or (file.filename or "Untitled Tutorial")

    tut_id = 'tutorials_' + uuid.uuid4().hex
    storage_path = _upload_path(uid, course_id, "tutorials", file.filename)
    accepted = await run_in_threadpool(_queue_supporting_acceptance,
        {'userId': uid, 'courseId': course_id, 'kind': 'tutorial', 'materialId': tut_id},
        foundation['revision'], {'title': tut_title, 'fileType': file_type,
        'fileSize': file_size, 'uploadedAt': int(_time.time() * 1000)},
        original_bytes=file_bytes, storage_path=storage_path)
    return {**accepted, 'tutorial_id': tut_id, 'title': tut_title}


@app.get("/api/tutorials/{course_id}")
def get_course_tutorials(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    tutorials = owned_only(db_client.get_course_tutorials(course_id, user_id=uid), uid)
    tutorials = [_supporting_projection(row, 'tutorial') for row in tutorials if row.get('courseId') == course_id]
    return {"status": "success", "tutorials": tutorials}


@app.delete("/api/tutorials/{tut_id}")
def delete_tutorial_endpoint(tut_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_tutorial(tut_id), uid, "Tutorial")
    tut = db_client.get_tutorial(tut_id)
    if not tut:
        raise HTTPException(status_code=404, detail="Tutorial not found")
    _require_record_storage(tut, uid, "tutorials")
    storage_path = tut.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path, user_id=uid)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
            raise HTTPException(status_code=503, detail="File cleanup failed. Please retry.")
    db_client.delete_tutorial(tut_id)
    logger.info(f"Tutorial {tut_id} deleted.")
    return {"status": "success", "deleted": tut_id}


# ──────────────────────────────────────────────────
# Model 2: Audio Intelligence Agent
# ──────────────────────────────────────────────────

from src.agents.audio_intelligence import AudioIntelligenceAgent
audio_agent = AudioIntelligenceAgent()

from src.agents.tutor_agent import AITutorAgent
tutor_agent = AITutorAgent()

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    # Video files: we extract the audio track to MP3 before transcribing.
    "video/mp4": "mp4",
    "video/quicktime": "mov",
}


def _extract_audio_to_mp3(src_path: str) -> str:
    """Extract the audio track from a video/container file to MP3 using ffmpeg
    (the same ffmpeg Whisper relies on). Returns the new .mp3 path."""
    import subprocess
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed or not on PATH; cannot convert video to MP3.")
    out_path = str(Path(src_path).with_suffix(".converted.mp3"))
    proc = subprocess.run(
        [ffmpeg, "-y", *FFMPEG_INPUT_OPTIONS, "-i", src_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", out_path],
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0 or not os.path.exists(out_path):
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-500:]
        raise RuntimeError(f"ffmpeg failed to extract audio: {err}")
    return out_path


def _download_url_audio_to_mp3(url: str, out_dir: str):
    """Fetch a video/audio URL (YouTube, Vimeo, direct link, ...) and extract its
    audio to MP3 using yt-dlp + ffmpeg. Returns (mp3_path, detected_title)."""
    import yt_dlp
    from src.utils.media_download import validate_media_url, download_direct_media, PLATFORM_HOSTS, MAX_MEDIA_BYTES
    parsed, _ = validate_media_url(url)
    if parsed.hostname.lower() not in PLATFORM_HOSTS:
        downloaded = download_direct_media(url, os.path.join(out_dir, "direct_media"))
        return _extract_audio_to_mp3(str(downloaded)), "Online Recording"

    out_tmpl = os.path.join(out_dir, "online_audio.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 2,
        "max_filesize": MAX_MEDIA_BYTES,
        "allowed_extractors": ["youtube.*", "vimeo.*"],
        "match_filter": lambda info, **kwargs: "Recordings must be at most four hours." if (info.get("duration") or 0) > 14400 else None,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = (info or {}).get("title") or "Online Recording"

    mp3_path = os.path.join(out_dir, "online_audio.mp3")
    if not os.path.exists(mp3_path):
        for f in os.listdir(out_dir):
            if f.lower().endswith(".mp3"):
                mp3_path = os.path.join(out_dir, f)
                break
    if not os.path.exists(mp3_path):
        raise RuntimeError("Could not extract audio from the provided URL.")
    return mp3_path, title

def _resolve_course_title(course_id: str, user_id: str) -> str:
    return _require_course(course_id, user_id).get("title", course_id)


_AUDIO_WORK_SLOTS = threading.BoundedSemaphore(2)


def _run_audio_pipeline(rec_id, course_id, *, file_bytes=None, audio_ext=None,
                        url=None, had_title=True):
    """Checkpoint text before analysis and abandon deleted jobs safely."""
    import tempfile
    import shutil

    record = db_client.get_audio_recording(rec_id)
    owner = record.get("userId") if record else None
    if not owner or not db_client.audio_job_exists(owner, rec_id):
        return False
    try:
        foundation = _require_document_foundation(course_id, owner, record.get('foundationRevision'))
    except HTTPException:
        if db_client.audio_job_exists(owner, rec_id):
            try:
                db_client.update_audio_recording(rec_id, {'status': 'failed',
                    'errorMessage': 'Upload and confirm all lecture documents, then retry this recording.'},
                    expected_legacy_audio=True)
            except DataConflict:
                pass  # An upgraded managed job owns the row now.
        return False

    def checkpoint(data):
        if not db_client.audio_job_exists(owner, rec_id):
            raise FileNotFoundError("The recording or course was deleted.")
        kwargs = {'expected_foundation_revision': foundation['revision']} if data.get('status') == 'completed' else {}
        db_client.update_audio_recording(rec_id, data, expected_legacy_audio=True, **kwargs)

    if not _AUDIO_WORK_SLOTS.acquire(timeout=1200):
        return False
    workdir = None
    try:
        _require_document_foundation(course_id, owner, foundation['revision'])
        workdir = tempfile.mkdtemp(prefix="mudaris-audio-")
        transcript = record.get("transcript", "")
        if not transcript:
            if url:
                checkpoint({"status": "downloading"})
                transcribe_path, video_title = _download_url_audio_to_mp3(url, workdir)
                if not had_title:
                    checkpoint({"title": video_title})
            else:
                if file_bytes is not None:
                    transcribe_path = os.path.join(workdir, f"input.{audio_ext or 'mp3'}")
                    with open(transcribe_path, "wb") as output:
                        output.write(file_bytes)
                else:
                    transcribe_path = str(db_client.download_file_from_storage(record["storagePath"], owner))
                    audio_ext = record.get("audioExt") or Path(transcribe_path).suffix.lstrip(".")
                if audio_ext in {"mp4", "mov"}:
                    checkpoint({"status": "converting"})
                    # Conversion always occurs in a disposable job folder.
                    copied = os.path.join(workdir, f"input.{audio_ext}")
                    if str(transcribe_path) != copied:
                        shutil.copyfile(transcribe_path, copied)
                    transcribe_path = _extract_audio_to_mp3(copied)
            checkpoint({"status": "transcribing"})
            transcript = audio_agent.transcribe_audio(transcribe_path)
            checkpoint({"transcript": transcript, "status": "analyzing"})
        else:
            checkpoint({"status": "analyzing"})
        text = _frame_notes(transcript) if record.get("sourceType") == "notes" else transcript
        _require_document_foundation(course_id, owner, foundation['revision'])
        reader = _source_reader(course_id, owner, audio_agent)
        lecture_evidence = _source_prepare(reader, "focused", text)
        insights = audio_agent.analyze_transcript(text, foundation['course'].get('title', course_id),
                                                document_insights=foundation['document_insights'], lecture_evidence=lecture_evidence)
        _require_document_foundation(course_id, owner, foundation['revision'])
        insights = reader.tag_analysis(insights)
        checkpoint({"transcript": transcript, "insights": insights, "status": "completed",
                    "foundationRevision": foundation['revision'],
                    "errorMessage": "", "processedAt": int(_time.time() * 1000)})
        return True
    except (FileNotFoundError, DataConflict):
        # A purge or managed upgrade wins over an in-flight legacy worker.
        return False
    except Exception:
        logger.exception("Audio processing failed")
        if db_client.audio_job_exists(owner, rec_id):
            try:
                checkpoint({"status": "failed", "errorMessage": "Processing failed. Your saved text can be retried."})
            except (FileNotFoundError, DataConflict):
                pass
        return False
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        _AUDIO_WORK_SLOTS.release()


def _run_saved_audio_job(rec_id):
    record = db_client.get_audio_recording(rec_id)
    if record and not record.get('supportingAnalysis'):
        _run_audio_pipeline(rec_id, record.get("courseId", ""),
                            url=record.get("sourceUrl"), had_title=record.get("hadTitle", True))


from src.utils.job_runner import AudioJobRunner
_audio_runner = AudioJobRunner(lambda: db_client, _run_saved_audio_job)


def _supporting_reader(identity):
    foundation = _require_document_foundation(identity['courseId'], identity['userId'])
    reader = _source_reader(identity['courseId'], identity['userId'], doc_processor)
    if reader.scope.get('foundationRevision') != foundation['revision']:
        raise ValueError('Lecture foundation changed while preparing supporting material')
    return reader


from src.supporting.repository import SupportingRepository
from src.supporting.library import SupportingLibrary
from src.supporting.extraction import SupportingExtractor
from src.supporting.workflows import SupportingWorkflow
from src.supporting.jobs import SupportingJobRunner

supporting_repository = SupportingRepository(db_client)
supporting_library = SupportingLibrary(supporting_repository)
supporting_extractor = SupportingExtractor(doc_processor.client, doc_processor.model_id)
supporting_workflow = SupportingWorkflow(supporting_repository, supporting_library,
    supporting_extractor, audio_agent, _supporting_reader)
_supporting_runner = SupportingJobRunner(supporting_repository, supporting_workflow.run,
    max_workers=settings.SUPPORTING_MAX_WORKERS, max_pending=settings.SUPPORTING_MAX_PENDING)


def _recover_supporting_jobs():
    global _supporting_runner
    if _supporting_runner._closed:
        _supporting_runner = SupportingJobRunner(supporting_repository, supporting_workflow.run,
            max_workers=settings.SUPPORTING_MAX_WORKERS, max_pending=settings.SUPPORTING_MAX_PENDING)
    _supporting_runner.recover()


def _close_supporting_jobs():
    _supporting_runner.close()


def _supporting_identity(kind: str, material_id: str, uid: str, course_id: str = None):
    getters = {
        'historical_exam': db_client.get_historical_exam,
        'tutorial': db_client.get_tutorial,
        'audio': db_client.get_audio_recording,
        'notes': db_client.get_audio_recording,
    }
    getter = getters.get(kind)
    if getter is None:
        raise HTTPException(status_code=404, detail='Supporting material not found')
    row = getter(material_id)
    try:
        row = assert_owner(row, uid, 'Supporting material')
    except (ValueError, HTTPException):
        raise HTTPException(status_code=404, detail='Supporting material not found')
    if not row or (course_id is not None and row.get('courseId') != course_id):
        raise HTTPException(status_code=404, detail='Supporting material not found')
    actual_kind = ('notes' if row.get('sourceType') == 'notes' else 'audio') if kind in ('audio', 'notes') else kind
    if actual_kind != kind:
        raise HTTPException(status_code=404, detail='Supporting material not found')
    return {'userId': uid, 'courseId': row['courseId'], 'kind': kind, 'materialId': material_id}


def _supporting_projection(row, kind):
    identity = {'userId': row['userId'], 'courseId': row['courseId'], 'kind': kind,
                'materialId': row['id']}
    if row.get('supportingAnalysis'):
        status = supporting_library.public_status(identity)
    else:
        status = {'materialId': row['id'], 'kind': kind, 'jobId': None, 'status': 'legacy',
            'stage': 'upgrade_required',
            'progress': {'completedUnits': 0, 'totalUnits': None,
                         'completedRequirements': 0, 'totalRequirements': None},
            'sourceRevision': None, 'reportRevision': None, 'scopeRevision': None,
            'coverage': None, 'legacy': True, 'stale': True,
            'errorMessage': row.get('errorMessage')}
    return {**status, 'id': row['id'], 'courseId': row['courseId'], **{key: row.get(key) for key in
        ('title', 'fileSize', 'uploadedAt', 'processedAt', 'sourceType', 'lectureId') if key in row}}


def _legacy_public_content(value):
    """Retain saved teaching content without exporting internal storage metadata."""
    if isinstance(value, list):
        return [_legacy_public_content(item) for item in value]
    if isinstance(value, dict):
        return {key: _legacy_public_content(item) for key, item in value.items()
                if isinstance(key, str) and not any(part in key.lower() for part in
                    ('path', 'url', 'token', 'checkpoint', 'artifact', 'workerid', 'jobid'))
                and key.lower() not in ('processingjob', 'supportinganalysis')}
    return value


@app.get('/api/supporting/{kind}/{material_id}/legacy-analysis')
def get_supporting_legacy_analysis(kind: str, material_id: str, course_id: str = None,
                                   uid: str = Depends(require_uid)):
    identity = _supporting_identity(kind, material_id, uid, course_id)
    try:
        row = supporting_repository.get_owned(identity)
    except (DataConflict, ValueError) as exc:
        raise HTTPException(status_code=404, detail='Supporting material not found') from exc
    return {'id': material_id, 'materialId': material_id, 'courseId': identity['courseId'],
            'kind': kind, 'legacy': True, 'verified': False,
            **{key: _legacy_public_content(row[key]) for key in
               ('title', 'sourceType', 'analysis', 'insights', 'transcript') if key in row}}


@app.post('/api/supporting/{kind}/{material_id}/prepare', status_code=202)
def prepare_supporting_material(kind: str, material_id: str, course_id: str = None,
                                retry: bool = False, uid: str = Depends(require_uid)):
    identity = _supporting_identity(kind, material_id, uid, course_id)
    try:
        result = supporting_workflow.prepare(identity, retry=retry)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={'code': 'upgrade_required', 'message': str(exc)}) from exc
    _supporting_runner.submit(identity)
    return result


@app.get('/api/supporting/{kind}/{material_id}/status')
def get_supporting_status(kind: str, material_id: str, course_id: str = None,
                          uid: str = Depends(require_uid)):
    identity = _supporting_identity(kind, material_id, uid, course_id)
    try:
        return supporting_library.public_status(identity)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail='Supporting material not found') from exc


@app.get('/api/supporting/{kind}/{material_id}/report')
def get_supporting_report(kind: str, material_id: str, revision: str, course_id: str = None,
                          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                          uid: str = Depends(require_uid)):
    identity = _supporting_identity(kind, material_id, uid, course_id)
    try:
        return supporting_library.report_page(identity, report_revision=revision, offset=offset, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail='Supporting report not found') from exc


@app.get('/api/supporting/{kind}/{material_id}/source')
def get_supporting_source(kind: str, material_id: str, revision: str, unit_id: str,
                          course_id: str = None, uid: str = Depends(require_uid)):
    identity = _supporting_identity(kind, material_id, uid, course_id)
    ref = {'kind': kind, 'materialId': material_id, 'sourceRevision': revision, 'unitId': unit_id}
    try:
        unit = supporting_library.read_refs(identity, [ref])[0]
        manifest = supporting_library.load_source(identity, revision)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail='Supporting source not found') from exc
    page = unit.get('position') if (manifest['fileType'] == 'pdf' and unit.get('kind') == 'page') else None
    return {'ref': ref, 'unit': unit, 'originalPage': page if type(page) is int and page > 0 else None}


def _supporting_original_media(file_type: str, body: bytes):
    """Label the immutable original from its bytes, falling back to a neutral type."""
    if file_type == 'notes':
        return 'text/plain; charset=utf-8', 'txt'
    if file_type == 'pdf' and body.startswith(b'%PDF-'):
        return 'application/pdf', 'pdf'
    if file_type in ('docx', 'pptx') and body.startswith(b'PK'):
        return ({'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                 'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}[file_type], file_type)
    if file_type == 'image':
        if body.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'image/png', 'png'
        if body.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg', 'jpg'
        if body.startswith((b'GIF87a', b'GIF89a')):
            return 'image/gif', 'gif'
        if body[:4] == b'RIFF' and body[8:12] == b'WEBP':
            return 'image/webp', 'webp'
        if body.startswith(b'BM'):
            return 'image/bmp', 'bmp'
        if body[4:8] == b'ftyp' and body[8:12] in (b'heic', b'heix', b'hevc', b'hevx', b'mif1'):
            return 'image/heic', 'heic'
    if file_type == 'audio':
        if body[:4] == b'RIFF' and body[8:12] == b'WAVE':
            return 'audio/wav', 'wav'
        if body.startswith(b'ID3') or (len(body) > 1 and body[0] == 0xff and body[1] & 0xe0 == 0xe0):
            return 'audio/mpeg', 'mp3'
        if body[4:8] == b'ftyp':
            brand = body[8:12]
            if brand in (b'M4A ', b'M4B '):
                return 'audio/mp4', 'm4a'
            if brand == b'qt  ':
                return 'video/quicktime', 'mov'
            if brand in (b'isom', b'iso2', b'mp41', b'mp42'):
                return 'video/mp4', 'mp4'
    return 'application/octet-stream', 'bin'


@app.get('/api/supporting/{kind}/{material_id}/original')
def get_supporting_original(kind: str, material_id: str, revision: str, course_id: str = None,
                            uid: str = Depends(require_uid)):
    identity = _supporting_identity(kind, material_id, uid, course_id)
    try:
        manifest = supporting_library.load_source(identity, revision)
        body = supporting_library.original_bytes(identity, revision)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail='Supporting original not found') from exc
    media, extension = _supporting_original_media(manifest['fileType'], body)
    disposition = ('inline' if media == 'application/pdf' or media.startswith(
        ('image/', 'audio/', 'video/')) else 'attachment')
    return Response(body, media_type=media, headers={
        'Content-Disposition': f'{disposition}; filename="{material_id}.{extension}"'})


def _run_document_pipeline(doc_id):
    from src.services.document_library import DocumentLibrary
    from src.services.document_pipeline import DocumentPipeline
    if DocumentPipeline(db_client, DocumentLibrary(db_client), doc_processor).run(doc_id):
        row = db_client.get_document(doc_id)
        if row:
            _recheck_past_exam_scope(row['courseId'], row['userId'])
        return True
    return False


from src.utils.document_job_runner import DocumentJobRunner
_document_job_runner = DocumentJobRunner(lambda: db_client, _run_document_pipeline)


def _spawn_document_job(doc_id):
    return _document_job_runner.submit(doc_id)


def _recover_document_jobs():
    global _document_job_runner
    if _document_job_runner._closed:
        _document_job_runner = DocumentJobRunner(lambda: db_client, _run_document_pipeline)
    _document_job_runner.recover()


def _close_document_jobs():
    _document_job_runner.close()


def _spawn_audio_job(**kwargs):
    # All inputs needed for restart recovery live on the recording document.
    # A full in-memory worker pool leaves the job queued in the database.
    _audio_runner.submit(kwargs["rec_id"])


def _recover_audio_jobs():
    global _audio_runner
    if _audio_runner._closed:
        _audio_runner = AudioJobRunner(lambda: db_client, _run_saved_audio_job)
    _audio_runner.recover()


def _close_audio_jobs():
    _audio_runner.close()



@app.post("/api/audio/upload", status_code=202)
async def upload_audio(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    title: str = Form(""),
    lecture_id: str = Form(""),
    # "1" = process in a background thread and return immediately.
    # "0" = process synchronously and return when done (used by the multi-file
    #       uploader so it can analyze one recording at a time, like documents).
    background: str = Form("1"), uid: str = Depends(require_uid),):
    user_id = uid  # the token decides the owner, not the form field
    foundation = _require_document_foundation(course_id, uid)
    _require_lecture(lecture_id, course_id, uid)
    import time as _time

    content_type = file.content_type or ""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    audio_ext = ALLOWED_AUDIO_TYPES.get(content_type) or (ext if ext in ("mp3", "wav", "m4a", "mp4", "mov") else None)
    if not audio_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported audio/video type: {content_type}")

    file_bytes = await _read_upload(file, limit=512 * 1024 * 1024)
    file_size = len(file_bytes)
    audio_title = title or (file.filename or "Untitled Recording")

    rec_id = 'audio_recordings_' + uuid.uuid4().hex
    storage_path = _upload_path(uid, course_id, "audio", file.filename)
    data = {'title': audio_title, 'fileSize': file_size, 'sourceType': 'upload',
            'audioExt': audio_ext, 'hadTitle': bool(title.strip()),
            'uploadedAt': int(_time.time() * 1000)}
    if lecture_id:
        data['lectureId'] = lecture_id
    accepted = await run_in_threadpool(_queue_supporting_acceptance,
        {'userId': uid, 'courseId': course_id, 'kind': 'audio', 'materialId': rec_id},
        foundation['revision'], data, original_bytes=file_bytes, storage_path=storage_path)
    return {**accepted, 'recording_id': rec_id, 'title': audio_title}


class AudioUrlRequest(BaseModel):
    user_id: str
    course_id: str
    video_url: str
    title: str = ""
    lecture_id: str = ""
    # "1" = download + analyze in the background; "0" = wait and return when done
    # (used by the multi-URL uploader so it can process one URL at a time).
    background: str = "1"


@app.post("/api/audio/upload-url", status_code=202)
def upload_audio_from_url(payload: AudioUrlRequest, uid: str = Depends(require_uid)):
    """Take a video/audio URL; download + extract audio to MP3 + transcribe +
    analyze. Runs in the background by default, or synchronously when the caller
    wants to process several URLs one at a time."""
    payload.user_id = uid  # ignore any client-supplied owner
    foundation = _require_document_foundation(payload.course_id, uid)
    _require_lecture(payload.lecture_id, payload.course_id, uid)
    import time as _time

    url = (payload.video_url or "").strip()
    try:
        from src.utils.media_download import validate_media_url
        validate_media_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    rec_id = 'audio_recordings_' + uuid.uuid4().hex
    data = {'title': payload.title or 'Online Recording', 'fileSize': 0,
            'sourceType': 'url', 'sourceUrl': url, 'fileUrl': url, 'storagePath': '',
            'hadTitle': bool(payload.title.strip()), 'uploadedAt': int(_time.time() * 1000)}
    if payload.lecture_id:
        data['lectureId'] = payload.lecture_id
    accepted = _queue_supporting_acceptance(
        {'userId': uid, 'courseId': payload.course_id, 'kind': 'audio', 'materialId': rec_id},
        foundation['revision'], data, storage_path=None, source_digest=None)
    return {**accepted, 'recording_id': rec_id, 'title': data['title']}


class LectureNotesRequest(BaseModel):
    user_id: str
    course_id: str
    notes: str = Field(max_length=250000)
    title: str = ""
    lecture_id: str = ""


@app.post("/api/audio/upload-notes", status_code=202)
def upload_lecture_notes(payload: LectureNotesRequest, uid: str = Depends(require_uid)):
    """Typed lecture notes: the student writes what happened in the lecture and
    what the professor emphasized (e.g. "the prof said section 3 will come in
    the midterm"). The same AI that analyzes recordings runs on the text — no
    transcription step — and the insights are saved exactly like a recording's,
    so exam generation, the intelligence view, and the tutor all use them."""
    payload.user_id = uid  # ignore any client-supplied owner
    foundation = _require_document_foundation(payload.course_id, uid)
    _require_lecture(payload.lecture_id, payload.course_id, uid)
    import time as _time

    notes = payload.notes or ""
    if len(notes.strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail="Please write at least a couple of sentences about the lecture.",
        )

    title = (payload.title or "").strip() or "Typed Lecture Notes"
    rec_id = 'audio_recordings_' + uuid.uuid4().hex
    original = notes.encode('utf-8')
    storage_path = _upload_path(uid, payload.course_id, 'audio', 'notes.txt')
    data = {'title': title, 'fileSize': len(original), 'sourceType': 'notes',
            'uploadedAt': int(_time.time() * 1000)}
    if payload.lecture_id:
        data['lectureId'] = payload.lecture_id
    accepted = _queue_supporting_acceptance(
        {'userId': uid, 'courseId': payload.course_id, 'kind': 'notes', 'materialId': rec_id},
        foundation['revision'], data, original_bytes=original, storage_path=storage_path)
    return {**accepted, 'recording_id': rec_id, 'title': title}


def _frame_notes(notes: str) -> str:
    """Wrap typed notes so the analyzer knows they're a student's account of the
    lecture, not a verbatim transcript, and treats "the prof said X is on the
    exam" as a first-hand exam hint."""
    return (
        "[Student's typed notes about this lecture — not a verbatim transcript. "
        "Statements about what the professor emphasized or promised for the exam "
        "are first-hand exam hints.]\n\n" + notes
    )


@app.post("/api/audio/{rec_id}/reanalyze")
def reanalyze_audio_recording(rec_id: str, uid: str = Depends(require_uid)):
    """Re-run the AI analysis on a recording or typed note using its stored
    transcript — so a failure caused by a transient problem (no OpenRouter
    credit, model overloaded) can be retried without re-uploading or retyping.
    """
    assert_owner(db_client.get_audio_recording(rec_id), uid, "Recording")
    import time as _time

    rec = db_client.get_audio_recording(rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec.get('supportingAnalysis'):
        kind = 'notes' if rec.get('sourceType') == 'notes' else 'audio'
        identity = {'userId': uid, 'courseId': rec.get('courseId'), 'kind': kind,
                    'materialId': rec_id}
        try:
            accepted = supporting_workflow.prepare(identity, retry=True)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={
                'code': 'upgrade_required', 'message': str(exc)}) from exc
        _supporting_runner.submit(identity)
        return accepted
    foundation = _require_document_foundation(rec.get('courseId', ''), uid)
    db_client.update_audio_recording(rec_id, {'foundationRevision': foundation['revision']},
                                     expected_legacy_audio=True)

    transcript = (rec.get("transcript") or "").strip()
    if len(transcript) < 20:
        if rec.get("storagePath") or rec.get("sourceUrl"):
            ok = _run_audio_pipeline(rec_id, rec.get("courseId", ""), url=rec.get("sourceUrl"), had_title=rec.get("hadTitle", True))
            if ok:
                return {"status": "success", "recording_id": rec_id}
            raise HTTPException(status_code=503, detail="Processing could not finish. Please retry.")
        raise HTTPException(
            status_code=422,
            detail=(
                "No stored text is available for this entry, so it can't be "
                "re-analyzed — please upload or type it again."
            ),
        )

    db_client.update_audio_recording(rec_id, {"status": "analyzing", "errorMessage": ""},
                                     expected_legacy_audio=True)

    is_notes = rec.get("sourceType") == "notes"
    text = _frame_notes(transcript) if is_notes else transcript

    try:
        reader = _source_reader(rec.get('courseId', ''), uid, audio_agent)
        lecture_evidence = _source_prepare(reader, "focused", text)
        insights = audio_agent.analyze_transcript(
            text, foundation['course'].get('title', rec.get('courseId', '')),
            document_insights=foundation['document_insights'], lecture_evidence=lecture_evidence
        )
        assert_owner(db_client.get_audio_recording(rec_id), uid, "Recording")
        _require_document_foundation(rec.get('courseId', ''), uid, foundation['revision'])
        insights = reader.tag_analysis(insights)
        db_client.update_audio_recording(rec_id, {
            "insights": insights,
            "foundationRevision": foundation['revision'],
            "status": "completed",
            "errorMessage": "",
            "processedAt": int(_time.time() * 1000),
        }, expected_foundation_revision=foundation['revision'], expected_legacy_audio=True)
        logger.info(f"Audio/notes record {rec_id} re-analyzed successfully.")
        return {"status": "success", "recording_id": rec_id, "insights": insights}
    except HTTPException as exc:
        db_client.update_audio_recording(rec_id, {'status': 'failed', 'errorMessage': str(exc.detail)},
                                         expected_legacy_audio=True)
        raise
    except DataConflict:
        raise
    except Exception as e:
        logger.error(f"Re-analysis failed for {rec_id}: {e}")
        db_client.update_audio_recording(rec_id, {"status": "failed", "errorMessage": "Processing failed. Your saved material is available to retry."},
                                         expected_legacy_audio=True)
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")


@app.get("/api/audio/{course_id}")
def get_course_audio_recordings(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    recordings = owned_only(db_client.get_course_audio_recordings(course_id, user_id=uid), uid)
    recordings = [_supporting_projection(row, 'notes' if row.get('sourceType') == 'notes' else 'audio')
                  for row in recordings if row.get('courseId') == course_id]
    return {"status": "success", "audio_recordings": recordings}


# ──────────────────────────────────────────────────
# Model 4 Enhanced: Generate with full intelligence
# ──────────────────────────────────────────────────

class SourceSelectionRequest(BaseModel):
    document_ids: Optional[List[str]] = None
    historical_exam_ids: Optional[List[str]] = None
    tutorial_ids: Optional[List[str]] = None
    audio_ids: Optional[List[str]] = None

    @field_validator("document_ids", "historical_exam_ids", "tutorial_ids", "audio_ids")
    @classmethod
    def validate_selection(cls, ids):
        if ids is None:
            return ids
        if len(ids) > 200:
            raise ValueError("Select at most 200 sources per type.")
        from src.utils.storage_paths import validate_component
        return list(dict.fromkeys(validate_component(item, "source ID") for item in ids))


def _require_selected_supporting_ready(course_id, uid, *, foundation_revision=None,
                                       historical_exam_ids=None, tutorial_ids=None,
                                       audio_ids=None):
    """Validate selection before legacy completed-only projections can hide rows."""
    groups = (
        ('historical_exam', db_client.get_course_historical_exams(course_id, user_id=uid), historical_exam_ids),
        ('tutorial', db_client.get_course_tutorials(course_id, user_id=uid), tutorial_ids),
        ('audio', db_client.get_course_audio_recordings(course_id, user_id=uid), audio_ids),
    )
    unavailable = []
    for category, values, selected_ids in groups:
        rows = [row for row in owned_only(values, uid) if row.get('courseId') == course_id]
        by_id = {row['id']: row for row in rows}
        if selected_ids is None:
            selected = rows
        else:
            missing = [material_id for material_id in selected_ids if material_id not in by_id]
            if missing:
                raise HTTPException(status_code=404, detail='Selected supporting material was not found')
            selected = [by_id[material_id] for material_id in selected_ids]
        for row in selected:
            kind = ('notes' if category == 'audio' and row.get('sourceType') == 'notes'
                    else category)
            analysis = row.get('supportingAnalysis') or {}
            job = row.get('processingJob') or {}
            ready = (analysis.get('version') == 1 and analysis.get('state') == 'completed'
                     and row.get('status') == 'completed' and analysis.get('sourceRevision')
                     and analysis.get('reportRevision') and not row.get('stale')
                     and (foundation_revision is None
                          or job.get('foundationRevision') == foundation_revision))
            if ready:
                continue
            queued = False
            recoverable_original = bool(
                row.get('originalDigest') or row.get('storagePath')
                or (kind == 'notes' and isinstance(row.get('transcript'), str)
                    and row['transcript'].strip())
                or (kind == 'audio' and row.get('sourceType') == 'url'
                    and row.get('sourceUrl')))
            if (recoverable_original
                    and analysis.get('state') not in ('queued', 'processing')):
                identity = {'userId': uid, 'courseId': course_id, 'kind': kind,
                            'materialId': row['id']}
                try:
                    supporting_workflow.prepare(identity, retry=True)
                    _supporting_runner.submit(identity)
                    queued = True
                except (ValueError, DataConflict):
                    pass
            unavailable.append({'materialId': row['id'], 'kind': kind,
                'status': analysis.get('state', 'legacy'), 'legacy': analysis.get('version') != 1,
                'queued': queued,
                'guidance': ('Retry, upgrade, or deselect this material' if recoverable_original
                             else 'Re-upload the original material')})
    if unavailable:
        raise HTTPException(status_code=409, detail={
            'code': 'supporting_upgrade_required',
            'message': 'Selected supporting material is not ready for generation.',
            'materials': unavailable})


class EnhancedExamGenerateRequest(SourceSelectionRequest):
    user_id: str
    course_id: str
    topics: List[str] = []
    preference: str = "Generate a comprehensive mock exam."
    total_marks: int = Field(default=40, ge=1, le=500)
    exam_type: str = "Final"
    transcripts: str = ""
    cues: str = "Standard academic prep."
    university: str = "Imam Mohammad Ibn Saud Islamic University"
    college: str = "College of Computer and Information Sciences"

def _normalize_marks(rubrics: dict, total_marks: int):
    """Scale each question's max_score so they sum to exactly total_marks.
    Mutates the rubric in place using positive integer largest-remainder scaling."""
    qs = rubrics.get("questions", {})
    if not qs:
        return
    if not isinstance(total_marks, int) or total_marks < len(qs):
        raise ValueError("Total marks must allow at least one mark per question.")
    ids = sorted(qs.keys(), key=lambda key: (int(key[1:]) if re.fullmatch(r"q\d+", key) else 1000000, key))
    defaults = {"mcq": 2.0, "true_false": 2.0}
    raw = []
    for qid in ids:
        q = qs[qid]
        try:
            v = float(q.get("max_score") or 0)
        except (TypeError, ValueError):
            v = 0
        if not math.isfinite(v) or v <= 0:
            v = defaults.get(q.get("question_type", "written"), 10.0)
        raw.append(v)
    remaining = total_marks - len(ids)
    shares = [v / sum(raw) * remaining for v in raw]
    scaled = [1 + math.floor(value) for value in shares]
    drift = total_marks - sum(scaled)
    order = sorted(range(len(ids)), key=lambda i: (-(shares[i] % 1), i))
    for index in order[:drift]:
        scaled[index] += 1
    for qid, m in zip(ids, scaled):
        qs[qid]["max_score"] = m


def _compile_answer_tex(tex: str, name: str):
    from src.utils.pdf_response import compile_temp_pdf
    # New structured keys declare fontspec. Retained legacy/deterministic keys
    # keep their original engine; cache reads use the same choice as serving.
    if r'\usepackage{fontspec}' in tex:
        return compile_temp_pdf(tex.strip(), name + "-answers", engine='xelatex')
    return compile_temp_pdf(tex.strip(), name + "-answers")


def _rubric_answer_key_tex(exam: dict) -> str:
    """Build a COMPLETE, always-compilable model-answer key deterministically —
    no LLM. It takes the exam's own LaTeX (so every full question is shown and it
    compiles exactly like the exam did) and appends a red 'Answer Key' section
    listing the official answer for EVERY question, from the stored rubric."""
    import re as _re

    tex = exam.get("texContent", "") or ""
    tex = _re.sub(r'<secret-rubrics>.*?</secret-rubrics>', '', tex, flags=_re.DOTALL)
    if not tex.strip():
        return ""

    # Make sure xcolor is available for the red answers.
    if '\\usepackage{xcolor}' not in tex:
        tex = _re.sub(r'(\\documentclass[^\n]*\n)', r'\1\\usepackage{xcolor}\n', tex, count=1)

    rubrics = exam.get("rubrics", {}) or {}
    qs = dict(rubrics.get("questions", {}) or {})
    for k, v in rubrics.items():
        if k.startswith("q") and k[1:].isdigit() and isinstance(v, dict):
            qs.setdefault(k, v)

    def _qnum(k):
        return int(k[1:]) if k.startswith("q") and k[1:].isdigit() else 0

    lines = [r"\clearpage", r"{\color{red}\section*{Answer Key}}"]
    for qid in sorted(qs.keys(), key=_qnum):
        r = qs[qid] or {}
        qt = r.get("question_type", "written")
        if qt in ("mcq", "true_false"):
            ans = f"Correct answer: {r.get('correct_answer', '')}."
            if r.get("explanation"):
                ans += " " + str(r["explanation"])
        else:
            ans = str(r.get("criteria", "") or r.get("explanation", "") or "")
        num = qid[1:] if qid.startswith("q") else qid
        lines.append(
            r"\noindent\textbf{Question " + _latex_escape(num) + r".} "
            + r"{\color{red}" + _latex_escape(ans) + r"}\par\medskip"
        )
    block = "\n" + "\n".join(lines) + "\n"

    if '\\end{document}' in tex:
        tex = tex.replace('\\end{document}', block + '\\end{document}', 1)
    else:
        tex = tex + block + "\n\\end{document}"
    return tex if exam.get('sourceScope') else ai_agent._sanitize_latex(tex)


def _complete_saved_rubrics(exam):
    """Legacy schemas may compile deterministically without restorable provenance."""
    from src.utils.ai_contracts import validate_rubrics, exam_question_numbers
    rubrics = deepcopy(exam.get('rubrics') or {})
    if 'questions' not in rubrics:
        rubrics = {'questions': {k: v for k, v in rubrics.items() if re.fullmatch(r'q[1-9]\d*', k)}}
    try:
        validate_rubrics(rubrics)
        if exam.get('sourceScope'):
            from src.services.source_evidence import saved_question_identity
            if saved_question_identity(exam['texContent'], rubrics) != exam.get('questionIdentity'):
                return None
        ids = [f'q{i}' for i in range(1, len(rubrics['questions']) + 1)]
        structure = exam.get('questionStructure') or []
        if structure and [q.get('id') for q in structure] != ids:
            return None
        printed = exam_question_numbers(exam.get('texContent', ''))
        if printed:
            validate_exam_contract(exam['texContent'], rubrics, total_marks=exam.get('totalMarks'), blueprint=exam.get('examBlueprint'))
        elif not structure:
            return None
        return rubrics
    except (ValueError, TypeError, KeyError):
        return None


def _answer_key_identity(exam, tex, mapping):
    from src.database.firebase_client import saved_exam_revision
    from src.utils.generation_context import source_bundle_text
    return {'version': 1, 'inputRevision': saved_exam_revision(exam),
            'texRevision': hashlib.sha256(tex.encode('utf-8')).hexdigest(),
            'mappingRevision': hashlib.sha256(source_bundle_text(mapping).encode('utf-8')).hexdigest(),
            'questionIds': [row['questionId'] for row in mapping], 'sourceRefs': mapping}


def _cached_answer_key(exam, count):
    tex, identity = exam.get('answerKeyTex', ''), exam.get('answerKeyIdentity')
    if not isinstance(tex, str) or not tex or not count or exam.get('answerKeyQuestionCount') != count:
        return ''
    if identity is None:
        # Only genuinely old outputs retain the historical count-based cache seam.
        return tex if not exam.get('sourceScope') else ''
    if not isinstance(identity, dict):
        return ''
    mapping = identity.get('sourceRefs')
    if (not isinstance(mapping, list) or len(mapping) != count
            or any(not isinstance(row, dict) or set(row) != {'questionId', 'sourceRefs'}
                   or not isinstance(row['sourceRefs'], list) for row in mapping)
            or [row['questionId'] for row in mapping] != [f'q{i+1}' for i in range(count)]):
        return ''
    if exam.get('sourceScope') and any(not row.get('sourceRefs') or any(
            ref not in exam['sourceScope'].get('allowedRefs', []) for ref in row['sourceRefs']) for row in mapping):
        return ''
    return tex if identity == _answer_key_identity(exam, tex, mapping) else ''


def _make_compilable_answer_key(exam: dict, *, reader, lecture_evidence) -> dict:
    """New AI explanations must map exactly to saved questions and official answers."""
    from src.utils.pdf_response import check_tex_compiles
    from src.services.source_evidence import exam_shared_context
    questions = exam['questionIdentity']['questions']
    packet = {**lecture_evidence, 'savedQuestions': deepcopy(questions), 'authoritativeRubrics': deepcopy(exam['rubrics'])}
    items = ai_agent.generate_answer_pairs(exam['texContent'], exam.get('examId', 'exam'), lecture_evidence=packet)
    if not isinstance(items, list) or len(items) != len(questions):
        raise ValueError('Answer count changed')
    checked, mapping = [], []
    for item, question in zip(items, questions):
        rubric = exam['rubrics']['questions'][question['id']]
        official = rubric.get('correct_answer') if rubric['question_type'] in ('mcq', 'true_false') else rubric.get('criteria')
        if (not isinstance(item, dict) or item.get('questionId') != question['id']
                or item.get('question') != question['text'] or item.get('answer') != official):
            raise ValueError('Answer mapping or authoritative answer changed')
        refs = reader.validate_refs(item.get('sourceRefs', []))
        if not refs:
            raise ValueError('Answer citations missing')
        refs = reader.validate_refs(refs + exam['sharedSourceRefs'])
        checked.append({'questionId': question['id'], 'question': question['text'], 'answer': official,
                        'explanation': item.get('explanation', ''), 'sourceRefs': refs})
        mapping.append({'questionId': question['id'], 'sourceRefs': refs})
    shared = exam_shared_context(exam['texContent'])
    reader.verify_rows(checked, shared_context=shared)
    tex = ai_agent._answers_to_latex(checked, exam.get('examId', 'exam'), shared_context=shared)
    if not check_tex_compiles(tex, exam.get('examId', 'exam') + '-answers', engine='xelatex'):
        raise ValueError('Verified answer document cannot compile')
    return {'tex': tex, 'mapping': mapping}


@app.post("/api/exams/generate-enhanced")
def generate_enhanced_exam_endpoint(payload: EnhancedExamGenerateRequest, uid: str = Depends(require_uid)):
    payload.user_id = uid  # ignore any client-supplied owner
    foundation = _require_document_foundation(payload.course_id, uid)
    _require_selected_supporting_ready(payload.course_id, uid,
        foundation_revision=foundation['revision'],
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids, audio_ids=payload.audio_ids)
    import uuid
    import base64
    import time as _time

    exam_id = f"exam_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating enhanced exam {exam_id} for course {payload.course_id}")

    intelligence = db_client.get_course_intelligence(
        payload.course_id,
        document_ids=payload.document_ids,
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids,
        audio_ids=payload.audio_ids,
        user_id=payload.user_id,
    )

    _require_sources(intelligence, payload.transcripts, require_documents=True)
    reader = _source_reader(payload.course_id, uid, ai_agent, payload.document_ids)
    lecture_evidence = _source_prepare(reader, "exam")

    selected_past_ids = set(intelligence.get('source_ids', {}).get('historical_exam_ids', []))
    if _ensure_historical_paper_analysis(payload.course_id, uid,
            sorted(selected_past_ids),
            foundation['document_insights'], foundation['revision'], lecture_evidence=lecture_evidence, source_reader=reader):
        intelligence = db_client.get_course_intelligence(payload.course_id,
            document_ids=payload.document_ids, historical_exam_ids=payload.historical_exam_ids,
            tutorial_ids=payload.tutorial_ids, audio_ids=payload.audio_ids, user_id=uid)
        refreshed_past_ids = set(intelligence.get('source_ids', {}).get('historical_exam_ids', []))
        if not selected_past_ids.issubset(refreshed_past_ids):
            raise HTTPException(status_code=409, detail='A selected past exam is no longer available. Select the sources again and retry.')
        _require_sources(intelligence, payload.transcripts, require_documents=True)
    historical = retag_topic_weights(intelligence.get('historical_analyses', []), intelligence.get('document_analyses', []), source_scope=reader.scope, read_evidence=reader.read_evidence)
    exam_blueprint = build_exam_blueprint(historical, payload.total_marks, payload.exam_type)
    if historical and not exam_blueprint:
        raise HTTPException(status_code=422, detail='The selected past papers do not have enough reliable structure to predict an exam. Re-analyze or re-upload them.')

    # Brand the exam header as "Mudaris University of {the student's major}".
    try:
        _udoc = db_client.db.collection("users").document(payload.user_id).get()
        _major = ((_udoc.to_dict() or {}).get("major") or "").strip() if _udoc.exists else ""
    except Exception:
        _major = ""
    university_name = f"Mudaris University of {_major}" if _major else "Mudaris University"

    context = {
        "transcripts": payload.transcripts or "No transcripts provided.",
        "cues": payload.cues,
        "university": university_name,
        "college": payload.college,
    }

    raw_tex = ai_agent.compile_enhanced_exam(
        academic_data=context,
        topics=payload.topics if payload.topics else ["General course review"],
        preference=payload.preference,
        exam_id=exam_id,
        user_id=payload.user_id,
        course_id=payload.course_id,
        document_insights=intelligence.get("document_analyses", []),
        audio_insights=intelligence.get("audio_insights", []),
        historical_analysis=historical,
        document_texts=intelligence.get("document_texts", []),
        historical_texts=intelligence.get("historical_texts", []),
        tutorial_insights=intelligence.get("tutorial_analyses", []),
        tutorial_texts=intelligence.get("tutorial_texts", []),
        total_marks=payload.total_marks,
        exam_type=payload.exam_type,
        exam_blueprint=exam_blueprint,
        lecture_evidence=lecture_evidence,
    )

    extraction = ai_agent.extract_and_save_exam_metadata(
        raw_tex, exam_id, payload.user_id, payload.course_id
    )
    cleaned_tex = extraction.get("cleaned_tex", raw_tex)
    rubrics = extraction.get("rubrics", {})

    # Fallback: if the inline rubrics block was missing/empty (e.g. the
    # generation got truncated before reaching it), derive rubrics from the
    # exam text so the student still gets an answer sheet + grading.
    if not rubrics or not rubrics.get("questions"):
        logger.warning(f"Rubrics missing for {exam_id}; deriving from exam text.")
        rubrics = ai_agent.generate_rubrics_from_tex(cleaned_tex, exam_id, lecture_evidence=lecture_evidence)

    # Normalize per-question marks so the exam totals EXACTLY the requested marks
    try:
        validate_exam_contract(cleaned_tex, rubrics, blueprint=exam_blueprint)
        _normalize_marks(rubrics, payload.total_marks)
        cleaned_tex = align_printed_marks(cleaned_tex, rubrics)
        validate_exam_contract(cleaned_tex, rubrics, total_marks=payload.total_marks, blueprint=exam_blueprint)
        from src.utils.compile_pdf import validate_tex_source
        validate_tex_source(cleaned_tex)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    _require_document_foundation(payload.course_id, uid, foundation['revision'])

    from src.services.source_evidence import saved_question_identity, validate_exam_repair
    try:
        reader.verify_exam(cleaned_tex, rubrics)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    identity = saved_question_identity(cleaned_tex, rubrics)
    question_structure = identity['questions']

    def _try_compile(tex: str):
        from src.utils.pdf_response import compile_temp_pdf, cleanup_temp_pdf
        path = compile_temp_pdf(tex, exam_id)
        if not path:
            return None
        try:
            return base64.b64encode(Path(path).read_bytes()).decode()
        finally:
            cleanup_temp_pdf(path)

    pdf_base64 = None
    try:
        pdf_base64 = _try_compile(cleaned_tex)
        if pdf_base64 is None:
            # LLM LaTeX often has stray errors — ask the model to repair once
            logger.warning(f"Exam {exam_id} failed first compile; attempting LaTeX repair.")
            repaired = ai_agent.repair_latex(cleaned_tex, lecture_evidence=lecture_evidence)
            if repaired and repaired.strip() != cleaned_tex.strip():
                validate_exam_repair(cleaned_tex, repaired, rubrics)
                validate_exam_contract(repaired, rubrics, total_marks=payload.total_marks, blueprint=exam_blueprint)
                pdf_base64 = _try_compile(repaired)
                if pdf_base64 is not None:
                    cleaned_tex = repaired
                    logger.info(f"Exam {exam_id} compiled after repair.")
    except Exception as e:
        logger.warning(f"PDF compilation skipped: {e}")

    _require_document_foundation(payload.course_id, uid, foundation['revision'])
    identity = saved_question_identity(cleaned_tex, rubrics)
    db_client.save_secret_rubrics(payload.user_id, payload.course_id, exam_id, rubrics, expected_foundation_revision=foundation['revision'])
    doc_db_id = db_client.save_exam_flat(payload.user_id, payload.course_id, {
        "examId": exam_id,
        "texContent": cleaned_tex,
        "questionStructure": question_structure,
        "questionIdentity": identity,
        "sharedSourceRefs": rubrics['sharedSourceRefs'],
        "rubrics": rubrics,
        "totalMarks": payload.total_marks,
        "examType": payload.exam_type,
        "examBlueprint": exam_blueprint,
        "foundationRevision": foundation['revision'],
        "status": "generated",
        "pdfStatus": "ready" if pdf_base64 else "retry_required",
        "sourceSummary": _source_summary(intelligence),
        "contextCoverage": reader.coverage(),
        "sourceScope": reader.snapshot(),
        "sourceCoverage": reader.coverage(),
        "modelId": settings.OPENROUTER_MODEL,
        "promptVersion": "2026-10-09",
        "createdAt": int(_time.time() * 1000),
    }, expected_foundation_revision=foundation['revision'])

    # NOTE: the model-answer key is intentionally NOT generated here — it's built
    # on demand the first time the student reveals it (kept separate from exam
    # generation, and allowed to use the full token budget for completeness).

    return {
        "status": "success",
        "exam_id": exam_id,
        "doc_id": doc_db_id,
        "tex_content": cleaned_tex,
        "pdf_base64": pdf_base64,
        "has_pdf": pdf_base64 is not None,
        "question_structure": question_structure,
        "intelligence_used": intelligence.get("counts", {}),
        "exam_blueprint": exam_blueprint,
    }


# ──────────────────────────────────────────────────
# Exam management: list, detail, questions, submit
# ──────────────────────────────────────────────────

def _public_exam(exam):
    """Project display metadata; never return caches, rubrics or storage pointers."""
    fields = ('id', 'examId', 'userId', 'courseId', 'status', 'createdAt', 'totalMarks',
              'examType', 'pdfStatus', 'foundationRevision', 'modelId', 'promptVersion',
              'solutionName', 'solutionType', 'solutionUploadedAt', 'grade')
    result = {key: exam[key] for key in fields if key in exam and not isinstance(exam[key], (dict, list))}
    result['texContent'] = re.sub(r'<secret-rubrics>.*?</secret-rubrics>', '', exam.get('texContent', ''), flags=re.DOTALL)
    solution = exam.get('solutionPath')
    if isinstance(solution, str):
        try:
            resolve_storage_path(solution, exam['userId'], root=UPLOADS_ROOT)
            parts = solution.split('/')
            if len(parts) == 4 and parts[:3] == ['solutions', exam['userId'], exam['courseId']]:
                result['solutionPath'] = solution
        except (KeyError, ValueError):
            pass

    def refs(values):
        return [{key: row[key] for key in ('documentId', 'sourceRevision', 'unitId')}
                for row in values or [] if isinstance(row, dict)
                and all(isinstance(row.get(key), str) for key in ('documentId', 'sourceRevision', 'unitId'))]

    result['questionStructure'] = [{**{key: row[key] for key in ('id', 'type', 'text', 'marks', 'identity') if key in row},
                                    'sourceRefs': refs(row.get('sourceRefs'))}
                                   for row in exam.get('questionStructure', []) or [] if isinstance(row, dict)]
    result['sharedSourceRefs'] = refs(exam.get('sharedSourceRefs'))
    scope = exam.get('sourceScope')
    if isinstance(scope, dict):
        # Guides are private restoration input; display needs only versioned identities.
        result['sourceScope'] = {key: scope.get(key) for key in ('version', 'scopeRevision')}
        result['sourceScope']['allowedRefs'] = refs(scope.get('allowedRefs'))
        result['sourceScope']['documents'] = [{key: row.get(key) for key in ('id', 'title', 'sourceRevision', 'guideRevision')}
                                             for row in scope.get('documents', []) if isinstance(row, dict)]
    for name in ('sourceCoverage', 'contextCoverage'):
        value = exam.get(name)
        if isinstance(value, dict):
            result[name] = {key: value[key] for key in ('state', 'mode', 'complete', 'batchCount', 'successfulBatchCount') if key in value}
            result[name].update({key: refs(value[key]) for key in ('processedRefs', 'includedRefs', 'excludedRefs', 'partialRefs', 'unavailableRefs') if key in value})
    summary = exam.get('sourceSummary')
    if isinstance(summary, dict):
        result['sourceSummary'] = {key: [item for item in summary.get(key, []) if isinstance(item, str)]
                                   for key in ('documentIds', 'audioIds', 'historicalExamIds', 'tutorialIds')}
    return result


@app.get("/api/exams/list/{course_id}")
def list_course_exams(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    exams = owned_only(db_client.get_course_exams(course_id, user_id=uid), uid)
    safe = []
    for e in exams:
        safe.append({
            "id": e.get("id"),
            "examId": e.get("examId"),
            "status": e.get("status", "generated"),
            "createdAt": e.get("createdAt"),
            "questionCount": len(e.get("questionStructure", [])),
            "grade": e.get("grade"),
        })
    return {"status": "success", "exams": safe}


@app.get("/api/exams/detail/{doc_id}")
def get_exam_detail(doc_id: str, uid: str = Depends(require_uid)):
    # A detail read never starts a model rescue or changes authoritative answers.
    exam = assert_owner(db_client.get_exam(doc_id), uid, 'Exam')
    return {'status': 'success', 'exam': _public_exam(exam)}


@app.get("/api/exams/{doc_id}/pdf")
def get_exam_pdf(doc_id: str, uid: str = Depends(require_uid)):
    """Recompile a saved exam's LaTeX to PDF on demand and serve it.
    Sanitizes the stored .tex first, which also rescues older exams that were
    saved before the sanitizer fix (conversational preamble / markdown fences)."""
    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    from src.utils.pdf_response import compile_temp_pdf, cleanup_temp_pdf, pdf_file_response
    from src.services.source_evidence import validate_exam_repair, saved_question_identity
    exam = assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    tex = exam.get('texContent', '')
    tex = (re.sub(r'<secret-rubrics>.*?</secret-rubrics>', '', tex, flags=re.DOTALL)
           if exam.get('sourceScope') else ai_agent._sanitize_latex(tex))
    if not tex:
        raise HTTPException(status_code=404, detail="No LaTeX content for this exam")
    exam_name = exam.get("examId", doc_id)
    path, handed_to_response = None, False
    try:
        path = compile_temp_pdf(tex, exam_name)
        if not path:
            restored = _load_saved_exam_evidence(exam, uid)
            foundation = _require_document_foundation(exam.get('courseId', ''), uid)
            reader = restored['reader']
            evidence = _source_prepare(reader, 'exam')
            _verify_saved_exam(reader, exam)
            repaired = ai_agent.repair_latex(exam['texContent'], lecture_evidence=evidence)
            if repaired and repaired.strip() != exam['texContent'].strip():
                repaired = validate_exam_repair(exam['texContent'], repaired, exam['rubrics'])
                validate_exam_contract(repaired, exam['rubrics'], total_marks=exam.get('totalMarks'), blueprint=exam.get('examBlueprint'))
                path = compile_temp_pdf(repaired, exam_name)
                if path:
                    _publish_saved_exam(doc_id, exam, {'texContent': repaired, 'pdfStatus': 'ready',
                        'questionIdentity': saved_question_identity(repaired, exam['rubrics'])}, uid, foundation['revision'])
        if not path:
            raise HTTPException(status_code=503, detail="PDF compilation failed or the compiler is unavailable. Please retry.")
        response = pdf_file_response(path, exam_name)
        handed_to_response = True
        return response
    except (DataConflict, DataSizeConflict):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The exam contains unsupported TeX or its repair changed the questions.") from exc
    finally:
        if path and not handed_to_response:
            cleanup_temp_pdf(path)


@app.get("/api/exams/{doc_id}/answer-key-pdf")
def get_exam_answer_key_pdf(doc_id: str, uid: str = Depends(require_uid)):
    """Generate (once, then cache) and serve the MODEL-ANSWER key PDF for an
    exam — a full worked-solutions document the student opens after solving the
    exam themselves. Watermarked + served inline."""
    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    from src.utils.pdf_response import cleanup_temp_pdf, pdf_file_response
    exam = assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    exam_name = exam.get("examId", doc_id)
    num_q = len(exam.get("questionStructure", []) or []) or len((exam.get("rubrics", {}) or {}).get("questions", {}) or {})
    complete_rubrics = _complete_saved_rubrics(exam)
    if complete_rubrics:
        num_q = len(complete_rubrics['questions'])
    answer_tex = _cached_answer_key(exam, num_q)
    path, handed_to_response = None, False
    try:
        if answer_tex:
            try:
                path = _compile_answer_tex(answer_tex if exam.get('answerKeyIdentity') else ai_agent._sanitize_latex(answer_tex), exam_name)
            except ValueError:
                # Legacy or unsupported cached keys must not poison every retry.
                answer_tex = ""
                path = None
        if not path:
            if not exam.get("texContent"):
                raise HTTPException(status_code=404, detail="No exam content to build answers from.")
            foundation_revision = None
            if complete_rubrics:
                answer_tex = _rubric_answer_key_tex({**exam, 'rubrics': complete_rubrics})
                mapping = [{'questionId': f'q{i+1}', 'sourceRefs': complete_rubrics['questions'][f'q{i+1}'].get('sourceRefs', [])}
                           for i in range(num_q)]
                try:
                    path = _compile_answer_tex(answer_tex, exam_name)
                except ValueError:
                    path = None
            if not path:
                restored = _load_saved_exam_evidence(exam, uid)
                foundation_revision = _require_document_foundation(exam.get('courseId', ''), uid)['revision']
                reader = restored['reader']
                evidence = _source_prepare(reader, 'exam')
                _verify_saved_exam(reader, exam)
                generated = _make_compilable_answer_key(exam, reader=reader, lecture_evidence=evidence)
                answer_tex, mapping = generated['tex'], generated['mapping']
                path = _compile_answer_tex(answer_tex, exam_name)
            if path:
                _publish_saved_exam(doc_id, exam, {'answerKeyTex': answer_tex, 'answerKeyQuestionCount': num_q,
                    'answerKeyIdentity': _answer_key_identity(exam, answer_tex, mapping)}, uid, foundation_revision)
        if not path:
            raise HTTPException(status_code=503, detail="Answer-key compilation failed or the compiler is unavailable. Please retry.")
        response = pdf_file_response(path, exam_name + "-answers")
        handed_to_response = True
        return response
    except (DataConflict, DataSizeConflict):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="A complete answer key could not be prepared. Please retry.") from exc
    finally:
        if path and not handed_to_response:
            cleanup_temp_pdf(path)


@app.post("/api/exams/{doc_id}/solution")
async def upload_exam_solution(doc_id: str, file: UploadFile = File(...), uid: str = Depends(require_uid)):
    """Attach the student's OWN solved exam to this exam for side-by-side review
    (NOT graded). Stored as a file; the page shows it next to the model answers."""
    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    import time as _time

    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    allowed = {"pdf", "png", "jpg", "jpeg", "webp", "docx", "txt"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    file_bytes = await _read_upload(file)
    user_id = exam.get("userId", "anon")
    course_id = exam.get("courseId", "course")
    _require_course(course_id, uid)
    storage_path = _upload_path(uid, course_id, "solutions", f"{doc_id}_{file.filename}")
    db_client.upload_file_to_storage(file_bytes, storage_path, user_id=uid)
    old_path = exam.get("solutionPath")
    if old_path:
        try:
            db_client.delete_file_from_storage(old_path, user_id=uid)
        except Exception:
            paths = list(exam.get("supersededSolutionPaths", []))
            paths.append(old_path)
            db_client.update_exam(doc_id, {"supersededSolutionPaths": paths})

    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    _require_course(course_id, uid)
    db_client.update_exam(doc_id, {
        "solutionPath": storage_path,
        "solutionName": file.filename or "solution",
        "solutionType": ext,
        "solutionUploadedAt": int(_time.time() * 1000),
    })

    return {
        "status": "success",
        "solution_path": storage_path,
        "solution_type": ext,
    }



# ──────────────────────────────────────────────────
# Course Intelligence Summary
# ──────────────────────────────────────────────────

@app.get("/api/intelligence/{course_id}")
def get_course_intelligence_endpoint(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    intelligence = db_client.get_course_intelligence(course_id, user_id=uid)
    # The aggregation snapshot is private input to source readers. The metadata
    # endpoint must not start returning complete manifests or original bodies.
    fields = ('document_analyses', 'document_texts', 'audio_insights', 'historical_analyses',
              'historical_texts', 'tutorial_analyses', 'tutorial_texts', 'source_ids', 'counts')
    public = {key: intelligence[key] for key in fields if key in intelligence}
    public['document_guides'] = []
    scope = intelligence.get('source_scope')
    if scope is not None:
        public['document_texts'] = []
        counts = {m['documentId']: m['unitCount'] for m in scope['manifests']}
        public['document_guides'] = [{'documentId': d['id'], 'sourceRevision': d['sourceRevision'],
                                      'guideRevision': d['guideRevision'], 'unitCount': counts[d['id']]}
                                     for d in scope['documents']]
    return {"status": "success", **public}


# ──────────────────────────────────────────────────
# Flashcards — generate study cards from course intelligence
# ──────────────────────────────────────────────────

class FlashcardGenerateRequest(SourceSelectionRequest):
    user_id: str
    course_id: str
    topics: List[str] = []
    count: int = Field(default=20, ge=1, le=20)

@app.post("/api/flashcards/generate")
def generate_flashcards_endpoint(payload: FlashcardGenerateRequest, uid: str = Depends(require_uid)):
    payload.user_id = uid  # ignore any client-supplied owner
    foundation = _require_document_foundation(payload.course_id, uid)
    _require_selected_supporting_ready(payload.course_id, uid,
        foundation_revision=foundation['revision'],
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids, audio_ids=payload.audio_ids)
    import uuid
    import time as _time

    set_id = f"fc_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating flashcard set {set_id} for course {payload.course_id}")

    intelligence = db_client.get_course_intelligence(
        payload.course_id,
        document_ids=payload.document_ids,
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids,
        audio_ids=payload.audio_ids,
        user_id=payload.user_id,
    )

    _require_sources(intelligence, require_documents=True)
    reader = _source_reader(payload.course_id, uid, ai_agent, payload.document_ids)
    lecture_evidence = _source_prepare(reader, "flashcards")

    scoped_hist = retag_topic_weights(intelligence.get('historical_analyses', []), intelligence.get('document_analyses', []),
                                      source_scope=reader.scope, read_evidence=reader.read_evidence)
    cards = ai_agent.generate_flashcards(
        academic_data={},
        topics=payload.topics,
        document_insights=intelligence.get("document_analyses", []),
        audio_insights=intelligence.get("audio_insights", []),
        historical_analysis=scoped_hist,
        document_texts=intelligence.get("document_texts", []),
        historical_texts=intelligence.get("historical_texts", []),
        tutorial_insights=intelligence.get("tutorial_analyses", []),
        tutorial_texts=intelligence.get("tutorial_texts", []),
        count=payload.count,
        lecture_evidence=lecture_evidence,
    )

    if not cards:
        raise HTTPException(status_code=422, detail="Could not generate flashcards. Make sure documents are analyzed.")

    _require_document_foundation(payload.course_id, uid, foundation['revision'])
    _source_verify(reader, cards)
    title = f"{len(cards)} cards · {_time.strftime('%b %d')}"
    _require_document_foundation(payload.course_id, uid, foundation['revision'])
    doc_db_id = db_client.save_flashcard_set(payload.user_id, payload.course_id, {
        "setId": set_id,
        "title": title,
        "cards": cards,
        "foundationRevision": foundation['revision'],
        "sourceSummary": _source_summary(intelligence),
        "contextCoverage": reader.coverage(),
        "sourceScope": reader.snapshot(),
        "sourceCoverage": reader.coverage(),
        "modelId": settings.OPENROUTER_MODEL,
        "promptVersion": "2026-10-09",
        "createdAt": int(_time.time() * 1000),
    }, expected_foundation_revision=foundation['revision'])

    return {
        "status": "success",
        "set_id": set_id,
        "doc_id": doc_db_id,
        "title": title,
        "cards": cards,
    }


@app.get("/api/flashcards/list/{course_id}")
def list_flashcard_sets(course_id: str, uid: str = Depends(require_uid)):
    sets = owned_only(db_client.get_course_flashcard_sets(course_id, user_id=uid), uid)
    safe = [{
        "id": s.get("id"),
        "setId": s.get("setId"),
        "title": s.get("title"),
        "cardCount": len(s.get("cards", [])),
        "createdAt": s.get("createdAt"),
    } for s in sets]
    return {"status": "success", "sets": safe}


@app.get("/api/flashcards/detail/{doc_id}")
def get_flashcard_set_detail(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_flashcard_set(doc_id), uid, "Flashcard set")
    fc = db_client.get_flashcard_set(doc_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Flashcard set not found")
    return {"status": "success", "set": fc}


@app.delete("/api/flashcards/{doc_id}")
def delete_flashcard_set_endpoint(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_flashcard_set(doc_id), uid, "Flashcard set")
    fc = db_client.get_flashcard_set(doc_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Flashcard set not found")
    db_client.delete_flashcard_set(doc_id)
    logger.info(f"Flashcard set {doc_id} deleted.")
    return {"status": "success", "deleted": doc_id}


# ──────────────────────────────────────────────────
# Summaries — generate study summaries from course intelligence
# ──────────────────────────────────────────────────

class SummaryGenerateRequest(SourceSelectionRequest):
    user_id: str
    course_id: str
    topics: List[str] = []
    instructions: str = Field(default="", max_length=10000)

_SUMMARY_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "what", "which", "how", "into", "using", "use", "based", "via", "per", "its",
    "introduction", "overview", "concepts", "concept", "fundamentals", "basics",
    "topic", "topics", "chapter", "section", "part", "general", "review",
}


def _topic_word_set(text: str) -> set:
    from src.utils.topic_scope import core_words
    return core_words(text or "") - _SUMMARY_STOPWORDS


def _derive_section_exam_weights(sections: list, historical_analyses: list) -> list:
    """Make each summary section's examWeight / examLikelihood TRACEABLE to the
    past exams instead of an LLM guess. We match each section to the past-exam
    topicWeights (from Model 3) by word overlap and assign weight proportionally.

    If there are no past-exam topic weights (nothing to derive from), the section's
    original LLM estimate is left untouched."""
    topics = []  # (normalized_word_set, weight)
    for h in historical_analyses or []:
        for tw in (h.get("topicWeights", []) or []):
            if tw.get("inScope") is False:
                continue  # outside the selected documents — carries no weight here
            name = tw.get("topic", "")
            w = float(tw.get("weight", 0) or 0)
            words = _topic_word_set(name)
            if words and w > 0:
                topics.append((words, w))
    if not topics or not sections:
        return sections  # no past-exam signal -> keep the model's estimate

    total_w = sum(w for _, w in topics) or 1.0

    raws = []
    for sec in sections:
        text = sec.get("heading", "") + " " + " ".join(sec.get("keyPoints", []) or [])
        sec_words = _topic_word_set(text)
        best = 0.0
        for words, w in topics:
            inter = len(sec_words & words)
            if inter:
                score = inter / len(words)          # how well the topic is covered
                best = max(best, (w / total_w) * score)
        raws.append(best)

    tot = sum(raws)
    if tot <= 0:
        return sections  # nothing matched any past-exam topic -> keep estimate

    for sec, raw in zip(sections, raws):
        pct = round(raw / tot * 100)
        sec["examWeight"] = pct
        sec["examLikelihood"] = "high" if pct >= 20 else ("medium" if pct >= 8 else "low")
    return sections


def _compose_summary_title(doc_titles: list, llm_title: str | None) -> str:
    """Title the summary after the documents/chapters it was built from, so a
    student can tell at a glance which material it covers. Falls back to the
    model's title (then a dated default) when no documents were selected."""
    import time as _time
    titles = [t.strip() for t in (doc_titles or []) if t and t.strip()]
    if titles:
        if len(titles) == 1:
            base = titles[0]
        elif len(titles) <= 3:
            base = ", ".join(titles)
        else:
            base = ", ".join(titles[:3]) + f" +{len(titles) - 3} more"
        return f"Summary — {base}"
    return (llm_title or "").strip() or f"Summary · {_time.strftime('%b %d')}"


def _parse_exclusions(instructions: str) -> list:
    """Pull excluded-topic phrases out of free-text custom instructions, e.g.
    "don't include Division & Additional Operations" -> ["Division & Additional
    Operations"]. Used as a safety net so an excluded topic is stripped even if
    the model ignores the instruction."""
    text = (instructions or "").replace("’", "'")
    pat = re.compile(
        r"(?:do not|don'?t|exclude|omit|skip|without|remove|leave out|ignore)\s+"
        r"(?:include|including|add|adding|cover|covering|mention(?:ing)?|have|put|the|any)?\s*[:\-]?\s*"
        r"(.+?)(?=\s+(?:in chapter|in the|from |for chapter|chapter\b)|[.\n;]|$)",
        re.IGNORECASE,
    )
    out = []
    for m in pat.finditer(text):
        ph = m.group(1).strip(" .,:;-–")
        if len(ph) > 2:
            out.append(ph)
    return out


def _apply_summary_exclusions(summary: dict, instructions: str) -> dict:
    """Remove any section / keyTerm / examFocus that matches a topic the user
    asked to exclude. Conservative: only drops entries that share most of an
    excluded phrase's words or >= 2 distinctive words, so it won't over-prune."""
    from src.utils.topic_scope import core_words, variants
    phrases = _parse_exclusions(instructions)
    if not phrases:
        return summary

    # An exclusion like "Division & Additional Operations (Outer Join, Outer
    # Union)" is really a LIST. Split it into sub-phrases so a section is removed
    # only if it strongly matches one of the listed items — not just because it
    # shares a generic word ("operations", "join") with the whole phrase.
    excl_subs = []
    for phrase in phrases:
        for part in re.split(r"[&/,()]|\band\b|\bor\b", phrase, flags=re.IGNORECASE):
            w = core_words(part)
            if w:
                excl_subs.append(w)
        whole = core_words(phrase)
        if whole and whole not in excl_subs:
            excl_subs.append(whole)
    if not excl_subs:
        return summary

    def expand(words: set) -> set:
        out = set()
        for w in words:
            out |= variants(w)
        return out

    def is_excluded(text: str) -> bool:
        tw = expand(core_words(text))
        if not tw:
            return False
        for sub in excl_subs:
            matched = sum(1 for w in sub if variants(w) & tw)
            # Require most of the sub-phrase's words to be present, so generic
            # single-word overlaps (e.g. "operations") don't trigger removal.
            if sub and matched / len(sub) >= 0.6:
                return True
        return False

    before = len(summary.get("sections", []) or [])
    summary["sections"] = [
        s for s in (summary.get("sections", []) or [])
        if not is_excluded(f"{s.get('heading', '')} {s.get('content', '')[:120]}")
    ]
    summary["keyTerms"] = [
        t for t in (summary.get("keyTerms", []) or []) if not is_excluded(t.get("term", ""))
    ]
    summary["examFocus"] = [
        f for f in (summary.get("examFocus", []) or []) if not is_excluded(f)
    ]
    removed = before - len(summary["sections"])
    if removed:
        logger.info(f"Summary: stripped {removed} section(s) matching user exclusion(s) {phrases}")
    return summary


def _apply_summary_scope(summary: dict, document_analyses: list, *, source_reader=None) -> dict:
    if source_reader is not None:
        _source_verify(source_reader, summary.get('sections', []))
        refs = source_reader.validate_refs([r for section in summary.get('sections', []) for r in section.get('sourceRefs', [])])
        extras = {key: summary.get(key) for key in ('overview', 'keyTerms', 'examFocus') if summary.get(key)}
        if extras:
            _source_verify(source_reader, [{**extras, 'sourceRefs': refs}])
        return summary
    """Drop sections about material outside the documents the student SELECTED.

    The prompt already scopes the summary; this is the safety net for when the
    model drifts back to the whole course because the past exams cover it. A
    section survives if its heading matches the selected documents' vocabulary,
    or if its body names enough of that vocabulary to show it really belongs to
    the selected material — so only sections with no connection at all are cut.
    (``topic_in_scope`` can't judge the body on its own: it needs MOST of a
    string's words to match, which a full sentence never manages.)

    Without selected document vocabulary scope is unknown. When vocabulary is
    available, unrelated content is removed even when it is the majority."""
    from src.utils.topic_scope import (
        course_scope_from_docs, topic_in_scope, core_words, variants,
    )

    _, words = course_scope_from_docs(document_analyses)
    sections = summary.get("sections", []) or []
    if not words or not sections:
        return summary

    def body_touches_scope(sec: dict, min_hits: int = 2) -> bool:
        """True when the section's body names at least `min_hits` DISTINCT
        in-scope terms — enough signal that it's about the selected material."""
        text = " ".join(
            [sec.get("content", "") or ""] + list(sec.get("keyPoints", []) or [])[:8]
        )
        hits = {w for w in core_words(text) if variants(w) & words}
        return len(hits) >= min(min_hits, len(words))

    def section_in_scope(sec: dict) -> bool:
        return topic_in_scope(sec.get("heading", ""), words) or body_touches_scope(sec)

    kept = [s for s in sections if section_in_scope(s)]
    dropped = len(sections) - len(kept)
    if dropped:
        logger.info("Summary: removed %d sections outside selected documents", dropped)
        summary["overview"] = ""
    summary["sections"] = kept
    summary["keyTerms"] = [term for term in summary.get("keyTerms", []) if topic_in_scope(term.get("term", ""), words)]
    summary["examFocus"] = [focus for focus in summary.get("examFocus", []) if topic_in_scope(focus, words) or len({w for w in core_words(focus) if variants(w) & words}) >= min(2, len(words))]
    return summary


@app.post("/api/summaries/generate")
def generate_summary_endpoint(payload: SummaryGenerateRequest, uid: str = Depends(require_uid)):
    payload.user_id = uid  # ignore any client-supplied owner
    foundation = _require_document_foundation(payload.course_id, uid)
    _require_selected_supporting_ready(payload.course_id, uid,
        foundation_revision=foundation['revision'],
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids, audio_ids=payload.audio_ids)
    import uuid
    import time as _time

    summary_id = f"sum_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating summary {summary_id} for course {payload.course_id}")

    intelligence = db_client.get_course_intelligence(
        payload.course_id,
        document_ids=payload.document_ids,
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids,
        audio_ids=payload.audio_ids,
        user_id=payload.user_id,
    )

    _require_sources(intelligence, require_documents=True)
    reader = _source_reader(payload.course_id, uid, summary_agent, payload.document_ids)
    lecture_evidence = _source_prepare(reader, "summary")

    scoped_hist = retag_topic_weights(intelligence.get('historical_analyses', []), intelligence.get('document_analyses', []),
                                      source_scope=reader.scope, read_evidence=reader.read_evidence)
    summary = summary_agent.generate_summary(
        academic_data={},
        topics=payload.topics,
        document_insights=intelligence.get("document_analyses", []),
        audio_insights=intelligence.get("audio_insights", []),
        historical_analysis=scoped_hist,
        document_texts=intelligence.get("document_texts", []),
        historical_texts=intelligence.get("historical_texts", []),
        tutorial_insights=intelligence.get("tutorial_analyses", []),
        tutorial_texts=intelligence.get("tutorial_texts", []),
        instructions=payload.instructions,
        lecture_evidence=lecture_evidence,
    )

    if not summary or not summary.get("sections"):
        raise HTTPException(status_code=422, detail="Could not generate a summary. Make sure documents are analyzed.")

    # Safety net: strip any topic the user asked to exclude, in case the model
    # still included it despite the instruction.
    summary = _apply_summary_exclusions(summary, payload.instructions)

    # Safety net: strip sections about material outside the SELECTED documents
    # (e.g. chapters the past exams cover but the student didn't pick).
    summary = _apply_summary_scope(summary, intelligence.get("document_analyses", []), source_reader=reader)
    if not summary.get("sections"):
        raise HTTPException(status_code=422, detail="No topics remain after applying your selection and exclusions.")

    # Replace the LLM's eyeballed exam weights with values DERIVED from the past
    # exams' topic weights (when past exams are available), so the percentages
    # are traceable rather than guessed. Only the weights of topics inside the
    # selected scope count, so a one-chapter summary's percentages aren't
    # diluted by the chapters the student left out.
    summary["sections"] = _derive_section_exam_weights(
        summary.get("sections", []),
        scoped_hist,
    )

    # Name the summary after the documents/chapters it was generated from
    # (in the order they were selected), so it's identifiable in the list.
    doc_titles = [d.get('title', '') for d in reader.scope['documents']]
    title = _compose_summary_title(doc_titles, summary.get("title"))
    summary["title"] = title

    _require_document_foundation(payload.course_id, uid, foundation['revision'])
    doc_db_id = db_client.save_summary(payload.user_id, payload.course_id, {
        "summaryId": summary_id,
        "title": title,
        "overview": summary.get("overview", ""),
        "sections": summary.get("sections", []),
        "keyTerms": summary.get("keyTerms", []),
        "examFocus": summary.get("examFocus", []),
        "foundationRevision": foundation['revision'],
        "sourceSummary": _source_summary(intelligence),
        "contextCoverage": reader.coverage(),
        "sourceScope": reader.snapshot(),
        "sourceCoverage": reader.coverage(),
        "modelId": settings.OPENROUTER_MODEL,
        "promptVersion": "2026-10-09",
        "createdAt": int(_time.time() * 1000),
    }, expected_foundation_revision=foundation['revision'])

    return {"status": "success", "summary_id": summary_id, "doc_id": doc_db_id, **summary}


@app.get("/api/summaries/list/{course_id}")
def list_summaries(course_id: str, uid: str = Depends(require_uid)):
    items = owned_only(db_client.get_course_summaries(course_id, user_id=uid), uid)
    safe = [{
        "id": s.get("id"),
        "summaryId": s.get("summaryId"),
        "title": s.get("title"),
        "sectionCount": len(s.get("sections", [])),
        "createdAt": s.get("createdAt"),
    } for s in items]
    return {"status": "success", "summaries": safe}


@app.get("/api/summaries/detail/{doc_id}")
def get_summary_detail(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_summary(doc_id), uid, "Summary")
    s = db_client.get_summary(doc_id)
    if not s:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"status": "success", "summary": s}


@app.delete("/api/summaries/{doc_id}")
def delete_summary_endpoint(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_summary(doc_id), uid, "Summary")
    s = db_client.get_summary(doc_id)
    if not s:
        raise HTTPException(status_code=404, detail="Summary not found")
    db_client.delete_summary(doc_id)
    logger.info(f"Summary {doc_id} deleted.")
    return {"status": "success", "deleted": doc_id}


from src.utils.latex_text import _UNICODE_LATEX, _LATEX_SPECIALS


def _latex_escape(s, keep_unknown_unicode: bool = False) -> str:
    """Escape text for LaTeX.

    For pdflatex (default), unknown non-ASCII is dropped (pdflatex can't render
    it and would hard-fail). For XeLaTeX (keep_unknown_unicode=True), unknown
    non-ASCII — e.g. Arabic — is kept verbatim so a Unicode font can render it.
    Known math/typographic symbols are always mapped to LaTeX equivalents."""
    if not s:
        return ""
    out = []
    for ch in str(s):
        if ch in _LATEX_SPECIALS:
            out.append(_LATEX_SPECIALS[ch])
        elif ch in _UNICODE_LATEX:
            out.append(_UNICODE_LATEX[ch])
        elif ord(ch) > 127:
            out.append(ch if keep_unknown_unicode else "")
        else:
            out.append(ch)
    return "".join(out)


def _md_inline_to_latex(s: str) -> str:
    """Convert the AI's inline markdown into LaTeX. Runs AFTER _latex_escape
    (which leaves * and ` untouched), so the content inside is already safe:
    **bold** -> \\textbf, *italic* -> \\textit, `code` -> \\texttt."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\\textit{\1}", s)
    s = re.sub(r"`([^`\n]+)`", r"\\texttt{\1}", s)
    return s


def _summary_to_latex(summary: dict) -> str:
    from src.utils.pdf_response import unicode_font_preamble
    def esc(value):
        body = _md_inline_to_latex(_latex_escape(value, keep_unknown_unicode=True))
        return r"\textarabic{\upshape " + body + "}" if any("\u0600" <= c <= "\u06ff" for c in str(value or "")) else body
    parts = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[a4paper,margin=2.2cm]{geometry}",
        *unicode_font_preamble(),
        r"\usepackage{enumitem}",
        r"\usepackage{parskip}",
        r"\usepackage{eso-pic}",
        r"\usepackage{xcolor}",
        r"\AddToShipoutPictureFG{\AtPageLowerLeft{\put(28,20){\textcolor{gray}{\small Mudaris}}}}",
        r"\begin{document}",
        r"\begin{center}{\LARGE\bfseries " + esc(summary.get("title", "Study Summary")) + r"}\end{center}",
        r"\vspace{0.4em}",
    ]
    if summary.get("overview"):
        parts.append(esc(summary["overview"]))
    if summary.get("examFocus"):
        parts.append(r"\section*{Focus for the exam}")
        parts.append(r"\begin{itemize}[leftmargin=*]")
        for f in summary["examFocus"]:
            parts.append(r"\item " + esc(f))
        parts.append(r"\end{itemize}")
    for i, sec in enumerate(summary.get("sections", []), 1):
        parts.append(r"\section*{" + f"{i}. " + esc(sec.get("heading", "")) + r"}")
        like = sec.get("examLikelihood", "")
        weight = sec.get("examWeight", 0)
        if like:
            note = f"exam likelihood: {esc(like)}"
            if weight:
                note += f" (~{int(weight)}\\% of exam)"
            parts.append(r"{\small\itshape " + note + r"}\par\vspace{0.3em}")
        if sec.get("content"):
            parts.append(esc(sec["content"]))
        if sec.get("keyPoints"):
            parts.append(r"\begin{itemize}[leftmargin=*]")
            for p in sec["keyPoints"]:
                parts.append(r"\item " + esc(p))
            parts.append(r"\end{itemize}")
    if summary.get("keyTerms"):
        parts.append(r"\section*{Key Terms}")
        parts.append(r"\begin{description}")
        for t in summary["keyTerms"]:
            parts.append(r"\item[" + esc(t.get("term", "")) + r"] " + esc(t.get("definition", "")))
        parts.append(r"\end{description}")
    parts.append(r"\end{document}")
    return "\n".join(parts)


@app.get("/api/summaries/{doc_id}/pdf")
def get_summary_pdf(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_summary(doc_id), uid, "Summary")
    from src.utils.pdf_response import compile_pdf_response
    summary = assert_owner(db_client.get_summary(doc_id), uid, "Summary")
    return compile_pdf_response(_summary_to_latex(summary), summary.get("summaryId", doc_id), engine="xelatex")


def _audio_to_latex(rec: dict) -> str:
    """Build a printable LaTeX document that mirrors the UI's audio view: the AI
    analysis only — Lecture Summary, Exam Hints, Key Emphasis, Chapter Breakdown
    (no raw transcript).

    A plain left-to-right document (like the web UI). Compiled with XeLaTeX (see
    get_audio_pdf) with a Unicode font, so the professor's verbatim quotes — which
    may be Arabic — render correctly inline instead of being stripped, while the
    summary/headings stay English."""
    from src.utils.pdf_response import unicode_font_preamble
    insights = rec.get("insights") or {}
    title = rec.get("title", "Lecture Recording")

    # Escape that PRESERVES non-ASCII (Arabic etc.) so XeLaTeX can render quotes.
    esc = lambda x: _latex_escape(x, keep_unknown_unicode=True)

    # Arabic-aware: if a field contains Arabic, wrap it in \textarabic so XeLaTeX
    # shapes it correctly (RTL + the Arabic font); otherwise leave it in the
    # default serif font so Latin text keeps the original look.
    def aw(x: str) -> str:
        body = esc(x)
        if any(0x0600 <= ord(c) <= 0x06FF for c in (x or "")):
            # \upshape: Arabic (Arial) has no italic face, so in an italic
            # context (e.g. quotes) it would fall back to tofu boxes. Force
            # upright so the Arabic always renders.
            return r"\textarabic{\upshape " + body + r"}"
        return body

    def quoted(x: str) -> str:
        """Quote a snippet correctly for its script. Arabic uses guillemets
        («…») INSIDE the RTL run so the marks sit on the right side (curly
        quotes placed outside land on the wrong side); Latin uses ``…''."""
        if any(0x0600 <= ord(c) <= 0x06FF for c in (x or "")):
            return "\\textarabic{\\upshape «" + esc(x) + "»}"
        return r"``" + esc(x) + r"''"

    parts = [
        r"\documentclass[12pt,a4paper]{article}",
        r"\usepackage[a4paper,margin=2.2cm]{geometry}",
        *unicode_font_preamble(),
        r"\usepackage{enumitem}",
        r"\usepackage{parskip}",
        r"\usepackage{eso-pic}",
        r"\usepackage{xcolor}",
        r"\AddToShipoutPictureFG{\AtPageLowerLeft{\put(28,20){\textcolor{gray}{\small Mudaris}}}}",
        r"\begin{document}",
        r"\begin{center}{\LARGE\bfseries " + aw(title) + r"}\\[0.3em]"
        + r"{\small\itshape Lecture analysis}\end{center}",
        r"\vspace{0.5em}",
    ]

    summary = insights.get("summary") or ""
    if summary.strip():
        parts.append(r"\section*{Lecture Summary}")
        for para in re.split(r"\n\n+", summary):
            if para.strip():
                parts.append(aw(para.strip()) + r"\par\vspace{0.3em}")

    hints = insights.get("examHints") or []
    if hints:
        parts.append(r"\section*{Exam Hints}")
        parts.append(r"\begin{itemize}[leftmargin=*]")
        for h in hints:
            line = aw(h.get("hint", ""))
            conf = h.get("confidence")
            if isinstance(conf, (int, float)) and conf:
                line += r"\hfill {\small\itshape (" + str(int(conf * 100)) + r"\% confidence)}"
            if h.get("source"):
                line += r"\\{\small\itshape " + quoted(h["source"]) + r"}"
            parts.append(r"\item " + line)
        parts.append(r"\end{itemize}")

    emphasis = insights.get("keyEmphasis") or []
    if emphasis:
        parts.append(r"\section*{Key Emphasis}")
        parts.append(r"\begin{itemize}[leftmargin=*]")
        for e in emphasis:
            level = (e.get("emphasisLevel") or "").strip()
            lbl = f"[{esc(level)}] " if level else ""
            line = r"\textbf{" + lbl + aw(e.get("topic", "")) + r"}"
            if e.get("quote"):
                line += r"\\{\small\itshape " + quoted(e["quote"]) + r"}"
            parts.append(r"\item " + line)
        parts.append(r"\end{itemize}")

    chapters = insights.get("chapterMapping") or []
    if chapters:
        parts.append(r"\section*{Chapter Breakdown}")
        for ch in chapters:
            parts.append(r"\subsection*{" + aw(ch.get("chapter", "")) + r"}")
            segs = ch.get("segments") or []
            if segs:
                parts.append(r"\begin{itemize}[leftmargin=*]")
                for seg in segs:
                    parts.append(r"\item " + aw(seg))
                parts.append(r"\end{itemize}")

    parts.append(r"\end{document}")
    return "\n".join(parts)


@app.get("/api/audio/{rec_id}/pdf")
def get_audio_pdf(rec_id: str, uid: str = Depends(require_uid)):
    """Compile and serve a PDF of a recording's analysis + transcript."""
    assert_owner(db_client.get_audio_recording(rec_id), uid, "Recording")
    from src.utils.pdf_response import compile_pdf_response
    rec = assert_owner(db_client.get_audio_recording(rec_id), uid, "Recording")
    if not rec.get("insights"):
        raise HTTPException(status_code=409, detail="This recording has not been analyzed yet. Retry its analysis first.")
    return compile_pdf_response(_audio_to_latex(rec), rec.get("title") or rec_id, engine="xelatex")


# ──────────────────────────────────────────────────
# Weekly lecture schedule (Sunday–Thursday)
# ──────────────────────────────────────────────────

_VALID_DAYS = {"sunday", "monday", "tuesday", "wednesday", "thursday"}

def _to_minutes(hhmm: str):
    try:
        if not re.fullmatch(r"\d{2}:\d{2}", hhmm or ""):
            return None
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m if 0 <= h <= 23 and 0 <= m <= 59 else None
    except Exception:
        return None

class ScheduleEntryRequest(BaseModel):
    user_id: str
    day: str
    start_time: str = ""
    end_time: str = ""
    hall: str = ""
    courseId: str = ""
    title: str = ""

@app.post("/api/schedule")
def create_schedule_entry(payload: ScheduleEntryRequest, uid: str = Depends(require_uid)):
    payload.user_id = uid  # ignore any client-supplied owner
    import time as _time
    day = (payload.day or "").strip().lower()
    if day not in _VALID_DAYS:
        raise HTTPException(status_code=400, detail="Day must be Sunday through Thursday.")

    start = _to_minutes(payload.start_time.strip())
    end = _to_minutes(payload.end_time.strip())
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="Start and end time are required (HH:MM).")
    if end <= start:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    if payload.courseId.strip():
        _require_course(payload.courseId.strip(), uid)

    entry = {
        "day": day,
        "startTime": payload.start_time.strip(),
        "endTime": payload.end_time.strip(),
        "hall": payload.hall.strip(),
        "courseId": payload.courseId.strip(),
        "title": payload.title.strip(),
        "createdAt": int(_time.time() * 1000),
    }
    from src.database.firebase_client import DataConflict
    try:
        entry_id = db_client.save_schedule_entry_atomic(uid, entry)
    except DataConflict as exc:
        raise HTTPException(status_code=409, detail="The schedule changed or this time overlaps another lecture. Reload and retry.") from exc
    return {"status": "success", "id": entry_id, **entry}


def _check_schedule_overlap(user_id: str, day: str, start: int, end: int, exclude_id=None):
    """Raise 409 if [start,end) overlaps another lecture on the same day."""
    for e in db_client.get_user_schedule_entries(user_id):
        if e.get("id") == exclude_id or e.get("day") != day:
            continue
        es = _to_minutes(e.get("startTime", ""))
        ee = _to_minutes(e.get("endTime", ""))
        if es is None or ee is None:
            continue
        if start < ee and end > es:
            raise HTTPException(
                status_code=409,
                detail=f"That time overlaps an existing lecture ({e.get('startTime')}–{e.get('endTime')}) on {day.capitalize()}.",
            )


@app.put("/api/schedule/{entry_id}")
def update_schedule_entry(entry_id: str, payload: ScheduleEntryRequest, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_schedule_entry(entry_id), uid, "Schedule entry")
    payload.user_id = uid  # ignore any client-supplied owner
    day = (payload.day or "").strip().lower()
    if day not in _VALID_DAYS:
        raise HTTPException(status_code=400, detail="Day must be Sunday through Thursday.")
    start = _to_minutes(payload.start_time.strip())
    end = _to_minutes(payload.end_time.strip())
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="Start and end time are required (HH:MM).")
    if end <= start:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    if payload.courseId.strip():
        _require_course(payload.courseId.strip(), uid)

    data = {
        "day": day,
        "startTime": payload.start_time.strip(),
        "endTime": payload.end_time.strip(),
        "hall": payload.hall.strip(),
        "courseId": payload.courseId.strip(),
        "title": payload.title.strip(),
    }
    from src.database.firebase_client import DataConflict
    try:
        db_client.save_schedule_entry_atomic(uid, data, entry_id=entry_id)
    except DataConflict as exc:
        raise HTTPException(status_code=409, detail="The schedule changed or this time overlaps another lecture. Reload and retry.") from exc
    return {"status": "success", "id": entry_id, **data}


@app.get("/api/schedule/{user_id}")
def list_schedule(user_id: str, uid: str = Depends(require_uid)):
    user_id = uid  # path value is advisory; the token is authoritative
    return {"status": "success", "entries": db_client.get_user_schedule_entries(user_id)}


@app.delete("/api/schedule/{entry_id}")
def delete_schedule_entry(entry_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_schedule_entry(entry_id), uid, "Schedule entry")
    db_client.delete_schedule_entry(entry_id)
    return {"status": "success", "deleted": entry_id}


# ──────────────────────────────────────────────────
# AI Tutor — chat grounded in the course's materials
# ──────────────────────────────────────────────────

class TutorChatRequest(BaseModel):
    user_id: str
    course_id: str
    chat_id: str = ""
    messages: List[Dict[str, str]] = []
    # Selected resource ids (None = include all of that type)
    document_ids: Optional[List[str]] = None
    recording_ids: Optional[List[str]] = None
    historical_exam_ids: Optional[List[str]] = None
    tutorial_ids: Optional[List[str]] = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, messages):
        if len(messages) > 200:
            raise ValueError("This conversation is too long. Please start a new chat.")
        for message in messages:
            if message.get("role") not in {"user", "assistant"}:
                raise ValueError("Messages must use user or assistant roles.")
            if not message.get("content", "").strip() or len(message["content"]) > 20000:
                raise ValueError("Messages must contain between 1 and 20000 characters.")
        return messages

@app.post("/api/tutor/chat")
def tutor_chat(payload: TutorChatRequest, uid: str = Depends(require_uid)):
    payload.user_id = uid  # ignore any client-supplied owner
    foundation = _require_document_foundation(payload.course_id, uid)
    _require_selected_supporting_ready(payload.course_id, uid,
        foundation_revision=foundation['revision'],
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids, audio_ids=payload.recording_ids)
    import time as _time
    if not payload.messages:
        raise HTTPException(status_code=400, detail="No messages provided.")

    if payload.chat_id:
        chat = assert_owner(db_client.get_tutor_chat(payload.chat_id), uid, "Chat")
        if chat.get("courseId") != payload.course_id:
            raise HTTPException(status_code=404, detail="Chat not found")
        saved_messages = chat.get("messages", [])
        # Accept one new user message after the server-owned history, never a
        # client replacement of an existing conversation.
        if payload.messages[:-1] != saved_messages or payload.messages[-1].get("role") != "user":
            raise HTTPException(status_code=409, detail="This conversation changed. Reopen it before sending again.")
    elif len(payload.messages) != 1 or payload.messages[-1].get("role") != "user":
        raise HTTPException(status_code=400, detail="Start a new conversation with one user message.")

    # Validate the original selection before the resource bundle can filter IDs.
    # Only omitted/null or intentionally empty selections use the foundation.
    selected_documents = payload.document_ids or [d['id'] for d in foundation['documents']]
    reader = _source_reader(payload.course_id, uid, tutor_agent, selected_documents)

    # The tutor reads its resources DIRECTLY from the DBs, restricted to the
    # specific lectures and past exams the student selected.
    resources = db_client.get_tutor_resources(
        payload.course_id,
        document_ids=payload.document_ids,
        recording_ids=payload.recording_ids,
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids,
        user_id=payload.user_id,
    )
    if not resources.get('documents'):
        resources['documents'] = foundation['documents']
    resources['course'] = foundation['course']

    lecture_evidence = _source_prepare(reader, 'focused', '\n'.join(m['content'] for m in payload.messages[-12:]))
    try:
        grounded = tutor_agent.reply_grounded(resources, payload.messages, lecture_evidence=lecture_evidence)
        reply = grounded['reply']
        refs = reader.validate_refs(grounded['sourceRefs'])
        if refs:
            _source_verify(reader, [{'reply': reply, 'sourceRefs': refs}])
        else:
            reader.verify_nonacademic_reply(reply)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as e:
        logger.error(f"Tutor reply failed: {e}")
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")

    if not isinstance(reply, str) or not reply.strip():
        raise HTTPException(status_code=502, detail="The tutor returned an empty response. Please retry.")

    # Persist the conversation in its own tutor_chats table
    full_messages = list(payload.messages) + [{"role": "assistant", "content": reply}]
    _require_document_foundation(payload.course_id, uid, foundation['revision'])
    now = int(_time.time() * 1000)
    source_turn = {'messageIndex': len(payload.messages), 'sourceRefs': refs,
                   'sourceScope': reader.snapshot(), 'sourceCoverage': reader.coverage()}
    if payload.chat_id:
        from src.database.firebase_client import DataConflict
        try:
            db_client.append_tutor_messages(uid, payload.course_id, payload.chat_id, saved_messages,
                                           [payload.messages[-1], {"role": "assistant", "content": reply}], now,
                                           foundation_revision=foundation['revision'],
                                           expected_foundation_revision=foundation['revision'], source_turn=source_turn)
        except DataConflict as exc:
            raise HTTPException(status_code=409, detail="This conversation changed. Reopen it before sending again.") from exc
        chat_id = payload.chat_id
    else:
        first_user = next((m.get("content", "") for m in payload.messages if m.get("role") == "user"), "New chat")
        title = (first_user[:60] + "…") if len(first_user) > 60 else (first_user or "New chat")
        chat_id = db_client.save_tutor_chat(payload.user_id, payload.course_id, {
            "title": title,
            "messages": full_messages,
            "sourceTurns": [source_turn],
            "foundationRevision": foundation['revision'],
            "createdAt": now,
            "updatedAt": now,
        }, expected_foundation_revision=foundation['revision'])

    return {"status": "success", "reply": reply, "chat_id": chat_id, "sourceRefs": refs}


@app.get("/api/tutor/chats/{user_id}/{course_id}")
def list_tutor_chats(user_id: str, course_id: str, uid: str = Depends(require_uid)):
    user_id = uid  # path value is advisory; the token is authoritative
    chats = db_client.get_user_course_tutor_chats(user_id, course_id)
    safe = sorted(
        [{
            "id": c.get("id"),
            "title": c.get("title", "Chat"),
            "messageCount": len(c.get("messages", [])),
            "updatedAt": c.get("updatedAt", c.get("createdAt", 0)),
        } for c in chats],
        key=lambda x: x["updatedAt"], reverse=True,
    )
    return {"status": "success", "chats": safe}


@app.get("/api/tutor/chat/{chat_id}")
def get_tutor_chat_detail(chat_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_tutor_chat(chat_id), uid, "Chat")
    chat = db_client.get_tutor_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "success", "chat": chat}


@app.delete("/api/tutor/chat/{chat_id}")
def delete_tutor_chat_endpoint(chat_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_tutor_chat(chat_id), uid, "Chat")
    db_client.delete_tutor_chat(chat_id)
    return {"status": "success", "deleted": chat_id}


if __name__ == "__main__":
    # reload=False: the auto-reloader watches the whole backend/ tree and would
    # restart (dropping in-flight requests → "failed to fetch") whenever an
    # uploaded file is written under backend/uploads/. Long exam generations
    # must not be interrupted, so reload is off. Set MUDARIS_RELOAD=1 to enable
    # it during active development.
    _reload = os.getenv("MUDARIS_RELOAD", "0") == "1"
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=_reload)
