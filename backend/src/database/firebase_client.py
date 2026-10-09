import os
import json
import logging
import time
import threading
import uuid
import tempfile
import re
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from src.utils.storage_paths import BACKEND_ROOT, UPLOADS_ROOT, resolve_storage_path, validate_component, STORAGE_CATEGORIES

logger = logging.getLogger("MudarisDatabase")

_LOCAL_MUTEX = threading.RLock()
_LOCAL_DEPTH = threading.local()


class DataConflict(ValueError):
    """A concurrently modified/deleted target prevents a stale write."""


class DataDeletionConflict(DataConflict):
    """An account deletion marker prevents new application writes."""


class DataSizeConflict(ValueError):
    """A complete record exceeds the conservative Firestore write limit."""


MAX_RECORD_BYTES = 750000


def validate_record_size(data: dict):
    estimated = len(json.dumps(data, ensure_ascii=False, default=str, separators=(',', ':'), allow_nan=False).encode('utf-8'))
    if estimated > MAX_RECORD_BYTES:
        raise DataSizeConflict('This saved record is too large. Split the source or start a smaller conversation.')


def local_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.use_local:
            return method(self, *args, **kwargs)
        with self._local_transaction():
            return method(self, *args, **kwargs)
    return wrapper

class FirebaseClient:
    def __init__(self, settings=None):
        """
        Initializes the Database Client robustly for Mudaris Exam Engine.
        """
        if settings is None:
            from src.config.settings import settings as _settings
            settings = _settings
        self.use_local = False
        self.local_db_path = BACKEND_ROOT / "mudaris_local_db.json"
        
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            # The service-account key is a firebase-key.json file resolved by
            # path. (A cloud deploy used to pass the whole JSON in an env var
            # instead; that path went away with the Render service.)
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

    @contextmanager
    def _local_transaction(self):
        """Serialize whole-file transactions across threads and worker processes."""
        with _LOCAL_MUTEX:
            depth = getattr(_LOCAL_DEPTH, "depth", 0)
            _LOCAL_DEPTH.depth = depth + 1
            try:
                if depth:
                    yield
                    return
                self.local_db_path.parent.mkdir(parents=True, exist_ok=True)
                with open(str(self.local_db_path) + ".lock", "a+b") as lock:
                    lock.seek(0)
                    if not lock.read(1):
                        lock.write(b"0")
                        lock.flush()
                    lock.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        # LK_LOCK has a bounded retry; exhaustion fails safely.
                        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        lock.seek(0)
                        if os.name == "nt":
                            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                _LOCAL_DEPTH.depth = depth

    @local_locked
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

    @local_locked
    def _read_local_db(self) -> dict:
        if not self.local_db_path.exists():
            self._initialize_local_database()
        with open(self.local_db_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @local_locked
    def _write_local_db(self, data: dict):
        fd, temporary = tempfile.mkstemp(dir=self.local_db_path.parent, prefix=".mudaris-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.local_db_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    # ──────────────────────────────────────────────────
    # Flat-collection methods for Models 1/2/3/4
    # ──────────────────────────────────────────────────

    @local_locked
    def _flat_save(self, collection_name: str, data: dict) -> str:
        validate_record_size(data)
        user_id = data.get('userId') or data.get('uid')
        course_id = data.get('courseId') or None
        if collection_name in self.OWNED_COLLECTIONS and not user_id:
            raise ValueError('Application records require an owner')
        if self.use_local:
            self._assert_write_allowed(user_id, course_id)
            local = self._read_local_db()
            local.setdefault(collection_name, {})
            doc_id = f"{collection_name}_{uuid.uuid4().hex}"
            if collection_name == 'courses':
                self._assert_write_allowed(user_id, doc_id, parent_required=False)
            local[collection_name][doc_id] = data
            self._write_local_db(local)
            return doc_id
        doc_ref = self.db.collection(collection_name).document()
        from google.cloud import firestore
        @firestore.transactional
        def save(transaction):
            self._assert_write_allowed(user_id, doc_ref.id if collection_name == 'courses' else course_id,
                                       transaction, parent_required=collection_name != 'courses')
            transaction.set(doc_ref, data)
            return doc_ref.id
        return save(self.db.transaction())

    @local_locked
    def _flat_update(self, collection_name: str, doc_id: str, data: dict):
        if self.use_local:
            local = self._read_local_db()
            if collection_name in local and doc_id in local[collection_name]:
                current = local[collection_name][doc_id]
                self._assert_update_owner(current, data)
                self._assert_write_allowed(current.get('userId') or current.get('uid'), doc_id if collection_name == 'courses' else data.get('courseId', current.get('courseId')) or None)
                validate_record_size({**current, **data})
                local[collection_name][doc_id].update(data)
                self._write_local_db(local)
                return True
            return False
        from google.cloud import firestore
        reference = self.db.collection(collection_name).document(doc_id)
        @firestore.transactional
        def update(transaction):
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                return False
            current = snapshot.to_dict() or {}
            self._assert_update_owner(current, data)
            self._assert_write_allowed(current.get('userId') or current.get('uid'), doc_id if collection_name == 'courses' else data.get('courseId', current.get('courseId')) or None, transaction)
            validate_record_size({**current, **data})
            transaction.update(reference, data)
            return True
        return update(self.db.transaction())

    @staticmethod
    def _assert_update_owner(current: dict, changes: dict):
        if 'userId' in changes and changes['userId'] != current.get('userId'):
            raise DataConflict('Record ownership cannot change')
        if 'uid' in changes and changes['uid'] != current.get('uid'):
            raise DataConflict('Record ownership cannot change')

    @local_locked
    def begin_account_deletion(self, user_id: str):
        """Retain a content-free tombstone to reject late/in-flight recreation."""
        validate_component(user_id, 'user ID')
        marker = {'userId': user_id, 'startedAt': int(time.time() * 1000)}
        if self.use_local:
            local = self._read_local_db()
            local.setdefault('_account_deletions', {}).setdefault(user_id, marker)
            self._write_local_db(local)
        else:
            self.db.collection('_account_deletions').document(user_id).set(marker, merge=True)

    def is_account_deleting(self, user_id: str, transaction=None) -> bool:
        validate_component(user_id, 'user ID')
        if self.use_local:
            return user_id in self._read_local_db().get('_account_deletions', {})
        return self.db.collection('_account_deletions').document(user_id).get(transaction=transaction).exists

    def get_course_deletion_marker(self, course_id: str) -> dict:
        validate_component(course_id, 'course ID')
        return self._flat_get('_course_deletions', course_id)

    def is_course_deleting(self, course_id: str, transaction=None) -> bool:
        validate_component(course_id, 'course ID')
        if self.use_local:
            return course_id in self._read_local_db().get('_course_deletions', {})
        return self.db.collection('_course_deletions').document(course_id).get(transaction=transaction).exists

    @local_locked
    def _begin_course_deletion(self, user_id: str, course_id: str):
        def authorize(course, existing):
            if (course and course.get('userId') != user_id) or (existing and existing.get('userId') != user_id):
                raise DataConflict('Course not owned')
        marker = {'userId': user_id, 'courseId': course_id, 'startedAt': int(time.time() * 1000)}
        if self.use_local:
            local = self._read_local_db()
            existing = local.get('_course_deletions', {}).get(course_id, {})
            authorize(local.get('courses', {}).get(course_id, {}), existing)
            local.setdefault('_course_deletions', {}).setdefault(course_id, marker)
            self._write_local_db(local)
            return
        from google.cloud import firestore
        marker_ref = self.db.collection('_course_deletions').document(course_id)
        course_ref = self.db.collection('courses').document(course_id)
        @firestore.transactional
        def begin(transaction):
            existing = marker_ref.get(transaction=transaction)
            course = course_ref.get(transaction=transaction)
            authorize(course.to_dict() or {} if course.exists else {}, existing.to_dict() or {} if existing.exists else {})
            if not existing.exists:
                transaction.set(marker_ref, marker)
        begin(self.db.transaction())

    def _assert_write_allowed(self, user_id: str, course_id: str = None, transaction=None, parent_required=True):
        if not user_id:
            return
        if self.is_account_deleting(user_id, transaction):
            raise DataDeletionConflict('Account cleanup is in progress; new writes are disabled')
        if course_id:
            validate_component(course_id, 'course ID')
            if self.is_course_deleting(course_id, transaction):
                raise DataDeletionConflict('Course cleanup is in progress; new writes are disabled')
            if not parent_required:
                return
            if self.use_local:
                course = self._flat_get('courses', course_id)
            else:
                snapshot = self.db.collection('courses').document(course_id).get(transaction=transaction)
                course = snapshot.to_dict() or {} if snapshot.exists else {}
            if course.get('userId') != user_id:
                raise DataConflict('Course is no longer available')

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

    def _flat_query_by_course(self, collection_name: str, course_id: str, user_id: str = None) -> list:
        if self.use_local:
            local = self._read_local_db()
            results = []
            for doc_id, doc_data in local.get(collection_name, {}).items():
                if doc_data.get("courseId") == course_id and (user_id is None or doc_data.get("userId") == user_id):
                    results.append({**doc_data, "id": doc_id})
            return results
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = self.db.collection(collection_name).where(
            filter=FieldFilter("courseId", "==", course_id)
        )
        if user_id is not None:
            query = query.where(filter=FieldFilter("userId", "==", user_id))
        docs = query.stream()
        return [{**d.to_dict(), "id": d.id} for d in docs]

    @local_locked
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

    def get_course_documents(self, course_id: str, user_id: str = None) -> list:
        return self._flat_query_by_course("documents", course_id, user_id)

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

    def get_course_audio_recordings(self, course_id: str, user_id: str = None) -> list:
        return self._flat_query_by_course("audio_recordings", course_id, user_id)

    def delete_audio_recording(self, rec_id: str):
        self._flat_delete("audio_recordings", rec_id)

    # --- Historical Exams (Model 3) ---
    def save_historical_exam(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("historical_exams", data)

    def update_historical_exam(self, exam_id: str, data: dict):
        self._flat_update("historical_exams", exam_id, data)

    def get_course_historical_exams(self, course_id: str, user_id: str = None) -> list:
        return self._flat_query_by_course("historical_exams", course_id, user_id)

    def get_historical_exam(self, exam_id: str) -> dict:
        # Needed to check ownership before update/delete.
        return self._flat_get("historical_exams", exam_id)

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

    def get_course_tutorials(self, course_id: str, user_id: str = None) -> list:
        return self._flat_query_by_course("tutorials", course_id, user_id)

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

    def get_course_exams(self, course_id: str, user_id: str = None) -> list:
        return self._flat_query_by_course("exams", course_id, user_id)

    def delete_exam(self, doc_id: str):
        self._flat_delete("exams", doc_id)

    # --- Flashcard Sets ---
    def save_flashcard_set(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("flashcard_sets", data)

    def get_flashcard_set(self, doc_id: str) -> dict:
        return self._flat_get("flashcard_sets", doc_id)

    def get_course_flashcard_sets(self, course_id: str, user_id: str = None) -> list:
        return self._flat_query_by_course("flashcard_sets", course_id, user_id)

    def delete_flashcard_set(self, doc_id: str):
        self._flat_delete("flashcard_sets", doc_id)

    # --- Summaries ---
    def save_summary(self, user_id: str, course_id: str, data: dict) -> str:
        data.update({"userId": user_id, "courseId": course_id})
        return self._flat_save("summaries", data)

    def get_summary(self, doc_id: str) -> dict:
        return self._flat_get("summaries", doc_id)

    def get_course_summaries(self, course_id: str, user_id: str = None) -> list:
        return self._flat_query_by_course("summaries", course_id, user_id)

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

    def get_schedule_entry(self, entry_id: str) -> dict:
        # Needed to check ownership before update/delete.
        return self._flat_get("schedule_entries", entry_id)

    def update_schedule_entry(self, entry_id: str, data: dict):
        self._flat_update("schedule_entries", entry_id, data)

    def delete_schedule_entry(self, entry_id: str):
        self._flat_delete("schedule_entries", entry_id)

    # ──────────────────────────────────────────────────
    # AI Tutor — own resources + persistent chat history
    # ──────────────────────────────────────────────────

    def get_tutor_resources(self, course_id: str, document_ids=None,
                            recording_ids=None, historical_exam_ids=None,
                            tutorial_ids=None, user_id: str = None) -> dict:
        """Resource bundle for the AI Tutor, read DIRECTLY from the course,
        voice-recording, past-exam, tutorial, and document collections —
        independent of the other AI agents. Optional id lists restrict which
        items are included (None = include all of that type)."""
        course = self._flat_get("courses", course_id)
        # The courses collection is client-writable and course_id comes from
        # the request, so don't hand back another student's course metadata.
        if user_id is not None and course.get("userId") != user_id:
            course = {}
        docs = [d for d in self.get_course_documents(course_id, user_id) if d.get("status") == "completed"]
        recs = [a for a in self.get_course_audio_recordings(course_id, user_id) if a.get("status") == "completed"]
        exams = [h for h in self.get_course_historical_exams(course_id, user_id) if h.get("status") == "completed"]
        tuts = [t for t in self.get_course_tutorials(course_id, user_id) if t.get("status") == "completed"]

        # course_id arrives from the client, so scope every source to the
        # caller before any of it reaches the model.
        if user_id is not None:
            docs = [d for d in docs if d.get("userId") == user_id]
            recs = [a for a in recs if a.get("userId") == user_id]
            exams = [h for h in exams if h.get("userId") == user_id]
            tuts = [t for t in tuts if t.get("userId") == user_id]

        docs = self._select_sources(docs, document_ids)
        recs = self._select_sources(recs, recording_ids)
        exams = self._select_sources(exams, historical_exam_ids)
        tuts = self._select_sources(tuts, tutorial_ids)

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

    @local_locked
    def append_tutor_messages(self, user_id: str, course_id: str, chat_id: str,
                              expected_messages: list, new_messages: list, updated_at: int) -> dict:
        """Atomically append one turn only to the exact authorized prior history."""
        validate_component(user_id, 'user ID')
        validate_component(course_id, 'course ID')
        validate_component(chat_id, 'chat ID')
        if (not isinstance(expected_messages, list) or not isinstance(new_messages, list)
                or len(new_messages) != 2 or len(expected_messages) + 2 > 200
                or [message.get('role') if isinstance(message, dict) else None for message in new_messages] != ['user', 'assistant']
                or any(not isinstance(message.get('content'), str) or not message['content'].strip()
                       or len(message['content']) > 20000 for message in new_messages)):
            raise ValueError('Invalid or oversized tutor turn')

        def authorize(course, chat):
            if course.get('userId') != user_id or chat.get('userId') != user_id or chat.get('courseId') != course_id:
                raise DataConflict('Conversation or course is no longer available')
            if chat.get('messages', []) != expected_messages:
                raise DataConflict('This conversation changed; reopen it before sending again')
            messages = list(expected_messages) + [dict(message) for message in new_messages]
            if len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) > 750000:
                raise ValueError('This conversation is too large; start a new chat')
            return {'messages': messages, 'updatedAt': updated_at}

        if self.use_local:
            self._assert_write_allowed(user_id, course_id)
            local = self._read_local_db()
            course = local.get('courses', {}).get(course_id, {})
            chat = local.get('tutor_chats', {}).get(chat_id, {})
            data = authorize(course, chat)
            validate_record_size({**chat, **data})
            chat.update(data)
            self._write_local_db(local)
            return {**chat, 'id': chat_id}

        from google.cloud import firestore
        course_ref = self.db.collection('courses').document(course_id)
        chat_ref = self.db.collection('tutor_chats').document(chat_id)

        @firestore.transactional
        def append(transaction):
            self._assert_write_allowed(user_id, course_id, transaction)
            course = course_ref.get(transaction=transaction)
            chat = chat_ref.get(transaction=transaction)
            current = chat.to_dict() or {} if chat.exists else {}
            data = authorize(course.to_dict() or {} if course.exists else {}, current)
            validate_record_size({**current, **data})
            transaction.update(chat_ref, data)
            return {**current, **data, 'id': chat_id}
        return append(self.db.transaction())

    @staticmethod
    def _schedule_minutes(value):
        if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
            raise ValueError('Schedule times must use HH:MM')
        hour, minute = map(int, value.split(':'))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError('Invalid schedule time')
        return hour * 60 + minute

    @local_locked
    def save_schedule_entry_atomic(self, user_id: str, data: dict, entry_id: str = None) -> str:
        """Serialize overlap checks and writes for one owner's schedule."""
        validate_component(user_id, 'user ID')
        if not isinstance(data, dict): raise ValueError('Invalid schedule entry')
        row = {**data, 'userId': user_id}
        if row.get('day') not in ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday'):
            raise ValueError('Invalid schedule day')
        start, end = self._schedule_minutes(row.get('startTime')), self._schedule_minutes(row.get('endTime'))
        if end <= start: raise ValueError('End time must follow start time')
        course_id = row.get('courseId', '')
        if course_id: validate_component(course_id, 'course ID')
        if entry_id: validate_component(entry_id, 'schedule entry ID')
        target_id = entry_id or f'schedule_entries_{uuid.uuid4().hex}'

        def check(course, current, entries):
            if course_id and course.get('userId') != user_id:
                raise DataConflict('Course is no longer available')
            if entry_id and current.get('userId') != user_id:
                raise DataConflict('Schedule entry is no longer available')
            for entry in entries:
                if entry.get('id') == target_id or entry.get('day') != row['day']:
                    continue
                try:
                    previous_start = self._schedule_minutes(entry.get('startTime'))
                    previous_end = self._schedule_minutes(entry.get('endTime'))
                except ValueError:
                    continue  # malformed legacy entries have no valid interval
                if start < previous_end and end > previous_start:
                    raise DataConflict('This time overlaps an existing schedule entry')

        if self.use_local:
            self._assert_write_allowed(user_id, course_id or None)
            local = self._read_local_db()
            existing = local.get('schedule_entries', {})
            entries = [{**value, 'id': key} for key, value in existing.items() if value.get('userId') == user_id]
            current = existing.get(target_id, {})
            check(local.get('courses', {}).get(course_id, {}), current, entries)
            validate_record_size({**current, **row})
            local.setdefault('schedule_entries', {})[target_id] = {**current, **row}
            self._write_local_db(local)
            return target_id

        from google.cloud import firestore
        from google.cloud.firestore_v1.base_query import FieldFilter
        version_ref = self.db.collection('_schedule_versions').document(user_id)
        target_ref = self.db.collection('schedule_entries').document(target_id)
        query = self.db.collection('schedule_entries').where(filter=FieldFilter('userId', '==', user_id))

        @firestore.transactional
        def save(transaction):
            self._assert_write_allowed(user_id, course_id or None, transaction)
            # Every schedule insert/update reads+writes this owner version, so
            # concurrent query phantom inserts must retry against new rows.
            version = version_ref.get(transaction=transaction)
            current = target_ref.get(transaction=transaction)
            course = self.db.collection('courses').document(course_id).get(transaction=transaction) if course_id else None
            entries = [{**snapshot.to_dict(), 'id': snapshot.id} for snapshot in query.stream(transaction=transaction)]
            existing = current.to_dict() or {} if current.exists else {}
            check(course.to_dict() or {} if course and course.exists else {}, existing, entries)
            validate_record_size({**existing, **row})
            transaction.set(target_ref, {**existing, **row})
            previous_version = (version.to_dict() or {}).get('version', 0) if version.exists else 0
            transaction.set(version_ref, {'userId': user_id, 'version': int(previous_version) + 1})
            return target_id
        return save(self.db.transaction())

    def get_user_course_tutor_chats(self, user_id: str, course_id: str) -> list:
        return [
            c for c in self._flat_query_by_course("tutor_chats", course_id, user_id)
            if c.get("userId") == user_id
        ]

    def delete_tutor_chat(self, chat_id: str):
        self._flat_delete("tutor_chats", chat_id)

    # --- Course Intelligence Aggregator ---
    @staticmethod
    def _select_sources(rows: list, selected_ids) -> list:
        if selected_ids is None:
            return rows
        indexed = {row['id']: row for row in rows}
        return [indexed[identifier] for identifier in dict.fromkeys(selected_ids) if identifier in indexed]

    def get_course_intelligence(self, course_id: str, document_ids: list = None,
                                historical_exam_ids: list = None,
                                tutorial_ids: list = None,
                                audio_ids: list = None,
                                user_id: str = None) -> dict:
        docs = self.get_course_documents(course_id, user_id)
        audio = self.get_course_audio_recordings(course_id, user_id)
        historical = self.get_course_historical_exams(course_id, user_id)
        tutorials = self.get_course_tutorials(course_id, user_id)

        # course_id arrives from the client, so scope every source to the
        # caller before aggregating.
        if user_id is not None:
            docs = [d for d in docs if d.get("userId") == user_id]
            audio = [a for a in audio if a.get("userId") == user_id]
            historical = [h for h in historical if h.get("userId") == user_id]
            tutorials = [t for t in tutorials if t.get("userId") == user_id]

        completed_docs = [d for d in docs if d.get("status") == "completed" and d.get("analysis")]
        completed_docs = self._select_sources(completed_docs, document_ids)
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
        completed_audio = self._select_sources(completed_audio, audio_ids)
        audio_insights = [a.get("insights", {}) for a in completed_audio]

        completed_hist = [h for h in historical if h.get("status") == "completed" and h.get("analysis")]
        completed_hist = self._select_sources(completed_hist, historical_exam_ids)
        hist_analyses = [h.get("analysis", {}) for h in completed_hist]
        hist_texts = [h.get("extractedText", "") for h in completed_hist if h.get("extractedText")]

        # Tutorials: ideas/content only — fed to the generator WITHOUT grading
        # weight or format influence (the prompt enforces that distinction).
        completed_tut = [t for t in tutorials if t.get("status") == "completed" and t.get("analysis")]
        completed_tut = self._select_sources(completed_tut, tutorial_ids)
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
            "source_ids": {
                "document_ids": [d["id"] for d in completed_docs],
                "audio_ids": [a["id"] for a in completed_audio],
                "historical_exam_ids": [h["id"] for h in completed_hist],
                "tutorial_ids": [t["id"] for t in completed_tut],
            },
            "counts": {
                "documents": len(doc_analyses),
                "audio": len(audio_insights),
                "historical_exams": len(hist_analyses),
                "tutorials": len(tut_analyses),
            }
        }

    # --- Firebase Storage helpers ---
    @local_locked
    def upload_file_to_storage(self, file_bytes: bytes, storage_path: str, user_id: str = None) -> str:
        local_path = resolve_storage_path(storage_path, user_id, root=UPLOADS_ROOT)
        owner, course_id = storage_path.split('/')[1:3]
        self._assert_write_allowed(owner, course_id)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        local_url = f"file:///{local_path.resolve()}"

        if not self.use_local:
            try:
                from firebase_admin import storage as fb_storage
                blob = fb_storage.bucket().blob(storage_path)
                blob.upload_from_string(file_bytes)
                # All cloud objects remain private; the API serves their bytes.
            except Exception as e:
                logger.warning('Cloud upload failed (%s); retaining private local copy', type(e).__name__)
        try:
            self._assert_write_allowed(owner, course_id)
        except DataConflict:
            try:
                self.delete_file_from_storage(storage_path, user_id=owner)
            except Exception:
                logger.exception('Late upload compensation failed; cleanup must be retried')
            raise
        return local_url

    def delete_file_from_storage(self, storage_path: str, user_id: str = None):
        local_path = resolve_storage_path(storage_path, user_id, root=UPLOADS_ROOT)
        # Delete remote first; a remote failure retains the local copy and
        # caller metadata so cleanup can be retried rather than hidden.
        if not self.use_local:
            from firebase_admin import storage
            blob = storage.bucket().blob(storage_path)
            if blob.exists():
                blob.delete()
        local_path.unlink(missing_ok=True)

    @local_locked
    def download_file_from_storage(self, storage_path: str, user_id: str) -> Path:
        """Restore a private cloud object after a restart, never expose its URL."""
        local_path = resolve_storage_path(storage_path, user_id, root=UPLOADS_ROOT)
        course_id = storage_path.split('/')[2]
        self._assert_write_allowed(user_id, course_id)
        if local_path.is_file():
            return local_path
        if self.use_local:
            raise FileNotFoundError("Stored file is unavailable")
        from firebase_admin import storage
        blob = storage.bucket().blob(storage_path)
        if not blob.exists():
            raise FileNotFoundError("Stored file is unavailable")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=local_path.parent, prefix=".download-")
        os.close(fd)
        try:
            blob.download_to_filename(temporary)
            self._assert_write_allowed(user_id, course_id)
            # Revalidate after I/O before placing the downloaded object.
            local_path = resolve_storage_path(storage_path, user_id, root=UPLOADS_ROOT)
            os.replace(temporary, local_path)
            return local_path
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    # --- Ownership, restart recovery, and application-data lifecycle ---
    OWNED_COLLECTIONS = ("documents", "audio_recordings", "historical_exams",
                         "tutorials", "exams", "flashcard_sets", "summaries",
                         "tutor_chats", "schedule_entries", "lectures", "_schedule_versions")

    def get_owned_course(self, user_id: str, course_id: str) -> dict:
        validate_component(user_id, "user ID")
        validate_component(course_id, "course ID")
        if self.is_account_deleting(user_id):
            return {}
        course = self._flat_get("courses", course_id)
        return course if course.get("userId") == user_id else {}

    def _flat_query_by_user(self, collection: str, user_id: str) -> list:
        if self.use_local:
            return [{**row, "id": key} for key, row in self._read_local_db().get(collection, {}).items()
                    if row.get("userId") == user_id]
        from google.cloud.firestore_v1.base_query import FieldFilter
        return [{**doc.to_dict(), "id": doc.id} for doc in self.db.collection(collection).where(
            filter=FieldFilter("userId", "==", user_id)).stream()]

    def get_pending_audio_jobs(self, limit: int = 100) -> list:
        pending = ("pending", "queued", "downloading", "converting", "transcribing", "analyzing")
        limit = max(1, min(int(limit), 1000))
        if self.use_local:
            rows = [{**row, "id": key} for key, row in self._read_local_db().get("audio_recordings", {}).items()
                    if row.get("status") in pending]
            return [row for row in rows if self._recoverable_audio_job(row)][:limit]
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = self.db.collection("audio_recordings").where(filter=FieldFilter("status", "in", list(pending)))
        rows = [{**doc.to_dict(), "id": doc.id} for doc in query.limit(limit * 10).stream()]
        return [row for row in rows if self._recoverable_audio_job(row)][:limit]

    def _recoverable_audio_job(self, row: dict) -> bool:
        try:
            return not self.is_course_deleting(row.get('courseId')) and bool(self.get_owned_course(row.get('userId'), row.get('courseId')))
        except (ValueError, TypeError):
            return False

    def audio_job_exists(self, user_id: str, rec_id: str) -> bool:
        row = self.get_audio_recording(rec_id)
        return row.get("userId") == user_id and self._recoverable_audio_job(row)

    def _record_storage_paths(self, row: dict, user_id: str, course_id: str = None) -> list:
        paths = []
        for key in ("storagePath", "solutionPath"):
            if row.get(key):
                paths.append(row[key])
        paths.extend(row.get("supersededSolutionPaths", []) or [])
        for path in paths:
            resolve_storage_path(path, user_id, root=UPLOADS_ROOT)
            expected_course = course_id or row.get("courseId")
            if expected_course and path.split("/")[2] != expected_course:
                raise ValueError("Storage course mismatch")
        return paths

    def _delete_record_files(self, row: dict, user_id: str):
        for path in self._record_storage_paths(row, user_id):
            self.delete_file_from_storage(path, user_id=user_id)

    def _delete_cloud_tree(self, reference) -> int:
        """Admin document delete does not cascade to nested collections."""
        count = 0
        for collection in reference.collections():
            for child in collection.stream():
                count += self._delete_cloud_tree(child.reference)
        reference.delete()
        return count + 1

    @local_locked
    def delete_exam_data(self, user_id: str, doc_id: str) -> dict:
        exam = self.get_exam(doc_id)
        if not exam:
            return {"exams": 0, "rubrics": 0}
        if exam.get("userId") != user_id:
            raise ValueError("Exam not owned")
        course_id = validate_component(exam["courseId"], "course ID")
        validate_component(doc_id, "exam document ID")
        self._delete_record_files(exam, user_id)
        self._cleanup_storage_namespace(user_id, course_id, filename_prefix=doc_id + "_", categories=("solutions",))
        rubric_id = validate_component(exam.get("examId") or doc_id, "exam ID")
        if self.use_local:
            local = self._read_local_db()
            nested = local.get("users", {}).get(user_id, {}).get("courses", {}).get(course_id, {}).get("exams", {})
            rubrics = int(rubric_id in nested)
            nested.pop(rubric_id, None)
            local.get("exams", {}).pop(doc_id, None)
            self._write_local_db(local)
        else:
            ref = self.db.collection("users").document(user_id).collection("courses").document(course_id).collection("exams").document(rubric_id)
            rubrics = self._delete_cloud_tree(ref)
            self._flat_delete("exams", doc_id)
        return {"exams": 1, "rubrics": rubrics}

    def _cleanup_storage_namespace(self, user_id: str, course_id: str = None,
                                   filename_prefix: str = None, categories=None) -> int:
        """Also remove orphaned/superseded files within this owner's prefix."""
        validate_component(user_id, "user ID")
        if course_id is not None:
            validate_component(course_id, "course ID")
        paths = set()
        def selected_filename(name):
            return (not filename_prefix or name.startswith(filename_prefix)
                    or re.match(r'^[0-9a-f]{32}_' + re.escape(filename_prefix), name) is not None)
        for category in categories or STORAGE_CATEGORIES:
            base = UPLOADS_ROOT / category / user_id
            if course_id is not None:
                base = base / course_id
            if base.is_symlink():
                raise ValueError("Unsafe storage directory")
            if base.exists():
                for file in base.rglob("*"):
                    if file.is_symlink():
                        raise ValueError("Unsafe storage entry")
                    if file.is_file():
                        if not selected_filename(file.name):
                            continue
                        path = file.relative_to(UPLOADS_ROOT).as_posix()
                        resolve_storage_path(path, user_id, root=UPLOADS_ROOT)
                        paths.add(path)
            if not self.use_local:
                from firebase_admin import storage
                prefix = f"{category}/{user_id}/" + (f"{course_id}/" if course_id is not None else "")
                for blob in storage.bucket().list_blobs(prefix=prefix):
                    if not selected_filename(blob.name.split("/")[-1]):
                        continue
                    resolve_storage_path(blob.name, user_id, root=UPLOADS_ROOT)
                    paths.add(blob.name)
        for path in sorted(paths):
            self.delete_file_from_storage(path, user_id=user_id)
        return len(paths)

    @local_locked
    def delete_course_data(self, user_id: str, course_id: str) -> dict:
        validate_component(user_id, "user ID")
        validate_component(course_id, "course ID")
        course = self._flat_get("courses", course_id)
        if course and course.get("userId") != user_id:
            raise ValueError("Course not owned")
        self._begin_course_deletion(user_id, course_id)
        records = {name: self._flat_query_by_course(name, course_id, user_id) for name in self.OWNED_COLLECTIONS}
        referenced_files = set()
        # Validate every untrusted metadata path before any destructive work.
        for rows in records.values():
            for row in rows:
                referenced_files.update(self._record_storage_paths(row, user_id, course_id))
        counts = {name: len(rows) for name, rows in records.items()}
        for rows in records.values():
            for row in rows:
                self._delete_record_files(row, user_id)
        counts["files"] = len(referenced_files) + self._cleanup_storage_namespace(user_id, course_id)
        if self.use_local:
            local = self._read_local_db()
            for name, rows in records.items():
                for row in rows:
                    local.get(name, {}).pop(row["id"], None)
            nested = local.get("users", {}).get(user_id, {}).get("courses", {})
            counts["nested_courses"] = int(course_id in nested)
            nested.pop(course_id, None)
            local.get("courses", {}).pop(course_id, None)
            self._write_local_db(local)
        else:
            for name, rows in records.items():
                for row in rows:
                    self._flat_delete(name, row["id"])
            nested = self.db.collection("users").document(user_id).collection("courses").document(course_id)
            counts["nested_courses"] = self._delete_cloud_tree(nested)
            self._flat_delete("courses", course_id)
        counts["courses"] = int(bool(course))
        return counts

    @local_locked
    def delete_user_data(self, user_id: str) -> dict:
        validate_component(user_id, "user ID")
        # Account purge also catches owner rows whose course has already gone.
        records = {name: self._flat_query_by_user(name, user_id) for name in self.OWNED_COLLECTIONS}
        courses = self._flat_query_by_user("courses", user_id)
        referenced_files = set()
        for rows in records.values():
            for row in rows:
                referenced_files.update(self._record_storage_paths(row, user_id))
        for rows in records.values():
            for row in rows:
                self._delete_record_files(row, user_id)
        files = len(referenced_files) + self._cleanup_storage_namespace(user_id)
        counts = {name: len(rows) for name, rows in records.items()}
        counts.update({"courses": len(courses), "files": files})
        if self.use_local:
            local = self._read_local_db()
            for name, rows in records.items():
                for row in rows:
                    local.get(name, {}).pop(row["id"], None)
            for row in courses:
                local.get("courses", {}).pop(row["id"], None)
            counts["users"] = int(user_id in local.get("users", {}))
            local.get("users", {}).pop(user_id, None)
            self._write_local_db(local)
        else:
            for name, rows in records.items():
                for row in rows:
                    self._flat_delete(name, row["id"])
            # Descendant cleanup must succeed before any course/profile parent.
            profile = self.db.collection("users").document(user_id)
            for nested_collection in profile.collections():
                for child in nested_collection.stream():
                    self._delete_cloud_tree(child.reference)
            for row in courses:
                self._flat_delete("courses", row["id"])
            profile.delete()
            counts["users"] = 1
        return counts

    # ──────────────────────────────────────────────────
    # Original methods (untouched)
    # ──────────────────────────────────────────────────

    @local_locked
    def save_secret_rubrics(self, user_id: str, course_id: str, exam_id: str, rubrics_data: dict):
        validate_record_size(rubrics_data)
        if self.use_local:
            self._assert_write_allowed(user_id, course_id)
            data = self._read_local_db()
            data.setdefault("users", {}).setdefault(user_id, {}).setdefault("courses", {}).setdefault(course_id, {}).setdefault("exams", {})
            data["users"][user_id]["courses"][course_id]["exams"][exam_id] = rubrics_data
            self._write_local_db(data)
            logger.info(f"🔒 Secret rubrics for exam '{exam_id}' saved securely in mudaris_local_db.json.")
            return

        from google.cloud import firestore
        reference = self.db.collection('users').document(user_id).collection('courses').document(course_id).collection('exams').document(exam_id)
        @firestore.transactional
        def save(transaction):
            self._assert_write_allowed(user_id, course_id, transaction)
            existing = reference.get(transaction=transaction)
            changes = {'exam_id': exam_id, 'rubrics': rubrics_data, 'created_at': firestore.SERVER_TIMESTAMP}
            validate_record_size({**(existing.to_dict() or {} if existing.exists else {}), **changes})
            transaction.set(reference, changes, merge=True)
        save(self.db.transaction())
