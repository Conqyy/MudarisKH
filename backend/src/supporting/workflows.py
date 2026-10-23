"""Durable preparation, extraction, alignment, and publication workflow."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import uuid

from src.supporting.contracts import digest, validate_identity
from src.supporting.alignment import SupportingAligner
from src.supporting.audio_sources import build_audio_manifest, build_notes_manifest
from src.utils.storage_paths import build_supporting_artifact_path


class SupportingWorkflow:
    def __init__(self, repository, library, extractor, audio_agent, reader_factory):
        if not callable(reader_factory):
            raise ValueError("A supporting lecture-reader factory is required")
        self.repository = repository
        self.library = library
        self.extractor = extractor
        self.audio_agent = audio_agent
        self.reader_factory = reader_factory

    @staticmethod
    def _now():
        return int(time.time() * 1000)

    def prepare(self, identity, *, retry: bool = False) -> dict:
        identity = validate_identity(identity)
        row = self.repository.get_owned(identity)
        reader = self.reader_factory(identity)
        scope = getattr(reader, "scope", None)
        foundation_revision = scope.get("foundationRevision") if isinstance(scope, dict) else None
        if not isinstance(foundation_revision, str) or len(foundation_revision) != 64:
            raise ValueError("Lecture foundation is not ready")
        source_digest = row.get("originalDigest")
        if source_digest is None and row.get("storagePath"):
            try:
                saved = self.repository.database.download_file_from_storage(
                    row["storagePath"], identity["userId"])
                source_digest = hashlib.sha256(Path(saved).read_bytes()).hexdigest()
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError(
                    "The original material is unavailable; re-upload it before retrying") from exc
        if (source_digest is None and identity["kind"] == "notes"
                and isinstance(row.get("transcript"), str) and row["transcript"].strip()):
            source_digest = hashlib.sha256(row["transcript"].encode("utf-8")).hexdigest()
        if source_digest is None and not (identity["kind"] == "audio" and row.get("sourceType") == "url"):
            raise ValueError("The original material is unavailable; re-upload it before retrying")
        input_revision = digest({
            "identity": identity,
            "sourceDigest": source_digest,
            "storagePath": row.get("storagePath"),
            "sourceUrl": row.get("sourceUrl"),
            "fileType": row.get("fileType"),
            "sourceType": row.get("sourceType"),
        })
        job = self.repository.queue(identity, input_revision=input_revision,
            source_digest=source_digest, foundation_revision=foundation_revision,
            now_ms=self._now(), model_call_budget=self._model_call_budget())
        return {
            "materialId": identity["materialId"], "kind": identity["kind"],
            "status": "queued", "stage": "queued",
            "progress": {"completedUnits": 0, "totalUnits": None,
                         "completedRequirements": 0, "totalRequirements": None},
            "sourceRevision": None, "reportRevision": None, "scopeRevision": None,
            "coverage": None, "legacy": False, "stale": False, "errorMessage": None,
            "jobId": job["id"],
        }

    @staticmethod
    def _model_call_budget():
        from src.config.settings import settings
        return settings.SUPPORTING_MODEL_CALL_BUDGET

    def _persist_checkpoint(self, identity, job, stage, state, *, inventory_revision=None):
        """Persist spent calls before detached state so interruption cannot undercount."""
        changes = {"stage": stage, "modelCalls": state.get("modelCalls", 0)}
        if not self.repository.checkpoint(identity, job, changes=changes, now_ms=self._now()):
            raise RuntimeError("Supporting analysis claim changed")
        version = self.library.save_checkpoint(identity, job, deepcopy(state))
        changes = {"checkpointRevision": version["revision"]}
        if stage == 'extracting':
            changes['extractionRevision'] = version['revision']
        if inventory_revision is not None:
            changes["inventoryRevision"] = inventory_revision
        if not self.repository.checkpoint(identity, job, changes=changes, now_ms=self._now()):
            raise RuntimeError("Supporting analysis claim changed")
        return version

    def _heartbeat(self, identity, job, stop):
        while not stop.wait(60):
            checked = deepcopy(job)
            if not self.repository.checkpoint(identity, checked, changes={}, now_ms=self._now()):
                # Capture can bind its digest between a heartbeat's read and
                # checkpoint. Follow only that transition on this exact claim.
                current = self.repository.get_owned(identity).get('processingJob') or {}
                if (checked.get('sourceDigest') is not None or not current.get('sourceDigest')
                        or any(current.get(key) != checked.get(key) for key in
                               ('id', 'claimToken', 'inputRevision', 'foundationRevision'))):
                    return
                bound = {**checked, 'sourceDigest': current['sourceDigest']}
                if not self.repository.checkpoint(identity, bound, changes={}, now_ms=self._now()):
                    return
                job['sourceDigest'] = bound['sourceDigest']

    def _read_original(self, identity, row, job):
        path = row.get('storagePath')
        if identity['kind'] == 'audio' and job.get('sourceDigest') is None:
            url = row.get('sourceUrl')
            if not url:
                raise ValueError('The captured recording is missing; re-upload the original audio')
            with tempfile.TemporaryDirectory(prefix='mudaris-supporting-capture-') as directory:
                from src.api import _download_url_audio_to_mp3
                captured_path, _ = _download_url_audio_to_mp3(url, directory)
                captured = Path(captured_path).read_bytes()
            if not captured:
                raise ValueError('The captured recording is empty; retry the URL or upload audio')
            captured_digest = hashlib.sha256(captured).hexdigest()
            attempt = uuid.uuid4().hex
            path = build_supporting_artifact_path(identity, job['id'], job['claimToken'],
                                                   attempt, 'original.bin')
            if not self.repository.reserve(identity, job, paths=[path], now_ms=self._now()):
                raise RuntimeError('Supporting analysis claim changed before URL capture')
            self.repository.database.upload_file_to_storage(
                captured, path, identity['userId'], require_remote=True)
            bound = self.repository.bind_capture(identity, job, path=path,
                source_digest=captured_digest, now_ms=self._now())
            # The heartbeat retains this same dictionary. Never replace it with
            # a newly fetched worker handle or a competing claim token.
            job['sourceDigest'] = bound['sourceDigest']
            row = self.repository.get_owned(identity)
        if not path:
            if identity['kind'] == 'notes' and isinstance(row.get('transcript'), str):
                body = row['transcript'].encode('utf-8')
            else:
                raise ValueError('The preserved original is missing; re-upload this material')
        else:
            saved = self.repository.database.download_file_from_storage(path, identity['userId'])
            body = saved.read_bytes()
        actual = hashlib.sha256(body).hexdigest()
        if actual != job.get('sourceDigest') or actual != row.get('originalDigest'):
            raise ValueError('The preserved original is missing or corrupt; re-upload this material')
        return body, row, job

    def _manifest(self, identity, row, job, original):
        if identity['kind'] in ('historical_exam', 'tutorial'):
            file_type = row.get('fileType')
            if not file_type:
                suffix = Path(row.get('storagePath') or '').suffix.lower().lstrip('.')
                if identity['kind'] == 'historical_exam':
                    file_type = 'pdf' if suffix == 'pdf' else (
                        'image' if suffix in {'jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'bmp', 'gif'} else None)
                elif suffix in {'pdf', 'pptx', 'docx'}:
                    file_type = suffix
            if not file_type:
                raise ValueError('The original file type is unavailable; re-upload this material')
            return self.extractor.prepare_pages(identity, original, file_type)
        if identity['kind'] == 'notes':
            try:
                notes = original.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise ValueError('Typed-note original is not valid UTF-8; re-upload it') from exc
            return build_notes_manifest(identity, notes)
        suffix = '.' + str(row.get('audioExt') or 'mp3').lower().lstrip('.')
        temporary = tempfile.NamedTemporaryFile(prefix='mudaris-supporting-audio-', suffix=suffix, delete=False)
        try:
            temporary.write(original)
            temporary.close()
            counter = {'value': self.repository.get_owned(identity)['processingJob']['modelCalls']}
            budget = self.repository.get_owned(identity)['processingJob']['modelCallBudget']

            def before_call():
                if counter['value'] >= budget:
                    raise RuntimeError('Successful model-call budget exhausted; retry with a fresh budget')
                if not self.repository.checkpoint(identity, job, changes={}, now_ms=self._now()):
                    raise RuntimeError('Supporting analysis claim changed')

            def on_response():
                counter['value'] += 1
                if not self.repository.checkpoint(identity, job,
                        changes={'modelCalls': counter['value']}, now_ms=self._now()):
                    raise RuntimeError('Supporting analysis claim changed')

            transcript = self.audio_agent.transcribe_audio_source(
                temporary.name, before_call=before_call, on_response=on_response)
        finally:
            try:
                Path(temporary.name).unlink(missing_ok=True)
            except OSError:
                pass
        return build_audio_manifest(identity, original_digest=job['sourceDigest'], transcript=transcript)

    def _inventory_checkpoint(self, identity, job, inventory, model_calls, source_revision):
        if inventory.get('extractionCoverage', {}).get('complete') is not True:
            raise ValueError('Incomplete supporting extraction cannot be reused as inventory')
        state = {'phase': 'inventory', 'sourceRevision': source_revision,
                 'inventoryDigest': digest(inventory), 'inventory': deepcopy(inventory),
                 'modelCalls': model_calls}
        if not self.repository.checkpoint(identity, job,
                changes={'stage': 'aligning', 'modelCalls': model_calls}, now_ms=self._now()):
            raise RuntimeError('Supporting analysis claim changed')
        version = self.library.save_checkpoint(identity, job, state)
        if not self.repository.checkpoint(identity, job, changes={
                'checkpointRevision': version['revision'], 'inventoryRevision': version['revision']},
                now_ms=self._now()):
            raise RuntimeError('Supporting analysis claim changed')
        return version['revision']

    def _load_inventory(self, identity, revision, source_revision):
        state = self.library.load_checkpoint(identity, revision)
        inventory = state.get('inventory') if isinstance(state, dict) and state.get('phase') == 'inventory' else None
        if (not isinstance(inventory, dict) or state.get('inventoryDigest') != digest(inventory)
                or state.get('sourceRevision') != source_revision
                or inventory.get('extractionCoverage', {}).get('complete') is not True):
            raise ValueError('Prepared supporting inventory checkpoint source is invalid')
        return inventory

    def run(self, identity) -> bool:
        """Claim and run preparation, extraction, alignment, and publication."""
        identity = validate_identity(identity)
        row = self.repository.get_owned(identity)
        pending = row.get("processingJob") or {}
        job = self.repository.claim(identity, pending.get("id"), worker_id=uuid.uuid4().hex,
                                    now_ms=self._now())
        if not job:
            return False
        stop = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(identity, job, stop), daemon=True)
        heartbeat.start()
        try:
            row = self.repository.get_owned(identity)
            runtime = row['processingJob']
            budget, calls = runtime['modelCallBudget'], runtime['modelCalls']
            reader = self.reader_factory(identity)
            if reader.scope.get('foundationRevision') != job['foundationRevision']:
                raise ValueError('Lecture foundation changed; confirm documents and retry')

            manifest = None
            source_revision = (row.get('supportingAnalysis') or {}).get('sourceRevision')
            if source_revision:
                try:
                    manifest = self.library.load_source(identity, source_revision)
                    if manifest.get('originalDigest') != job.get('sourceDigest'):
                        raise ValueError('Prepared supporting source no longer matches the queued original')
                except ValueError:
                    manifest = None
            if manifest is None:
                original, row, job = self._read_original(identity, row, job)
                manifest = self._manifest(identity, row, job, original)
                self.library.save_source(identity, job, original, manifest)

            runtime = self.repository.get_owned(identity)['processingJob']
            calls = runtime['modelCalls']
            inventory_revision = runtime.get('inventoryRevision')
            inventory = None
            if inventory_revision:
                try:
                    inventory = self._load_inventory(
                        identity, inventory_revision, manifest['sourceRevision'])
                except ValueError:
                    inventory = None
            current_revision = runtime.get('checkpointRevision')
            current_state = None
            if current_revision and current_revision != inventory_revision:
                try:
                    current_state = self.library.load_checkpoint(identity, current_revision)
                except ValueError:
                    current_state = None

            if inventory is None:
                resume = current_state if isinstance(current_state, dict) and current_state.get('stage') in (
                    'extract', 'reconcile', 'complete') else None
                if resume is None and runtime.get('extractionRevision'):
                    # Alignment and partial-report checkpoints may replace the
                    # active pointer, but must not erase extraction's exact prefix.
                    resume = self.library.load_checkpoint(identity, runtime['extractionRevision'])

                def extraction_checkpoint(state):
                    self._persist_checkpoint(identity, job, 'extracting', state)

                def render(unit):
                    ref = {'kind': identity['kind'], 'materialId': identity['materialId'],
                           'sourceRevision': manifest['sourceRevision'], 'unitId': unit['unitId']}
                    return self.library.render_reference(identity, ref)

                course = self.repository.database.get_owned_course(identity['userId'], identity['courseId'])
                inventory = self.extractor.extract(manifest,
                    course_title=course.get('title', identity['courseId']), lecture_reader=reader,
                    render=render, checkpoint=extraction_checkpoint, resume=resume,
                    model_call_budget=budget, model_calls=calls)
                calls = self.repository.get_owned(identity)['processingJob']['modelCalls']
                if inventory.get('extractionCoverage', {}).get('complete') is True:
                    inventory_revision = self._inventory_checkpoint(
                        identity, job, inventory, calls, manifest['sourceRevision'])

            runtime = self.repository.get_owned(identity)['processingJob']
            calls = runtime['modelCalls']
            checkpoint_revision = runtime.get('checkpointRevision')
            resume_revision = None
            if checkpoint_revision and checkpoint_revision != inventory_revision:
                try:
                    candidate = self.library.load_checkpoint(identity, checkpoint_revision)
                    if isinstance(candidate, dict) and candidate.get('stage') == 'align':
                        resume_revision = checkpoint_revision
                except ValueError:
                    pass

            def alignment_checkpoint(state):
                self._persist_checkpoint(identity, job, 'aligning', state,
                                         inventory_revision=inventory_revision)

            report = SupportingAligner(reader, self.library).align(identity, inventory,
                scope=reader.scope, checkpoint=alignment_checkpoint,
                resume_revision=resume_revision, model_call_budget=budget, model_calls=calls)
            self.library.save_report(identity, job, report)
            return True
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
            try:
                self.repository.checkpoint(identity, job,
                    changes={'stage': 'failed', 'error': message[:2000]}, now_ms=self._now())
            except Exception:
                pass
            return False
        finally:
            stop.set()
            heartbeat.join(timeout=1)

