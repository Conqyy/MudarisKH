"""Coherent source artifacts for workflow tests; foundation guards remain real."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile

from docx import Document
from src.utils.course_foundation import build_foundation_status
from src.utils.document_sources import extract_source_units
from src.utils.source_contracts import build_source_manifest, guide_digest, guide_to_legacy_analysis
from src.utils.storage_paths import build_document_artifact_path


def lecture_document(identity='doc', topic='Limits', **overrides):
    owner, course = overrides.get('userId', 'owner'), overrides.get('courseId', 'course')
    office = Document()
    office.add_paragraph(f'Lecture material about {topic}.')
    stream = BytesIO()
    office.save(stream)
    raw = stream.getvalue()
    digest = sha256(raw).hexdigest()
    manifest = build_source_manifest(identity, digest, 'docx', extract_source_units(raw, 'docx'))
    ids = manifest['coverage']['readableUnitIds']
    guide = {'version': 1, 'sourceRevision': manifest['sourceRevision'],
             'sections': [{'label': topic, 'purpose': f'Understand {topic}', 'unitIds': ids}],
             'concepts': [{'name': topic, 'unitIds': ids}], 'visualReferences': [], 'warnings': [],
             'unitCoverage': deepcopy(manifest['coverage'])}
    original_path = f'documents/{owner}/{course}/{identity}.docx'
    exact = build_document_artifact_path(owner, course, identity, 'a'*32, 'b'*32, 'c'*32, 'original.docx')
    path = build_document_artifact_path(owner, course, identity, 'a'*32, 'b'*32, 'c'*32, 'manifest.json')
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    root = Path(tempfile.mkdtemp(prefix='foundation-fixture-'))
    artifact_files = {}
    for index, (name, content) in enumerate(((original_path, raw), (exact, raw), (path, body))):
        file = root / str(index)
        file.write_bytes(content)
        artifact_files[name] = file
    version = {'manifestPath': path, 'manifestDigest': sha256(body).hexdigest(), 'originalPath': exact,
               'originalDigest': digest, 'fileType': 'docx', 'unitCount': manifest['unitCount'], 'coverageComplete': True}
    return {'id': identity, 'userId': owner, 'courseId': course, 'title': topic, 'status': 'completed',
            'fileType': 'docx', 'storagePath': original_path, 'originalDigest': digest,
            'sourceRevision': manifest['sourceRevision'], 'sourceVersions': {manifest['sourceRevision']: version},
            'guide': guide, 'guideRevision': guide_digest(guide), 'analysis': guide_to_legacy_analysis(guide),
            'preparationStatus': 'completed', 'guideStatus': 'completed', 'unitCount': manifest['unitCount'],
            'processingJob': {'id': 'a'*32, 'stage': 'completed'},
            '_sourceManifest': manifest, '_sourceArtifactsValid': True, '_artifactFiles': artifact_files,
            **deepcopy(overrides)}


def install_source_artifacts(db, documents):
    def owned(owner, course, identity):
        rows = [row for row in documents if row.get('id') == identity and row.get('userId') == owner and row.get('courseId') == course]
        if not rows: raise ValueError('Missing owned document')
        return rows[0]
    def download(path, user_id=None):
        for row in documents:
            if row.get('userId') == user_id and path in row.get('_artifactFiles', {}):
                return row['_artifactFiles'][path]
        raise FileNotFoundError(path)
    db.get_owned_document.side_effect = owned
    db.download_file_from_storage.side_effect = download
    db.get_course_documents.return_value = documents


def confirm_lecture_foundation(db, documents=None, *, course_id='course', owner='owner'):
    course = db.get_owned_course.return_value
    course = dict(course) if isinstance(course, dict) else {}
    course.update({'id': course_id, 'userId': owner})
    course.setdefault('title', 'Course')
    if documents is None:
        documents = [lecture_document(courseId=course_id, userId=owner)]
    owned_documents = [row for row in documents if row.get('userId') == owner and row.get('courseId') == course_id]
    foundation = build_foundation_status(owned_documents)
    assert foundation['state'] == 'confirmation_required', 'Fixture must provide complete prepared sources and guides'
    db.get_document_foundation.return_value = {'userId': owner, 'courseId': course_id, 'revision': foundation['revision']}
    db.get_owned_course.return_value = course
    db._flat_get.return_value = course
    install_source_artifacts(db, documents)
    return owned_documents


def source_refs(documents):
    return [{'documentId': d['id'], 'sourceRevision': d['sourceRevision'], 'unitId': u['unitId']}
            for d in documents for u in d['_sourceManifest']['units'] if not u['blank']]


def stub_source_provider(monkeypatch):
    """External semantic provider seam for existing API routing/race tests only."""
    from types import SimpleNamespace
    def provider(client, **kwargs):
        packet = json.loads(kwargs['messages'][1]['content'][0]['text'])
        policy = kwargs['messages'][0]['content']
        refs = [e['ref'] for e in packet['evidence'] if e['ranges']]
        if 'supportedSpans' in policy:
            text = packet['task']['text']
            result = {'supportedSpans': [{'start': 0, 'end': len(text), 'text': text, 'reason': 'Synthetic fixture support'}]}
        elif 'Independently check' in policy:
            result = {'supports': True, 'reason': 'Synthetic fixture support'}
        elif '"proofs"' in policy:
            result = {'proofs': [{**r, 'ref': e['ref'], 'relation': 'supports_topic', 'reason': 'Synthetic topic support'}
                                  for e in packet['evidence'] for r in e['ranges']]}
        else:
            result = {'facts': [{'text': 'Synthetic fixture fact', 'sourceRefs': refs}], 'administrativeRefs': []}
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(result)))])
    monkeypatch.setattr('src.services.source_evidence.chat_with_retry', provider)
