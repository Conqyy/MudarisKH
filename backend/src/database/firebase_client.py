import os
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("MudarisDatabase")

class FirebaseClient:
    def __init__(self, settings=None):
        """
        Initializes the Database Client robustly for Mudaris Exam Engine.
        """
        if settings is None:
            from src.config.settings import settings as _settings
            settings = _settings
        self.use_local = False
        self.local_db_path = Path("mudaris_local_db.json")
        
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            
            # Smart key path resolution
            key_path = getattr(settings, 'FIREBASE_KEY_PATH', None)
            
            if not key_path or not os.path.exists(key_path):
                if os.path.exists("src/config/firebase-key.json"):
                    key_path = "src/config/firebase-key.json"
                elif os.path.exists("config/firebase-key.json"):
                    key_path = "config/firebase-key.json"
                
            if key_path and os.path.exists(key_path):
                if not firebase_admin._apps:
                    cred = credentials.Certificate(key_path)
                    bucket_name = getattr(settings, 'STORAGE_BUCKET', None)
                    init_opts = {}
                    if bucket_name:
                        init_opts['storageBucket'] = bucket_name
                    firebase_admin.initialize_app(cred, init_opts)
                self.db = firestore.client()
                logger.info("🔥 Successfully connected to Cloud Firebase Firestore Database.")
            else:
                logger.warning(f"⚠️ Firebase Key not found. Falling back to local offline DB.")
                self.use_local = True
                
        except Exception as e:
            logger.warning(f"⚠️ Firebase initialization failed ({e}). Falling back to local offline DB.")
            self.use_local = True

        if self.use_local:
            self._initialize_local_database()

    def _initialize_local_database(self):
        if self.local_db_path.exists():
            return
        logger.info("📦 First run: Seeding local mock database 'mudaris_local_db.json' for Al Imam University...")
        initial_data = {
            "users": {
                "sultan_123": {
                    "profile": {
                        "name": "Sultan Al-Otaibi",
                        "university": "Imam Mohammad Ibn Saud Islamic University"
                    },
                    "courses": {
                        "cs464": {
                            "university": "Imam Mohammad Ibn Saud Islamic University",
                            "college": "College of Computer and Information Sciences",
                            "lectures": {
                                "lec_3": {"text": "CNNs calculate output sizes using (W - F + 2P)/S + 1."},
                                "lec_4": {"text": "Backpropagation uses the Chain Rule to calculate gradients."}
                            },
                            "exams": {}
                        }
                    }
                }
            }
        }
        with open(self.local_db_path, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=4, ensure_ascii=False)
        logger.info("✅ Local database successfully created and seeded offline!")

    def _read_local_db(self) -> dict:
        if not self.local_db_path.exists():
            self._initialize_local_database()
        with open(self.local_db_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_local_db(self, data: dict):
        with open(self.local_db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def get_selected_context(self, user_id: str, course_id: str, selected_lectures: list) -> dict:
        if self.use_local:
            data = self._read_local_db()
            course_node = data.get("users", {}).get(user_id, {}).get("courses", {}).get(course_id, {})
            lectures_content = [
                course_node.get("lectures", {}).get(lec_id, {}).get("text", "") 
                for lec_id in selected_lectures if lec_id in course_node.get("lectures", {})
            ]
            return {
                "transcripts": "\n".join(lectures_content) if lectures_content else "No lecture data.",
                "cues": "Focus heavily on Backpropagation chain rules and Convolution matrix dimensions.",
                "university": course_node.get("university", "Imam University"),
                "college": course_node.get("college", "")
            }
        
        try:
            course_ref = self.db.collection('users').document(user_id) \
                                .collection('courses').document(course_id)
            course_doc = course_ref.get()
            context = {
                "transcripts": "No transcripts found.",
                "cues": "Standard academic prep.",
                "university": "Imam Mohammad Ibn Saud Islamic University",
                "college": "College of Computer and Information Sciences"
            }
            if course_doc.exists:
                course_data = course_doc.to_dict()
                context["university"] = course_data.get("university", context["university"])
                context["college"] = course_data.get("college", context["college"])
                lectures_content = []
                for lec_id in selected_lectures:
                    lec_doc = course_ref.collection('lectures').document(lec_id).get()
                    if lec_doc.exists:
                        lectures_content.append(lec_doc.to_dict().get("text", ""))
                if lectures_content:
                    context["transcripts"] = "\n".join(lectures_content)
            return context
        except Exception as e:
            logger.error(f"Error fetching context: {e}")
            return {"transcripts": "", "cues": "", "university": "", "college": ""}

    def upload_generated_exam(self, user_id: str, course_id: str, exam_id: str, html_content: str) -> str:
        output_file = f"mock_exam_{exam_id}.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        return f"file:///{os.path.abspath(output_file)}"

    # ──────────────────────────────────────────────────
    # Flat-collection methods for Models 1/2/3/4
    # ──────────────────────────────────────────────────

    def _flat_save(self, collection_name: str, data: dict) -> str:
        if self.use_local:
            local = self._read_local_db()
            local.setdefault(collection_name, {})
            doc_id = f"{collection_name}_{int(time.time()*1000)}"
            local[collection_name][doc_id] = data
            self._write_local_db(local)
            return doc_id
        doc_ref = self.db.collection(collection_name).document()
        doc_ref.set(data)
        return doc_ref.id

    def _flat_update(self, collection_name: str, doc_id: str, data: dict):
        if self.use_local:
            local = self._read_local_db()
            if collection_name in local and doc_id in local[collection_name]:
                local[collection_name][doc_id].update(data)
                self._write_local_db(local)
            return
        self.db.collection(collection_name).document(doc_id).update(data)

    def _flat_get(self, collection_name: str, doc_id: str) -> dict:
        if self.use_local:
            local = self._read_local_db()
            item = local.get(collection_name, {}).get(doc_id)
            if item:
                return {**item, "id": doc_id}
            return {}
        doc = self.db.collection(collection_name).document(doc_id).get()
        if doc.exists:
            return {**doc.to_dict(), "id": doc.id}
        return {}

    def _flat_query_by_course(self, collection_name: str, course_id: str) -> list:
        if self.use_local:
            local = self._read_local_db()
            results = []
            for doc_id, doc_data in local.get(collection_name, {}).items():
                if doc_data.get("courseId") == course_id:
                    results.append({**doc_data, "id": doc_id})
            return results
        from google.cloud.firestore_v1.base_query import FieldFilter
        docs = self.db.collection(collection_name).where(
            filter=FieldFilter("courseId", "==", course_id)
        ).stream()
        return [{**d.to_dict(), "id": d.id} for d in docs]

    def _flat_delete(self, collection_name: str, doc_id: str):
        if self.use_local:
            local = self._read_local_db()
            if collection_name in local and doc_id in local[collection_name]:
                del local[collection_name][doc_id]
                self._write_local_db(local)
            return
        self.db.collection(collection_name).document(doc_id).delete()

    # --- Documents (Model 1) ---
    def save_document(self, user_id: str, course_id: str, doc_data: dict) -> str:
        doc_data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("documents", doc_data)

    def update_document(self, doc_id: str, data: dict):
        self._flat_update("documents", doc_id, data)

    def get_document(self, doc_id: str) -> dict:
        return self._flat_get("documents", doc_id)

    def get_course_documents(self, course_id: str) -> list:
        return self._flat_query_by_course("documents", course_id)

    def delete_document(self, doc_id: str):
        self._flat_delete("documents", doc_id)

    # --- Audio Recordings (Model 2) ---
    def save_audio_recording(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("audio_recordings", data)

    def update_audio_recording(self, rec_id: str, data: dict):
        self._flat_update("audio_recordings", rec_id, data)

    def get_audio_recording(self, rec_id: str) -> dict:
        return self._flat_get("audio_recordings", rec_id)

    def get_course_audio_recordings(self, course_id: str) -> list:
        return self._flat_query_by_course("audio_recordings", course_id)

    def delete_audio_recording(self, rec_id: str):
        self._flat_delete("audio_recordings", rec_id)

    # --- Historical Exams (Model 3) ---
    def save_historical_exam(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("historical_exams", data)

    def update_historical_exam(self, exam_id: str, data: dict):
        self._flat_update("historical_exams", exam_id, data)

    def get_course_historical_exams(self, course_id: str) -> list:
        return self._flat_query_by_course("historical_exams", course_id)

    def delete_historical_exam(self, exam_id: str):
        self._flat_delete("historical_exams", exam_id)

    # --- Tutorials (practice problems — ideas only, no grading weight/format) ---
    def save_tutorial(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("tutorials", data)

    def update_tutorial(self, tut_id: str, data: dict):
        self._flat_update("tutorials", tut_id, data)

    def get_tutorial(self, tut_id: str) -> dict:
        return self._flat_get("tutorials", tut_id)

    def get_course_tutorials(self, course_id: str) -> list:
        return self._flat_query_by_course("tutorials", course_id)

    def delete_tutorial(self, tut_id: str):
        self._flat_delete("tutorials", tut_id)

    # --- Generated Exams (flat, for enhanced generator) ---
    def save_exam_flat(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("exams", data)

    def update_exam(self, doc_id: str, data: dict):
        self._flat_update("exams", doc_id, data)

    def get_exam(self, doc_id: str) -> dict:
        return self._flat_get("exams", doc_id)

    def get_course_exams(self, course_id: str) -> list:
        return self._flat_query_by_course("exams", course_id)

    def delete_exam(self, doc_id: str):
        self._flat_delete("exams", doc_id)

    # --- Flashcard Sets ---
    def save_flashcard_set(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("flashcard_sets", data)

    def get_flashcard_set(self, doc_id: str) -> dict:
        return self._flat_get("flashcard_sets", doc_id)

    def get_course_flashcard_sets(self, course_id: str) -> list:
        return self._flat_query_by_course("flashcard_sets", course_id)

    def delete_flashcard_set(self, doc_id: str):
        self._flat_delete("flashcard_sets", doc_id)

    # --- Summaries ---
    def save_summary(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("summaries", data)

    def get_summary(self, doc_id: str) -> dict:
        return self._flat_get("summaries", doc_id)

    def get_course_summaries(self, course_id: str) -> list:
        return self._flat_query_by_course("summaries", course_id)

    def delete_summary(self, doc_id: str):
        self._flat_delete("summaries", doc_id)

    # --- Weekly schedule entries (by user) ---
    def save_schedule_entry(self, user_id: str, data: dict) -> str:
        data.update({"userId": user_id})
        return self._flat_save("schedule_entries", data)

    def get_user_schedule_entries(self, user_id: str) -> list:
        if self.use_local:
            local = self._read_local_db()
            return [
                {**d, "id": k}
                for k, d in local.get("schedule_entries", {}).items()
                if d.get("userId") == user_id
            ]
        from google.cloud.firestore_v1.base_query import FieldFilter
        docs = self.db.collection("schedule_entries").where(
            filter=FieldFilter("userId", "==", user_id)
        ).stream()
        return [{**d.to_dict(), "id": d.id} for d in docs]

    def update_schedule_entry(self, entry_id: str, data: dict):
        self._flat_update("schedule_entries", entry_id, data)

    def delete_schedule_entry(self, entry_id: str):
        self._flat_delete("schedule_entries", entry_id)

    # ──────────────────────────────────────────────────
    # AI Tutor — own resources + persistent chat history
    # ──────────────────────────────────────────────────

    def get_tutor_resources(self, course_id: str, document_ids=None,
                            recording_ids=None, historical_exam_ids=None,
                            tutorial_ids=None) -> dict:
        """Resource bundle for the AI Tutor, read DIRECTLY from the course,
        voice-recording, past-exam, tutorial, and document collections —
        independent of the other AI agents. Optional id lists restrict which
        items are included (None = include all of that type)."""
        course = self._flat_get("courses", course_id)
        docs = [d for d in self.get_course_documents(course_id) if d.get("status") == "completed"]
        recs = [a for a in self.get_course_audio_recordings(course_id) if a.get("status") == "completed"]
        exams = [h for h in self.get_course_historical_exams(course_id) if h.get("status") == "completed"]
        tuts = [t for t in self.get_course_tutorials(course_id) if t.get("status") == "completed"]

        if document_ids is not None:
            docs = [d for d in docs if d.get("id") in document_ids]
        if recording_ids is not None:
            recs = [a for a in recs if a.get("id") in recording_ids]
        if historical_exam_ids is not None:
            exams = [h for h in exams if h.get("id") in historical_exam_ids]
        if tutorial_ids is not None:
            tuts = [t for t in tuts if t.get("id") in tutorial_ids]

        return {
            "course": {
                "title": course.get("title", ""),
                "code": course.get("code", ""),
                "instructor": course.get("instructor", ""),
            },
            "documents": [
                {"id": d.get("id"), "title": d.get("title", ""), "extractedText": d.get("extractedText", ""), "analysis": d.get("analysis", {})}
                for d in docs
            ],
            "recordings": [
                {"id": a.get("id"), "title": a.get("title", ""), "transcript": a.get("transcript", ""), "insights": a.get("insights", {})}
                for a in recs
            ],
            "past_exams": [
                {"id": h.get("id"), "title": h.get("title", ""), "extractedText": h.get("extractedText", ""), "analysis": h.get("analysis", {})}
                for h in exams
            ],
            "tutorials": [
                {"id": t.get("id"), "title": t.get("title", ""), "extractedText": t.get("extractedText", ""), "analysis": t.get("analysis", {})}
                for t in tuts
            ],
        }

    def save_tutor_chat(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("tutor_chats", data)

    def get_tutor_chat(self, chat_id: str) -> dict:
        return self._flat_get("tutor_chats", chat_id)

    def update_tutor_chat(self, chat_id: str, data: dict):
        self._flat_update("tutor_chats", chat_id, data)

    def get_user_course_tutor_chats(self, user_id: str, course_id: str) -> list:
        return [
            c for c in self._flat_query_by_course("tutor_chats", course_id)
            if c.get("userId") == user_id
        ]

    def delete_tutor_chat(self, chat_id: str):
        self._flat_delete("tutor_chats", chat_id)

    # --- Course Intelligence Aggregator ---
    def get_course_intelligence(self, course_id: str, document_ids: list = None,
                                historical_exam_ids: list = None,
                                tutorial_ids: list = None,
                                audio_ids: list = None) -> dict:
        docs = self.get_course_documents(course_id)
        audio = self.get_course_audio_recordings(course_id)
        historical = self.get_course_historical_exams(course_id)
        tutorials = self.get_course_tutorials(course_id)

        completed_docs = [d for d in docs if d.get("status") == "completed" and d.get("analysis")]
        if document_ids:
            completed_docs = [d for d in completed_docs if d.get("id") in document_ids]
        # Merge the document's title into its analysis — the title is often the
        # clearest topic name (e.g. "13- NP-Completeness") and is used for course
        # scope matching alongside the extracted topics.
        doc_analyses = []
        for d in completed_docs:
            a = dict(d.get("analysis", {}) or {})
            a.setdefault("documentTitle", d.get("title", ""))
            doc_analyses.append(a)
        doc_texts = [d.get("extractedText", "") for d in completed_docs if d.get("extractedText")]

        completed_audio = [a for a in audio if a.get("status") == "completed" and a.get("insights")]
        if audio_ids:
            completed_audio = [a for a in completed_audio if a.get("id") in audio_ids]
        audio_insights = [a.get("insights", {}) for a in completed_audio]

        completed_hist = [h for h in historical if h.get("status") == "completed" and h.get("analysis")]
        if historical_exam_ids:
            completed_hist = [h for h in completed_hist if h.get("id") in historical_exam_ids]
        hist_analyses = [h.get("analysis", {}) for h in completed_hist]
        hist_texts = [h.get("extractedText", "") for h in completed_hist if h.get("extractedText")]

        # Tutorials: ideas/content only — fed to the generator WITHOUT grading
        # weight or format influence (the prompt enforces that distinction).
        completed_tut = [t for t in tutorials if t.get("status") == "completed" and t.get("analysis")]
        if tutorial_ids:
            completed_tut = [t for t in completed_tut if t.get("id") in tutorial_ids]
        tut_analyses = [t.get("analysis", {}) for t in completed_tut]
        tut_texts = [t.get("extractedText", "") for t in completed_tut if t.get("extractedText")]

        return {
            "document_analyses": doc_analyses,
            "document_texts": doc_texts,
            "audio_insights": audio_insights,
            "historical_analyses": hist_analyses,
            "historical_texts": hist_texts,
            "tutorial_analyses": tut_analyses,
            "tutorial_texts": tut_texts,
            "counts": {
                "documents": len(doc_analyses),
                "audio": len(audio_insights),
                "historical_exams": len(hist_analyses),
                "tutorials": len(tut_analyses),
            }
        }

    # --- Firebase Storage helpers ---
    def upload_file_to_storage(self, file_bytes: bytes, storage_path: str) -> str:
        local_path = Path("uploads") / storage_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        local_url = f"file:///{local_path.resolve()}"

        if self.use_local:
            return local_url

        try:
            from firebase_admin import storage as fb_storage
            bucket = fb_storage.bucket()
            blob = bucket.blob(storage_path)
            blob.upload_from_string(file_bytes)
            blob.make_public()
            return blob.public_url
        except Exception as e:
            logger.warning(f"Cloud storage upload failed ({e}), using local file.")
            return local_url

    def delete_file_from_storage(self, storage_path: str):
        if self.use_local:
            local_path = Path("uploads") / storage_path
            if local_path.exists():
                local_path.unlink()
            return
        from firebase_admin import storage
        bucket = storage.bucket()
        blob = bucket.blob(storage_path)
        if blob.exists():
            blob.delete()

    # ──────────────────────────────────────────────────
    # Original methods (untouched)
    # ──────────────────────────────────────────────────

    def save_secret_rubrics(self, user_id: str, course_id: str, exam_id: str, rubrics_data: dict):
        if self.use_local:
            data = self._read_local_db()
            data.setdefault("users", {}).setdefault(user_id, {}).setdefault("courses", {}).setdefault(course_id, {}).setdefault("exams", {})
            data["users"][user_id]["courses"][course_id]["exams"][exam_id] = rubrics_data
            self._write_local_db(data)
            logger.info(f"🔒 Secret rubrics for exam '{exam_id}' saved securely in mudaris_local_db.json.")
            return

        try:
            from firebase_admin import firestore
            self.db.collection('users').document(user_id) \
                   .collection('courses').document(course_id) \
                   .collection('exams').document(exam_id).set({
                       "exam_id": exam_id,
                       "rubrics": rubrics_data,
                       "created_at": firestore.SERVER_TIMESTAMP
                   }, merge=True)
            logger.info(f"🔒 Secret rubrics for exam '{exam_id}' uploaded securely to Cloud Firestore.")
        except Exception as e:
            logger.error(f"Failed to save rubrics to cloud: {e}")