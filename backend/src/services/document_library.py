"""Immutable private source artifacts with claim-fenced publication."""
from copy import deepcopy
import hashlib
import json
import re
import time
import uuid

from src.utils.document_sources import render_source_unit
from src.utils.source_contracts import validate_manifest, validate_source_reference
from src.utils.storage_paths import build_document_artifact_path


class DocumentLibrary:
    def __init__(self, database):
        self.database = database

    def _document(self, user_id, course_id, doc_id):
        return self.database.get_owned_document(user_id, course_id, doc_id)

    def save_manifest(self, user_id: str, course_id: str, doc_id: str,
                      job_id: str, claim_token: str, manifest: dict) -> dict:
        manifest = validate_manifest(manifest)
        if manifest['documentId'] != doc_id:
            raise ValueError('Manifest document mismatch')
        row = self._document(user_id, course_id, doc_id)
        original_path = row.get('storagePath')
        self.database.validate_document_storage_path(user_id, course_id, original_path)
        attempt = uuid.uuid4().hex
        paths = [build_document_artifact_path(user_id, course_id, doc_id, job_id, claim_token, attempt, suffix)
                 for suffix in ('original.' + manifest['fileType'], 'manifest.json')]
        if not self.database.reserve_document_artifacts(user_id, course_id, doc_id, job_id, claim_token,
                                                        paths=paths, now_ms=int(time.time() * 1000)):
            raise ValueError('Document job claim is no longer live')
        try:
            original = self.database.download_file_from_storage(original_path, user_id).read_bytes()
            if hashlib.sha256(original).hexdigest() != manifest['originalDigest']:
                raise ValueError('Original source digest changed or is unavailable')
            body = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
            for path, data in zip(paths, (original, body)):
                # Recheck immediately before each write; publication checks again after I/O.
                if not self.database.checkpoint_document_job(user_id, course_id, doc_id, job_id, claim_token,
                                                             changes={}, now_ms=int(time.time() * 1000)):
                    raise ValueError('Document job claim is no longer live')
                self.database.upload_file_to_storage(data, path, user_id, require_remote=True)
            version = {'manifestPath': paths[1], 'manifestDigest': hashlib.sha256(body).hexdigest(),
                       'originalPath': paths[0], 'originalDigest': manifest['originalDigest'],
                       'fileType': manifest['fileType'], 'unitCount': manifest['unitCount'],
                       'coverageComplete': manifest['coverage']['complete']}
            if not self.database.publish_document_source(user_id, course_id, doc_id, job_id, claim_token,
                                                         source_revision=manifest['sourceRevision'], version=version,
                                                         now_ms=int(time.time() * 1000)):
                raise ValueError('Document job claim is no longer live')
            # An identical existing revision keeps its immutable pointers.
            current = self._document(user_id, course_id, doc_id)['sourceVersions'][manifest['sourceRevision']]
            if current['manifestPath'] != paths[1]:
                self._compensate(user_id, course_id, doc_id, paths)
            return manifest
        except Exception:
            self._compensate(user_id, course_id, doc_id, paths)
            raise

    def _compensate(self, user_id, course_id, doc_id, paths):
        # Failed cleanup keeps pending metadata for a later lifecycle cleanup.
        for path in paths:
            self.database.delete_file_from_storage(path, user_id)
        self.database.release_document_artifacts(user_id, course_id, doc_id, paths=paths)

    def load_manifest(self, user_id: str, course_id: str, doc_id: str,
                      source_revision: str | None = None) -> dict:
        row = self._document(user_id, course_id, doc_id)
        revision = source_revision if source_revision is not None else row.get('sourceRevision')
        if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{64}', revision):
            raise ValueError('Requested source version is unavailable')
        version = row.get('sourceVersions', {}).get(revision)
        if not isinstance(version, dict):
            raise ValueError('Requested source version is unavailable')
        if source_revision is None and version.get('originalDigest') != row.get('originalDigest'):
            raise ValueError('Current original source has not been prepared')
        path = version.get('manifestPath')
        self.database.validate_document_storage_path(user_id, course_id, path, doc_id=doc_id)
        body = self.database.download_file_from_storage(path, user_id).read_bytes()
        if hashlib.sha256(body).hexdigest() != version.get('manifestDigest'):
            raise ValueError('Source manifest artifact is corrupt')
        manifest = validate_manifest(json.loads(body))
        if (manifest['documentId'] != doc_id or manifest['sourceRevision'] != revision
                or manifest['originalDigest'] != version.get('originalDigest')
                or manifest['fileType'] != version.get('fileType')):
            raise ValueError('Source version metadata mismatch')
        self._document(user_id, course_id, doc_id)
        return manifest

    def load_units(self, user_id: str, course_id: str, refs: list[dict]) -> list[dict]:
        if not isinstance(refs, list):
            raise ValueError('Source references must be a list')
        manifests, result = {}, []
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError('Invalid source reference')
            key = (ref.get('documentId'), ref.get('sourceRevision'))
            if not all(isinstance(value, str) and value for value in key):
                raise ValueError('Source references require an exact document and revision')
            if key not in manifests:
                manifests[key] = self.load_manifest(user_id, course_id, *key)
            manifest = manifests[key]
            valid = validate_source_reference(ref, manifest)
            unit = next(u for u in manifest['units'] if u['unitId'] == valid['unitId'])
            result.append({**deepcopy(unit), **valid})
        return result

    def render_reference(self, user_id: str, course_id: str, ref: dict) -> list[str]:
        units = self.load_units(user_id, course_id, [ref])
        row = self._document(user_id, course_id, ref['documentId'])
        version = row['sourceVersions'][ref['sourceRevision']]
        path = version.get('originalPath')
        self.database.validate_document_storage_path(user_id, course_id, path, doc_id=ref['documentId'])
        original = self.database.download_file_from_storage(path, user_id).read_bytes()
        if hashlib.sha256(original).hexdigest() != version.get('originalDigest'):
            raise ValueError('Exact original source version is corrupt')
        rendered = render_source_unit(original, version['fileType'], units[0]['unitId'])
        self._document(user_id, course_id, ref['documentId'])
        return rendered
