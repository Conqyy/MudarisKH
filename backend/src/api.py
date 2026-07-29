import os
import sys
import re
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

# إضافة مسار المشروع الرئيسي لحل أي تعارضات في الاستدعاء تلقائياً
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 1. التحقق من وجود المكتبات الأساسية لتشغيل الخادم
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
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
    from src.database.firebase_client import FirebaseClient
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

# تهيئة تطبيق FastAPI
app = FastAPI(
    title="Mudaris AI Examination Core API",
    description="Backend Grading & Exam Generation Engine for Imam University",
    version="1.0.0"
)

# CORS: allow the frontend (local dev + the deployed Vercel domain) to call the API.
# Default "*" keeps local/dev open; in production set CORS_ALLOW_ORIGINS to a
# comma-separated list of allowed origins (e.g. https://mudaris.vercel.app).
_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Catch-all: log the FULL traceback for any unhandled error and return the real
# reason to the client, instead of a bare "Internal Server Error" with no detail.
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
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )

# تهيئة عملاء الاتصال بقاعدة البيانات والذكاء الاصطناعي - نقوم هنا بتمرير كائن الإعدادات المورد من الـ Canvas
db_client = FirebaseClient(settings)
ai_agent = ExamGeneratorAgent()

# تعريف هيكلية البيانات المتوقعة من صفحة الـ HTML عند إرسال الإجابات
class ExamSubmission(BaseModel):
    user_id: str
    course_id: str
    exam_id: str
    answers: Dict[str, str]  # الإجابات المرسلة، على سبيل المثال: {"q1": "B", "q2": "..."}

@app.get("/")
def read_root():
    return {
        "status": "Online",
        "system": "Mudaris Exam Engine",
        "university": "Imam Mohammad Ibn Saud Islamic University",
        "api_docs": "/docs"
    }

@app.post("/api/exams/submit")
async def submit_exam(payload: ExamSubmission):
    """
    يتلقى إجابات الطالب، يجلب معايير التصحيح السرية من قاعدة البيانات، 
    ويقوم بتصحيح الأسئلة (المتعدد الخيارات تلقائياً، والأسئلة المقالية عبر الذكاء الاصطناعي).
    """
    logger.info(f"Received exam submission for user: {payload.user_id}, exam: {payload.exam_id}")

    # 1. جلب الإجابات ومعايير التصحيح السرية (Rubrics) من قاعدة البيانات
    secret_rubrics = {}
    
    if db_client.use_local:
        # إذا كنا نستخدم قاعدة البيانات المحلية
        data = db_client._read_local_db()
        secret_rubrics = data.get("users", {}).get(payload.user_id, {}) \
                             .get("courses", {}).get(payload.course_id, {}) \
                             .get("exams", {}).get(payload.exam_id, {})
    else:
        # إذا كنا نستخدم Firebase Firestore السحابية الحقيقية
        try:
            doc_ref = db_client.db.collection('users').document(payload.user_id) \
                                  .collection('courses').document(payload.course_id) \
                                  .collection('exams').document(payload.exam_id)
            doc = doc_ref.get()
            if doc.exists:
                secret_rubrics = doc.to_dict().get("rubrics", {})
        except Exception as e:
            logger.error(f"Error fetching cloud rubrics: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve exam keys from Cloud Database.")

    # التحقق من وجود المعايير
    if not secret_rubrics:
        logger.warning(f"No rubrics found for exam: {payload.exam_id}. Using dynamic baseline grading.")
        secret_rubrics = {
            "questions": {
                "q1": {"question_type": "mcq", "correct_answer": "B", "max_score": 5.0, "explanation": "It allows decomposition of the gradients."},
                "q2": {"question_type": "written", "max_score": 15.0, "criteria": "Mention gradient of loss, local derivatives, and backward error flow."}
            }
        }

    # Extract questions — handle both nested {"questions": {...}} and flat {"q1": {...}} formats
    questions_rubrics = secret_rubrics.get("questions", {})
    # Also check for top-level question keys (e.g. "q1", "q2" at root level)
    for key, val in secret_rubrics.items():
        if key.startswith("q") and key[1:].isdigit() and isinstance(val, dict):
            # Merge top-level question rubrics (prefer the nested ones if they exist)
            if key not in questions_rubrics:
                questions_rubrics[key] = val

    results = {}
    total_score = 0.0
    max_score = 0.0

    # 2. عملية التصحيح والتقييم خطوة بخطوة
    for q_id, rubric in sorted(questions_rubrics.items()):
        student_answer = payload.answers.get(q_id, "").strip()
        q_type = rubric.get("question_type", "written")

        if q_type == "mcq":
            # تصحيح السؤال المتعدد الخيارات (تطابق الحروف)
            correct_ans = rubric.get("correct_answer", "").strip().upper()
            q_max = float(rubric.get("max_score", 5.0))
            is_correct = (student_answer.upper() == correct_ans)
            points = q_max if is_correct else 0.0
            
            results[q_id] = {
                "score": points,
                "max_score": q_max,
                "is_correct": is_correct,
                "correct_answer": correct_ans,
                "explanation": rubric.get("explanation", "")
            }
            total_score += points
            max_score += q_max

        elif q_type == "written":
            # تصحيح السؤال المقالي بالذكاء الاصطناعي (AI Grader)
            criteria = rubric.get("criteria", "Evaluate explanation thoroughly for technical accuracy.")
            q_max = float(rubric.get("max_score", 15.0))
            logger.info(f"Grading written question {q_id} using the AI grader...")

            if not student_answer:
                # Empty answer = 0
                results[q_id] = {
                    "score": 0.0,
                    "max_score": q_max,
                    "feedback": "لم يتم تقديم إجابة لهذا السؤال."
                }
                max_score += q_max
                continue

            grader_prompt = f"""
            You are the "Mudaris AI Grader", an elite academic examiner at Imam Mohammad Ibn Saud Islamic University.
            Your task is to grade the student's written response fairly based on the provided rubric criteria.

            [QUESTION RUBRIC / CRITERIA]
            {criteria}

            [STUDENT'S ANSWER]
            "{student_answer}"

            Please evaluate the student's answer out of {q_max} marks. Provide:
            1. An exact numeric score (from 0.0 to {q_max}).
            2. Detailed constructive feedback in professional Arabic, highlighting where they scored points and where they missed key technical concepts.

            You MUST respond ONLY with a clean, raw JSON block matching this schema:
            {{
                "score": float,
                "feedback": "Arabic feedback explaining strengths and weaknesses."
            }}
            Do NOT include any code block quotes (e.g. ```json) or conversational text. Return ONLY the raw JSON.
            """

            try:
                response = ai_agent.client.chat.completions.create(
                    model=ai_agent.model_id,
                    messages=[{"role": "user", "content": grader_prompt}],
                    temperature=0.1,
                    max_tokens=1024,
                )

                ai_text = (response.choices[0].message.content or "").strip()
                if ai_text.startswith("```json"):
                    ai_text = ai_text[7:]
                if ai_text.startswith("```"):
                    ai_text = ai_text[3:]
                if ai_text.endswith("```"):
                    ai_text = ai_text[:-3]
                ai_text = ai_text.strip()
                
                import json
                grade_data = json.loads(ai_text)
                score = min(float(grade_data.get("score", 0.0)), q_max)
                feedback = grade_data.get("feedback", "لم نتمكن من استخلاص تقييم دقيق.")
                
            except Exception as e:
                logger.error(f"AI Grader failed: {e}. Falling back to baseline grade.")
                score = q_max * 0.5 if len(student_answer) > 50 else 0.0
                feedback = "تم تقييم الإجابة تلقائياً بشكل مبدئي لتعذر الاتصال بمحرك التقييم المتقدم."

            results[q_id] = {
                "score": score,
                "max_score": q_max,
                "feedback": feedback
            }
            total_score += score
            max_score += q_max

    # 3. حفظ نتائج الطالب في قاعدة البيانات لضمان تعقب التقدم لاحقاً
    grade_record = {
        "exam_id": payload.exam_id,
        "total_score": total_score,
        "max_score": max_score,
        "percentage": round((total_score / max_score) * 100, 2) if max_score > 0 else 0,
        "results": results,
        "answers": payload.answers,
    }

    try:
        if db_client.use_local:
            data = db_client._read_local_db()
            data.setdefault("users", {}).setdefault(payload.user_id, {}) \
                .setdefault("courses", {}).setdefault(payload.course_id, {}) \
                .setdefault("grades", {})[payload.exam_id] = grade_record
            db_client._write_local_db(data)
        else:
            from firebase_admin import firestore
            db_client.db.collection("users").document(payload.user_id) \
                .collection("courses").document(payload.course_id) \
                .collection("grades").document(payload.exam_id).set({
                    **grade_record,
                    "graded_at": firestore.SERVER_TIMESTAMP,
                }, merge=True)
        logger.info(f"📊 Grade saved to database for {payload.user_id}/{payload.exam_id}")
    except Exception as e:
        logger.warning(f"⚠️ Could not save grade to DB: {e}")

    logger.info(f"Grading finalized! Total Score: {total_score}/{max_score}")

    return {
        "status": "Graded Successfully",
        "exam_id": payload.exam_id,
        "total_score": total_score,
        "max_score": max_score,
        "percentage": round((total_score / max_score) * 100, 2) if max_score > 0 else 0,
        "results": results
    }

class ExamGenerateRequest(BaseModel):
    user_id: str
    course_id: str
    topics: List[str] = []
    preference: str = "Generate a comprehensive mock exam."
    transcripts: str = ""
    cues: str = "Standard academic prep."
    university: str = "Imam Mohammad Ibn Saud Islamic University"
    college: str = "College of Computer and Information Sciences"

@app.post("/api/exams/generate")
def generate_exam_endpoint(payload: ExamGenerateRequest):
    import uuid
    import base64
    import tempfile
    from src.utils.compile_pdf import compile_tex_to_pdf

    exam_id = f"exam_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating exam {exam_id} for course {payload.course_id}")

    context = {
        "transcripts": payload.transcripts or "No transcripts provided.",
        "cues": payload.cues,
        "university": payload.university,
        "college": payload.college,
    }

    raw_tex = ai_agent.compile_exam(
        academic_data=context,
        topics=payload.topics if payload.topics else ["General course review"],
        preference=payload.preference,
        exam_id=exam_id,
        user_id=payload.user_id,
        course_id=payload.course_id,
    )

    extraction = ai_agent.extract_and_save_exam_metadata(
        raw_tex, exam_id, payload.user_id, payload.course_id
    )
    cleaned_tex = extraction.get("cleaned_tex", raw_tex)
    rubrics = extraction.get("rubrics", {})

    db_client.save_secret_rubrics(payload.user_id, payload.course_id, exam_id, rubrics)

    pdf_base64 = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, f"{exam_id}.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(f"% !TEX root = {exam_id}.tex\n" + cleaned_tex.strip())

            pdf_path = compile_tex_to_pdf(tex_path)
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as pf:
                    pdf_base64 = base64.b64encode(pf.read()).decode()
    except Exception as e:
        logger.warning(f"PDF compilation skipped: {e}")

    return {
        "status": "success",
        "exam_id": exam_id,
        "tex_content": cleaned_tex,
        "pdf_base64": pdf_base64,
        "has_pdf": pdf_base64 is not None,
    }

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


def _recheck_past_exam_scope(course_id: str):
    """Re-tag every past exam's topics as in/out of the CURRENT course (using the
    Historical Exam Analyzer's scope logic). Cheap — pure string match, no LLM
    call. Called when the course's documents change so the analyzer's scope
    decision stays current even if a past exam was uploaded before the lectures."""
    try:
        intel = db_client.get_course_intelligence(course_id)
        doc_insights = intel.get("document_analyses", [])
        if not doc_insights:
            return
        for h in db_client.get_course_historical_exams(course_id):
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
    lecture_id: str = Form(""),
):
    import time as _time

    content_type = file.content_type or ""
    file_type = ALLOWED_DOC_TYPES.get(content_type)
    if not file_type:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        file_type = {"pdf": "pdf", "pptx": "pptx", "docx": "docx"}.get(ext)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    file_bytes = await file.read()
    file_size = len(file_bytes)
    doc_title = title or (file.filename or "Untitled Document")

    existing_docs = db_client.get_course_documents(course_id)
    for ed in existing_docs:
        if ed.get("title") == doc_title or (file.filename and file.filename in ed.get("storagePath", "")):
            raise HTTPException(
                status_code=409,
                detail=f"A document named '{doc_title}' has already been uploaded to this course."
            )

    storage_path = f"documents/{user_id}/{course_id}/{int(_time.time())}_{file.filename}"
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path)

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

    doc_id = db_client.save_document(user_id, course_id, doc_data)
    logger.info(f"Document {doc_id} saved, starting processing...")

    try:
        extracted_text = doc_processor.extract_text(file_bytes, file_type)

        # If we couldn't read any text, fail clearly instead of saving an empty
        # "completed" doc with 0 topics / 0 chapters.
        from src.utils.pdf_extract import is_meaningful_text
        if not is_meaningful_text(extracted_text):
            msg = (
                "Couldn't read text from this file. If it's a scanned or "
                "image-only PDF, it needs OCR (not enabled)."
            )
            db_client.update_document(doc_id, {
                "status": "failed",
                "errorMessage": msg,
            })
            raise HTTPException(status_code=422, detail=msg)

        course_doc = None
        try:
            from firebase_admin import firestore as _fs
            course_doc = db_client.db.collection("courses").document(course_id).get()
        except Exception:
            pass
        course_title = course_doc.to_dict().get("title", course_id) if course_doc and course_doc.exists else course_id

        # For PDFs, also give the analyzer the page images so it can read
        # equations, diagrams, figures, and code (not just extracted text).
        page_images = []
        if file_type == "pdf":
            from src.utils.pdf_extract import pdf_to_image_uris
            page_images = pdf_to_image_uris(file_bytes)
        analysis = doc_processor.analyze_document(extracted_text, course_title, image_uris=page_images)

        db_client.update_document(doc_id, {
            "extractedText": extracted_text[:50000],
            "analysis": analysis,
            "status": "completed",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Document {doc_id} processed successfully.")

        # A new document changes the course scope — refresh the in/out-of-course
        # tags on this course's already-analyzed past exams.
        _recheck_past_exam_scope(course_id)

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
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        db_client.update_document(doc_id, {
            "status": "failed",
            "errorMessage": str(e),
        })
        raise HTTPException(status_code=500, detail=f"Document processing failed: {str(e)}")


@app.get("/api/documents/{course_id}")
def get_course_documents(course_id: str):
    docs = db_client.get_course_documents(course_id)
    return {"status": "success", "documents": docs}


@app.get("/api/documents/detail/{doc_id}")
def get_document_detail(doc_id: str):
    doc = db_client.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "success", "document": doc}


@app.post("/api/documents/{doc_id}/reanalyze")
def reanalyze_document(doc_id: str):
    """Re-run the AI analysis on a document using its already-extracted text.

    Lets the user retry when the first analysis failed or came back empty
    (without having to re-upload the file).
    """
    doc = db_client.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    text = doc.get("extractedText", "")
    if not text or len(text.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="No extracted text is available for this document — please re-upload it.",
        )

    db_client.update_document(doc_id, {"status": "processing", "errorMessage": ""})

    try:
        course_id = doc.get("courseId", "")
        course_title = course_id
        if course_id:
            try:
                course_doc = (
                    db_client.db.collection("courses").document(course_id).get()
                )
                if course_doc and course_doc.exists:
                    course_title = course_doc.to_dict().get("title", course_id)
            except Exception:
                pass

        analysis = doc_processor.analyze_document(text, course_title)

        db_client.update_document(doc_id, {
            "analysis": analysis,
            "status": "completed",
            "errorMessage": "",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Document {doc_id} re-analyzed successfully.")
        return {"status": "success", "document_id": doc_id, "analysis": analysis}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Re-analysis failed for {doc_id}: {e}")
        db_client.update_document(doc_id, {
            "status": "failed",
            "errorMessage": str(e),
        })
        raise HTTPException(
            status_code=500,
            detail=f"Re-analysis failed: {str(e)}",
        )


@app.delete("/api/documents/{doc_id}")
def delete_document_endpoint(doc_id: str):
    doc = db_client.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    storage_path = doc.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
    db_client.delete_document(doc_id)
    logger.info(f"Document {doc_id} deleted.")
    return {"status": "success", "deleted": doc_id}


@app.delete("/api/audio/{rec_id}")
def delete_audio_endpoint(rec_id: str):
    rec = db_client._flat_get("audio_recordings", rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    storage_path = rec.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
    db_client.delete_audio_recording(rec_id)
    logger.info(f"Audio recording {rec_id} deleted.")
    return {"status": "success", "deleted": rec_id}


@app.delete("/api/historical-exams/{exam_id}")
def delete_historical_exam_endpoint(exam_id: str):
    exam = db_client._flat_get("historical_exams", exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Historical exam not found")
    storage_path = exam.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
    db_client.delete_historical_exam(exam_id)
    logger.info(f"Historical exam {exam_id} deleted.")
    return {"status": "success", "deleted": exam_id}


@app.delete("/api/exams/{doc_id}")
def delete_generated_exam_endpoint(doc_id: str):
    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    db_client.delete_exam(doc_id)
    logger.info(f"Generated exam {doc_id} deleted.")
    return {"status": "success", "deleted": doc_id}


UPLOADS_ROOT = Path(__file__).resolve().parent.parent / "uploads"

@app.get("/api/files/serve")
def serve_uploaded_file(path: str):
    file_path = UPLOADS_ROOT / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
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
    title: str = Form(""),
):
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

    file_bytes = await file.read()
    file_size = len(file_bytes)
    exam_title = title or (file.filename or "Untitled Exam")

    storage_path = f"historical_exams/{user_id}/{course_id}/{int(_time.time())}_{file.filename}"
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path)

    exam_data = {
        "title": exam_title,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "status": "processing",
        "uploadedAt": int(_time.time() * 1000),
    }

    exam_id = db_client.save_historical_exam(user_id, course_id, exam_data)
    logger.info(f"Historical exam {exam_id} saved, starting analysis...")

    try:
        course_doc = None
        try:
            from firebase_admin import firestore as _fs
            course_doc = db_client.db.collection("courses").document(course_id).get()
        except Exception:
            pass
        course_title = course_doc.to_dict().get("title", course_id) if course_doc and course_doc.exists else course_id

        if is_pdf:
            extracted_text = hist_analyzer.extract_exam_text(file_bytes)
            # Render the exam pages to images so the analyzer (vision model) can
            # read equations, diagrams, figures, and code — not just the text.
            from src.utils.pdf_extract import pdf_to_image_uris
            page_images = pdf_to_image_uris(file_bytes)
        else:
            # A photo / image of the exam: there's no embedded text, so the
            # vision model reads the page straight from the (normalized) image.
            from src.utils.pdf_extract import image_to_image_uri
            extracted_text = ""
            page_images = [image_to_image_uri(file_bytes)]

        # Pass the course's CURRENT lecture-document analyses so the analyzer can
        # tag each past-exam topic as in/out of the course as it is taught now.
        course_intel = db_client.get_course_intelligence(course_id)
        document_insights = course_intel.get("document_analyses", [])

        analysis = hist_analyzer.analyze_exam(
            extracted_text, course_title, image_uris=page_images,
            document_insights=document_insights,
        )

        db_client.update_historical_exam(exam_id, {
            "extractedText": extracted_text[:50000],
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

    except Exception as e:
        logger.error(f"Historical exam analysis failed: {e}")
        db_client.update_historical_exam(exam_id, {
            "status": "failed",
            "errorMessage": str(e),
        })
        raise HTTPException(status_code=500, detail=f"Historical exam analysis failed: {str(e)}")


@app.get("/api/historical-exams/{course_id}")
def get_course_historical_exams(course_id: str):
    exams = db_client.get_course_historical_exams(course_id)
    return {"status": "success", "historical_exams": exams}


# ──────────────────────────────────────────────────
# Tutorials — ungraded practice problems (ideas only, no marks/format)
# ──────────────────────────────────────────────────

@app.post("/api/tutorials/upload")
async def upload_tutorial(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    title: str = Form(""),
):
    """Upload a tutorial / practice sheet (PDF, PPTX, DOCX). We analyze it for
    TOPICS and worked-problem IDEAS only — it never contributes grading weight
    or exam format (those come from past exams). Reuses the document analyzer."""
    import time as _time

    content_type = file.content_type or ""
    file_type = ALLOWED_DOC_TYPES.get(content_type)
    if not file_type:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        file_type = {"pdf": "pdf", "pptx": "pptx", "docx": "docx"}.get(ext)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    file_bytes = await file.read()
    file_size = len(file_bytes)
    tut_title = title or (file.filename or "Untitled Tutorial")

    storage_path = f"tutorials/{user_id}/{course_id}/{int(_time.time())}_{file.filename}"
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path)

    tut_data = {
        "title": tut_title,
        "fileType": file_type,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "status": "processing",
        "uploadedAt": int(_time.time() * 1000),
    }

    tut_id = db_client.save_tutorial(user_id, course_id, tut_data)
    logger.info(f"Tutorial {tut_id} saved, starting analysis...")

    try:
        extracted_text = doc_processor.extract_text(file_bytes, file_type)

        from src.utils.pdf_extract import is_meaningful_text
        page_images = []
        if file_type == "pdf":
            from src.utils.pdf_extract import pdf_to_image_uris
            page_images = pdf_to_image_uris(file_bytes)

        # Allow image-only PDFs (vision will read them); only fail if neither
        # text nor page images are available.
        if not is_meaningful_text(extracted_text) and not page_images:
            msg = "Couldn't read this tutorial file. If it's a scanned/image-only PDF, it needs OCR."
            db_client.update_tutorial(tut_id, {"status": "failed", "errorMessage": msg})
            raise HTTPException(status_code=422, detail=msg)

        course_doc = None
        try:
            course_doc = db_client.db.collection("courses").document(course_id).get()
        except Exception:
            pass
        course_title = course_doc.to_dict().get("title", course_id) if course_doc and course_doc.exists else course_id

        analysis = doc_processor.analyze_tutorial(extracted_text, course_title, image_uris=page_images)

        db_client.update_tutorial(tut_id, {
            "extractedText": extracted_text[:50000],
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
    except Exception as e:
        logger.error(f"Tutorial analysis failed: {e}")
        db_client.update_tutorial(tut_id, {"status": "failed", "errorMessage": str(e)})
        raise HTTPException(status_code=500, detail=f"Tutorial analysis failed: {str(e)}")


@app.get("/api/tutorials/{course_id}")
def get_course_tutorials(course_id: str):
    tutorials = db_client.get_course_tutorials(course_id)
    return {"status": "success", "tutorials": tutorials}


@app.delete("/api/tutorials/{tut_id}")
def delete_tutorial_endpoint(tut_id: str):
    tut = db_client.get_tutorial(tut_id)
    if not tut:
        raise HTTPException(status_code=404, detail="Tutorial not found")
    storage_path = tut.get("storagePath")
    if storage_path:
        try:
            db_client.delete_file_from_storage(storage_path)
        except Exception as e:
            logger.warning(f"Could not delete file from storage: {e}")
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
    out_path = src_path.rsplit(".", 1)[0] + ".converted.mp3"
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", src_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", out_path],
        capture_output=True,
    )
    if proc.returncode != 0 or not os.path.exists(out_path):
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-500:]
        raise RuntimeError(f"ffmpeg failed to extract audio: {err}")
    return out_path


def _download_url_audio_to_mp3(url: str, out_dir: str):
    """Fetch a video/audio URL (YouTube, Vimeo, direct link, ...) and extract its
    audio to MP3 using yt-dlp + ffmpeg. Returns (mp3_path, detected_title)."""
    import yt_dlp

    out_tmpl = os.path.join(out_dir, "online_audio.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
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

def _resolve_course_title(course_id: str) -> str:
    try:
        doc = db_client.db.collection("courses").document(course_id).get()
        if doc and doc.exists:
            return doc.to_dict().get("title", course_id)
    except Exception:
        pass
    return course_id


def _run_audio_pipeline(rec_id, course_id, *, file_bytes=None, audio_ext=None,
                        url=None, had_title=True):
    """Background worker: build an MP3 (from uploaded bytes OR a URL), transcribe
    it, analyze the transcript, and update the recording's status as it goes.
    Runs in a daemon thread so long (1-2 hour) recordings never block the HTTP
    request or trip the browser's timeout."""
    import time as _time
    import tempfile
    import shutil as _shutil

    workdir = tempfile.mkdtemp()
    try:
        if url:
            db_client.update_audio_recording(rec_id, {"status": "downloading"})
            mp3_path, vid_title = _download_url_audio_to_mp3(url, workdir)
            if not had_title:
                db_client.update_audio_recording(rec_id, {"title": vid_title})
            transcribe_path = mp3_path
        else:
            src_path = os.path.join(workdir, f"input.{audio_ext}")
            with open(src_path, "wb") as f:
                f.write(file_bytes)
            transcribe_path = src_path
            if audio_ext in ("mp4", "mov"):
                db_client.update_audio_recording(rec_id, {"status": "converting"})
                transcribe_path = _extract_audio_to_mp3(src_path)

        db_client.update_audio_recording(rec_id, {"status": "transcribing"})
        transcript = audio_agent.transcribe_audio(transcribe_path)

        db_client.update_audio_recording(rec_id, {"status": "analyzing"})
        insights = audio_agent.analyze_transcript(transcript, _resolve_course_title(course_id))

        db_client.update_audio_recording(rec_id, {
            "transcript": transcript[:50000],
            "insights": insights,
            "status": "completed",
            "processedAt": int(_time.time() * 1000),
        })
        logger.info(f"Audio recording {rec_id} analyzed successfully.")
        return True
    except Exception as e:
        logger.error(f"Audio processing failed for {rec_id}: {e}")
        db_client.update_audio_recording(rec_id, {"status": "failed", "errorMessage": str(e)})
        return False
    finally:
        _shutil.rmtree(workdir, ignore_errors=True)


def _spawn_audio_job(**kwargs):
    import threading
    threading.Thread(target=_run_audio_pipeline, kwargs=kwargs, daemon=True).start()


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
    background: str = Form("1"),
):
    import time as _time

    content_type = file.content_type or ""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    audio_ext = ALLOWED_AUDIO_TYPES.get(content_type) or (ext if ext in ("mp3", "wav", "m4a", "mp4", "mov") else None)
    if not audio_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported audio/video type: {content_type}")

    file_bytes = await file.read()
    file_size = len(file_bytes)
    audio_title = title or (file.filename or "Untitled Recording")

    storage_path = f"audio/{user_id}/{course_id}/{int(_time.time())}_{file.filename}"
    file_url = db_client.upload_file_to_storage(file_bytes, storage_path)

    rec_data = {
        "title": audio_title,
        "fileUrl": file_url,
        "storagePath": storage_path,
        "fileSize": file_size,
        "status": "queued",
        "uploadedAt": int(_time.time() * 1000),
    }
    if lecture_id:
        rec_data["lectureId"] = lecture_id

    rec_id = db_client.save_audio_recording(user_id, course_id, rec_data)

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
    ok = _run_audio_pipeline(rec_id, course_id, file_bytes=file_bytes, audio_ext=audio_ext)
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
def upload_audio_from_url(payload: AudioUrlRequest):
    """Take a video/audio URL; download + extract audio to MP3 + transcribe +
    analyze. Runs in the background by default, or synchronously when the caller
    wants to process several URLs one at a time."""
    import time as _time

    url = (payload.video_url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Please provide a valid http(s) video URL.")

    rec_data = {
        "title": payload.title or "Online Recording",
        "fileUrl": url,
        "storagePath": "",
        "sourceUrl": url,
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
    notes: str
    title: str = ""
    lecture_id: str = ""


@app.post("/api/audio/upload-notes")
def upload_lecture_notes(payload: LectureNotesRequest):
    """Typed lecture notes: the student writes what happened in the lecture and
    what the professor emphasized (e.g. "the prof said section 3 will come in
    the midterm"). The same AI that analyzes recordings runs on the text — no
    transcription step — and the insights are saved exactly like a recording's,
    so exam generation, the intelligence view, and the tutor all use them."""
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
        "transcript": notes[:50000],
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
        insights = audio_agent.analyze_transcript(framed, _resolve_course_title(payload.course_id))
        db_client.update_audio_recording(rec_id, {
            "insights": insights,
            "status": "completed",
            "processedAt": int(_time.time() * 1000),
        })
    except Exception as e:
        # The typed notes stay on the record (saved above), so nothing the
        # student wrote is lost — the entry can be re-analyzed instead.
        logger.error(f"Notes analysis failed for {rec_id}: {e}")
        db_client.update_audio_recording(rec_id, {"status": "failed", "errorMessage": str(e)})
        raise HTTPException(status_code=500, detail=f"Could not analyze the notes: {e}")

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
def reanalyze_audio_recording(rec_id: str):
    """Re-run the AI analysis on a recording or typed note using its stored
    transcript — so a failure caused by a transient problem (no OpenRouter
    credit, model overloaded) can be retried without re-uploading or retyping.
    """
    import time as _time

    rec = db_client.get_audio_recording(rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    transcript = (rec.get("transcript") or "").strip()
    if len(transcript) < 20:
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
            text, _resolve_course_title(rec.get("courseId", ""))
        )
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
        db_client.update_audio_recording(rec_id, {"status": "failed", "errorMessage": str(e)})
        raise HTTPException(status_code=500, detail=f"Re-analysis failed: {e}")


@app.get("/api/audio/{course_id}")
def get_course_audio_recordings(course_id: str):
    recordings = db_client.get_course_audio_recordings(course_id)
    return {"status": "success", "audio_recordings": recordings}


# ──────────────────────────────────────────────────
# Model 4 Enhanced: Generate with full intelligence
# ──────────────────────────────────────────────────

class EnhancedExamGenerateRequest(BaseModel):
    user_id: str
    course_id: str
    topics: List[str] = []
    preference: str = "Generate a comprehensive mock exam."
    document_ids: List[str] = []
    historical_exam_ids: List[str] = []
    tutorial_ids: List[str] = []
    audio_ids: List[str] = []
    total_marks: int = 40
    exam_type: str = "Final"
    transcripts: str = ""
    cues: str = "Standard academic prep."
    university: str = "Imam Mohammad Ibn Saud Islamic University"
    college: str = "College of Computer and Information Sciences"

def _normalize_marks(rubrics: dict, total_marks: int):
    """Scale each question's max_score so they sum to exactly total_marks.
    Mutates the rubric in place; integer marks, remainder added to the last."""
    qs = rubrics.get("questions", {})
    if not qs or not total_marks:
        return
    ids = sorted(qs.keys())
    defaults = {"mcq": 2.0, "true_false": 2.0}
    raw = []
    for qid in ids:
        q = qs[qid]
        try:
            v = float(q.get("max_score") or 0)
        except (TypeError, ValueError):
            v = 0
        if v <= 0:
            v = defaults.get(q.get("question_type", "written"), 10.0)
        raw.append(v)
    s = sum(raw) or 1
    scaled = [max(1, round(v / s * total_marks)) for v in raw]
    # fix rounding drift so it sums to exactly total_marks
    drift = total_marks - sum(scaled)
    scaled[-1] = max(1, scaled[-1] + drift)
    for qid, m in zip(ids, scaled):
        qs[qid]["max_score"] = m


def _compile_answer_tex(tex: str, name: str):
    """Compile answer-key LaTeX to a PDF; return the pdf path or None."""
    import tempfile
    from src.utils.compile_pdf import compile_tex_to_pdf
    tmpdir = tempfile.mkdtemp()
    tex_path = os.path.join(tmpdir, f"{name}-answers.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex.strip())
    try:
        return compile_tex_to_pdf(tex_path)
    except Exception as e:
        logger.warning(f"Answer-key compile error: {e}")
        return None


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
    """Return a COMPLETE, compilable, INTERLEAVED model-answer key — each question
    immediately followed by its answer in red (NOT a separate answers section).

    Primary: the rich LLM key (typeset math, worked solutions). Backup: a safe
    template built from structured plain-text Q&A (also interleaved, always
    compiles). Both keep the question-then-red-answer layout. The append-at-end
    rubric key is only a last resort if both LLM paths fail entirely."""
    exam_tex = exam.get("texContent", "") or ""
    exam_id = exam.get("examId", "exam")
    num_q = len(exam.get("questionStructure", []) or []) or len((exam.get("rubrics", {}) or {}).get("questions", {}) or {})
    need = max(3, num_q - 1) if num_q else 3  # allow a small off-by-one

    # 1) Rich interleaved worked solutions (typeset). Accept if complete + compiles.
    rich = ""
    try:
        rich = ai_agent._sanitize_latex(ai_agent.generate_answer_key(exam_tex, exam_id))
        if rich.count("Answer") >= need and _compile_answer_tex(rich, exam_id):
            return rich
    except Exception as e:
        logger.warning(f"Rich answer key failed for {exam_id}: {e}")

    # 2) Safe interleaved template from structured Q&A (question + red answer each).
    logger.info(f"Trying safe interleaved answer key for {exam_id}.")
    safe = ""
    try:
        items = ai_agent.generate_answer_pairs(exam_tex, exam_id)
        if items:
            safe = ai_agent._sanitize_latex(ai_agent._answers_to_latex(items, exam_id))
            if len(items) >= need and _compile_answer_tex(safe, exam_id):
                return safe
    except Exception as e:
        logger.warning(f"Safe answer key failed for {exam_id}: {e}")

    # 3) Use whichever interleaved version compiled, even if a bit short.
    if rich and _compile_answer_tex(rich, exam_id):
        return rich
    if safe and _compile_answer_tex(safe, exam_id):
        return safe

    # 4) Absolute last resort: deterministic rubric key (answers appended at end)
    #    — only so the student gets *something* complete if the model fully fails.
    det = _rubric_answer_key_tex(exam)
    if det and _compile_answer_tex(det, exam_id):
        return det
    return rich or safe or det


@app.post("/api/exams/generate-enhanced")
def generate_enhanced_exam_endpoint(payload: EnhancedExamGenerateRequest):
    import uuid
    import base64
    import tempfile
    import time as _time
    from src.utils.compile_pdf import compile_tex_to_pdf

    exam_id = f"exam_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating enhanced exam {exam_id} for course {payload.course_id}")

    intelligence = db_client.get_course_intelligence(
        payload.course_id,
        document_ids=payload.document_ids if payload.document_ids else None,
        historical_exam_ids=payload.historical_exam_ids if payload.historical_exam_ids else None,
        tutorial_ids=payload.tutorial_ids if payload.tutorial_ids else None,
        audio_ids=payload.audio_ids if payload.audio_ids else None,
    )

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
    _normalize_marks(rubrics, payload.total_marks)

    db_client.save_secret_rubrics(payload.user_id, payload.course_id, exam_id, rubrics)

    questions_rubrics = rubrics.get("questions", {})
    question_structure = []
    for qid, qdata in sorted(questions_rubrics.items()):
        question_structure.append({
            "id": qid,
            "type": qdata.get("question_type", "written"),
        })

    def _try_compile(tex: str):
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, f"{exam_id}.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(f"% !TEX root = {exam_id}.tex\n" + tex.strip())
            pdf_path = compile_tex_to_pdf(tex_path)
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as pf:
                    return base64.b64encode(pf.read()).decode()
        return None

    pdf_base64 = None
    try:
        pdf_base64 = _try_compile(cleaned_tex)
        if pdf_base64 is None:
            # LLM LaTeX often has stray errors — ask the model to repair once
            logger.warning(f"Exam {exam_id} failed first compile; attempting LaTeX repair.")
            repaired = ai_agent.repair_latex(cleaned_tex)
            if repaired and repaired.strip() != cleaned_tex.strip():
                pdf_base64 = _try_compile(repaired)
                if pdf_base64 is not None:
                    cleaned_tex = repaired
                    logger.info(f"Exam {exam_id} compiled after repair.")
    except Exception as e:
        logger.warning(f"PDF compilation skipped: {e}")

    doc_db_id = db_client.save_exam_flat(payload.user_id, payload.course_id, {
        "examId": exam_id,
        "texContent": cleaned_tex[:50000],
        "questionStructure": question_structure,
        "rubrics": rubrics,
        "totalMarks": payload.total_marks,
        "examType": payload.exam_type,
        "status": "generated",
        "sourceSummary": {
            "documentIds": payload.document_ids or [],
            "audioIds": [],
            "historicalExamIds": [],
        },
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
def list_course_exams(course_id: str):
    exams = db_client.get_course_exams(course_id)
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
def get_exam_detail(doc_id: str):
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
def get_exam_pdf(doc_id: str):
    """Recompile a saved exam's LaTeX to PDF on demand and serve it.
    Sanitizes the stored .tex first, which also rescues older exams that were
    saved before the sanitizer fix (conversational preamble / markdown fences)."""
    import tempfile
    from src.utils.compile_pdf import compile_tex_to_pdf

    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    tex = exam.get("texContent", "")
    if not tex:
        raise HTTPException(status_code=404, detail="No LaTeX content for this exam")

    # Re-clean in case the stored tex still has a preamble/fence (legacy exams)
    tex = ai_agent._sanitize_latex(tex)

    def _compile(t: str):
        tmpdir = tempfile.mkdtemp()
        tex_path = os.path.join(tmpdir, f"{exam_name}.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(t.strip())
        return compile_tex_to_pdf(tex_path)

    try:
        exam_name = exam.get("examId", doc_id)
        pdf_path = _compile(tex)
        if not pdf_path or not os.path.exists(pdf_path):
            # Self-heal: repair the LaTeX once, cache the fixed version, retry
            logger.warning(f"Exam {doc_id} failed compile on view; repairing.")
            repaired = ai_agent.repair_latex(tex)
            if repaired and repaired.strip() != tex.strip():
                pdf_path = _compile(repaired)
                if pdf_path and os.path.exists(pdf_path):
                    db_client.update_exam(doc_id, {"texContent": repaired[:50000]})
        if not pdf_path or not os.path.exists(pdf_path):
            raise HTTPException(status_code=422, detail="LaTeX compilation failed")
        # inline so the browser previews it in an iframe instead of downloading
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"{exam_name}.pdf",
            content_disposition_type="inline",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exam PDF compile failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF compilation error: {str(e)}")


@app.get("/api/exams/{doc_id}/answer-key-pdf")
def get_exam_answer_key_pdf(doc_id: str):
    """Generate (once, then cache) and serve the MODEL-ANSWER key PDF for an
    exam — a full worked-solutions document the student opens after solving the
    exam themselves. Watermarked + served inline."""
    import tempfile
    from src.utils.compile_pdf import compile_tex_to_pdf

    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    exam_name = exam.get("examId", doc_id)
    exam_tex = exam.get("texContent", "")
    num_q = len(exam.get("questionStructure", []) or []) or len((exam.get("rubrics", {}) or {}).get("questions", {}) or {})

    # Use the cached answer key only if it's substantial (covers most questions).
    # Otherwise rebuild — this discards earlier incomplete/empty caches.
    answer_tex = exam.get("answerKeyTex", "")
    if answer_tex and answer_tex.count("Answer") < max(2, num_q):
        answer_tex = ""
    pdf_path = None
    if answer_tex:
        pdf_path = _compile_answer_tex(ai_agent._sanitize_latex(answer_tex), exam_name)

    if not pdf_path or not os.path.exists(pdf_path):
        if not exam_tex:
            raise HTTPException(status_code=404, detail="No exam content to build answers from.")
        try:
            answer_tex = _make_compilable_answer_key(exam)
        except Exception as e:
            logger.error(f"Answer-key generation failed for {doc_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Could not generate model answers: {str(e)}")
        db_client.update_exam(doc_id, {"answerKeyTex": answer_tex[:60000]})
        pdf_path = _compile_answer_tex(answer_tex, exam_name)

    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=422, detail="Answer-key compilation failed")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{exam_name}-answers.pdf",
        content_disposition_type="inline",
    )


@app.post("/api/exams/{doc_id}/solution")
async def upload_exam_solution(doc_id: str, file: UploadFile = File(...)):
    """Attach the student's OWN solved exam to this exam for side-by-side review
    (NOT graded). Stored as a file; the page shows it next to the model answers."""
    import time as _time

    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    allowed = {"pdf", "png", "jpg", "jpeg", "webp", "docx", "txt"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    file_bytes = await file.read()
    user_id = exam.get("userId", "anon")
    course_id = exam.get("courseId", "course")
    storage_path = f"solutions/{user_id}/{course_id}/{doc_id}_{int(_time.time())}_{file.filename}"
    db_client.upload_file_to_storage(file_bytes, storage_path)

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


@app.get("/api/exams/{doc_id}/questions")
def get_exam_questions(doc_id: str):
    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return {
        "status": "success",
        "examId": exam.get("examId"),
        "questions": exam.get("questionStructure", []),
    }


@app.post("/api/exams/{doc_id}/submit-answers")
def submit_exam_answers(doc_id: str, payload: dict):
    import json as _json
    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    answers = payload.get("answers", {})
    rubrics = exam.get("rubrics", {})
    if not rubrics:
        raise HTTPException(status_code=400, detail="No rubrics found for this exam")

    questions_rubrics = rubrics.get("questions", {})
    for key, val in rubrics.items():
        if key.startswith("q") and key[1:].isdigit() and isinstance(val, dict):
            if key not in questions_rubrics:
                questions_rubrics[key] = val

    results = {}
    total_score = 0.0
    max_score = 0.0

    for q_id, rubric in sorted(questions_rubrics.items()):
        student_answer = answers.get(q_id, "").strip()
        q_type = rubric.get("question_type", "written")
        q_max = float(rubric.get("max_score", 5.0 if q_type == "mcq" else 15.0))

        if q_type == "mcq":
            correct_ans = rubric.get("correct_answer", "").strip().upper()
            is_correct = (student_answer.upper() == correct_ans)
            points = q_max if is_correct else 0.0
            results[q_id] = {
                "score": points,
                "max_score": q_max,
                "is_correct": is_correct,
                "correct_answer": correct_ans,
                "explanation": rubric.get("explanation", ""),
            }
            total_score += points
            max_score += q_max

        elif q_type in ("true_false",):
            correct_ans = rubric.get("correct_answer", "").strip().upper()
            is_correct = (student_answer.upper() == correct_ans)
            points = q_max if is_correct else 0.0
            results[q_id] = {
                "score": points,
                "max_score": q_max,
                "is_correct": is_correct,
                "correct_answer": correct_ans,
                "explanation": rubric.get("explanation", ""),
            }
            total_score += points
            max_score += q_max

        else:
            if not student_answer:
                results[q_id] = {"score": 0.0, "max_score": q_max, "feedback": "No answer provided."}
                max_score += q_max
                continue

            criteria = rubric.get("criteria", "Evaluate for technical accuracy.")
            grader_prompt = f"""You are an academic grader. Grade this answer out of {q_max} marks.
[RUBRIC] {criteria}
[STUDENT ANSWER] "{student_answer}"
Respond ONLY with raw JSON: {{"score": float, "feedback": "constructive feedback"}}"""

            try:
                response = ai_agent.client.chat.completions.create(
                    model=ai_agent.model_id,
                    messages=[{"role": "user", "content": grader_prompt}],
                    temperature=0.1,
                    max_tokens=1024,
                )
                ai_text = (response.choices[0].message.content or "").strip()
                if ai_text.startswith("```"): ai_text = ai_text.split("\n", 1)[-1]
                if ai_text.endswith("```"): ai_text = ai_text[:-3]
                ai_text = ai_text.strip()
                grade_data = _json.loads(ai_text)
                score = min(float(grade_data.get("score", 0.0)), q_max)
                feedback = grade_data.get("feedback", "")
            except Exception as e:
                logger.error(f"AI grading failed for {q_id}: {e}")
                score = q_max * 0.5 if len(student_answer) > 50 else 0.0
                feedback = "Auto-graded due to grading engine error."

            results[q_id] = {"score": score, "max_score": q_max, "feedback": feedback}
            total_score += score
            max_score += q_max

    grade = {
        "totalScore": round(total_score, 2),
        "maxScore": round(max_score, 2),
        "percentage": round((total_score / max_score) * 100, 2) if max_score > 0 else 0,
        "results": results,
    }

    import time as _time
    db_client.update_exam(doc_id, {
        "status": "graded",
        "answers": answers,
        "grade": grade,
        "gradedAt": int(_time.time() * 1000),
    })

    return {"status": "success", "grade": grade}


def _pdf_to_image_uris(file_bytes: bytes, max_pages: int = 6) -> list:
    """Render PDF pages to PNG data URIs (for scanned/handwritten PDFs) using PyMuPDF."""
    import base64
    import fitz  # PyMuPDF
    uris = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        for page in doc[:max_pages]:
            # ~150 DPI is enough for the vision model to read handwriting/diagrams
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            png = pix.tobytes("png")
            uris.append(f"data:image/png;base64,{base64.b64encode(png).decode()}")
    finally:
        doc.close()
    return uris


@app.post("/api/exams/{doc_id}/submit-document")
async def submit_exam_document(doc_id: str, file: UploadFile = File(...)):
    """Grade a student's UPLOADED solved exam — typed (PDF/DOCX/TXT) or handwritten
    (PNG/JPG/WEBP, or a scanned PDF). Answers may include diagrams, code, and math.
    Reads the answers, grades against the rubric, stores and returns the result."""
    import base64
    import time as _time

    exam = db_client.get_exam(doc_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    rubrics = exam.get("rubrics", {})
    questions_rubrics = rubrics.get("questions", {})
    for key, val in rubrics.items():
        if key.startswith("q") and key[1:].isdigit() and isinstance(val, dict):
            questions_rubrics.setdefault(key, val)
    if not questions_rubrics:
        raise HTTPException(status_code=400, detail="No rubric found for this exam.")

    file_bytes = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()

    submission_text = None
    image_data_uris = None
    image_mimes = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}

    try:
        if ext in image_mimes:
            uri = f"data:{image_mimes[ext]};base64,{base64.b64encode(file_bytes).decode()}"
            image_data_uris = [uri]
        elif ext == "pdf":
            text = doc_processor.extract_text(file_bytes, "pdf")
            if len(text.strip()) >= 40:
                # Typed PDF — grade from extracted text
                submission_text = text
            else:
                # Scanned / handwritten PDF — render pages to images for the vision model
                try:
                    image_data_uris = _pdf_to_image_uris(file_bytes)
                except Exception as e:
                    logger.error(f"PDF->image render failed: {e}")
                    image_data_uris = None
                if not image_data_uris:
                    raise HTTPException(
                        status_code=422,
                        detail="Couldn't read this PDF. Please upload a clearer scan or a photo (PNG/JPG).",
                    )
        elif ext == "docx":
            submission_text = doc_processor.extract_text(file_bytes, "docx")
        elif ext == "txt":
            submission_text = file_bytes.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read the file: {str(e)}")

    raw_results = ai_agent.grade_document_submission(
        questions_rubrics,
        exam.get("texContent", ""),
        submission_text=submission_text,
        image_data_uris=image_data_uris,
    )

    results = {}
    total_score = 0.0
    max_score = 0.0
    for q_id, rubric in sorted(questions_rubrics.items()):
        q_type = rubric.get("question_type", "written")
        q_max = float(rubric.get("max_score", 5.0 if q_type in ("mcq", "true_false") else 15.0))
        got = raw_results.get(q_id, {}) if isinstance(raw_results, dict) else {}
        try:
            score = min(float(got.get("score", 0) or 0), q_max)
        except (TypeError, ValueError):
            score = 0.0
        # Model answer: prefer the grader's full worked answer; fall back to the
        # rubric's correct_answer/criteria so there's always something to show.
        model_answer = (got.get("model_answer") or "").strip()
        if not model_answer:
            if q_type in ("mcq", "true_false"):
                ca = rubric.get("correct_answer", "")
                expl = rubric.get("explanation", "")
                model_answer = f"{ca}{(' — ' + expl) if expl else ''}".strip()
            else:
                model_answer = rubric.get("criteria", "")
        entry = {
            "score": round(score, 2),
            "max_score": q_max,
            "feedback": got.get("feedback", ""),
            "student_answer": (got.get("student_answer") or "").strip(),
            "model_answer": model_answer,
        }
        if q_type in ("mcq", "true_false"):
            entry["correct_answer"] = rubric.get("correct_answer", "")
            entry["is_correct"] = score >= q_max
            entry["explanation"] = rubric.get("explanation", "")
        results[q_id] = entry
        total_score += score
        max_score += q_max

    grade = {
        "totalScore": round(total_score, 2),
        "maxScore": round(max_score, 2),
        "percentage": round((total_score / max_score) * 100, 2) if max_score > 0 else 0,
        "results": results,
    }

    db_client.update_exam(doc_id, {
        "status": "graded",
        "grade": grade,
        "submissionMethod": "document",
        "gradedAt": int(_time.time() * 1000),
    })

    return {"status": "success", "grade": grade}


# ──────────────────────────────────────────────────
# Course Intelligence Summary
# ──────────────────────────────────────────────────

@app.get("/api/intelligence/{course_id}")
def get_course_intelligence_endpoint(course_id: str):
    intelligence = db_client.get_course_intelligence(course_id)
    return {"status": "success", **intelligence}


# ──────────────────────────────────────────────────
# Flashcards — generate study cards from course intelligence
# ──────────────────────────────────────────────────

class FlashcardGenerateRequest(BaseModel):
    user_id: str
    course_id: str
    topics: List[str] = []
    document_ids: List[str] = []
    historical_exam_ids: List[str] = []
    tutorial_ids: List[str] = []
    audio_ids: List[str] = []
    count: int = 20

@app.post("/api/flashcards/generate")
def generate_flashcards_endpoint(payload: FlashcardGenerateRequest):
    import uuid
    import time as _time

    set_id = f"fc_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating flashcard set {set_id} for course {payload.course_id}")

    intelligence = db_client.get_course_intelligence(
        payload.course_id,
        document_ids=payload.document_ids if payload.document_ids else None,
        historical_exam_ids=payload.historical_exam_ids if payload.historical_exam_ids else None,
        tutorial_ids=payload.tutorial_ids if payload.tutorial_ids else None,
        audio_ids=payload.audio_ids if payload.audio_ids else None,
    )

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
    doc_db_id = db_client.save_flashcard_set(payload.user_id, payload.course_id, {
        "setId": set_id,
        "title": title,
        "cards": cards,
        "sourceSummary": {"documentIds": payload.document_ids or []},
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
def list_flashcard_sets(course_id: str):
    sets = db_client.get_course_flashcard_sets(course_id)
    safe = [{
        "id": s.get("id"),
        "setId": s.get("setId"),
        "title": s.get("title"),
        "cardCount": len(s.get("cards", [])),
        "createdAt": s.get("createdAt"),
    } for s in sets]
    return {"status": "success", "sets": safe}


@app.get("/api/flashcards/detail/{doc_id}")
def get_flashcard_set_detail(doc_id: str):
    fc = db_client.get_flashcard_set(doc_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Flashcard set not found")
    return {"status": "success", "set": fc}


@app.delete("/api/flashcards/{doc_id}")
def delete_flashcard_set_endpoint(doc_id: str):
    fc = db_client.get_flashcard_set(doc_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Flashcard set not found")
    db_client.delete_flashcard_set(doc_id)
    logger.info(f"Flashcard set {doc_id} deleted.")
    return {"status": "success", "deleted": doc_id}


# ──────────────────────────────────────────────────
# Summaries — generate study summaries from course intelligence
# ──────────────────────────────────────────────────

class SummaryGenerateRequest(BaseModel):
    user_id: str
    course_id: str
    topics: List[str] = []
    document_ids: List[str] = []
    historical_exam_ids: List[str] = []
    tutorial_ids: List[str] = []
    audio_ids: List[str] = []
    instructions: str = ""

_SUMMARY_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "what", "which", "how", "into", "using", "use", "based", "via", "per", "its",
    "introduction", "overview", "concepts", "concept", "fundamentals", "basics",
    "topic", "topics", "chapter", "section", "part", "general", "review",
}


def _topic_word_set(text: str) -> set:
    import re as _re
    return {
        w for w in _re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _SUMMARY_STOPWORDS
    }


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

    Deliberately conservative: with no selected documents there's nothing to
    scope against, and if the filter would remove more than half the sections we
    assume the heuristic — not the model — is wrong and keep everything."""
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
        return len(hits) >= min_hits

    def section_in_scope(sec: dict) -> bool:
        return topic_in_scope(sec.get("heading", ""), words) or body_touches_scope(sec)

    kept = [s for s in sections if section_in_scope(s)]
    dropped = len(sections) - len(kept)
    if not dropped:
        return summary
    if len(kept) < len(sections) / 2:
        logger.warning(
            f"Summary: scope filter would drop {dropped}/{len(sections)} sections — "
            "treating that as a bad match and keeping all of them."
        )
        return summary

    logger.info(
        "Summary: dropped %d section(s) outside the selected documents: %s",
        dropped,
        ", ".join(s.get("heading", "?") for s in sections if s not in kept),
    )
    summary["sections"] = kept
    return summary


@app.post("/api/summaries/generate")
def generate_summary_endpoint(payload: SummaryGenerateRequest):
    import uuid
    import time as _time

    summary_id = f"sum_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating summary {summary_id} for course {payload.course_id}")

    intelligence = db_client.get_course_intelligence(
        payload.course_id,
        document_ids=payload.document_ids if payload.document_ids else None,
        historical_exam_ids=payload.historical_exam_ids if payload.historical_exam_ids else None,
        tutorial_ids=payload.tutorial_ids if payload.tutorial_ids else None,
        audio_ids=payload.audio_ids if payload.audio_ids else None,
    )

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
    course_docs = db_client.get_course_documents(payload.course_id)
    course_docs = [d for d in course_docs if d.get("status") == "completed" and d.get("analysis")]
    if payload.document_ids:
        by_id = {d.get("id"): d for d in course_docs}
        course_docs = [by_id[i] for i in payload.document_ids if i in by_id]
    doc_titles = [(d.get("title") or "") for d in course_docs]
    title = _compose_summary_title(doc_titles, summary.get("title"))

    doc_db_id = db_client.save_summary(payload.user_id, payload.course_id, {
        "summaryId": summary_id,
        "title": title,
        "overview": summary.get("overview", ""),
        "sections": summary.get("sections", []),
        "keyTerms": summary.get("keyTerms", []),
        "examFocus": summary.get("examFocus", []),
        "sourceSummary": {"documentIds": payload.document_ids or []},
        "createdAt": int(_time.time() * 1000),
    })

    return {"status": "success", "summary_id": summary_id, "doc_id": doc_db_id, **summary}


@app.get("/api/summaries/list/{course_id}")
def list_summaries(course_id: str):
    items = db_client.get_course_summaries(course_id)
    safe = [{
        "id": s.get("id"),
        "summaryId": s.get("summaryId"),
        "title": s.get("title"),
        "sectionCount": len(s.get("sections", [])),
        "createdAt": s.get("createdAt"),
    } for s in items]
    return {"status": "success", "summaries": safe}


@app.get("/api/summaries/detail/{doc_id}")
def get_summary_detail(doc_id: str):
    s = db_client.get_summary(doc_id)
    if not s:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"status": "success", "summary": s}


@app.delete("/api/summaries/{doc_id}")
def delete_summary_endpoint(doc_id: str):
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
    esc = lambda x: _md_inline_to_latex(_latex_escape(x))
    parts = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[a4paper,margin=2.2cm]{geometry}",
        r"\usepackage[T1]{fontenc}",
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
def get_summary_pdf(doc_id: str):
    import tempfile
    from src.utils.compile_pdf import compile_tex_to_pdf

    s = db_client.get_summary(doc_id)
    if not s:
        raise HTTPException(status_code=404, detail="Summary not found")

    tex = _summary_to_latex(s)
    name = s.get("summaryId", doc_id)
    try:
        tmpdir = tempfile.mkdtemp()
        tex_path = os.path.join(tmpdir, f"{name}.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)
        pdf_path = compile_tex_to_pdf(tex_path)
        if not pdf_path or not os.path.exists(pdf_path):
            raise HTTPException(status_code=422, detail="Summary PDF compilation failed")
        return FileResponse(
            pdf_path, media_type="application/pdf",
            filename=f"{name}.pdf", content_disposition_type="inline",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Summary PDF compile failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF error: {str(e)}")


def _audio_to_latex(rec: dict) -> str:
    """Build a printable LaTeX document that mirrors the UI's audio view: the AI
    analysis only — Lecture Summary, Exam Hints, Key Emphasis, Chapter Breakdown
    (no raw transcript).

    A plain left-to-right document (like the web UI). Compiled with XeLaTeX (see
    get_audio_pdf) with a Unicode font, so the professor's verbatim quotes — which
    may be Arabic — render correctly inline instead of being stripped, while the
    summary/headings stay English."""
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
        r"\usepackage{fontspec}",
        r"\usepackage{polyglossia}",
        r"\setmainlanguage{english}",
        r"\setotherlanguage{arabic}",
        # No \setmainfont: keep XeLaTeX's default Latin Modern (the original
        # serif look). Only Arabic runs use an Arabic-capable font, shaped.
        # Font family is platform-configurable: Windows dev defaults to "Arial";
        # the Linux/Docker deploy sets AUDIO_ARABIC_FONT=Amiri (bundled TTF).
        r"\newfontfamily\arabicfont[Script=Arabic]{" + os.getenv("AUDIO_ARABIC_FONT", "Arial") + r"}",
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
def get_audio_pdf(rec_id: str):
    """Compile and serve a PDF of a recording's analysis + transcript."""
    import tempfile
    from src.utils.compile_pdf import compile_tex_to_pdf

    rec = db_client.get_audio_recording(rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if not (rec.get("insights") or rec.get("transcript")):
        raise HTTPException(
            status_code=409,
            detail="This recording hasn't been analyzed yet.",
        )

    tex = _audio_to_latex(rec)
    name = (rec.get("title") or rec_id).strip() or rec_id
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60] or rec_id
    try:
        tmpdir = tempfile.mkdtemp()
        tex_path = os.path.join(tmpdir, f"{safe}.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)
        # XeLaTeX so the professor's original-language (Arabic / mixed) speech
        # renders with correct shaping + RTL instead of being stripped.
        pdf_path = compile_tex_to_pdf(tex_path, engine="xelatex")
        if not pdf_path or not os.path.exists(pdf_path):
            raise HTTPException(status_code=422, detail="Audio PDF compilation failed")
        return FileResponse(
            pdf_path, media_type="application/pdf",
            filename=f"{safe}.pdf", content_disposition_type="inline",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Audio PDF compile failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF error: {str(e)}")


# ──────────────────────────────────────────────────
# Weekly lecture schedule (Sunday–Thursday)
# ──────────────────────────────────────────────────

_VALID_DAYS = {"sunday", "monday", "tuesday", "wednesday", "thursday"}

def _to_minutes(hhmm: str):
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
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
def create_schedule_entry(payload: ScheduleEntryRequest):
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

    _check_schedule_overlap(payload.user_id, day, start, end, exclude_id=None)

    entry = {
        "day": day,
        "startTime": payload.start_time.strip(),
        "endTime": payload.end_time.strip(),
        "hall": payload.hall.strip(),
        "courseId": payload.courseId.strip(),
        "title": payload.title.strip(),
        "createdAt": int(_time.time() * 1000),
    }
    entry_id = db_client.save_schedule_entry(payload.user_id, entry)
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
def update_schedule_entry(entry_id: str, payload: ScheduleEntryRequest):
    day = (payload.day or "").strip().lower()
    if day not in _VALID_DAYS:
        raise HTTPException(status_code=400, detail="Day must be Sunday through Thursday.")
    start = _to_minutes(payload.start_time.strip())
    end = _to_minutes(payload.end_time.strip())
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="Start and end time are required (HH:MM).")
    if end <= start:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    _check_schedule_overlap(payload.user_id, day, start, end, exclude_id=entry_id)

    data = {
        "day": day,
        "startTime": payload.start_time.strip(),
        "endTime": payload.end_time.strip(),
        "hall": payload.hall.strip(),
        "courseId": payload.courseId.strip(),
        "title": payload.title.strip(),
    }
    db_client.update_schedule_entry(entry_id, data)
    return {"status": "success", "id": entry_id, **data}


@app.get("/api/schedule/{user_id}")
def list_schedule(user_id: str):
    return {"status": "success", "entries": db_client.get_user_schedule_entries(user_id)}


@app.delete("/api/schedule/{entry_id}")
def delete_schedule_entry(entry_id: str):
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

@app.post("/api/tutor/chat")
def tutor_chat(payload: TutorChatRequest):
    import time as _time
    if not payload.messages:
        raise HTTPException(status_code=400, detail="No messages provided.")

    # The tutor reads its resources DIRECTLY from the DBs, restricted to the
    # specific lectures and past exams the student selected.
    resources = db_client.get_tutor_resources(
        payload.course_id,
        document_ids=payload.document_ids,
        recording_ids=payload.recording_ids,
        historical_exam_ids=payload.historical_exam_ids,
        tutorial_ids=payload.tutorial_ids,
    )

    try:
        reply = tutor_agent.reply(resources, payload.messages)
    except Exception as e:
        logger.error(f"Tutor reply failed: {e}")
        raise HTTPException(status_code=500, detail=f"Tutor error: {str(e)}")

    # Persist the conversation in its own tutor_chats table
    full_messages = list(payload.messages) + [{"role": "assistant", "content": reply}]
    now = int(_time.time() * 1000)
    if payload.chat_id:
        db_client.update_tutor_chat(payload.chat_id, {"messages": full_messages, "updatedAt": now})
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
def list_tutor_chats(user_id: str, course_id: str):
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
def get_tutor_chat_detail(chat_id: str):
    chat = db_client.get_tutor_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "success", "chat": chat}


@app.delete("/api/tutor/chat/{chat_id}")
def delete_tutor_chat_endpoint(chat_id: str):
    db_client.delete_tutor_chat(chat_id)
    return {"status": "success", "deleted": chat_id}


if __name__ == "__main__":
    # reload=False: the auto-reloader watches the whole backend/ tree and would
    # restart (dropping in-flight requests → "failed to fetch") whenever an
    # uploaded file is written under backend/uploads/. Long exam generations
    # must not be interrupted, so reload is off. Set MUDARIS_RELOAD=1 to enable
    # it during active development.
    _reload = os.getenv("MUDARIS_RELOAD", "0") == "1"
    # Cloud hosts (Render) inject $PORT and require binding to 0.0.0.0.
    # Local dev keeps the original 127.0.0.1:8000 defaults.
    _host = os.getenv("HOST", "127.0.0.1")
    _port = int(os.getenv("PORT", "8000"))
    uvicorn.run("src.api:app", host=_host, port=_port, reload=_reload)