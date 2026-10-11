"""Canonical source and guide contracts."""
from copy import deepcopy
import hashlib
import json
import re

SOURCE_VERSION = 1
GUIDE_VERSION = 1
PREPARATION_VERSION = 1
MAX_SOURCE_UNITS = 160
MAX_SOURCE_CHARACTERS = 600_000
FILE_TYPES = {'pdf': ('p', 'page'), 'pptx': ('s', 'slide'), 'docx': ('b', 'block')}
VISUAL_READ_STATUSES = frozenset({'not_required', 'pending', 'readable', 'uncertain', 'unsupported'})


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Source content must be JSON-safe') from exc


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _string(value, name, nonempty=True):
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError(f'Invalid {name}')
    return value


def _strings(value, name):
    if not isinstance(value, list):
        raise ValueError(f'Invalid {name}')
    for item in value:
        _string(item, name)
    return value


def _units(units, file_type):
    if file_type not in FILE_TYPES or not isinstance(units, list) or not units:
        raise ValueError('Source requires units and a supported file type')
    if file_type != 'docx' and len(units) > MAX_SOURCE_UNITS:
        raise ValueError('Split the file: maximum 160 pages/slides per source')
    prefix, kind = FILE_TYPES[file_type]
    count = 0
    for position, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            raise ValueError('Invalid source unit')
        if (unit.get('unitId') != f'{prefix}{position:04d}' or unit.get('kind') != kind
                or type(unit.get('position')) is not int or unit['position'] != position):
            raise ValueError('Invalid, duplicate, missing or unordered source unit')
        _string(unit.get('label'), 'unit label')
        count += len(_string(unit.get('text'), 'unit text', False))
        count += len(_string(unit.get('visualText', ''), 'visual text', False))
        _strings(unit.get('warnings'), 'unit warnings')
        if type(unit.get('blank')) is not bool or type(unit.get('needsVisualRead')) is not bool:
            raise ValueError('Invalid blank/visual state')
        assets = unit.get('visualAssets')
        if not isinstance(assets, list) or any(not isinstance(a, dict) for a in assets):
            raise ValueError('Invalid visual assets')
        if assets and not unit['needsVisualRead']:
            raise ValueError('Embedded visual content requires visual reading')
        asset_ids = set()
        for asset in assets:
            asset_id = _string(asset.get('assetId'), 'asset ID')
            if asset_id in asset_ids:
                raise ValueError('Duplicate visual asset')
            asset_ids.add(asset_id)
            _string(asset.get('kind'), 'asset kind')
            _string(asset.get('mimeType'), 'asset MIME type')
            if file_type != 'pdf':
                _string(asset.get('relationshipId'), 'embedded image relationship')
        status = unit.get('visualReadStatus', 'pending' if unit['needsVisualRead'] else 'not_required')
        if status not in VISUAL_READ_STATUSES:
            raise ValueError('Invalid visual read status')
        if unit['blank'] and (unit['text'].strip() or unit.get('visualText', '').strip() or assets or unit['needsVisualRead'] or unit['warnings']):
            raise ValueError('Content cannot be claimed blank')
        if unit['needsVisualRead'] and status == 'not_required':
            raise ValueError('Required visual content cannot be skipped')
        if status == 'readable' and not unit.get('visualText', '').strip():
            raise ValueError('Readable visual requires extracted visual text')
    if count > MAX_SOURCE_CHARACTERS:
        raise ValueError('Split the file: maximum 600,000 extracted characters per source')
    _canonical(units)
    return units


def source_coverage(units):
    """Compute complete accounting; pending visuals never pass readiness."""
    coverage = {'unitIds': [], 'readableUnitIds': [], 'blankUnitIds': [], 'unresolvedUnitIds': [], 'complete': False}
    for unit in units:
        uid = unit['unitId']
        coverage['unitIds'].append(uid)
        status = unit.get('visualReadStatus', 'pending' if unit['needsVisualRead'] else 'not_required')
        if unit['blank']:
            bucket = 'blankUnitIds'
        elif status in ('pending', 'uncertain', 'unsupported') or (not unit['text'].strip() and not unit.get('visualText', '').strip()):
            bucket = 'unresolvedUnitIds'
        else:
            bucket = 'readableUnitIds'
        coverage[bucket].append(uid)
    coverage['complete'] = bool(units) and not coverage['unresolvedUnitIds']
    return coverage


def build_source_manifest(document_id, original_digest, file_type, units):
    """Build a stable identity from the complete prepared original, not guide labels."""
    _units(units, file_type)
    manifest = {'version': SOURCE_VERSION, 'documentId': document_id,
                'originalDigest': original_digest, 'fileType': file_type,
                'unitCount': len(units), 'units': deepcopy(units),
                'coverage': source_coverage(units),
                'warnings': list(dict.fromkeys(w for u in units for w in u['warnings']))}
    manifest['sourceRevision'] = _source_revision(manifest)
    return validate_manifest(manifest)


def _source_revision(manifest):
    return _digest({'originalDigest': manifest['originalDigest'], 'preparationVersion': PREPARATION_VERSION,
                    'fileType': manifest['fileType'], 'units': manifest['units']})


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or type(manifest.get('version')) is not int or manifest['version'] != SOURCE_VERSION:
        raise ValueError('Invalid source manifest version')
    _string(manifest.get('documentId'), 'document ID')
    if not isinstance(manifest.get('originalDigest'), str) or not re.fullmatch(r'[0-9a-f]{64}', manifest['originalDigest']):
        raise ValueError('Invalid original digest')
    units = _units(manifest.get('units'), manifest.get('fileType'))
    if type(manifest.get('unitCount')) is not int or manifest['unitCount'] != len(units):
        raise ValueError('Missing source units')
    if manifest.get('coverage') != source_coverage(units):
        raise ValueError('Source coverage contradicts complete units')
    _strings(manifest.get('warnings'), 'manifest warnings')
    if manifest.get('sourceRevision') != _source_revision(manifest):
        raise ValueError('Source revision does not match original and prepared units')
    _canonical(manifest)
    return deepcopy(manifest)


def validate_guide(guide, manifest):
    manifest = validate_manifest(manifest)
    if not manifest['coverage']['complete'] or not manifest['coverage']['readableUnitIds']:
        raise ValueError('Source is blank or has unresolved preparation coverage')
    if not isinstance(guide, dict) or type(guide.get('version')) is not int or guide['version'] != GUIDE_VERSION:
        raise ValueError('Invalid guide version')
    if guide.get('sourceRevision') != manifest['sourceRevision']:
        raise ValueError('Guide references a different source revision')
    allowed = set(manifest['coverage']['unitIds'])
    for key, fields in [('sections', ('label', 'purpose')), ('concepts', ('name',)), ('visualReferences', ('kind', 'label'))]:
        rows = guide.get(key)
        if not isinstance(rows, list):
            raise ValueError(f'Invalid guide {key}')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f'Invalid guide {key} row')
            for field in fields:
                _string(row.get(field), field)
            refs = _strings(row.get('unitIds'), 'guide unit references')
            if not refs or len(set(refs)) != len(refs) or not set(refs) <= allowed:
                raise ValueError('Invented, duplicate or empty guide references')
    if not guide['sections'] and not guide['concepts']:
        raise ValueError('Guide requires a supported academic section or concept')
    readable = set(manifest['coverage']['readableUnitIds'])
    if not any(readable.intersection(row['unitIds']) for row in guide['sections'] + guide['concepts']):
        raise ValueError('Academic guide references must include readable source content')
    _strings(guide.get('warnings'), 'guide warnings')
    coverage = manifest['coverage']
    if 'unitCoverage' in guide and guide['unitCoverage'] != coverage:
        raise ValueError('Guide coverage contradicts source units')
    result = deepcopy(guide)
    result['unitCoverage'] = deepcopy(coverage)
    _canonical(result)
    return result


def guide_digest(guide):
    return _digest(guide)


def validate_source_reference(reference, manifest):
    """Match an evidence location after the library checks owner/course access."""
    manifest = validate_manifest(manifest)
    if (not isinstance(reference, dict) or set(reference) != {'documentId', 'sourceRevision', 'unitId'}
            or reference.get('documentId') != manifest['documentId']
            or reference.get('sourceRevision') != manifest['sourceRevision']
            or reference.get('unitId') not in manifest['coverage']['unitIds']):
        raise ValueError('Citation is outside the document version and source locations')
    return deepcopy(reference)


def guide_to_legacy_analysis(guide):
    return {'topics': list(dict.fromkeys(c['name'] for c in guide['concepts'])),
            'chapterMapping': [{'chapter': s['label'], 'content': s['purpose']} for s in guide['sections']],
            'keyConceptCount': len(guide['concepts']), 'definitions': [], 'formulas': []}
