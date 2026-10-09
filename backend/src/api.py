import os
import sys
import re
import logging
import time as _time
import math
import threading
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from pathlib import Path

# إضافة مسار المشروع الرئيسي لحل أي تعارضات في الاستدعاء تلقائياً
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 1. التحقق من وجود المكتبات الأساسية لتشغيل الخادم
try:
    from fastapi import FastAPI, HTTPException, Depends
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


def _require_sources(intelligence: dict, supplemental_text: str = "") -> None:
    groups = ("document_analyses", "audio_insights", "historical_analyses", "tutorial_analyses",
              "document_texts", "historical_texts", "tutorial_texts")
    if not supplemental_text.strip() and not any(intelligence.get(key) for key in groups):
        raise HTTPException(status_code=422, detail="Select at least one successfully analyzed source before generating.")


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
    try:
        yield
    finally:
        await run_in_threadpool(_close_audio_jobs)


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


@app.post("/api/documents/upload")
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
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path, user_id=uid)

    doc_data = {
        "title": doc_title,
        "fileType": file_type,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "status": "processing",
        "uploadedAt": int(_time.time() * 1000),
    }
    if lecture_id:
        doc_data["lectureId"] = lecture_id

    doc_id = _save_uploaded_record(db_client.save_document, user_id, course_id, doc_data)
    logger.info(f"Document {doc_id} saved, starting processing...")

    try:
        extracted_text = await run_in_threadpool(doc_processor.extract_text, file_bytes, file_type)

        db_client.update_document(doc_id, {"extractedText": extracted_text})
        page_images = []
        if file_type == "pdf":
            from src.utils.pdf_extract import pdf_to_image_uris
            page_images = await run_in_threadpool(pdf_to_image_uris, file_bytes)

        # If we couldn't read any text, fail clearly instead of saving an empty
        # "completed" doc with 0 topics / 0 chapters.
        from src.utils.pdf_extract import is_meaningful_text
        if not is_meaningful_text(extracted_text) and not page_images:
            msg = (
                "Couldn't read text from this file. If it's a scanned or "
                "image-only PDF, its pages could not be read."
            )
            db_client.update_document(doc_id, {
                "status": "failed",
                "errorMessage": msg,
            })
            raise HTTPException(status_code=422, detail=msg)

        course_title = course.get("title", course_id)

        # For PDFs, also give the analyzer the page images so it can read
        # equations, diagrams, figures, and code (not just extracted text).
        analysis = await run_in_threadpool(doc_processor.analyze_document, extracted_text, course_title, image_uris=page_images)

        _require_course(course_id, uid)

        db_client.update_document(doc_id, {
            "extractedText": extracted_text,
            "analysis": analysis,
            "status": "completed",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Document {doc_id} processed successfully.")

        # A new document changes the course scope — refresh the in/out-of-course
        # tags on this course's already-analyzed past exams.
        _recheck_past_exam_scope(course_id, user_id)

        return {
            "status": "success",
            "document_id": doc_id,
            "title": doc_title,
            "file_type": file_type,
            "analysis": analysis,
        }

    except HTTPException:
        # Already handled (e.g. unreadable file) — keep the clean status/message.
        raise
    except DataSizeConflict as exc:
        db_client.update_document(doc_id, {"status": "failed", "errorMessage": "This file is too large to save safely. Split it into smaller parts."})
        raise HTTPException(status_code=413, detail="This file is too large to save safely. Split it into smaller parts.") from exc
    except DataConflict:
        raise
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        db_client.update_document(doc_id, {
            "status": "failed",
            "errorMessage": "Processing failed. Your saved material is available to retry.",
        })
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")


@app.get("/api/documents/{course_id}")
def get_course_documents(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    docs = owned_only(db_client.get_course_documents(course_id, user_id=uid), uid)
    return {"status": "success", "documents": docs}


@app.get("/api/documents/detail/{doc_id}")
def get_document_detail(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_document(doc_id), uid, "Document")
    doc = db_client.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "success", "document": doc}


@app.post("/api/documents/{doc_id}/reanalyze")
def reanalyze_document(doc_id: str, uid: str = Depends(require_uid)):
    """Re-run the AI analysis on a document using its already-extracted text.

    Lets the user retry when the first analysis failed or came back empty
    (without having to re-upload the file).
    """
    assert_owner(db_client.get_document(doc_id), uid, "Document")
    doc = db_client.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    text = doc.get("extractedText", "")
    images = []
    if doc.get("fileType") == "pdf" and doc.get("storagePath"):
        try:
            from src.utils.pdf_extract import pdf_to_image_uris
            path = db_client.download_file_from_storage(doc["storagePath"], uid)
            images = pdf_to_image_uris(path.read_bytes())
        except FileNotFoundError:
            pass
    if (not text or len(text.strip()) < 20) and not images:
        raise HTTPException(
            status_code=422,
            detail="No extracted text is available for this document — please re-upload it.",
        )

    db_client.update_document(doc_id, {"status": "processing", "errorMessage": ""})

    try:
        course_id = doc.get("courseId", "")
        course_title = _require_course(course_id, uid).get("title", course_id)

        analysis = doc_processor.analyze_document(text, course_title, image_uris=images)

        db_client.update_document(doc_id, {
            "analysis": analysis,
            "status": "completed",
            "errorMessage": "",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Document {doc_id} re-analyzed successfully.")
        _recheck_past_exam_scope(course_id, uid)
        return {"status": "success", "document_id": doc_id, "analysis": analysis}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Re-analysis failed for {doc_id}: {e}")
        db_client.update_document(doc_id, {
            "status": "failed",
            "errorMessage": "Processing failed. Your saved material is available to retry.",
        })
        raise HTTPException(
            status_code=500,
            detail="Processing could not finish. Please retry or check backend configuration.",
        )


@app.delete("/api/documents/{doc_id}")
def delete_document_endpoint(doc_id: str, uid: str = Depends(require_uid)):
    assert_owner(db_client.get_document(doc_id), uid, "Document")
    doc = db_client.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    _require_record_storage(doc, uid, "documents")
    storage_path = doc.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path, user_id=uid)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
            raise HTTPException(status_code=503, detail="File cleanup failed. Please retry.")
    db_client.delete_document(doc_id)
    _recheck_past_exam_scope(doc.get("courseId", ""), uid)
    logger.info(f"Document {doc_id} deleted.")
    return {"status": "success", "deleted": doc_id}


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

@app.post("/api/historical-exams/upload")
async def upload_historical_exam(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    title: str = Form(""), uid: str = Depends(require_uid),):
    user_id = uid  # the token decides the owner, not the form field
    course = _require_course(course_id, uid)
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

    storage_path = _upload_path(uid, course_id, "historical_exams", file.filename)
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path, user_id=uid)

    exam_data = {
        "title": exam_title,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "status": "processing",
        "uploadedAt": int(_time.time() * 1000),
    }

    exam_id = _save_uploaded_record(db_client.save_historical_exam, user_id, course_id, exam_data)
    logger.info(f"Historical exam {exam_id} saved, starting analysis...")

    try:
        course_title = course.get("title", course_id)

        if is_pdf:
            extracted_text = await run_in_threadpool(hist_analyzer.extract_exam_text, file_bytes)
            # Render the exam pages to images so the analyzer (vision model) can
            # read equations, diagrams, figures, and code — not just the text.
            from src.utils.pdf_extract import pdf_to_image_uris
            page_images = await run_in_threadpool(pdf_to_image_uris, file_bytes)
        else:
            # A photo / image of the exam: there's no embedded text, so the
            # vision model reads the page straight from the (normalized) image.
            from src.utils.pdf_extract import image_to_image_uri
            extracted_text = ""
            page_images = [image_to_image_uri(file_bytes)]

        # Pass the course's CURRENT lecture-document analyses so the analyzer can
        # tag each past-exam topic as in/out of the course as it is taught now.
        course_intel = db_client.get_course_intelligence(course_id, user_id=user_id)
        document_insights = course_intel.get("document_analyses", [])

        db_client.update_historical_exam(exam_id, {"extractedText": extracted_text})
        analysis = await run_in_threadpool(hist_analyzer.analyze_exam,
            extracted_text, course_title, image_uris=page_images,
            document_insights=document_insights,
        )

        _require_course(course_id, uid)
        db_client.update_historical_exam(exam_id, {
            "extractedText": extracted_text,
            "analysis": analysis,
            "status": "completed",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Historical exam {exam_id} analyzed successfully.")

        return {
            "status": "success",
            "exam_id": exam_id,
            "title": exam_title,
            "analysis": analysis,
        }

    except DataSizeConflict as exc:
        db_client.update_historical_exam(exam_id, {"status": "failed", "errorMessage": "This file is too large to save safely. Split it into smaller parts."})
        raise HTTPException(status_code=413, detail="This file is too large to save safely. Split it into smaller parts.") from exc
    except DataConflict:
        raise
    except Exception as e:
        logger.error(f"Historical exam analysis failed: {e}")
        db_client.update_historical_exam(exam_id, {
            "status": "failed",
            "errorMessage": "Processing failed. Your saved material is available to retry.",
        })
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")


@app.get("/api/historical-exams/{course_id}")
def get_course_historical_exams(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    exams = owned_only(db_client.get_course_historical_exams(course_id, user_id=uid), uid)
    return {"status": "success", "historical_exams": exams}


# ──────────────────────────────────────────────────
# Tutorials — ungraded practice problems (ideas only, no marks/format)
# ──────────────────────────────────────────────────

@app.post("/api/tutorials/upload")
async def upload_tutorial(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    title: str = Form(""), uid: str = Depends(require_uid),):
    """Upload a tutorial / practice sheet (PDF, PPTX, DOCX). We analyze it for
    TOPICS and worked-problem IDEAS only — it never contributes grading weight
    or exam format (those come from past exams). Reuses the document analyzer."""
    user_id = uid  # the token decides the owner, not the form field
    course = _require_course(course_id, uid)
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

    storage_path = _upload_path(uid, course_id, "tutorials", file.filename)
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path, user_id=uid)

    tut_data = {
        "title": tut_title,
        "fileType": file_type,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "status": "processing",
        "uploadedAt": int(_time.time() * 1000),
    }

    tut_id = _save_uploaded_record(db_client.save_tutorial, user_id, course_id, tut_data)
    logger.info(f"Tutorial {tut_id} saved, starting analysis...")

    try:
        extracted_text = await run_in_threadpool(doc_processor.extract_text, file_bytes, file_type)
        db_client.update_tutorial(tut_id, {"extractedText": extracted_text})

        from src.utils.pdf_extract import is_meaningful_text
        page_images = []
        if file_type == "pdf":
            from src.utils.pdf_extract import pdf_to_image_uris
            page_images = await run_in_threadpool(pdf_to_image_uris, file_bytes)

        # Allow image-only PDFs (vision will read them); only fail if neither
        # text nor page images are available.
        if not is_meaningful_text(extracted_text) and not page_images:
            msg = "Couldn't read this tutorial file. If it's a scanned/image-only PDF, it needs OCR."
            db_client.update_tutorial(tut_id, {"status": "failed", "errorMessage": msg})
            raise HTTPException(status_code=422, detail=msg)

        course_title = course.get("title", course_id)

        analysis = await run_in_threadpool(doc_processor.analyze_tutorial, extracted_text, course_title, image_uris=page_images)
        _require_course(course_id, uid)

        db_client.update_tutorial(tut_id, {
            "extractedText": extracted_text,
            "analysis": analysis,
            "status": "completed",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Tutorial {tut_id} analyzed successfully.")

        return {
            "status": "success",
            "tutorial_id": tut_id,
            "title": tut_title,
            "analysis": analysis,
        }

    except HTTPException:
        raise
    except DataSizeConflict as exc:
        db_client.update_tutorial(tut_id, {"status": "failed", "errorMessage": "This file is too large to save safely. Split it into smaller parts."})
        raise HTTPException(status_code=413, detail="This file is too large to save safely. Split it into smaller parts.") from exc
    except DataConflict:
        raise
    except Exception as e:
        logger.error(f"Tutorial analysis failed: {e}")
        db_client.update_tutorial(tut_id, {"status": "failed", "errorMessage": "Processing failed. Your saved material is available to retry."})
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")


@app.get("/api/tutorials/{course_id}")
def get_course_tutorials(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    tutorials = owned_only(db_client.get_course_tutorials(course_id, user_id=uid), uid)
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

    def checkpoint(data):
        if not db_client.audio_job_exists(owner, rec_id):
            raise FileNotFoundError("The recording or course was deleted.")
        db_client.update_audio_recording(rec_id, data)

    if not _AUDIO_WORK_SLOTS.acquire(timeout=1200):
        return False
    workdir = None
    try:
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
        insights = audio_agent.analyze_transcript(text, _resolve_course_title(course_id, owner))
        checkpoint({"transcript": transcript, "insights": insights, "status": "completed",
                    "errorMessage": "", "processedAt": int(_time.time() * 1000)})
        return True
    except FileNotFoundError:
        # A purge wins over an in-flight model request. Never recreate its row.
        return False
    except Exception:
        logger.exception("Audio processing failed")
        if db_client.audio_job_exists(owner, rec_id):
            checkpoint({"status": "failed", "errorMessage": "Processing failed. Your saved text can be retried."})
        return False
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        _AUDIO_WORK_SLOTS.release()


def _run_saved_audio_job(rec_id):
    record = db_client.get_audio_recording(rec_id)
    if record:
        _run_audio_pipeline(rec_id, record.get("courseId", ""),
                            url=record.get("sourceUrl"), had_title=record.get("hadTitle", True))


from src.utils.job_runner import AudioJobRunner
_audio_runner = AudioJobRunner(lambda: db_client, _run_saved_audio_job)


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



@app.post("/api/audio/upload")
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
    _require_course(course_id, uid)
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

    storage_path = _upload_path(uid, course_id, "audio", file.filename)
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path, user_id=uid)

    rec_data = {
        "title": audio_title,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "sourceType": "upload",
        "audioExt": audio_ext,
        "hadTitle": bool(title.strip()),
        "status": "queued",
        "uploadedAt": int(_time.time() * 1000),
    }
    if lecture_id:
        rec_data["lectureId"] = lecture_id

    rec_id = _save_uploaded_record(db_client.save_audio_recording, user_id, course_id, rec_data)

    if background == "1":
        logger.info(f"Audio recording {rec_id} saved; processing in background.")
        _spawn_audio_job(rec_id=rec_id, course_id=course_id, file_bytes=file_bytes, audio_ext=audio_ext)
        return {
            "status": "processing",
            "recording_id": rec_id,
            "title": audio_title,
            "message": "Transcription started — this can take a few minutes for long recordings.",
        }

    # Synchronous: transcribe + analyze now, return when finished (one at a time).
    logger.info(f"Audio recording {rec_id} saved; processing synchronously.")
    from starlette.concurrency import run_in_threadpool
    ok = await run_in_threadpool(_run_audio_pipeline, rec_id, course_id, file_bytes=file_bytes, audio_ext=audio_ext)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Could not transcribe \"{audio_title}\".")
    return {"status": "success", "recording_id": rec_id, "title": audio_title}


class AudioUrlRequest(BaseModel):
    user_id: str
    course_id: str
    video_url: str
    title: str = ""
    lecture_id: str = ""
    # "1" = download + analyze in the background; "0" = wait and return when done
    # (used by the multi-URL uploader so it can process one URL at a time).
    background: str = "1"


@app.post("/api/audio/upload-url")
def upload_audio_from_url(payload: AudioUrlRequest, uid: str = Depends(require_uid)):
    """Take a video/audio URL; download + extract audio to MP3 + transcribe +
    analyze. Runs in the background by default, or synchronously when the caller
    wants to process several URLs one at a time."""
    payload.user_id = uid  # ignore any client-supplied owner
    _require_course(payload.course_id, uid)
    _require_lecture(payload.lecture_id, payload.course_id, uid)
    import time as _time

    url = (payload.video_url or "").strip()
    try:
        from src.utils.media_download import validate_media_url
        validate_media_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    rec_data = {
        "title": payload.title or "Online Recording",
        "fileUrl": url,
        "storagePath": "",
        "sourceUrl": url,
        "sourceType": "url",
        "hadTitle": bool(payload.title.strip()),
        "fileSize": 0,
        "status": "queued",
        "uploadedAt": int(_time.time() * 1000),
    }
    if payload.lecture_id:
        rec_data["lectureId"] = payload.lecture_id

    rec_id = db_client.save_audio_recording(payload.user_id, payload.course_id, rec_data)

    if payload.background == "1":
        logger.info(f"Audio URL recording {rec_id}: queued background download for {url}")
        _spawn_audio_job(
            rec_id=rec_id, course_id=payload.course_id, url=url,
            had_title=bool(payload.title.strip()),
        )
        return {
            "status": "processing",
            "recording_id": rec_id,
            "title": payload.title or "Online Recording",
            "message": "Fetching and transcribing in the background — long videos can take a while.",
        }

    # Synchronous: download + transcribe + analyze now, return when finished.
    logger.info(f"Audio URL recording {rec_id}: processing synchronously for {url}")
    ok = _run_audio_pipeline(
        rec_id, payload.course_id, url=url, had_title=bool(payload.title.strip())
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Could not fetch/transcribe that URL.")
    return {"status": "success", "recording_id": rec_id}


class LectureNotesRequest(BaseModel):
    user_id: str
    course_id: str
    notes: str = Field(max_length=250000)
    title: str = ""
    lecture_id: str = ""


@app.post("/api/audio/upload-notes")
def upload_lecture_notes(payload: LectureNotesRequest, uid: str = Depends(require_uid)):
    """Typed lecture notes: the student writes what happened in the lecture and
    what the professor emphasized (e.g. "the prof said section 3 will come in
    the midterm"). The same AI that analyzes recordings runs on the text — no
    transcription step — and the insights are saved exactly like a recording's,
    so exam generation, the intelligence view, and the tutor all use them."""
    payload.user_id = uid  # ignore any client-supplied owner
    _require_course(payload.course_id, uid)
    _require_lecture(payload.lecture_id, payload.course_id, uid)
    import time as _time

    notes = (payload.notes or "").strip()
    if len(notes) < 20:
        raise HTTPException(
            status_code=400,
            detail="Please write at least a couple of sentences about the lecture.",
        )

    title = (payload.title or "").strip() or "Typed Lecture Notes"
    rec_data = {
        "title": title,
        "fileUrl": "",
        "storagePath": "",
        "sourceType": "notes",
        "fileSize": len(notes.encode("utf-8")),
        "status": "analyzing",
        # Store what the student typed BEFORE calling the AI. Unlike a recording
        # (whose audio file is still on disk if analysis fails), these notes exist
        # nowhere else — if we only saved them on success, a failed AI call would
        # throw away everything the student wrote and force them to retype it.
        "transcript": notes,
        "uploadedAt": int(_time.time() * 1000),
    }
    if payload.lecture_id:
        rec_data["lectureId"] = payload.lecture_id

    rec_id = db_client.save_audio_recording(payload.user_id, payload.course_id, rec_data)

    # Give the analyzer honest context: these are a student's notes ABOUT the
    # lecture, not a verbatim transcript — hints like "section 3 will come in
    # the midterm" should be treated as high-confidence exam signals.
    framed = _frame_notes(notes)
    try:
        insights = audio_agent.analyze_transcript(framed, _resolve_course_title(payload.course_id, uid))
        _require_course(payload.course_id, uid)
        db_client.update_audio_recording(rec_id, {
            "insights": insights,
            "status": "completed",
            "processedAt": int(_time.time() * 1000),
        })
    except Exception as e:
        # The typed notes stay on the record (saved above), so nothing the
        # student wrote is lost — the entry can be re-analyzed instead.
        logger.error(f"Notes analysis failed for {rec_id}: {e}")
        db_client.update_audio_recording(rec_id, {"status": "failed", "errorMessage": "Processing failed. Your saved material is available to retry."})
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")

    return {"status": "success", "recording_id": rec_id, "title": title}


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

    db_client.update_audio_recording(rec_id, {"status": "analyzing", "errorMessage": ""})

    is_notes = rec.get("sourceType") == "notes"
    text = _frame_notes(transcript) if is_notes else transcript

    try:
        insights = audio_agent.analyze_transcript(
            text, _resolve_course_title(rec.get("courseId", ""), uid)
        )
        assert_owner(db_client.get_audio_recording(rec_id), uid, "Recording")
        _require_course(rec.get("courseId", ""), uid)
        db_client.update_audio_recording(rec_id, {
            "insights": insights,
            "status": "completed",
            "errorMessage": "",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Audio/notes record {rec_id} re-analyzed successfully.")
        return {"status": "success", "recording_id": rec_id, "insights": insights}
    except Exception as e:
        logger.error(f"Re-analysis failed for {rec_id}: {e}")
        db_client.update_audio_recording(rec_id, {"status": "failed", "errorMessage": "Processing failed. Your saved material is available to retry."})
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")


@app.get("/api/audio/{course_id}")
def get_course_audio_recordings(course_id: str, uid: str = Depends(require_uid)):
    _require_course(course_id, uid)
    recordings = owned_only(db_client.get_course_audio_recordings(course_id, user_id=uid), uid)
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
    return ai_agent._sanitize_latex(tex)


def _make_compilable_answer_key(exam: dict) -> str:
    """Choose only a complete answer document whose temporary compile is cleaned."""
    from src.utils.pdf_response import check_tex_compiles
    exam_tex = exam.get("texContent", "") or ""
    exam_id = exam.get("examId", "exam")
    need = len(exam.get("questionStructure", []) or []) or len((exam.get("rubrics", {}) or {}).get("questions", {}) or {})
    if not need:
        raise ValueError("The exam has no complete question structure. Reopen or regenerate it.")
    try:
        rich = ai_agent._sanitize_latex(ai_agent.generate_answer_key(exam_tex, exam_id))
        if rich.count("Answer:") == need and check_tex_compiles(rich, exam_id + "-answers"):
            return rich
    except Exception:
        logger.warning("Rich answer-key generation or compilation failed")
    try:
        items = ai_agent.generate_answer_pairs(exam_tex, exam_id)
        if len(items) == need:
            safe = ai_agent._sanitize_latex(ai_agent._answers_to_latex(items, exam_id))
            if check_tex_compiles(safe, exam_id + "-answers"):
                return safe
    except Exception:
        logger.warning("Structured answer-key generation or compilation failed")
    rubrics = (exam.get("rubrics", {}) or {}).get("questions", {}) or {}
    if len(rubrics) == need and all(q.get("correct_answer") or q.get("criteria") for q in rubrics.values()):
        deterministic = _rubric_answer_key_tex(exam)
        if deterministic and check_tex_compiles(deterministic, exam_id + "-answers"):
            return deterministic
    raise ValueError("A complete answer-key PDF could not be prepared. Please retry.")


@app.post("/api/exams/generate-enhanced")
def generate_enhanced_exam_endpoint(payload: EnhancedExamGenerateRequest, uid: str = Depends(require_uid)):
    payload.user_id = uid  # ignore any client-supplied owner
    _require_course(payload.course_id, uid)
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

    _require_sources(intelligence, payload.transcripts)

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
        historical_analysis=intelligence.get("historical_analyses", []),
        document_texts=intelligence.get("document_texts", []),
        historical_texts=intelligence.get("historical_texts", []),
        tutorial_insights=intelligence.get("tutorial_analyses", []),
        tutorial_texts=intelligence.get("tutorial_texts", []),
        total_marks=payload.total_marks,
        exam_type=payload.exam_type,
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
        rubrics = ai_agent.generate_rubrics_from_tex(cleaned_tex, exam_id)

    # Normalize per-question marks so the exam totals EXACTLY the requested marks
    try:
        validate_exam_contract(cleaned_tex, rubrics, intelligence.get("historical_analyses", []))
        _normalize_marks(rubrics, payload.total_marks)
        cleaned_tex = align_printed_marks(cleaned_tex, rubrics)
        validate_exam_contract(cleaned_tex, rubrics, intelligence.get("historical_analyses", []), payload.total_marks)
        from src.utils.compile_pdf import validate_tex_source
        validate_tex_source(cleaned_tex)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    _require_course(payload.course_id, uid)

    questions_rubrics = rubrics.get("questions", {})
    question_structure = []
    for qid, qdata in sorted(questions_rubrics.items(), key=lambda item: int(item[0][1:])):
        question_structure.append({
            "id": qid,
            "type": qdata.get("question_type", "written"),
        })

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
            repaired = ai_agent.repair_latex(cleaned_tex)
            if repaired and repaired.strip() != cleaned_tex.strip():
                validate_exam_contract(repaired, rubrics, intelligence.get("historical_analyses", []), payload.total_marks)
                pdf_base64 = _try_compile(repaired)
                if pdf_base64 is not None:
                    cleaned_tex = repaired
                    logger.info(f"Exam {exam_id} compiled after repair.")
    except Exception as e:
        logger.warning(f"PDF compilation skipped: {e}")

    _require_course(payload.course_id, uid)
    db_client.save_secret_rubrics(payload.user_id, payload.course_id, exam_id, rubrics)
    doc_db_id = db_client.save_exam_flat(payload.user_id, payload.course_id, {
        "examId": exam_id,
        "texContent": cleaned_tex,
        "questionStructure": question_structure,
        "rubrics": rubrics,
        "totalMarks": payload.total_marks,
        "examType": payload.exam_type,
        "status": "generated",
        "pdfStatus": "ready" if pdf_base64 else "retry_required",
        "sourceSummary": _source_summary(intelligence),
        "contextCoverage": context_coverage(intelligence),
        "modelId": settings.OPENROUTER_MODEL,
        "promptVersion": "2026-10-09",
        "createdAt": int(_time.time() * 1000),
    })

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
    }


# ──────────────────────────────────────────────────
# Exam management: list, detail, questions, submit
# ──────────────────────────────────────────────────

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
    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Auto-rescue: older exams may have an empty questionStructure (rubrics were
    # truncated at generation time). Derive them from the stored LaTeX once.
    if not exam.get("questionStructure") and exam.get("texContent"):
        derived = ai_agent.generate_rubrics_from_tex(
            exam["texContent"], exam.get("examId", doc_id)
        )
        q = derived.get("questions", {}) if derived else {}
        if q:
            structure = [
                {"id": qid, "type": qd.get("question_type", "written")}
                for qid, qd in sorted(q.items())
            ]
            db_client.update_exam(doc_id, {
                "rubrics": derived,
                "questionStructure": structure,
            })
            exam["questionStructure"] = structure

    # Strip rubrics (secret) and the heavy/legacy pdfBase64 field
    safe = {k: v for k, v in exam.items() if k not in ("rubrics", "pdfBase64")}
    return {"status": "success", "exam": safe}


@app.get("/api/exams/{doc_id}/pdf")
def get_exam_pdf(doc_id: str, uid: str = Depends(require_uid)):
    """Recompile a saved exam's LaTeX to PDF on demand and serve it.
    Sanitizes the stored .tex first, which also rescues older exams that were
    saved before the sanitizer fix (conversational preamble / markdown fences)."""
    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    from src.utils.pdf_response import compile_temp_pdf, cleanup_temp_pdf, pdf_file_response
    from src.utils.ai_contracts import exam_question_numbers
    exam = assert_owner(db_client.get_exam(doc_id), uid, "Exam")
    tex = ai_agent._sanitize_latex(exam.get("texContent", ""))
    if not tex:
        raise HTTPException(status_code=404, detail="No LaTeX content for this exam")
    exam_name = exam.get("examId", doc_id)
    path, handed_to_response = None, False
    try:
        path = compile_temp_pdf(tex, exam_name)
        if not path:
            repaired = ai_agent.repair_latex(tex)
            if repaired and repaired.strip() != tex.strip():
                if exam_question_numbers(tex):
                    validate_exam_contract(repaired, exam.get("rubrics", {}), total_marks=exam.get("totalMarks"))
                path = compile_temp_pdf(repaired, exam_name)
                if path:
                    assert_owner(db_client.get_exam(doc_id), uid, "Exam")
                    db_client.update_exam(doc_id, {"texContent": repaired, "pdfStatus": "ready"})
        if not path:
            raise HTTPException(status_code=503, detail="PDF compilation failed or the compiler is unavailable. Please retry.")
        response = pdf_file_response(path, exam_name)
        handed_to_response = True
        return response
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
    answer_tex = exam.get("answerKeyTex", "") if exam.get("answerKeyQuestionCount") == num_q and num_q else ""
    path, handed_to_response = None, False
    try:
        if answer_tex:
            try:
                path = _compile_answer_tex(ai_agent._sanitize_latex(answer_tex), exam_name)
            except ValueError:
                # Legacy or unsupported cached keys must not poison every retry.
                answer_tex = ""
                path = None
        if not path:
            if not exam.get("texContent"):
                raise HTTPException(status_code=404, detail="No exam content to build answers from.")
            answer_tex = _make_compilable_answer_key(exam)
            path = _compile_answer_tex(answer_tex, exam_name)
            if path:
                assert_owner(db_client.get_exam(doc_id), uid, "Exam")
                db_client.update_exam(doc_id, {"answerKeyTex": answer_tex, "answerKeyQuestionCount": num_q})
        if not path:
            raise HTTPException(status_code=503, detail="Answer-key compilation failed or the compiler is unavailable. Please retry.")
        response = pdf_file_response(path, exam_name + "-answers")
        handed_to_response = True
        return response
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
    return {"status": "success", **intelligence}


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
    _require_course(payload.course_id, uid)
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

    _require_sources(intelligence)

    cards = ai_agent.generate_flashcards(
        academic_data={},
        topics=payload.topics,
        document_insights=intelligence.get("document_analyses", []),
        audio_insights=intelligence.get("audio_insights", []),
        historical_analysis=intelligence.get("historical_analyses", []),
        document_texts=intelligence.get("document_texts", []),
        historical_texts=intelligence.get("historical_texts", []),
        tutorial_insights=intelligence.get("tutorial_analyses", []),
        tutorial_texts=intelligence.get("tutorial_texts", []),
        count=payload.count,
    )

    if not cards:
        raise HTTPException(status_code=422, detail="Could not generate flashcards. Make sure documents are analyzed.")

    title = f"{len(cards)} cards · {_time.strftime('%b %d')}"
    _require_course(payload.course_id, uid)
    doc_db_id = db_client.save_flashcard_set(payload.user_id, payload.course_id, {
        "setId": set_id,
        "title": title,
        "cards": cards,
        "sourceSummary": _source_summary(intelligence),
        "contextCoverage": context_coverage(intelligence),
        "modelId": settings.OPENROUTER_MODEL,
        "promptVersion": "2026-10-09",
        "createdAt": int(_time.time() * 1000),
    })

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


def _apply_summary_scope(summary: dict, document_analyses: list) -> dict:
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
    _require_course(payload.course_id, uid)
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

    _require_sources(intelligence)

    summary = ai_agent.generate_summary(
        academic_data={},
        topics=payload.topics,
        document_insights=intelligence.get("document_analyses", []),
        audio_insights=intelligence.get("audio_insights", []),
        historical_analysis=intelligence.get("historical_analyses", []),
        document_texts=intelligence.get("document_texts", []),
        historical_texts=intelligence.get("historical_texts", []),
        tutorial_insights=intelligence.get("tutorial_analyses", []),
        tutorial_texts=intelligence.get("tutorial_texts", []),
        instructions=payload.instructions,
    )

    if not summary or not summary.get("sections"):
        raise HTTPException(status_code=422, detail="Could not generate a summary. Make sure documents are analyzed.")

    # Safety net: strip any topic the user asked to exclude, in case the model
    # still included it despite the instruction.
    summary = _apply_summary_exclusions(summary, payload.instructions)

    # Safety net: strip sections about material outside the SELECTED documents
    # (e.g. chapters the past exams cover but the student didn't pick).
    summary = _apply_summary_scope(summary, intelligence.get("document_analyses", []))
    if not summary.get("sections"):
        raise HTTPException(status_code=422, detail="No topics remain after applying your selection and exclusions.")

    # Replace the LLM's eyeballed exam weights with values DERIVED from the past
    # exams' topic weights (when past exams are available), so the percentages
    # are traceable rather than guessed. Only the weights of topics inside the
    # selected scope count, so a one-chapter summary's percentages aren't
    # diluted by the chapters the student left out.
    from src.utils.topic_scope import retag_topic_weights
    scoped_hist = retag_topic_weights(
        intelligence.get("historical_analyses", []),
        intelligence.get("document_analyses", []),
    )
    summary["sections"] = _derive_section_exam_weights(
        summary.get("sections", []),
        scoped_hist,
    )

    # Name the summary after the documents/chapters it was generated from
    # (in the order they were selected), so it's identifiable in the list.
    course_docs = owned_only(db_client.get_course_documents(payload.course_id, user_id=uid), uid)
    course_docs = [d for d in course_docs if d.get("status") == "completed" and d.get("analysis")]
    if payload.document_ids is not None:
        by_id = {d.get("id"): d for d in course_docs}
        course_docs = [by_id[i] for i in payload.document_ids if i in by_id]
    doc_titles = [(d.get("title") or "") for d in course_docs]
    title = _compose_summary_title(doc_titles, summary.get("title"))
    summary["title"] = title

    _require_course(payload.course_id, uid)
    doc_db_id = db_client.save_summary(payload.user_id, payload.course_id, {
        "summaryId": summary_id,
        "title": title,
        "overview": summary.get("overview", ""),
        "sections": summary.get("sections", []),
        "keyTerms": summary.get("keyTerms", []),
        "examFocus": summary.get("examFocus", []),
        "sourceSummary": _source_summary(intelligence),
        "contextCoverage": context_coverage(intelligence),
        "modelId": settings.OPENROUTER_MODEL,
        "promptVersion": "2026-10-09",
        "createdAt": int(_time.time() * 1000),
    })

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


# Common non-ASCII characters the LLM emits in technical summaries. pdflatex
# (T1 fontenc, no Unicode setup) hard-fails on these with "Unicode character
# not set up for use with LaTeX", so map them to LaTeX equivalents. Math symbols
# are wrapped in $...$; typographic ones map to their text form.
_UNICODE_LATEX = {
    # Greek lowercase
    "α": r"$\alpha$", "β": r"$\beta$", "γ": r"$\gamma$", "δ": r"$\delta$",
    "ε": r"$\varepsilon$", "ζ": r"$\zeta$", "η": r"$\eta$", "θ": r"$\theta$",
    "ι": r"$\iota$", "κ": r"$\kappa$", "λ": r"$\lambda$", "μ": r"$\mu$",
    "ν": r"$\nu$", "ξ": r"$\xi$", "π": r"$\pi$", "ρ": r"$\rho$",
    "σ": r"$\sigma$", "τ": r"$\tau$", "υ": r"$\upsilon$", "φ": r"$\varphi$",
    "χ": r"$\chi$", "ψ": r"$\psi$", "ω": r"$\omega$", "ϕ": r"$\phi$",
    # Greek uppercase
    "Γ": r"$\Gamma$", "Δ": r"$\Delta$", "Θ": r"$\Theta$", "Λ": r"$\Lambda$",
    "Ξ": r"$\Xi$", "Π": r"$\Pi$", "Σ": r"$\Sigma$", "Φ": r"$\Phi$",
    "Ψ": r"$\Psi$", "Ω": r"$\Omega$",
    # Relations
    "≤": r"$\leq$", "≥": r"$\geq$", "≠": r"$\neq$", "≈": r"$\approx$",
    "≡": r"$\equiv$", "∈": r"$\in$", "∉": r"$\notin$", "⊂": r"$\subset$",
    "⊆": r"$\subseteq$", "⊃": r"$\supset$", "⊇": r"$\supseteq$", "∝": r"$\propto$",
    # Arrows
    "→": r"$\rightarrow$", "←": r"$\leftarrow$", "↔": r"$\leftrightarrow$",
    "⇒": r"$\Rightarrow$", "⇐": r"$\Leftarrow$", "⇔": r"$\Leftrightarrow$",
    "↦": r"$\mapsto$",
    # Operators / misc math
    "×": r"$\times$", "÷": r"$\div$", "±": r"$\pm$", "∓": r"$\mp$",
    "·": r"$\cdot$", "∗": r"$*$", "∘": r"$\circ$", "∑": r"$\sum$",
    "∏": r"$\prod$", "∫": r"$\int$", "√": r"$\sqrt{\,}$", "∞": r"$\infty$",
    "∂": r"$\partial$", "∇": r"$\nabla$", "∧": r"$\wedge$", "∨": r"$\vee$",
    "¬": r"$\neg$", "∀": r"$\forall$", "∃": r"$\exists$", "∅": r"$\emptyset$",
    "°": r"$^{\circ}$", "′": r"$'$", "″": r"$''$",
    # Typographic
    "–": "--", "—": "---", "•": r"$\bullet$", "…": r"\ldots{}",
    "‘": "`", "’": "'", "“": "``", "”": "''", " ": " ",
}

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


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
    _require_course(payload.course_id, uid)
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

    try:
        reply = tutor_agent.reply(resources, payload.messages)
    except Exception as e:
        logger.error(f"Tutor reply failed: {e}")
        raise HTTPException(status_code=500, detail="Processing could not finish. Please retry or check backend configuration.")

    if not isinstance(reply, str) or not reply.strip():
        raise HTTPException(status_code=502, detail="The tutor returned an empty response. Please retry.")

    # Persist the conversation in its own tutor_chats table
    full_messages = list(payload.messages) + [{"role": "assistant", "content": reply}]
    _require_course(payload.course_id, uid)
    now = int(_time.time() * 1000)
    if payload.chat_id:
        from src.database.firebase_client import DataConflict
        try:
            db_client.append_tutor_messages(uid, payload.course_id, payload.chat_id, saved_messages,
                                           [payload.messages[-1], {"role": "assistant", "content": reply}], now)
        except DataConflict as exc:
            raise HTTPException(status_code=409, detail="This conversation changed. Reopen it before sending again.") from exc
        chat_id = payload.chat_id
    else:
        first_user = next((m.get("content", "") for m in payload.messages if m.get("role") == "user"), "New chat")
        title = (first_user[:60] + "…") if len(first_user) > 60 else (first_user or "New chat")
        chat_id = db_client.save_tutor_chat(payload.user_id, payload.course_id, {
            "title": title,
            "messages": full_messages,
            "createdAt": now,
            "updatedAt": now,
        })

    return {"status": "success", "reply": reply, "chat_id": chat_id}


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
