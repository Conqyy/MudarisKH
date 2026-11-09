"""Immutable original preparation and complete, bounded evidence windows."""
from copy import copy, deepcopy
import hashlib
from io import BytesIO

from PIL import Image

from src.supporting.contracts import (canonical_bytes, source_coverage, supporting_revision,
    validate_identity, validate_supporting_manifest, MAX_IMAGES_PER_CALL, MAX_TEXT_PER_CALL)
from src.utils.document_sources import extract_source_units
from src.utils.pdf_extract import image_to_image_uri
from src.utils.source_context import build_source_plan, navigation_guides


def prepare_pages(identity, original, file_type):
    identity = validate_identity(identity)
    if not isinstance(original, bytes) or not original:
        raise ValueError('Original supporting bytes are required')
    if not isinstance(file_type, str):
        raise ValueError('Unsupported original file type')
    file_type = file_type.lower().lstrip('.')
    if file_type in ('png', 'jpg', 'jpeg', 'webp'):
        file_type = 'image'
    if identity['kind'] not in ('historical_exam', 'tutorial') or file_type not in (
            ('pdf', 'image') if identity['kind'] == 'historical_exam' else ('pdf', 'image', 'docx', 'pptx')):
        raise ValueError('File type conflicts with supporting material')
    if file_type == 'image':
        with Image.open(BytesIO(original)) as image:
            if getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Multiple image frames are unsupported; convert every frame to PDF')
        image_to_image_uri(original)  # validates and applies the same normalized image reader
        source = [{'unitId': 'i0001', 'position': 1, 'kind': 'image', 'text': '',
                   'visualAssets': [{'assetId': 'i0001-image', 'kind': 'image', 'mimeType': 'image/png'}]}]
    else:
        source = extract_source_units(original, file_type)
    units = []
    for entry in source:
        if entry.get('warnings') or entry.get('visualReadStatus') == 'unsupported':
            raise ValueError('Unsupported Office content; convert the original to PDF to preserve all content')
        assets = deepcopy(entry['visualAssets'])
        if file_type == 'pdf':
            assets = [{'assetId': entry['unitId'] + '-page', 'kind': 'page', 'mimeType': 'image/png', 'unitId': entry['unitId']}]
        for asset in assets:
            asset['mimeType'] = 'image/png'  # render_source_unit normalizes all embedded images
        units.append({k: entry[k] for k in ('unitId', 'position', 'kind', 'text')} | {
            'visualText': '', 'visualAssets': assets, 'timing': None,
            'disposition': 'readable' if entry['text'].strip() or assets else 'blank'})
    original_digest = hashlib.sha256(original).hexdigest()
    return validate_supporting_manifest({'version': 1, 'identity': identity, 'originalDigest': original_digest,
        'extractorVersion': 1, 'sourceRevision': supporting_revision(original_digest, units),
        'fileType': file_type, 'units': units, 'coverage': source_coverage(units)})


def reference(manifest, unit):
    return {k: manifest['identity'][k] for k in ('kind', 'materialId')} | {
        'sourceRevision': manifest['sourceRevision'], 'unitId': unit['unitId']}


def _navigation_guides(reader, batch):
    """Select complete guide rows for supplied units; never redefine lecture scope."""
    return navigation_guides(reader.guide, batch)


def lecture_context(reader, query, *, text_budget, image_budget):
    """No-provider bridge to SourceEvidence's original planning/materialization.

    A shallow reader copy replans within the actual remaining request budget;
    the caller's scope, guide, budgets and successful-read ledger never change.
    Guide rows are selected intact for the supplied original units. This is partial
    navigation only. Task 5 can replace the private planning/materialization seam.
    """
    navigation = copy(reader)
    navigation.text_budget, navigation.image_budget = text_budget - 40, image_budget
    navigation.guide = []

    def planned():
        # This bridge already reserves the enclosing extraction policy/schema.
        # Reserve the actual packet additions instead of SourceEvidence._plan's
        # extra 1,000-character general-purpose request-wrapper allowance.
        reserved = len(canonical_bytes(navigation.guide).decode('utf-8')) - 2 + len(',"navigationView":"partial"')
        candidates = build_source_plan(navigation.scope, 'focused', query=query,
            text_budget=navigation.text_budget - reserved, image_budget=navigation.image_budget)
        if not candidates:
            candidates = build_source_plan(navigation.scope, 'summary',
                text_budget=navigation.text_budget - reserved, image_budget=navigation.image_budget)
        return next((p for p in candidates if any(e['disposition'] != 'excluded_blank' for e in p['evidence'])), None)

    batch = planned()
    if batch is None:
        raise ValueError('Prepared lecture guide and original context are required')
    navigation.guide = _navigation_guides(reader, batch)
    # Captions are real request text. Reserve their exact metadata before
    # packing the selected lecture context, which is navigation only.
    navigation.text_budget -= image_caption_size({'lectureNavigation': batch})
    batch = planned()  # reserve selected guide bytes before packing original ranges
    if batch is None:
        raise ValueError('No bounded original lecture context is available')
    navigation.guide = _navigation_guides(reader, batch)
    packet = deepcopy(navigation._materialize(batch))
    packet['navigationView'] = 'partial'
    packet['coverage']['complete'], packet['coverage']['mode'] = False, 'partial'
    images = packet.pop('imageParts', [])
    if not packet.get('guide') or not packet.get('evidence'):
        raise ValueError('Prepared lecture guide and original context are required')
    captions = image_role_captions({'lectureNavigation': packet})
    if len(captions) != len(images):
        raise ValueError('Lecture image count differs from its original asset metadata')
    if len(images) > image_budget or len(canonical_bytes(packet).decode('utf-8')) + sum(map(len, captions)) > text_budget:
        raise ValueError('Indivisible lecture guide/metadata exceeds available request bounds; split or simplify the source guide')
    if any(p.get('type') != 'image_url' or not str(p.get('image_url', {}).get('url', '')).startswith('data:image/') for p in images):
        raise ValueError('Lecture original image is unavailable')
    return packet, images


def source_plan(manifest, lecture_images):
    """Every original character and asset exactly once; preceding evidence is extra.

    Windows intentionally stay small enough for continuity, schema, and a bounded
    guide. The final serialized request is still checked including all metadata.
    """
    plan = []
    image_capacity = MAX_IMAGES_PER_CALL - lecture_images - 1
    for unit in manifest['units']:
        ranges = [{'field': field, 'start': start, 'end': min(start + 4000, len(unit[field])),
                   'text': unit[field][start:start+4000]} for field in ('text', 'visualText')
                  for start in range(0, len(unit[field]), 4000)]
        assets = [a['assetId'] for a in unit['visualAssets']]
        images = [assets[i:i+image_capacity] for i in range(0, len(assets), image_capacity)]
        for index in range(max(1, len(ranges), len(images))):
            plan.append({'ref': reference(manifest, unit), 'kind': unit['kind'], 'position': unit['position'],
                         'ranges': ranges[index:index+1], 'assetIds': images[index] if index < len(images) else []})
    return plan


def previous_evidence(plan, cursor):
    if not cursor:
        return None
    previous = deepcopy(plan[cursor-1])
    # Retain an earlier original image even if an intervening long text range
    # had no image; unit identity remains explicit.
    if not previous['assetIds']:
        for earlier in reversed(plan[:cursor]):
            if earlier['ref'] == previous['ref'] and earlier['assetIds']:
                previous['assetIds'] = [earlier['assetIds'][-1]]
                break
    else:
        previous['assetIds'] = [previous['assetIds'][-1]]
    return previous


def materialize(manifest, records, render):
    units = {u['unitId']: u for u in manifest['units']}
    parts, cache = [], {}
    for record in records:
        if not record:
            continue
        unit = units[record['ref']['unitId']]
        if record['assetIds'] and unit['unitId'] not in cache:
            uris = render(deepcopy(unit))
            if (not isinstance(uris, list) or len(uris) != len(unit['visualAssets']) or
                    any(not isinstance(uri, str) or not uri.startswith('data:image/') for uri in uris)):
                raise ValueError('Original renderer omitted or changed source assets')
            cache[unit['unitId']] = dict(zip((a['assetId'] for a in unit['visualAssets']), uris))
        for asset in record['assetIds']:
            parts.append({'type': 'image_url', 'image_url': {'url': cache[unit['unitId']][asset]}})
    return parts


def image_role_captions(envelope):
    """Match materialize's previous/current order, then lecture image order."""
    captions = []

    def add(role, ref, asset, instruction):
        if not isinstance(asset, str) or not asset or not isinstance(ref, (dict, str)):
            raise ValueError('Original image role is missing its exact source/asset locator')
        if isinstance(ref, str) and ref not in envelope.get('sourceReferences', {}):
            raise ValueError('Original image role has an unknown source reference')
        captions.append(canonical_bytes({'imageRole': role, 'sourceReference': ref,
            'assetId': asset, 'instruction': instruction}).decode('utf-8'))

    for name, role, instruction in (
        ('previous', 'PREVIOUS_CONTEXT_ONLY',
         'Context only. Do not inventory again or classify the current source from this image.'),
        ('source', 'CURRENT_SOURCE',
         'Current source to inventory. Classify this page and retain all its academic content.')):
        record = envelope.get(name)
        if record is None:
            continue
        if not isinstance(record, dict) or not isinstance(record.get('assetIds'), list):
            raise ValueError('Original image role metadata is invalid')
        for asset in record['assetIds']:
            add(role, record.get('ref'), asset, instruction)
    for entry in envelope.get('lectureNavigation', {}).get('evidence', []):
        for image in entry.get('images', []):
            add('LECTURE_NAVIGATION_ONLY', image.get('ref'), image.get('asset', {}).get('assetId'),
                'Lecture navigation only. Do not inventory it or classify the supporting page from it.')
    return captions


def image_caption_size(envelope):
    return sum(map(len, image_role_captions(envelope)))


def request_messages(policy, envelope, images, *, schema_size=0):
    encoded = canonical_bytes(envelope).decode('utf-8')
    captions = image_role_captions(envelope)
    if len(captions) != len(images):
        raise ValueError('Original image count differs from its role/asset metadata')
    if any(not isinstance(part, dict) or part.get('type') != 'image_url' or
           not isinstance(part.get('image_url'), dict) or
           not str(part['image_url'].get('url', '')).startswith('data:image/') for part in images):
        raise ValueError('Original image content is unavailable')
    if type(schema_size) is not int or schema_size < 0:
        raise ValueError('Invalid supporting schema size')
    if len(policy) + len(encoded) + sum(map(len, captions)) + schema_size > MAX_TEXT_PER_CALL or len(images) > MAX_IMAGES_PER_CALL:
        raise ValueError('Supporting request metadata/context exceeds bounds; split source or reduce lecture context')
    content = [{'type': 'text', 'text': encoded}]
    for caption, part in zip(captions, images):
        content.extend([{'type': 'text', 'text': caption}, deepcopy(part)])
    return [{'role': 'system', 'content': policy}, {'role': 'user', 'content': content}]
