"""Prepare immutable recording and typed-note evidence for supporting extraction."""
import hashlib
from copy import deepcopy

from src.supporting.contracts import (source_coverage, supporting_revision,
    validate_identity, validate_supporting_manifest)
from src.supporting.extraction import SupportingExtractor


def _manifest(identity, original_digest, file_type, units):
    return validate_supporting_manifest({
        'version': 1, 'identity': identity, 'originalDigest': original_digest,
        'extractorVersion': 1, 'sourceRevision': supporting_revision(original_digest, units),
        'fileType': file_type, 'units': units, 'coverage': source_coverage(units),
    })


def build_notes_manifest(identity, notes: str):
    identity = validate_identity(identity)
    if identity['kind'] != 'notes' or not isinstance(notes, str) or not notes.strip():
        raise ValueError('Nonempty original typed notes and notes identity are required')
    unit = {'unitId': 'n0001', 'position': 1, 'kind': 'notes', 'text': notes,
            'visualText': '', 'visualAssets': [], 'disposition': 'readable', 'timing': None}
    return _manifest(identity, hashlib.sha256(notes.encode('utf-8')).hexdigest(), 'notes', [unit])


def build_audio_manifest(identity, *, original_digest: str, transcript: dict):
    identity = validate_identity(identity)
    if identity['kind'] != 'audio' or not isinstance(transcript, dict):
        raise ValueError('Recording identity and structured transcript are required')
    segments, coverage = transcript.get('segments'), transcript.get('coverage')
    if not isinstance(segments, list) or not segments or not isinstance(coverage, dict):
        raise ValueError('Transcript segments and chunk coverage are required')
    chunk_ids = coverage.get('chunkIds')
    accounted = coverage.get('accountedChunkIds')
    unresolved = coverage.get('unresolvedChunkIds')
    if (not isinstance(chunk_ids, list) or not chunk_ids or len(set(chunk_ids)) != len(chunk_ids)
            or not isinstance(accounted, list) or set(accounted) != set(chunk_ids)
            or not isinstance(unresolved, list) or not set(unresolved) <= set(chunk_ids)
            or type(coverage.get('complete')) is not bool):
        raise ValueError('Incomplete or invalid transcript chunk coverage')
    units = []
    for position, segment in enumerate(segments, 1):
        if not isinstance(segment, dict) or not isinstance(segment.get('text'), str):
            raise ValueError('Invalid raw transcript segment')
        chunk_id = segment.get('chunkId')
        if not isinstance(chunk_id, str) or chunk_id not in chunk_ids:
            raise ValueError('Transcript segment has no accounted chunk')
        disposition = segment.get('disposition')
        if disposition not in ('readable', 'blank', 'nonacademic', 'uncertain', 'unsupported'):
            raise ValueError('Invalid transcript segment outcome')
        if not segment['text'].strip() and disposition != 'uncertain':
            raise ValueError('Empty provider text requires uncertain speech coverage')
        units.append({'unitId': f'a{position:06d}', 'position': position, 'kind': 'transcript',
            'chunkId': chunk_id, 'text': segment['text'], 'visualText': '', 'visualAssets': [],
            'disposition': disposition, 'timing': deepcopy(segment.get('timing'))})
    if set(chunk_ids) != {unit['chunkId'] for unit in units}:
        raise ValueError('Transcript omitted a chunk outcome')
    actual_timing_available = all(unit['timing'] is not None for unit in units if unit['text'])
    if type(transcript.get('timingAvailable')) is not bool or transcript['timingAvailable'] != actual_timing_available:
        raise ValueError('Transcript timing availability conflicts with provider segments')
    expected_unresolved = {unit['chunkId'] for unit in units if unit['disposition'] in ('uncertain', 'unsupported')}
    if set(unresolved) != expected_unresolved or coverage['complete'] != (not expected_unresolved):
        raise ValueError('Incomplete transcript coverage cannot be marked complete')
    return _manifest(identity, original_digest, 'audio', units)


def extract_teaching_items(manifest, *, client, model, lecture_reader, checkpoint,
                           course_title='', resume=None, model_call_budget=512, model_calls=None):
    manifest = validate_supporting_manifest(manifest)
    if manifest['identity']['kind'] not in ('audio', 'notes'):
        raise ValueError('Teaching extraction requires audio or typed notes')
    return SupportingExtractor(client, model).extract(manifest, course_title=course_title,
        lecture_reader=lecture_reader, render=lambda unit: [], checkpoint=checkpoint,
        resume=resume, model_call_budget=model_call_budget, model_calls=model_calls)
