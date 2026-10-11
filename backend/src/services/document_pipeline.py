"""Claim-fenced, stage-durable source preparation and automatic guide work."""
import hashlib
import logging
import threading
import time
import uuid

from src.database.firebase_client import DataSizeConflict
from src.utils.document_sources import extract_source_units, render_source_unit
from src.utils.source_contracts import apply_source_visual_result, build_source_manifest

logger = logging.getLogger('MudarisDocuments')
HEARTBEAT_SECONDS = 60


class DocumentPipeline:
    def __init__(self, database, library, processor):
        self.database, self.library, self.processor = database, library, processor

    def run(self, doc_id: str) -> bool:
        db = self.database
        row = db.get_document(doc_id)
        if not row or not isinstance(row.get('processingJob'), dict):
            return False
        uid, course_id = row.get('userId'), row.get('courseId')
        job_id = row['processingJob'].get('id')
        job = db.claim_document_job(uid, course_id, doc_id, job_id,
                                    worker_id=uuid.uuid4().hex, now_ms=int(time.time() * 1000))
        if not job:
            return False
        token = job['claimToken']
        stopped, lost = threading.Event(), threading.Event()
        stage = 'preparation'

        def checkpoint(changes):
            if lost.is_set() or not db.checkpoint_document_job(
                    uid, course_id, doc_id, job_id, token, changes=changes, now_ms=int(time.time() * 1000)):
                lost.set()
                raise ValueError('Document job claim is no longer live')

        def heartbeat():
            while not stopped.wait(HEARTBEAT_SECONDS):
                try:
                    checkpoint({})
                except Exception:
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, name='document-lease-' + job_id, daemon=True)
        thread.start()
        try:
            row = db.get_owned_document(uid, course_id, doc_id)
            path = row.get('storagePath')
            db.validate_document_storage_path(uid, course_id, path)
            original = db.download_file_from_storage(path, uid).read_bytes()
            if hashlib.sha256(original).hexdigest() != job['sourceDigest']:
                raise ValueError('Original source digest mismatch')
            manifest = None
            restore = False
            if row.get('preparationStatus') == 'completed':
                try:
                    manifest = self.library.load_manifest(uid, course_id, doc_id)
                    version = row['sourceVersions'][manifest['sourceRevision']]
                    db.validate_document_storage_path(uid, course_id, version['originalPath'], doc_id=doc_id)
                    exact = db.download_file_from_storage(version['originalPath'], uid).read_bytes()
                    if hashlib.sha256(exact).hexdigest() != manifest['originalDigest']:
                        raise ValueError('Exact source original is corrupt')
                except (ValueError, FileNotFoundError):
                    # Only a claimed explicit/recovered job may restore from the
                    # digest-verified preserved upload. Healthy prepared text is reused.
                    restore = True
                    checkpoint({'stage': 'preparing', 'preparationStatus': 'processing', 'guideStatus': 'pending'})
            if manifest is None:
                units = extract_source_units(original, row['fileType'])
                for index, unit in enumerate(units):
                    checkpoint({'cursor': {'unitIndex': index}})
                    if unit.get('needsVisualRead') and unit.get('visualReadStatus') != 'unsupported':
                        images = render_source_unit(original, row['fileType'], unit['unitId'])
                        result = self.processor.read_source_visual(unit, images)
                        checkpoint({})
                        units[index] = apply_source_visual_result(unit, result)
                manifest = build_source_manifest(doc_id, job['sourceDigest'], row['fileType'], units)
                if not manifest['coverage']['complete']:
                    raise ValueError('Source contains uncertain or unsupported material')
                restore = True
            if restore:
                checkpoint({})
                manifest = self.library.save_manifest(uid, course_id, doc_id, job_id, token, manifest)
            stage = 'guide'
            checkpoint({'stage': 'guiding', 'guideStatus': 'processing', 'cursor': None})
            course = db.get_owned_course(uid, course_id)
            def render(unit):
                checkpoint({})
                return self.library.render_reference(uid, course_id, {
                    'documentId': doc_id, 'sourceRevision': manifest['sourceRevision'], 'unitId': unit['unitId']})
            guide = self.processor.analyze_source_guide(manifest, course.get('title', course_id), render)
            checkpoint({'guide': guide, 'guideStatus': 'completed', 'status': 'completed', 'stage': 'completed'})
            return True
        except Exception as exc:
            # Never persist source/model bodies or raw provider errors.
            message = ('This material is too large. Split it into smaller files and retry.'
                       if isinstance(exc, DataSizeConflict) or 'limit' in str(exc).lower() or str(exc).startswith('Split the file:') else
                       'Source preparation failed. Check the original, use a faithful PDF conversion or an image-capable model, and retry.'
                       if stage == 'preparation' else
                       'Guide creation failed. Check the configured model and retry; prepared source material is saved.')
            try:
                checkpoint({'stage': 'failed', stage + 'Status': 'failed', 'error': message})
            except Exception:
                pass  # Lost/deleted/replaced jobs must never publish failure over a successor.
            logger.warning('Document %s %s did not complete (%s)', doc_id, stage, type(exc).__name__)
            return False
        finally:
            stopped.set()
            thread.join()
