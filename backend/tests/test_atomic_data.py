from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.database.firebase_client import FirebaseClient
from .test_data_storage import FakeFirestore, FakeCollection, FakeReference


class TransactionReference(FakeReference):
    @property
    def id(self): return self.path.split('/')[-1]
    def get(self, transaction=None):
        if transaction: assert not transaction.written, 'Firestore transactions must read before writing'
        return super().get()
    def set(self, data, merge=False):
        self.db.rows[self.path] = {**self.db.rows.get(self.path, {}), **data} if merge else dict(data)
    def update(self, data):
        assert self.path in self.db.rows, 'Updating must never create a missing row'
        self.db.rows[self.path].update(data)


class TransactionCollection(FakeCollection):
    def document(self, key=None):
        if key is None:
            self.db.next_id += 1
            key = f'new{self.db.next_id}'
        return TransactionReference(self.db, self.path + '/' + key)
    def where(self, filter): return TransactionCollection(self.db, self.path, self.filters + (filter,))
    def stream(self, transaction=None):
        if transaction: assert not transaction.written, 'Firestore query must precede transaction writes'
        return super().stream()


class Transaction:
    def __init__(self): self.written = False
    def set(self, reference, data, merge=False):
        self.written = True
        reference.set(data, merge=merge)
    def update(self, reference, data):
        self.written = True
        reference.update(data)


class TransactionFirestore(FakeFirestore):
    next_id = 0
    def collection(self, name): return TransactionCollection(self, name)
    def transaction(self): return Transaction()


@pytest.fixture
def cloud_database(monkeypatch):
    from google.cloud import firestore
    monkeypatch.setattr(firestore, 'transactional', lambda fn: fn)
    monkeypatch.setattr('google.cloud.firestore_v1.base_query.FieldFilter', lambda field, op, value: types.SimpleNamespace(field=field, value=value))
    client = FirebaseClient.__new__(FirebaseClient)
    client.use_local = False
    client.db = TransactionFirestore({'courses/c': {'userId': 'u'}, 'tutor_chats/chat': {'userId': 'u', 'courseId': 'c', 'messages': []}})
    return client


@pytest.fixture
def database():
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
        client = FirebaseClient.__new__(FirebaseClient)
        client.use_local = True
        client.local_db_path = Path(directory) / 'db.json'
        client._write_local_db({'courses': {'c': {'userId': 'u'}, 'v': {'userId': 'v'}},
                                'tutor_chats': {'chat': {'userId': 'u', 'courseId': 'c', 'messages': []}}})
        yield client


def test_two_replies_with_same_history_cannot_overwrite_each_other(database):
    assert hasattr(database, 'append_tutor_messages')
    def append(number):
        try:
            database.append_tutor_messages('u', 'c', 'chat', [], [
                {'role': 'user', 'content': f'question {number}'}, {'role': 'assistant', 'content': f'answer {number}'}], 123)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, range(2)))
    assert sum(results) == 1
    assert len(database.get_tutor_chat('chat')['messages']) == 2


def test_atomic_reply_never_recreates_a_deleted_chat_or_parent(database):
    assert hasattr(database, 'append_tutor_messages')
    database.delete_tutor_chat('chat')
    with pytest.raises(ValueError):
        database.append_tutor_messages('u', 'c', 'chat', [], [{'role': 'user', 'content': 'Q'}, {'role': 'assistant', 'content': 'A'}], 1)
    assert database.get_tutor_chat('chat') == {}


def test_atomic_schedule_rejects_concurrent_overlap_but_allows_touching_boundary(database):
    assert hasattr(database, 'save_schedule_entry_atomic')
    def save(number):
        try:
            return database.save_schedule_entry_atomic('u', {'courseId': 'c', 'day': 'monday', 'startTime': '09:00', 'endTime': '10:00', 'title': str(number)})
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert sum(result is not None for result in results) == 1
    database.save_schedule_entry_atomic('u', {'courseId': 'c', 'day': 'monday', 'startTime': '10:00', 'endTime': '11:00'})
    assert len(database.get_user_schedule_entries('u')) == 2


def test_schedule_updates_cannot_transfer_owner_or_target_foreign_course(database):
    assert hasattr(database, 'save_schedule_entry_atomic')
    first = database.save_schedule_entry_atomic('u', {'courseId': 'c', 'day': 'monday', 'startTime': '09:00', 'endTime': '10:00'})
    with pytest.raises(ValueError):
        database.save_schedule_entry_atomic('v', {'courseId': 'v', 'day': 'monday', 'startTime': '09:00', 'endTime': '10:00'}, entry_id=first)
    with pytest.raises(ValueError):
        database.save_schedule_entry_atomic('u', {'courseId': 'v', 'day': 'monday', 'startTime': '11:00', 'endTime': '12:00'})
    assert database.get_schedule_entry(first)['userId'] == 'u'


@pytest.mark.parametrize('start,end', [('24:00', '25:00'), ('09:60', '10:00'), ('10:00', '09:00'), ('9:00', '10:00')])
def test_atomic_schedule_validates_time_range_before_writing(database, start, end):
    assert hasattr(database, 'save_schedule_entry_atomic')
    with pytest.raises(ValueError):
        database.save_schedule_entry_atomic('u', {'day': 'monday', 'startTime': start, 'endTime': end})
    assert database.get_user_schedule_entries('u') == []


def test_account_deletion_marker_survives_purge_and_blocks_late_writes(database):
    assert hasattr(database, 'begin_account_deletion')
    database.begin_account_deletion('u')
    database.delete_user_data('u')
    assert database.is_account_deleting('u')
    with pytest.raises(ValueError): database.save_document('u', 'c', {'title': 'late'})
    with pytest.raises(ValueError): database.save_schedule_entry_atomic('u', {'day': 'monday', 'startTime': '09:00', 'endTime': '10:00'})
    assert database._read_local_db().get('documents', {}) == {}


def test_account_deletion_marker_blocks_existing_row_updates_for_failed_cleanup(database):
    assert hasattr(database, 'begin_account_deletion')
    database.save_document('u', 'c', {'title': 'before'})
    doc = database.get_course_documents('c')[0]
    database.begin_account_deletion('u')
    with pytest.raises(ValueError): database.update_document(doc['id'], {'title': 'late overwrite'})
    assert database.get_document(doc['id'])['title'] == 'before'


def test_parentless_and_deleting_audio_jobs_are_not_recovered_forever(database):
    rows = database._read_local_db()
    rows['audio_recordings'] = {'orphan': {'userId': 'u', 'courseId': 'missing', 'status': 'queued'},
                                 'owned': {'userId': 'u', 'courseId': 'c', 'status': 'queued'}}
    database._write_local_db(rows)
    assert [row['id'] for row in database.get_pending_audio_jobs()] == ['owned']
    database.begin_account_deletion('u')
    assert database.get_pending_audio_jobs() == []


def test_upload_completion_after_deletion_marker_compensates_files(database, monkeypatch):
    root = database.local_db_path.parent / 'uploads'
    monkeypatch.setattr('src.database.firebase_client.UPLOADS_ROOT', root)
    previous_assert = database._assert_write_allowed
    checks = []
    def authorize(owner, course=None, transaction=None):
        checks.append(owner)
        if len(checks) == 2:
            database.begin_account_deletion(owner)
        previous_assert(owner, course, transaction)
    monkeypatch.setattr(database, '_assert_write_allowed', authorize)
    with pytest.raises(ValueError): database.upload_file_to_storage(b'late bytes', 'documents/u/c/a.pdf', 'u')
    assert not (root / 'documents/u/c/a.pdf').exists()


def test_cloud_tutor_transaction_detects_stale_history_and_deletion_marker(cloud_database):
    delta = [{'role': 'user', 'content': 'Q'}, {'role': 'assistant', 'content': 'A'}]
    cloud_database.append_tutor_messages('u', 'c', 'chat', [], delta, 1)
    with pytest.raises(ValueError): cloud_database.append_tutor_messages('u', 'c', 'chat', [], delta, 2)
    cloud_database.begin_account_deletion('u')
    with pytest.raises(ValueError): cloud_database.append_tutor_messages('u', 'c', 'chat', delta, delta, 3)
    assert cloud_database.get_tutor_chat('chat')['messages'] == delta


def test_cloud_schedule_version_is_written_with_each_atomic_overlap_checked_save(cloud_database):
    data = {'courseId': 'c', 'day': 'monday', 'startTime': '09:00', 'endTime': '10:00'}
    cloud_database.save_schedule_entry_atomic('u', data)
    assert cloud_database.db.rows['_schedule_versions/u']['version'] == 1
    with pytest.raises(ValueError): cloud_database.save_schedule_entry_atomic('u', data)
    cloud_database.save_schedule_entry_atomic('u', {**data, 'startTime': '10:00', 'endTime': '11:00'})
    assert cloud_database.db.rows['_schedule_versions/u']['version'] == 2


def test_cloud_flat_writes_guard_marker_and_parent_inside_transaction(cloud_database):
    doc = cloud_database.save_document('u', 'c', {'title': 'before'})
    cloud_database.begin_account_deletion('u')
    with pytest.raises(ValueError): cloud_database.update_document(doc, {'title': 'after'})
    with pytest.raises(ValueError): cloud_database.save_document('u', 'c', {'title': 'new'})
    assert cloud_database.get_document(doc)['title'] == 'before'


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
def test_oversized_extracted_text_save_rejected_before_new_record_is_written(request, backend):
    database = request.getfixturevalue(backend)
    with pytest.raises(ValueError): database.save_document('u', 'c', {'extractedText': 'x' * 750001})
    assert database.get_course_documents('c') == []


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
def test_merged_record_size_is_checked_before_update_leaving_original_intact(request, backend):
    database = request.getfixturevalue(backend)
    identifier = database.save_document('u', 'c', {'extractedText': 'x' * 400000})
    with pytest.raises(ValueError): database.update_document(identifier, {'analysis': {'content': 'y' * 400000}})
    document = database.get_document(identifier)
    assert document['extractedText'] == 'x' * 400000
    assert 'analysis' not in document


def test_oversized_nested_rubric_preserves_existing_local_secret(database):
    database.save_secret_rubrics('u', 'c', 'exam', {'questions': {'q1': {'criteria': 'original'}}})
    with pytest.raises(ValueError): database.save_secret_rubrics('u', 'c', 'exam', {'questions': {'q1': {'criteria': 'x' * 750001}}})
    secret = database._read_local_db()['users']['u']['courses']['c']['exams']['exam']
    assert secret['questions']['q1']['criteria'] == 'original'


def test_course_purge_fences_late_save_and_upload_before_dependent_cleanup(database, monkeypatch):
    document = database.save_document('u', 'c', {'title': 'before'})
    root = database.local_db_path.parent / 'uploads'
    monkeypatch.setattr('src.database.firebase_client.UPLOADS_ROOT', root)
    previous_cleanup = database._cleanup_storage_namespace
    checks = []
    def cleanup(*args, **kwargs):
        with pytest.raises(ValueError): database.save_document('u', 'c', {'title': 'late'})
        with pytest.raises(ValueError): database.upload_file_to_storage(b'late', 'documents/u/c/late.pdf', 'u')
        checks.append(True)
        return previous_cleanup(*args, **kwargs)
    monkeypatch.setattr(database, '_cleanup_storage_namespace', cleanup)
    database.delete_course_data('u', 'c')
    assert checks == [True]
    assert database.get_document(document) == {}
    assert database.get_course_documents('c') == []
    assert not (root / 'documents/u/c/late.pdf').exists()
    database.delete_course_data('u', 'c')  # original owner can retry idempotently


def test_explicit_source_ids_preserve_requested_historical_reference_order(database):
    records = database._read_local_db()
    records['historical_exams'] = {'a': {'userId': 'u', 'courseId': 'c', 'status': 'completed', 'analysis': {'gradingBlueprint': 'A'}},
                                   'b': {'userId': 'u', 'courseId': 'c', 'status': 'completed', 'analysis': {'gradingBlueprint': 'B'}}}
    database._write_local_db(records)
    intelligence = database.get_course_intelligence('c', historical_exam_ids=['b', 'a'], user_id='u')
    assert [item['gradingBlueprint'] for item in intelligence['historical_analyses']] == ['B', 'A']
    assert intelligence['source_ids']['historical_exam_ids'] == ['b', 'a']
    resources = database.get_tutor_resources('c', historical_exam_ids=['b', 'a'], user_id='u')
    assert [item['id'] for item in resources['past_exams']] == ['b', 'a']


@pytest.mark.parametrize('collection,selection,provenance,result_key,stored_key', [
    ('documents', 'document_ids', 'document_ids', 'document_analyses', 'analysis'),
    ('audio_recordings', 'audio_ids', 'audio_ids', 'audio_insights', 'insights'),
    ('tutorials', 'tutorial_ids', 'tutorial_ids', 'tutorial_analyses', 'analysis'),
])
def test_source_order_applies_to_every_generator_source_type(database, collection, selection, provenance, result_key, stored_key):
    records = database._read_local_db()
    records[collection] = {key: {'userId': 'u', 'courseId': 'c', 'status': 'completed', stored_key: {'sourceLabel': key}}
                           for key in ('a', 'b')}
    database._write_local_db(records)
    result = database.get_course_intelligence('c', **{selection: ['b', 'a']}, user_id='u')
    assert [item['sourceLabel'] for item in result[result_key]] == ['b', 'a']
    assert result['source_ids'][provenance] == ['b', 'a']


def test_cloud_course_marker_fences_flat_chat_schedule_and_rubric_writes(cloud_database):
    cloud_database._begin_course_deletion('u', 'c')
    assert cloud_database.get_course_deletion_marker('c')['userId'] == 'u'
    with pytest.raises(ValueError): cloud_database.save_document('u', 'c', {'title': 'late'})
    delta = [{'role': 'user', 'content': 'Q'}, {'role': 'assistant', 'content': 'A'}]
    with pytest.raises(ValueError): cloud_database.append_tutor_messages('u', 'c', 'chat', [], delta, 1)
    with pytest.raises(ValueError): cloud_database.save_schedule_entry_atomic('u', {'courseId': 'c', 'day': 'monday', 'startTime': '09:00', 'endTime': '10:00'})
    with pytest.raises(ValueError): cloud_database.save_secret_rubrics('u', 'c', 'e', {'questions': {'q1': {}}})
