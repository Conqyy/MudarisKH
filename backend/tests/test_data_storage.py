import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.database.firebase_client import FirebaseClient
from src.utils.storage_paths import build_storage_path, resolve_storage_path


class FakeSnapshot:
    def __init__(self, reference):
        self.reference = reference
        self.id = reference.path.split('/')[-1]
        self.exists = reference.path in reference.db.rows
    def to_dict(self): return self.reference.db.rows.get(self.reference.path, {}).copy()


class FakeReference:
    def __init__(self, db, path): self.db, self.path = db, path
    def get(self, **kwargs): return FakeSnapshot(self)
    def collection(self, name): return FakeCollection(self.db, self.path + '/' + name)
    def collections(self):
        prefix = self.path + '/'
        names = {p[len(prefix):].split('/')[0] for p in self.db.rows if p.startswith(prefix) and '/' in p[len(prefix):]}
        return [self.collection(name) for name in names]
    def delete(self):
        if self.path == self.db.fail_delete:
            raise RuntimeError('dependent cleanup failed')
        self.db.rows.pop(self.path, None)
    def set(self, data, merge=False):
        self.db.rows[self.path] = {**self.db.rows.get(self.path, {}), **data} if merge else dict(data)


class FakeCollection:
    def __init__(self, db, path, filters=()): self.db, self.path, self.filters = db, path, filters
    def document(self, key): return FakeReference(self.db, self.path + '/' + key)
    def where(self, filter): return FakeCollection(self.db, self.path, self.filters + (filter,))
    def stream(self):
        prefix = self.path + '/'
        for path, row in list(self.db.rows.items()):
            if path.startswith(prefix) and '/' not in path[len(prefix):] and all(row.get(f.field) == f.value for f in self.filters):
                yield FakeSnapshot(FakeReference(self.db, path))


class FakeFirestore:
    def __init__(self, rows, fail_delete=None): self.rows, self.fail_delete = rows, fail_delete
    def collection(self, name): return FakeCollection(self, name)
    def transaction(self): return types.SimpleNamespace(set=lambda reference, data, merge=False: reference.set(data, merge))


class DataStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.client = FirebaseClient.__new__(FirebaseClient)
        self.client.use_local = True
        self.client.local_db_path = Path(self.temp.name) / 'db.json'
        self.client._write_local_db({})

    def seed(self, data):
        self.client._write_local_db(data)

    def test_explicit_empty_selections_exclude_all_sources(self):
        self.seed({'documents': {'a': {'courseId': 'c', 'userId': 'u', 'status': 'completed', 'analysis': {'topics': ['secret']}}}})
        result = self.client.get_course_intelligence('c', document_ids=[], user_id='u')
        self.assertEqual(result['counts']['documents'], 0)

    def test_source_provenance_matches_only_owned_completed_sources(self):
        self.seed({'documents': {
            'a': {'courseId': 'c', 'userId': 'u', 'status': 'completed', 'analysis': {'topics': ['one']}},
            'b': {'courseId': 'c', 'userId': 'other', 'status': 'completed', 'analysis': {'topics': ['two']}},
        }})
        result = self.client.get_course_intelligence('c', user_id='u')
        self.assertEqual(result.get('source_ids'), {'document_ids': ['a'], 'audio_ids': [], 'historical_exam_ids': [], 'tutorial_ids': []})

    def test_simultaneous_saves_keep_all_rows_and_unique_ids(self):
        self.seed({'courses': {'c': {'userId': 'u'}}})
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            ids = list(executor.map(lambda n: self.client.save_document('u', 'c', {'n': n}), range(80)))
        self.assertEqual(len(set(ids)), 80)
        self.assertEqual(len(self.client._read_local_db()['documents']), 80)

    def test_storage_rejects_traversal_before_writing(self):
        with self.assertRaises(ValueError):
            self.client.upload_file_to_storage(b'bad', 'documents/u/../../escape.txt')

    def test_storage_rejects_normalized_owner_escape_and_windows_special_names(self):
        for path in ['documents/u/../v/a.pdf', 'documents/v/c/a.pdf', 'documents/u/c/CON.pdf',
                     'documents/u/c/a.pdf.', 'documents/u/c/a\\b.pdf', '/documents/u/c/a.pdf']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                resolve_storage_path(path, 'u', root=Path(self.temp.name))
        self.assertEqual(build_storage_path('u', 'c', 'documents', 'محاضرة.pdf'), 'documents/u/c/محاضرة.pdf')

    def test_owned_course_and_pending_audio_recovery_ignore_foreign_and_finished_rows(self):
        self.seed({'courses': {'c': {'userId': 'u'}, 'v': {'userId': 'v'}}, 'audio_recordings': {
            'queued': {'userId': 'u', 'courseId': 'c', 'status': 'queued', 'sourceUrl': 'https://youtube.com/watch?v=x'},
            'completed': {'userId': 'u', 'courseId': 'c', 'status': 'completed'},
        }})
        self.assertEqual(self.client.get_owned_course('u', 'v'), {})
        self.assertEqual([r['id'] for r in self.client.get_pending_audio_jobs()], ['queued'])
        self.assertTrue(self.client.audio_job_exists('u', 'queued'))
        self.assertFalse(self.client.audio_job_exists('v', 'queued'))

    def test_exam_delete_removes_solution_and_nested_secret_but_retains_other_exam(self):
        self.seed({'courses': {'c': {'userId': 'u'}}, 'exams': {'e': {'userId': 'u', 'courseId': 'c', 'examId': 'secret', 'solutionPath': 'solutions/u/c/e.pdf'},
                             'other': {'userId': 'v', 'courseId': 'c'}},
                   'users': {'u': {'courses': {'c': {'exams': {'secret': {'rubrics': {}}}}}}}})
        with patch('src.database.firebase_client.UPLOADS_ROOT', Path(self.temp.name) / 'uploads'):
            self.client.upload_file_to_storage(b'answer', 'solutions/u/c/e.pdf', 'u')
            self.client.upload_file_to_storage(b'old answer', 'solutions/u/c/e_123_old.pdf', 'u')
            self.client.upload_file_to_storage(b'new stale', 'solutions/u/c/0123456789abcdef0123456789abcdef_e_new.pdf', 'u')
            self.client.upload_file_to_storage(b'keep', 'solutions/u/c/other_123.pdf', 'u')
            self.client.delete_exam_data('u', 'e')
            self.assertFalse((Path(self.temp.name) / 'uploads/solutions/u/c/e.pdf').exists())
            self.assertFalse((Path(self.temp.name) / 'uploads/solutions/u/c/e_123_old.pdf').exists())
            self.assertFalse((Path(self.temp.name) / 'uploads/solutions/u/c/0123456789abcdef0123456789abcdef_e_new.pdf').exists())
            self.assertTrue((Path(self.temp.name) / 'uploads/solutions/u/c/other_123.pdf').exists())
        data = self.client._read_local_db()
        self.assertEqual(set(data['exams']), {'other'})
        self.assertEqual(data['users']['u']['courses']['c']['exams'], {})

    def test_forged_metadata_prevents_cascade_without_touching_foreign_file(self):
        self.seed({'courses': {'c': {'userId': 'u'}}, 'documents': {
            'forged': {'userId': 'u', 'courseId': 'c', 'storagePath': 'documents/v/c/private.pdf'}}})
        root = Path(self.temp.name) / 'uploads'
        with patch('src.database.firebase_client.UPLOADS_ROOT', root):
            private = root / 'documents/v/c/private.pdf'
            private.parent.mkdir(parents=True)
            private.write_bytes(b'private')
            with self.assertRaises(ValueError):
                self.client.delete_course_data('u', 'c')
        self.assertEqual((root / 'documents/v/c/private.pdf').read_bytes(), b'private')
        self.assertIn('c', self.client._read_local_db()['courses'])

    def test_account_cascade_removes_owned_orphans_and_superseded_solutions(self):
        self.seed({'courses': {'c': {'userId': 'u'}, 'v': {'userId': 'v'}},
                   'users': {'u': {'courses': {'legacy': {'exams': {'x': {'rubrics': {}}}}}}, 'v': {'name': 'V'}},
                   'summaries': {'orphan': {'userId': 'u', 'courseId': 'gone'}, 'foreign': {'userId': 'v', 'courseId': 'v'}}})
        root = Path(self.temp.name) / 'uploads'
        with patch('src.database.firebase_client.UPLOADS_ROOT', root):
            orphan = root / 'solutions/u/gone/old.pdf'
            orphan.parent.mkdir(parents=True)
            orphan.write_bytes(b'old')
            self.client.upload_file_to_storage(b'keep', 'documents/v/v/private.pdf', 'v')
            self.client.delete_user_data('u')
        data = self.client._read_local_db()
        self.assertEqual(set(data['users']), {'v'})
        self.assertEqual(set(data['courses']), {'v'})
        self.assertEqual(set(data['summaries']), {'foreign'})
        self.assertFalse((root / 'solutions/u/gone/old.pdf').exists())
        self.assertEqual((root / 'documents/v/v/private.pdf').read_bytes(), b'keep')

    def test_course_cascade_keeps_foreign_rows_and_removes_nested_rubrics(self):
        self.seed({'courses': {'c': {'userId': 'u'}, 'other': {'userId': 'v'}},
                   'documents': {'a': {'userId': 'u', 'courseId': 'c'}, 'foreign': {'userId': 'v', 'courseId': 'c'}},
                   'schedule_entries': {'s': {'userId': 'u', 'courseId': 'c'}},
                   'lectures': {'l': {'userId': 'u', 'courseId': 'c'}},
                   'users': {'u': {'name': 'U', 'courses': {'c': {'exams': {'secret': {'rubrics': 'secret'}}, 'lectures': {'x': {}}}}}}})
        self.assertTrue(hasattr(self.client, 'delete_course_data'), 'Cascade implementation missing')
        counts = self.client.delete_course_data('u', 'c')
        data = self.client._read_local_db()
        self.assertEqual(set(data['documents']), {'foreign'})
        self.assertNotIn('c', data['courses'])
        self.assertNotIn('c', data['users']['u']['courses'])
        self.assertEqual(data['schedule_entries'], {})
        self.assertEqual(data['lectures'], {})
        self.assertEqual(counts['documents'], 1)
        self.client.delete_course_data('u', 'c')

    def test_failed_file_cleanup_keeps_parent_and_metadata_for_retry(self):
        self.seed({'courses': {'c': {'userId': 'u'}}, 'users': {'u': {'name': 'U'}},
                   'documents': {'a': {'userId': 'u', 'courseId': 'c', 'storagePath': 'documents/u/c/a.pdf'}}})
        self.assertTrue(hasattr(self.client, 'delete_user_data'), 'Account purge implementation missing')
        with patch.object(self.client, 'delete_file_from_storage', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                self.client.delete_user_data('u')
        data = self.client._read_local_db()
        self.assertIn('u', data['users'])
        self.assertIn('c', data['courses'])
        self.assertIn('a', data['documents'])

    def test_private_upload_and_deletion_remove_both_copies(self):
        class Blob:
            public = False
            present = False
            def upload_from_string(self, data): self.present = True
            def make_public(self): self.public = True
            def exists(self): return self.present
            def delete(self): self.present = False
            public_url = 'https://public.test/object'
        blob = Blob()
        fake = types.ModuleType('firebase_admin')
        fake.storage = types.SimpleNamespace(bucket=lambda: types.SimpleNamespace(blob=lambda path: blob))
        self.client.use_local = False
        self.client.db = FakeFirestore({'courses/c': {'userId': 'u'}})
        with patch.dict(sys.modules, {'firebase_admin': fake}):
            with patch('src.database.firebase_client.UPLOADS_ROOT', Path(self.temp.name) / 'uploads', create=True):
                url = self.client.upload_file_to_storage(b'content', 'documents/u/c/a.pdf')
                self.assertFalse(blob.public, 'Upload granted public access')
                self.assertNotEqual(url, blob.public_url)
                self.client.delete_file_from_storage('documents/u/c/a.pdf', user_id='u')
                self.assertFalse(blob.present)
                self.assertFalse((Path(self.temp.name) / 'uploads/documents/u/c/a.pdf').exists())

    def cloud_client(self, rows, fail_delete=None):
        self.client.use_local = False
        self.client.db = FakeFirestore(rows, fail_delete)
        from google.cloud import firestore
        transactional = patch.object(firestore, 'transactional', lambda function: function)
        transactional.start()
        self.addCleanup(transactional.stop)
        field_filter = types.ModuleType('google.cloud.firestore_v1.base_query')
        field_filter.FieldFilter = lambda field, op, value: types.SimpleNamespace(field=field, value=value)
        modules = patch.dict(sys.modules, {'google.cloud.firestore_v1.base_query': field_filter})
        modules.start()
        self.addCleanup(modules.stop)
        storage = types.ModuleType('firebase_admin')
        storage.storage = types.SimpleNamespace(bucket=lambda: types.SimpleNamespace(list_blobs=lambda prefix: []))
        modules = patch.dict(sys.modules, {'firebase_admin': storage})
        modules.start()
        self.addCleanup(modules.stop)

    def test_cloud_course_cascade_deletes_subcollections_and_only_owner_rows(self):
        rows = {'courses/c': {'userId': 'u'}, 'users/u': {'uid': 'u'},
                'documents/d': {'userId': 'u', 'courseId': 'c'},
                'documents/foreign': {'userId': 'v', 'courseId': 'c'},
                'users/u/courses/c': {}, 'users/u/courses/c/lectures/old': {},
                'users/u/courses/c/exams/e': {'rubrics': {}},
                'users/u/courses/c/exams/e/details/secret': {'answer': 'x'}}
        self.cloud_client(rows)
        self.client.delete_course_data('u', 'c')
        self.assertEqual(set(rows), {'users/u', 'documents/foreign', '_course_deletions/c'})

    def test_cloud_failed_nested_cleanup_keeps_course_and_profile_parents(self):
        rows = {'courses/c': {'userId': 'u'}, 'users/u': {'uid': 'u'},
                'users/u/courses/c': {}, 'users/u/courses/c/exams/e': {'rubrics': {}}}
        self.cloud_client(rows, 'users/u/courses/c/exams/e')
        with self.assertRaises(RuntimeError):
            self.client.delete_user_data('u')
        self.assertIn('courses/c', rows)
        self.assertIn('users/u', rows)
        self.client.db.fail_delete = None
        self.client.delete_user_data('u')
        self.assertEqual(rows, {})

    def test_private_cloud_download_restores_local_copy_and_rejects_foreign_owner(self):
        self.assertTrue(hasattr(self.client, 'download_file_from_storage'), 'Private retrieval missing')
        class Blob:
            def exists(self): return True
            def download_to_filename(self, filename): Path(filename).write_bytes(b'cloud private content')
        fake = types.ModuleType('firebase_admin')
        fake.storage = types.SimpleNamespace(bucket=lambda: types.SimpleNamespace(blob=lambda path: Blob()))
        root = Path(self.temp.name) / 'uploads'
        self.client.use_local = False
        self.client.db = FakeFirestore({'courses/c': {'userId': 'u'}})
        with patch.dict(sys.modules, {'firebase_admin': fake}), patch('src.database.firebase_client.UPLOADS_ROOT', root):
            with self.assertRaises(ValueError):
                self.client.download_file_from_storage('documents/v/c/a.pdf', 'u')
            path = self.client.download_file_from_storage('documents/u/c/a.pdf', 'u')
            self.assertEqual(path.read_bytes(), b'cloud private content')
            self.assertFalse((root / 'documents/v/c/a.pdf').exists())

    def test_course_cleanup_counts_referenced_files(self):
        self.seed({'courses': {'c': {'userId': 'u'}}, 'documents': {'d': {
            'userId': 'u', 'courseId': 'c', 'storagePath': 'documents/u/c/a.pdf'}}})
        with patch('src.database.firebase_client.UPLOADS_ROOT', Path(self.temp.name) / 'uploads'):
            self.client.upload_file_to_storage(b'content', 'documents/u/c/a.pdf')
            counts = self.client.delete_course_data('u', 'c')
        self.assertEqual(counts['files'], 1)


if __name__ == '__main__':
    unittest.main()
