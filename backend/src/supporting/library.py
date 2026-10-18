"""Private immutable supporting originals and chunked evidence reports."""
from copy import deepcopy
import hashlib
import json
import time
import uuid

from src.supporting.contracts import (
    validate_supporting_manifest, validate_alignment_report, validate_source_proof, validate_ref,
    canonical_bytes, digest, MAX_REPORT_CHUNK_BYTES, MAX_REPORT_CHUNK_ITEMS,
)
from src.supporting.alignment_evidence import proof_in_supplied, ref_key, validate_review_ledger
from src.utils.storage_paths import build_supporting_artifact_path

REPORT_ARRAYS = ('items', 'alignments', 'sharedContexts', 'papers', 'topics')


class SupportingLibrary:
    def __init__(self, repository):
        self.repository = repository
        self.database = repository.database

    @staticmethod
    def _now(): return int(time.time()*1000)

    def _read(self, identity, path, expected_digest):
        self.repository._paths(identity, [path])
        file = self.database.download_file_from_storage(path, identity['userId'])
        from src.utils.media_download import MAX_MEDIA_BYTES
        limit = MAX_MEDIA_BYTES if identity['kind'] == 'audio' else 100*1024*1024
        with file.open('rb') as stream:
            body = stream.read(limit+1)
        if len(body) > limit or hashlib.sha256(body).hexdigest() != expected_digest:
            raise ValueError('Exact supporting artifact is missing, corrupt or oversized')
        self.repository.get_owned(identity)
        return body

    def _store(self, identity, job, payloads, descriptor, *, expected=None):
        attempt = uuid.uuid4().hex
        handle = job if job is not None else {'id': uuid.uuid4().hex, 'claimToken': uuid.uuid4().hex}
        paths = [build_supporting_artifact_path(identity, handle['id'], handle['claimToken'], attempt, name) for name, data in payloads]
        descriptor = {**deepcopy(descriptor), **identity, 'supportingArtifactPaths': paths,
                      'reservationId': self.repository.reservation_id(identity, paths)}
        if descriptor['versionKind'] == 'source':
            descriptor.update(originalPath=paths[0], manifestPath=paths[1])
        else:
            descriptor['headerPath'] = paths[0]
            for path, chunk in zip(paths[1:], descriptor['chunks']): chunk['path'] = path
        reserve = (self.repository.reserve(identity, job, paths=paths, now_ms=self._now()) if job is not None
                   else self.repository.reserve_scoped_artifacts(identity, expected, paths=paths))
        if not reserve: raise ValueError('Supporting source changed before artifact reservation')
        try:
            for path, (_, body) in zip(paths, payloads):
                live = (self.repository.checkpoint(identity, job, changes={}, now_ms=self._now()) if job is not None
                        else self.repository._expected(self.repository.get_owned(identity), expected))
                if not live: raise ValueError('Supporting source changed before artifact write')
                self.database.upload_file_to_storage(body, path, identity['userId'], require_remote=True)
        except Exception:
            # This attempt has never reached publication; its unique paths have
            # no adopted descriptor. Leave metadata if cleanup itself fails.
            for path in paths: self.database.delete_file_from_storage(path, identity['userId'])
            raise
        # Transport failure here may follow a committed transaction: preserve
        # every reserved object and allow exact-version reads/recovery to decide.
        if job is not None:
            adopted = self.repository.publish(identity, job,
                manifest_version=descriptor if descriptor['versionKind'] == 'source' else None,
                report_version=descriptor if descriptor['versionKind'] == 'report' else None,
                checkpoint_version=descriptor if descriptor['versionKind'] == 'checkpoint' else None, now_ms=self._now())
        else:
            adopted = self.repository.publish_scoped_report(identity, expected, report_version=descriptor)
        if not adopted:
            for path in paths: self.database.delete_file_from_storage(path, identity['userId'])
            raise ValueError('Supporting publication was rejected after source changed')
        retained = self.repository.get_version(identity, descriptor['versionKind'], descriptor['revision'])
        for path in set(paths) - set(retained['supportingArtifactPaths']):
            self.database.delete_file_from_storage(path, identity['userId'])
        return retained

    def save_source(self, identity, job, original, manifest):
        manifest = validate_supporting_manifest(manifest)
        if manifest['identity'] != identity: raise ValueError('Manifest ownership or material identity differs')
        if not isinstance(original, bytes) or hashlib.sha256(original).hexdigest() != manifest['originalDigest']:
            raise ValueError('Preserved original digest differs')
        body = canonical_bytes(manifest)
        descriptor = {'versionKind': 'source', 'revision': manifest['sourceRevision'],
            'contentDigest': hashlib.sha256(body).hexdigest(), 'originalDigest': manifest['originalDigest'],
            'fileType': manifest['fileType'], 'unitCount': len(manifest['units']),
            'coverageComplete': manifest['coverage']['complete']}
        return self._store(identity, job, [('original.bin', original), ('manifest.json', body)], descriptor)

    def load_source(self, identity, source_revision=None):
        row = self.repository.get_owned(identity)
        revision = source_revision or (row.get('supportingAnalysis') or {}).get('sourceRevision')
        if not revision: raise ValueError('Prepare this supporting material first')
        version = self.repository.get_version(identity, 'source', revision)
        manifest = validate_supporting_manifest(json.loads(self._read(identity, version['manifestPath'], version['contentDigest'])))
        if manifest['identity'] != identity or manifest['sourceRevision'] != revision or manifest['originalDigest'] != version['originalDigest']:
            raise ValueError('Supporting manifest version differs')
        if source_revision is None and row.get('originalDigest') != manifest['originalDigest']:
            raise ValueError('Current original needs preparation')
        return manifest

    def original_bytes(self, identity, source_revision):
        self.load_source(identity, source_revision)
        version = self.repository.get_version(identity, 'source', source_revision)
        return self._read(identity, version['originalPath'], version['originalDigest'])

    def read_refs(self, identity, refs):
        if not isinstance(refs, list): raise ValueError('Invalid source references')
        manifests, result = {}, []
        for ref in refs:
            validate_ref(ref, supporting=True)
            if ref['kind'] != identity['kind'] or ref['materialId'] != identity['materialId']:
                raise ValueError('Supporting reference points to another material')
            revision = ref['sourceRevision']
            if revision not in manifests: manifests[revision] = self.load_source(identity, revision)
            unit = next((u for u in manifests[revision]['units'] if u['unitId'] == ref['unitId']), None)
            if unit is None: raise ValueError('Supporting unit is unavailable')
            result.append(deepcopy(unit))
        return result

    def render_reference(self, identity, ref):
        """Render an exact owned supporting unit from its immutable original."""
        unit = self.read_refs(identity, [ref])[0]
        manifest = self.load_source(identity, ref['sourceRevision'])
        if manifest['fileType'] == 'image':
            from src.utils.pdf_extract import image_to_image_uri
            rendered = [image_to_image_uri(self.original_bytes(identity, ref['sourceRevision']))]
        elif manifest['fileType'] in ('pdf', 'docx', 'pptx'):
            from src.utils.document_sources import render_source_unit
            rendered = render_source_unit(self.original_bytes(identity, ref['sourceRevision']),
                                          manifest['fileType'], unit['unitId'])
        else:
            rendered = []
        if len(rendered) != len(unit['visualAssets']):
            raise ValueError('Original supporting image asset count changed')
        return rendered

    def _report_payloads(self, identity, report, *, foundation_revision):
        report = validate_alignment_report(report)
        manifest = self.load_source(identity, report['sourceRevision'])
        refs = {u['unitId']: {**{k: identity[k] for k in ('kind', 'materialId')},
                             'sourceRevision': manifest['sourceRevision'], 'unitId': u['unitId']} for u in manifest['units']}
        units = {u['unitId']: u for u in manifest['units']}
        if report['extractionCoverage']['unitIds'] != [u['unitId'] for u in manifest['units']]:
            raise ValueError('Report omitted original units')
        if not set(manifest['coverage']['unresolvedUnitIds']) <= set(report['extractionCoverage']['unresolvedUnitIds']):
            raise ValueError('Report cannot hide unresolved original units')
        from src.services.document_library import DocumentLibrary
        from src.utils.course_foundation import foundation_material_revision
        from src.utils.source_contracts import validate_guide, guide_digest
        # Historical originals remain readable, but new evidence must use the
        # actual source/guide identities of its claimed whole foundation.
        current = self.database.get_course_documents(identity['courseId'], identity['userId'])
        if foundation_material_revision(current) != foundation_revision:
            raise ValueError('Report lecture foundation changed')
        current = {row['id']: row for row in current}
        documents = report['scopeSnapshot'].get('documents')
        if not isinstance(documents, list) or not documents:
            raise ValueError('Report lecture scope documents are missing')
        selected, available = set(), set()
        lecture_library = DocumentLibrary(self.database)
        for document in documents:
            doc_id = document.get('id')
            row = current.get(doc_id)
            if (doc_id in selected or row is None or any(document.get(key) != row.get(key)
                    for key in ('sourceRevision', 'guideRevision'))):
                raise ValueError('Report lecture source or guide differs from current foundation')
            selected.add(doc_id)
            original = lecture_library.load_manifest(identity['userId'], identity['courseId'], doc_id)
            guide = validate_guide(document.get('guide'), original)
            if guide_digest(guide) != row.get('guideRevision'):
                raise ValueError('Report lecture guide content differs')
            available.update(canonical_bytes({'documentId': doc_id, 'sourceRevision': original['sourceRevision'],
                                              'unitId': unit['unitId']}) for unit in original['units'])
        lecture_refs = report['scopeSnapshot']['allowedRefs']
        scope_revision = digest([{key: document[key] for key in ('id', 'sourceRevision', 'guideRevision')}
                                 for document in documents])
        if report['scopeSnapshot']['scopeRevision'] != scope_revision:
            raise ValueError('Report selected scope revision differs from its lecture identities')
        # Existing selection is whole documents, exactly as resolve_source_scope
        # and its complete-unit plan require; partial-document scopes need an
        # explicit future contract rather than silently narrowing this set.
        if ({ref['documentId'] for ref in lecture_refs} != selected
                or {canonical_bytes(ref) for ref in lecture_refs} != available):
            raise ValueError('Report lecture references differ from selected current sources')
        lecture_units = lecture_library.load_units(identity['userId'], identity['courseId'], lecture_refs)
        lectures = {canonical_bytes(ref): unit for ref, unit in zip(lecture_refs, lecture_units)}
        exact_lecture_units = {ref_key(ref): unit for ref, unit in zip(lecture_refs, lecture_units)}

        def validate_excluded_evidence(finding):
            envelope = finding.get('excludedLectureEvidence')
            if envelope is None:
                return
            if envelope['foundationRevision'] != foundation_revision:
                raise ValueError('Excluded lecture evidence belongs to another foundation')
            descriptors = {document['id']: document for document in envelope['documents']}
            if set(descriptors) & selected:
                raise ValueError('Excluded lecture evidence overlaps the selected scope')
            excluded_units = {}
            for doc_id, descriptor in descriptors.items():
                row = current.get(doc_id)
                if row is None or any(descriptor[key] != row.get(key)
                                      for key in ('sourceRevision', 'guideRevision')):
                    raise ValueError('Excluded lecture source or guide differs from current foundation')
                original = lecture_library.load_manifest(identity['userId'], identity['courseId'], doc_id)
                if original['sourceRevision'] != descriptor['sourceRevision']:
                    raise ValueError('Excluded lecture original differs from current foundation')
                for unit in original['units']:
                    ref = {'documentId': doc_id, 'sourceRevision': original['sourceRevision'],
                           'unitId': unit['unitId']}
                    excluded_units[ref_key(ref)] = unit
            supplied = validate_review_ledger({'allowedRefs': [entry['ref'] for entry in
                envelope['suppliedEvidence']], 'suppliedEvidence': envelope['suppliedEvidence'],
                'excludedBlankRefs': [], 'checkState': 'complete'})
            for entry in envelope['suppliedEvidence']:
                ref = entry['ref']
                if ref['documentId'] not in descriptors:
                    raise ValueError('Excluded supplied evidence is outside its document envelope')
                unit = excluded_units.get(ref_key(ref))
                if unit is None:
                    raise ValueError('Excluded supplied evidence is unavailable in the owned original')
                for part in entry['ranges']:
                    if part['end'] > len(unit.get(part['textField'], '')):
                        raise ValueError('Excluded supplied interval exceeds the owned original')
                actual_assets = {asset['assetId'] for asset in unit['visualAssets']}
                if any(asset not in actual_assets for asset in entry['assetIds']):
                    raise ValueError('Excluded supplied image is absent from the owned original')
            for proof in envelope['proofs']:
                unit = excluded_units.get(ref_key(proof['ref']))
                if unit is None:
                    raise ValueError('Excluded proof is unavailable in the owned original')
                validate_source_proof(proof, ref=proof['ref'], unit=unit)
                proof_in_supplied(proof, supplied)

        for alignment in report['alignments']:
            for finding in alignment['requirements']:
                validate_review_ledger(finding['reviewCoverage'], units=exact_lecture_units)
                for proof in finding['lectureSupportProofs']:
                    unit = lectures.get(canonical_bytes(proof['ref']))
                    if unit is None: raise ValueError('Lecture evidence is unavailable in the owned selected scope')
                    validate_source_proof(proof, ref=proof['ref'], unit=unit)
                for proof in finding['supportingSourceProofs']:
                    unit_id = proof['ref']['unitId']
                    if unit_id not in units: raise ValueError('Report cites an unavailable original unit')
                    validate_source_proof(proof, ref=refs[unit_id], unit=units[unit_id])
                validate_excluded_evidence(finding)
            for dependency in alignment['contextDependencies']:
                validate_review_ledger(dependency['reviewCoverage'], units=exact_lecture_units)
                for proof in dependency['lectureSupportProofs']:
                    unit = lectures.get(canonical_bytes(proof['ref']))
                    if unit is None: raise ValueError('Context lecture proof is outside selected originals')
                    validate_source_proof(proof, ref=proof['ref'], unit=unit)
                for proof in dependency['supportingSourceProofs']:
                    unit_id = proof['ref']['unitId']
                    if unit_id not in units: raise ValueError('Context source proof is unavailable')
                    validate_source_proof(proof, ref=refs[unit_id], unit=units[unit_id])
        for topic in report['topics']:
            finding = topic.get('alignment')
            if finding is None:
                continue
            validate_review_ledger(finding['reviewCoverage'], units=exact_lecture_units)
            for proof in finding['lectureSupportProofs']:
                unit = lectures.get(canonical_bytes(proof['ref']))
                if unit is None: raise ValueError('Topic lecture proof is outside selected originals')
                validate_source_proof(proof, ref=proof['ref'], unit=unit)
            for proof in finding['supportingSourceProofs']:
                unit_id = proof['ref']['unitId']
                if unit_id not in units: raise ValueError('Topic source proof is unavailable')
                validate_source_proof(proof, ref=refs[unit_id], unit=units[unit_id])
            validate_excluded_evidence(finding)
        header = {k: v for k, v in report.items() if k not in REPORT_ARRAYS}
        header_bytes = canonical_bytes({'foundationRevision': foundation_revision, 'report': header})
        if len(header_bytes) > MAX_REPORT_CHUNK_BYTES: raise ValueError('Report metadata is too large; split selected sources')
        chunks, pending = [], []
        for kind in REPORT_ARRAYS:
            for item in report[kind]:
                entry = {'collection': kind, 'value': item}
                if len(canonical_bytes([entry])) > MAX_REPORT_CHUNK_BYTES:
                    raise ValueError('A report item is too large; split the source and retry')
                if pending and (len(pending) >= MAX_REPORT_CHUNK_ITEMS or len(canonical_bytes([*pending, entry])) > MAX_REPORT_CHUNK_BYTES):
                    chunks.append(canonical_bytes(pending))
                    pending = []
                pending.append(entry)
        if pending: chunks.append(canonical_bytes(pending))
        revision = digest({'foundationRevision': foundation_revision, 'report': report})
        descriptor = {'versionKind': 'report', 'revision': revision, 'contentDigest': revision,
            'foundationRevision': foundation_revision,
            'sourceRevision': report['sourceRevision'], 'scopeRevision': report['scopeSnapshot']['scopeRevision'],
            'coverageComplete': report['extractionCoverage']['complete'] and report['alignmentCoverage']['complete'],
            'headerDigest': hashlib.sha256(header_bytes).hexdigest(), 'itemCount': len(report['items']),
            'chunks': [{'digest': hashlib.sha256(body).hexdigest(), 'count': len(json.loads(body))} for body in chunks]}
        payloads = [('report.json', header_bytes), *[(f'part-{i}.json', body) for i, body in enumerate(chunks)]]
        return payloads, descriptor

    def save_report(self, identity, job, report):
        payloads, descriptor = self._report_payloads(identity, report, foundation_revision=job['foundationRevision'])
        return self._store(identity, job, payloads, descriptor)

    def save_checkpoint(self, identity, job, data):
        bindings = {key: job[key] for key in ('inputRevision', 'sourceDigest', 'foundationRevision')}
        body = canonical_bytes({**bindings, 'data': data})
        parts = [body[start:start+MAX_REPORT_CHUNK_BYTES] for start in range(0, len(body), MAX_REPORT_CHUNK_BYTES)]
        header = canonical_bytes({'encoding': 'json-utf8', 'byteLength': len(body)})
        revision = hashlib.sha256(body).hexdigest()
        descriptor = {**bindings, 'versionKind': 'checkpoint', 'revision': revision, 'contentDigest': revision,
            'coverageComplete': False, 'headerDigest': hashlib.sha256(header).hexdigest(),
            'chunks': [{'digest': hashlib.sha256(part).hexdigest(), 'count': len(part)} for part in parts]}
        payloads = [('checkpoint.json', header), *[(f'part-{i}.json', part) for i, part in enumerate(parts)]]
        return self._store(identity, job, payloads, descriptor)

    def load_checkpoint(self, identity, revision):
        version = self.repository.get_version(identity, 'checkpoint', revision)
        row = self.repository.get_owned(identity)
        job = row.get('processingJob') or {}
        if any(version.get(key) != job.get(key) for key in ('inputRevision', 'sourceDigest', 'foundationRevision')):
            raise ValueError('Checkpoint belongs to a different source or foundation')
        header = json.loads(self._read(identity, version['headerPath'], version['headerDigest']))
        body = b''.join(self._read(identity, chunk['path'], chunk['digest']) for chunk in version['chunks'])
        if len(body) != header['byteLength'] or hashlib.sha256(body).hexdigest() != version['contentDigest']:
            raise ValueError('Checkpoint content changed')
        envelope = json.loads(body)
        if any(envelope.get(key) != job.get(key) for key in ('inputRevision', 'sourceDigest', 'foundationRevision')):
            raise ValueError('Checkpoint identity differs')
        return envelope['data']

    def save_scoped_report(self, identity, expected, report):
        if report.get('sourceRevision') != expected.get('sourceRevision'): raise ValueError('Scoped report source differs')
        row = self.repository.get_owned(identity)
        if not self.repository._expected(row, expected): raise ValueError('Scoped analysis changed')
        payloads, descriptor = self._report_payloads(identity, report,
            foundation_revision=row['processingJob']['foundationRevision'])
        return self._store(identity, None, payloads, descriptor, expected=expected)

    def load_report(self, identity, report_revision=None):
        row = self.repository.get_owned(identity)
        revision = report_revision or (row.get('supportingAnalysis') or {}).get('reportRevision')
        if not revision: raise ValueError('Supporting evidence report is not ready')
        version = self.repository.get_version(identity, 'report', revision)
        envelope = json.loads(self._read(identity, version['headerPath'], version['headerDigest']))
        if 'foundationRevision' in version:
            if envelope.get('foundationRevision') != version['foundationRevision']:
                raise ValueError('Report foundation binding differs')
            report = envelope['report']
        else:
            # Pre-binding versions remain owned immutable reads; snapshot
            # authorization rejects their missing foundation descriptor.
            report = envelope
        report.update({key: [] for key in REPORT_ARRAYS})
        for chunk in version['chunks']:
            rows = json.loads(self._read(identity, chunk['path'], chunk['digest']))
            if len(rows) != chunk['count']: raise ValueError('Report chunk count differs')
            for row in rows:
                if row['collection'] not in REPORT_ARRAYS: raise ValueError('Unknown report content')
                report[row['collection']].append(row['value'])
        if digest(envelope) != version['contentDigest'] or digest(envelope) != revision:
            raise ValueError('Report content revision differs')
        checked = validate_alignment_report(report)
        if (checked['sourceRevision'] != version['sourceRevision']
                or checked['scopeSnapshot']['scopeRevision'] != version['scopeRevision']):
            raise ValueError('Report source or scope revision differs')
        return checked

    def public_status(self, identity):
        row = self.repository.get_owned(identity)
        analysis, job = row.get('supportingAnalysis') or {}, row.get('processingJob') or {}
        return {'materialId': identity['materialId'], 'kind': identity['kind'], 'status': analysis.get('state', 'legacy'),
            'stage': job.get('stage'), 'cursor': deepcopy(job.get('cursor')), 'error': row.get('error'),
            'sourceRevision': analysis.get('sourceRevision'), 'reportRevision': analysis.get('reportRevision'),
            'analysisId': analysis.get('analysisId'), 'scopeRevision': analysis.get('scopeRevision')}

    def report_page(self, identity, *, report_revision, offset=0, limit=50):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid report page')
        report = self.load_report(identity, report_revision)
        items = report['items'][offset:offset+limit]
        ids = {item['id'] for item in items}
        contexts = {key for item in items for key in item['sharedContextIds']}
        return {'reportRevision': report_revision, 'items': items, 'total': len(report['items']),
            'offset': offset, 'limit': limit, 'nextOffset': offset+limit if offset+limit < len(report['items']) else None,
            'alignments': [a for a in report['alignments'] if a['itemId'] in ids],
            'sharedContexts': [c for c in report['sharedContexts'] if c['id'] in contexts],
            'papers': report['papers'], 'topics': report['topics'], 'scopeSnapshot': report['scopeSnapshot'],
            'extractionCoverage': report['extractionCoverage'], 'alignmentCoverage': report['alignmentCoverage']}
