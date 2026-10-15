"""Owned, transactionally fenced supporting jobs and immutable descriptors.

Artifact I/O belongs to the library. Every transaction reads its deletion,
foundation, material and version fences before performing any writes.
"""
from copy import deepcopy
import hashlib
import time
import uuid

from src.database.firebase_client import DataConflict, validate_record_size
from src.supporting.contracts import (
    validate_identity, digest, canonical_bytes, CLAIM_LEASE_MS, DEFAULT_MODEL_CALL_BUDGET,
)
from src.utils.storage_paths import validate_component, validate_supporting_storage_path, supporting_artifact_prefix, SUPPORTING_CATEGORIES

COLLECTIONS = {'historical_exam': 'historical_exams', 'tutorial': 'tutorials', 'audio': 'audio_recordings', 'notes': 'audio_recordings'}
VERSIONS = 'supporting_material_versions'
ACTIVE_STAGES = frozenset(('queued', 'capturing', 'preparing', 'extracting', 'aligning'))


def version_id(identity, kind, revision):
    return digest({'identity': validate_identity(identity), 'versionKind': kind, 'revision': revision})


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid supporting revision')
    return value


def _clock(value):
    if type(value) is not int or value < 0: raise ValueError('Invalid job clock')


class SupportingRepository:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _row(identity, row, *, allow_missing=False, allow_deleting=False):
        if not row and allow_missing: return
        if (not row or row.get('userId') != identity['userId'] or row.get('courseId') != identity['courseId']
                or (not allow_deleting and row.get('status') == 'deleting')):
            raise DataConflict('Supporting material is no longer available')
        if identity['kind'] in ('audio', 'notes') and ((row.get('sourceType') == 'notes') != (identity['kind'] == 'notes')):
            raise DataConflict('Supporting source type changed')

    @staticmethod
    def _descriptor(identity, row):
        if not row or any(row.get(key) != val for key, val in identity.items()):
            raise DataConflict('Supporting version is missing or belongs to another material')
        return row

    def _atomic(self, identity, change, *, foundation_revision=None, create=False,
                allow_deleting=False, require_parent=True, version_ids=()):
        identity = validate_identity(identity)
        db = self.database
        collection, material = COLLECTIONS[identity['kind']], identity['materialId']
        tombstone = version_id(identity, 'tombstone', 'deleted')
        keys = list(dict.fromkeys([tombstone, *version_ids]))

        def apply(row, versions):
            if versions[tombstone] and not allow_deleting:
                self._descriptor(identity, versions[tombstone])
                raise DataConflict('Supporting material was deleted')
            self._row(identity, row, allow_missing=create or allow_deleting, allow_deleting=allow_deleting)
            updated, writes, result = change(deepcopy(row), deepcopy(versions))
            if updated is not None: validate_record_size(updated)
            for key, value in writes.items():
                if key not in keys: raise ValueError('Version writes must be read before transaction writes')
                self._descriptor(identity, value)
                validate_record_size(value)
            return updated, writes, result

        if db.use_local:
            with db._local_transaction():
                if require_parent: db._assert_write_allowed(identity['userId'], identity['courseId'])
                local = db._read_local_db()
                db._assert_foundation_current(identity['userId'], identity['courseId'], foundation_revision, local=local)
                row = local.get(collection, {}).get(material, {})
                versions = {key: local.get(VERSIONS, {}).get(key, {}) for key in keys}
                updated, writes, result = apply(row, versions)
                if updated is not None: local.setdefault(collection, {})[material] = updated
                if writes: local.setdefault(VERSIONS, {}).update(writes)
                if updated is not None or writes: db._write_local_db(local)
                return result
        from google.cloud import firestore
        reference = db.db.collection(collection).document(material)
        references = {key: db.db.collection(VERSIONS).document(key) for key in keys}
        @firestore.transactional
        def transaction(tx):
            if require_parent: db._assert_write_allowed(identity['userId'], identity['courseId'], tx)
            db._assert_foundation_current(identity['userId'], identity['courseId'], foundation_revision, transaction=tx)
            snap = reference.get(transaction=tx)
            row = snap.to_dict() or {} if snap.exists else {}
            versions = {}
            for key, ref in references.items():
                snapshot = ref.get(transaction=tx)
                versions[key] = snapshot.to_dict() or {} if snapshot.exists else {}
            updated, writes, result = apply(row, versions)
            if updated is not None: tx.set(reference, updated)
            for key, value in writes.items(): tx.set(references[key], value)
            return result
        return transaction(db.db.transaction())

    def get_owned(self, identity):
        return self._atomic(identity, lambda row, versions: (None, {}, row))

    def get_version(self, identity, kind, revision):
        key = version_id(identity, kind, revision)
        def read(row, versions):
            version = self._descriptor(identity, versions[key])
            if version.get('versionKind') != kind or version.get('revision') != revision or version.get('state') != 'adopted':
                raise DataConflict('Exact supporting version is unavailable')
            return None, {}, deepcopy(version)
        return self._atomic(identity, read, version_ids=[key])

    def queue(self, identity, *, input_revision, source_digest, foundation_revision, now_ms, initial_data=None):
        identity = validate_identity(identity)
        _hash(input_revision)
        _hash(foundation_revision)
        _clock(now_ms)
        if source_digest is not None: _hash(source_digest)
        elif identity['kind'] != 'audio': raise ValueError('Only an uncaptured recording can omit its digest')
        if initial_data is not None and not isinstance(initial_data, dict): raise ValueError('Invalid initial material')
        job = {'id': uuid.uuid4().hex, 'claimToken': None, 'inputRevision': input_revision,
               'sourceDigest': source_digest, 'foundationRevision': foundation_revision,
               'stage': 'queued', 'leaseUntil': 0, 'cursor': None, 'modelCalls': 0,
               'modelCallBudget': DEFAULT_MODEL_CALL_BUDGET, 'createdAt': now_ms, 'error': None}
        def queue(row, versions):
            if initial_data is not None:
                if row: raise DataConflict('An existing material cannot be overwritten')
                row = deepcopy(initial_data)
                if any(key in row for key in ('processingJob', 'supportingAnalysis', 'sourceRevision')):
                    raise ValueError('Initial material cannot supply processed state')
                row.update(userId=identity['userId'], courseId=identity['courseId'])
                if identity['kind'] == 'notes': row['sourceType'] = 'notes'
            if row.get('originalDigest') not in (None, source_digest): raise DataConflict('Original source changed')
            self._row(identity, row)
            queued = deepcopy(job)
            previous = row.get('processingJob') or {}
            if all(previous.get(k) == queued[k] for k in ('inputRevision', 'sourceDigest', 'foundationRevision')):
                for key in ('checkpointRevision', 'cursor'):
                    if key in previous: queued[key] = deepcopy(previous[key])
            row.update(status='queued', originalDigest=source_digest, processingJob=queued, error=None)
            row['supportingAnalysis'] = {**row.get('supportingAnalysis', {}), 'version': 1, 'state': 'queued'}
            return row, {}, deepcopy(job)
        return self._atomic(identity, queue, foundation_revision=foundation_revision, create=initial_data is not None)

    @staticmethod
    def _live(row, handle, now_ms):
        job = row.get('processingJob') or {}
        return (job.get('stage') in ACTIVE_STAGES and job.get('stage') != 'queued'
                and row.get('status') not in ('completed', 'incomplete', 'failed', 'deleting')
                and bool(handle.get('claimToken')) and all(job.get(key) == handle.get(key) for key in
                    ('id', 'claimToken', 'inputRevision', 'sourceDigest', 'foundationRevision'))
                and job.get('sourceDigest') == row.get('originalDigest')
                and type(job.get('leaseUntil')) is int and job['leaseUntil'] > now_ms)

    def claim(self, identity, job_id, *, worker_id, now_ms):
        _clock(now_ms)
        validate_component(worker_id, 'worker ID')
        try:
            current = self.get_owned(identity)
            foundation = (current.get('processingJob') or {}).get('foundationRevision')
            _hash(foundation)
            def claim(row, versions):
                job = row.get('processingJob') or {}
                if (job.get('id') != job_id or job.get('stage') not in ACTIVE_STAGES or job.get('leaseUntil', 0) > now_ms
                        or job.get('sourceDigest') != row.get('originalDigest')):
                    return None, {}, None
                job.update(claimToken=uuid.uuid4().hex, leaseUntil=now_ms+CLAIM_LEASE_MS, workerId=worker_id)
                if job['stage'] == 'queued': job['stage'] = 'capturing' if job['sourceDigest'] is None else 'preparing'
                row.update(processingJob=job, status='processing')
                row['supportingAnalysis']['state'] = 'processing'
                return row, {}, {key: job[key] for key in ('id', 'claimToken', 'inputRevision', 'sourceDigest', 'foundationRevision')}
            return self._atomic(identity, claim, foundation_revision=foundation)
        except DataConflict:
            return None

    def checkpoint(self, identity, job, *, changes, now_ms):
        _clock(now_ms)
        allowed = {'stage', 'cursor', 'modelCalls', 'error', 'checkpointRevision'}
        if not isinstance(changes, dict) or set(changes) - allowed: raise ValueError('Invalid supporting checkpoint fields')
        if 'modelCalls' in changes and (type(changes['modelCalls']) is not int or changes['modelCalls'] < 0):
            raise ValueError('Invalid model-call count')
        if 'stage' in changes and changes['stage'] not in ACTIVE_STAGES - {'queued'} | {'failed', 'incomplete'}:
            raise ValueError('Only report publication can complete a job')
        if changes.get('cursor') is not None:
            cursor = changes['cursor']
            if not isinstance(cursor, dict) or len(cursor) > 16 or any(type(v) is not int or v < 0 for v in cursor.values()):
                raise ValueError('Checkpoint cursor must contain compact numeric positions')
        if 'checkpointRevision' in changes: _hash(changes['checkpointRevision'])
        if changes.get('error') is not None and (not isinstance(changes['error'], str) or len(changes['error']) > 2000):
            raise ValueError('Invalid checkpoint error')
        def checkpoint(row, versions):
            if not self._live(row, job, now_ms): return None, {}, False
            current = row['processingJob']
            if 'modelCalls' in changes and not current['modelCalls'] <= changes['modelCalls'] <= current['modelCallBudget']:
                raise ValueError('Model-call accounting cannot decrease or exceed the budget')
            current.update(deepcopy(changes), leaseUntil=now_ms+CLAIM_LEASE_MS)
            if current['stage'] in ('failed', 'incomplete'):
                row['status'] = row['supportingAnalysis']['state'] = current['stage']
                row['error'] = current.get('error')
            return row, {}, True
        try:
            return self._atomic(identity, checkpoint, foundation_revision=job['foundationRevision'])
        except DataConflict:
            return False

    def _paths(self, identity, paths):
        if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
            raise ValueError('Invalid supporting artifact paths')
        from src.database import firebase_client
        for path in paths: validate_supporting_storage_path(identity, path, root=firebase_client.UPLOADS_ROOT)
        return paths

    def reservation_id(self, identity, paths):
        return version_id(identity, 'reservation', digest(sorted(paths)))

    def bind_capture(self, identity, job, *, path, source_digest, now_ms):
        """Bind a URL job once to already preserved bytes, outside the DB lock."""
        self._paths(identity, [path])
        _hash(source_digest)
        _clock(now_ms)
        if identity['kind'] != 'audio' or job.get('sourceDigest') is not None:
            raise ValueError('Only an uncaptured recording can bind an original')
        hasher = hashlib.sha256()
        original = self.database.download_file_from_storage(path, identity['userId'])
        with original.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''): hasher.update(block)
        if hasher.hexdigest() != source_digest: raise ValueError('Captured recording digest differs')
        reservation = self.reservation_id(identity, [path])
        def bind(row, versions):
            if not self._live(row, job, now_ms) or row.get('originalDigest') is not None:
                raise DataConflict('Recording was already captured or its claim changed')
            reserved = self._descriptor(identity, versions[reservation])
            if reserved.get('jobId') != job['id'] or reserved.get('claimToken') != job['claimToken']:
                raise DataConflict('Recording capture reservation changed')
            row.update(originalDigest=source_digest, storagePath=path)
            row['processingJob'].update(sourceDigest=source_digest, stage='preparing', leaseUntil=now_ms+CLAIM_LEASE_MS)
            return row, {}, {**job, 'sourceDigest': source_digest}
        return self._atomic(identity, bind, foundation_revision=job['foundationRevision'], version_ids=[reservation])

    def reserve(self, identity, job, *, paths, now_ms):
        self._paths(identity, paths)
        _clock(now_ms)
        key = self.reservation_id(identity, paths)
        def reserve(row, versions):
            if not self._live(row, job, now_ms): return None, {}, False
            value = {**identity, 'versionKind': 'reservation', 'revision': digest(sorted(paths)), 'state': 'reserved',
                     'jobId': job['id'], 'claimToken': job['claimToken'], 'supportingArtifactPaths': paths}
            if versions[key] and versions[key] != value: raise DataConflict('Artifact reservation changed')
            return None, {key: value}, True
        try:
            return self._atomic(identity, reserve, foundation_revision=job['foundationRevision'], version_ids=[key])
        except DataConflict:
            return False

    def _check_version(self, identity, version, kind):
        if not isinstance(version, dict) or version.get('versionKind') != kind: raise ValueError('Invalid version descriptor')
        self._descriptor(identity, version)
        _hash(version.get('revision'))
        _hash(version.get('contentDigest'))
        self._paths(identity, version.get('supportingArtifactPaths'))
        if version.get('reservationId') != self.reservation_id(identity, version['supportingArtifactPaths']):
            raise ValueError('Version has no exact artifact reservation')
        if type(version.get('coverageComplete')) is not bool: raise ValueError('Version coverage is missing')
        if kind == 'report':
            for field in ('sourceRevision', 'scopeRevision', 'foundationRevision'): _hash(version.get(field))
        return version

    def publish(self, identity, job, *, manifest_version, report_version, now_ms, checkpoint_version=None):
        _clock(now_ms)
        entries = [(v, kind) for v, kind in ((manifest_version, 'source'), (report_version, 'report'),
                                            (checkpoint_version, 'checkpoint')) if v is not None]
        if not entries: raise ValueError('Nothing to publish')
        keys = []
        for version, kind in entries:
            self._check_version(identity, version, kind)
            keys.extend([version_id(identity, kind, version['revision']), version['reservationId']])
            if kind == 'report': keys.append(version_id(identity, 'source', version['sourceRevision']))
        def publish(row, versions):
            if not self._live(row, job, now_ms): return None, {}, False
            writes = {}
            for version, kind in entries:
                reserved = self._descriptor(identity, versions[version['reservationId']])
                if (reserved.get('jobId') != job['id'] or reserved.get('claimToken') != job['claimToken']
                        or reserved.get('supportingArtifactPaths') != version['supportingArtifactPaths']):
                    raise DataConflict('Publication does not own reserved artifacts')
                key = version_id(identity, kind, version['revision'])
                existing = versions[key]
                if existing:
                    self._descriptor(identity, existing)
                    if existing.get('contentDigest') != version['contentDigest']:
                        raise DataConflict('Immutable version content changed')
                    if kind == 'report' and any(existing.get(k) != version.get(k) for k in
                            ('foundationRevision', 'scopeRevision', 'sourceRevision', 'coverageComplete')):
                        raise DataConflict('Immutable report binding changed')
                else: writes[key] = {**deepcopy(version), 'state': 'adopted'}
                if kind == 'source':
                    if version.get('originalDigest') != job['sourceDigest']: raise DataConflict('Source digest changed')
                    row['supportingAnalysis']['sourceRevision'] = version['revision']
                elif kind == 'checkpoint':
                    if any(version.get(k) != job[k] for k in ('inputRevision', 'sourceDigest', 'foundationRevision')):
                        raise DataConflict('Checkpoint source identity changed')
                    row['processingJob']['checkpointRevision'] = version['revision']
                else:
                    if version['sourceRevision'] != row['supportingAnalysis'].get('sourceRevision'):
                        raise DataConflict('Report source version changed')
                    source_key = version_id(identity, 'source', version['sourceRevision'])
                    source = self._descriptor(identity, writes.get(source_key, versions[source_key]))
                    if (source.get('originalDigest') != job['sourceDigest']
                            or version['foundationRevision'] != job['foundationRevision']):
                        raise DataConflict('Report source or foundation binding changed')
                    status = 'completed' if version['coverageComplete'] else 'incomplete'
                    row.update(status=status, error=None)
                    row['processingJob'].update(stage=status, leaseUntil=0)
                    row['supportingAnalysis'].update(state=status, sourceRevision=version['sourceRevision'],
                        reportRevision=version['revision'], analysisId=job['id'], scopeRevision=version['scopeRevision'])
            return row, writes, True
        try:
            return self._atomic(identity, publish, foundation_revision=job['foundationRevision'], version_ids=keys)
        except DataConflict:
            return False

    @staticmethod
    def _expected(row, expected):
        analysis = row.get('supportingAnalysis') or {}
        job = row.get('processingJob') or {}
        return (row.get('status') == 'completed' and analysis.get('state') == 'completed'
                and bool(row.get('originalDigest')) and row['originalDigest'] == job.get('sourceDigest')
                and job.get('id') == analysis.get('analysisId') and job.get('stage') == 'completed'
                and all(analysis.get(k) == expected.get(k) for k in ('sourceRevision', 'reportRevision', 'analysisId')))

    def _completed_source(self, identity, row, expected, source):
        source = self._descriptor(identity, source)
        return (self._expected(row, expected) and source.get('state') == 'adopted'
                and source.get('versionKind') == 'source' and source.get('revision') == expected.get('sourceRevision')
                and source.get('originalDigest') == row.get('originalDigest') and source.get('coverageComplete') is True)

    def reserve_scoped_artifacts(self, identity, expected, *, paths):
        self._paths(identity, paths)
        key = self.reservation_id(identity, paths)
        source_key = version_id(identity, 'source', _hash(expected.get('sourceRevision')))
        def reserve(row, versions):
            if not self._completed_source(identity, row, expected, versions[source_key]): return None, {}, False
            value = {**identity, 'versionKind': 'reservation', 'revision': digest(sorted(paths)), 'state': 'reserved',
                     'expected': deepcopy(expected), 'supportingArtifactPaths': paths}
            if versions[key] and versions[key] != value: raise DataConflict('Scoped reservation changed')
            return None, {key: value}, True
        try:
            foundation = _hash(self.get_owned(identity).get('processingJob', {}).get('foundationRevision'))
            return self._atomic(identity, reserve, foundation_revision=foundation, version_ids=[key, source_key])
        except DataConflict: return False

    def publish_scoped_report(self, identity, expected, *, report_version):
        version = self._check_version(identity, report_version, 'report')
        key = version_id(identity, 'report', version['revision'])
        source_key = version_id(identity, 'source', _hash(expected.get('sourceRevision')))
        def publish(row, versions):
            if (not self._completed_source(identity, row, expected, versions[source_key])
                    or version['sourceRevision'] != expected.get('sourceRevision')
                    or version['foundationRevision'] != row['processingJob'].get('foundationRevision')):
                return None, {}, False
            reserved = self._descriptor(identity, versions[version['reservationId']])
            if reserved.get('expected') != expected or reserved.get('supportingArtifactPaths') != version['supportingArtifactPaths']:
                raise DataConflict('Scoped reservation identity changed')
            existing = versions[key]
            if existing:
                self._descriptor(identity, existing)
                if existing.get('contentDigest') != version['contentDigest']: raise DataConflict('Immutable scoped report changed')
                if any(existing.get(k) != version.get(k) for k in
                       ('foundationRevision', 'scopeRevision', 'sourceRevision', 'coverageComplete')):
                    raise DataConflict('Immutable scoped report binding changed')
                return None, {}, True
            return None, {key: {**deepcopy(version), 'state': 'adopted'}}, True
        try:
            foundation = _hash(self.get_owned(identity).get('processingJob', {}).get('foundationRevision'))
            return self._atomic(identity, publish, foundation_revision=foundation,
                                version_ids=[key, version['reservationId'], source_key])
        except DataConflict: return False

    def assert_snapshot(self, snapshot, *, transaction=None, local=None, scope_revision=None):
        if not isinstance(snapshot, dict) or snapshot.get('version') != 1 or not isinstance(snapshot.get('materials'), list):
            raise DataConflict('Supporting snapshot is unavailable')
        db = self.database
        if scope_revision is not None: _hash(scope_revision)
        if transaction is None and local is None:
            if db.use_local:
                with db._local_transaction():
                    return self.assert_snapshot(snapshot, local=db._read_local_db(), scope_revision=scope_revision)
            from google.cloud import firestore
            @firestore.transactional
            def check(tx): return self.assert_snapshot(snapshot, transaction=tx, scope_revision=scope_revision)
            return check(db.db.transaction())
        def read(collection, key):
            if local is not None: return local.get(collection, {}).get(key, {})
            snap = db.db.collection(collection).document(key).get(transaction=transaction)
            return snap.to_dict() or {} if snap.exists else {}
        seen = set()
        for entry in snapshot['materials']:
            identity = validate_identity(entry.get('identity'))
            db._assert_write_allowed(identity['userId'], identity['courseId'], transaction)
            if read(VERSIONS, version_id(identity, 'tombstone', 'deleted')):
                raise DataConflict('Selected supporting material was deleted')
            marker = canonical_bytes(identity)
            if marker in seen: raise ValueError('Duplicate supporting snapshot identity')
            seen.add(marker)
            row = read(COLLECTIONS[identity['kind']], identity['materialId'])
            self._row(identity, row)
            if not self._expected(row, entry): raise DataConflict('Selected supporting source changed; retry generation')
            foundation = _hash(row['processingJob'].get('foundationRevision'))
            db._assert_foundation_current(identity['userId'], identity['courseId'], foundation,
                                          local=local, transaction=transaction)
            for kind, field in (('source', 'sourceRevision'), ('report', 'reportRevision'), ('report', 'scopedReportRevision')):
                revision = _hash(entry.get(field))
                version = self._descriptor(identity, read(VERSIONS, version_id(identity, kind, revision)))
                if version.get('state') != 'adopted' or version.get('revision') != revision or not version.get('coverageComplete'):
                    raise DataConflict('Supporting evidence version is unavailable or incomplete')
                if kind == 'report' and version.get('sourceRevision') != entry['sourceRevision']:
                    raise DataConflict('Supporting report source changed')
                if kind == 'source' and not self._completed_source(identity, row, entry, version):
                    raise DataConflict('Supporting original source changed')
                if kind == 'report' and version.get('foundationRevision') != foundation:
                    raise DataConflict('Supporting report lecture foundation changed')
                if field == 'scopedReportRevision' and scope_revision is not None and version.get('scopeRevision') != scope_revision:
                    raise DataConflict('Supporting report selected scope changed')

    def pending(self, *, now_ms, limit=1000):
        _clock(now_ms)
        if type(limit) is not int or not 1 <= limit <= 1000: raise ValueError('Invalid job limit')
        db, result = self.database, []
        def candidates(collection):
            if db.use_local:
                yield from ({**row, 'id': key} for key, row in db._read_local_db().get(collection, {}).items())
                return
            from google.cloud.firestore_v1.base_query import FieldFilter
            query = db.db.collection(collection).where(filter=FieldFilter('status', 'in', ['queued', 'processing']))
            query = query.order_by('__name__')
            # Bound each database fetch, advancing past live/stale rows rather
            # than applying the caller's result limit to unfiltered candidates.
            page_size = 100
            while True:
                page = list(query.limit(page_size).stream())
                for snap in page: yield {**snap.to_dict(), 'id': snap.id}
                if len(page) < page_size: return
                query = query.start_after(page[-1])
        for kind, collection in COLLECTIONS.items():
            if kind == 'notes': continue
            for row in candidates(collection):
                job = row.get('processingJob') or {}
                if job.get('stage') not in ACTIVE_STAGES or job.get('leaseUntil', 0) > now_ms: continue
                identity = {'userId': row.get('userId'), 'courseId': row.get('courseId'),
                            'materialId': row['id'], 'kind': 'notes' if kind == 'audio' and row.get('sourceType') == 'notes' else kind}
                try:
                    valid = self._atomic(identity, lambda current, versions: (None, {},
                        current.get('originalDigest') == job.get('sourceDigest')
                        and current.get('processingJob', {}).get('id') == job.get('id')
                        and current.get('processingJob', {}).get('stage') in ACTIVE_STAGES
                        and current.get('processingJob', {}).get('leaseUntil', 0) <= now_ms),
                        foundation_revision=job.get('foundationRevision'))
                    if valid: result.append(identity)
                except (ValueError, TypeError): continue
                if len(result) >= limit: return result
        return result

    def delete(self, identity):
        identity = validate_identity(identity)
        db = self.database
        tombstone = version_id(identity, 'tombstone', 'deleted')
        def cancel(row, versions):
            deleted = {**identity, 'versionKind': 'tombstone', 'revision': 'deleted', 'state': 'deleted'}
            if row:
                row.update(status='deleting', processingJob={})
            return row or None, {tombstone: deleted}, deepcopy(row)
        row = self._atomic(identity, cancel, allow_deleting=True, require_parent=False)
        descriptors = [r for r in db._flat_query_by_course(VERSIONS, identity['courseId'], identity['userId'])
                       if r.get('kind') == identity['kind'] and r.get('materialId') == identity['materialId']]
        paths = set()
        for descriptor in descriptors:
            for path in descriptor.get('supportingArtifactPaths', []):
                self._paths(identity, [path])
                paths.add(path)
        # Validate the legacy original too before deleting any owned object.
        if row: paths.update(db._record_storage_paths({**row, 'id': identity['materialId']}, identity['userId'], identity['courseId']))
        for path in paths: db.delete_file_from_storage(path, identity['userId'])
        db._cleanup_storage_namespace(identity['userId'], identity['courseId'],
            filename_prefix=supporting_artifact_prefix(identity['kind'], identity['materialId']),
            categories=(SUPPORTING_CATEGORIES[identity['kind']],))
        for descriptor in descriptors:
            if descriptor['id'] != tombstone: db._flat_delete(VERSIONS, descriptor['id'])
        if row: db._flat_delete(COLLECTIONS[identity['kind']], identity['materialId'])
        return {'materials': int(bool(row)), 'files': len(paths)}
