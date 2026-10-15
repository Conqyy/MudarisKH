"""JSON contracts for supporting evidence.

Structural validity is not semantic verification. Reports store references, not
copies of originals; publishers must resolve proofs with validate_source_proof
and the alignment service must assess what those original passages establish.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Literal, TypedDict

MaterialKind = Literal['historical_exam', 'tutorial', 'audio', 'notes']
Relation = Literal['lecture_supported', 'related_supplementary', 'outside_selected_scope', 'not_found', 'unverified', 'conflicting']
MATERIAL_KINDS = frozenset(('historical_exam', 'tutorial', 'audio', 'notes'))
RELATIONS = frozenset(('lecture_supported', 'related_supplementary', 'outside_selected_scope', 'not_found', 'unverified', 'conflicting'))
ITEM_TYPES = frozenset(('question', 'subpart', 'topic_statement', 'teaching_point', 'example', 'emphasis', 'nonacademic'))
REQUIREMENT_CATEGORIES = frozenset(('fact', 'concept', 'method', 'operation', 'deduction'))
DISPOSITIONS = frozenset(('readable', 'blank', 'nonacademic', 'uncertain', 'unsupported'))
VERSION = ALIGNMENT_VERSION = EXTRACTOR_VERSION = 1
HISTORICAL_PROJECTION_VERSION = 3
CLAIM_LEASE_MS = 300_000
HEARTBEAT_SECONDS = 60
MAX_SOURCE_PAGES = 160
MAX_SOURCE_CHARACTERS = 600_000
MAX_LECTURE_BATCHES = 128
MAX_LECTURE_UNITS = 3200
MAX_IMAGES_PER_CALL = 8
MAX_TEXT_PER_CALL = 24_000
MAX_REPORT_CHUNK_ITEMS = 100
MAX_REPORT_CHUNK_BYTES = 500_000
MAX_RECORD_BYTES = 750_000
DEFAULT_MODEL_CALL_BUDGET = 512


class MaterialIdentity(TypedDict):
    userId: str
    courseId: str
    kind: MaterialKind
    materialId: str


class SupportingRef(TypedDict):
    kind: MaterialKind
    materialId: str
    sourceRevision: str
    unitId: str


class LectureRef(TypedDict):
    documentId: str
    sourceRevision: str
    unitId: str


class Timing(TypedDict):
    startSeconds: float
    endSeconds: float


class SupportingUnit(TypedDict):
    unitId: str
    position: int
    kind: str
    text: str
    visualText: str
    visualAssets: list[dict]
    disposition: str
    timing: Timing | None


class SupportingManifest(TypedDict):
    version: int
    identity: MaterialIdentity
    originalDigest: str
    extractorVersion: int
    sourceRevision: str
    fileType: str
    units: list[SupportingUnit]
    coverage: dict


class TextSpanProof(TypedDict):
    type: Literal['text_span']
    ref: SupportingRef | LectureRef
    field: Literal['text', 'visualText']
    start: int
    end: int
    quote: str


class VisualRegionProof(TypedDict):
    type: Literal['visual_region']
    ref: SupportingRef | LectureRef
    assetId: str
    box: list[float]


SourceProof = TextSpanProof | VisualRegionProof


class SupportingRequirement(TypedDict):
    id: str
    text: str
    category: str
    supportingSourceRefs: list[SupportingRef]


class SupportingItem(TypedDict):
    id: str
    parentId: str | None
    paperId: str | None
    printedLabel: str | None
    itemType: str
    text: str
    sharedContextIds: list[str]
    choices: list
    givenData: list
    printedMarks: float | None
    requirements: list[SupportingRequirement]
    supportingSourceRefs: list[SupportingRef]


class RequirementAlignment(TypedDict):
    requirementId: str
    relation: Relation
    reason: str
    lectureAnchorRefs: list[LectureRef]
    lectureSupportProofs: list[SourceProof]
    supportingSourceProofs: list[SourceProof]
    reviewCoverage: dict


class ItemAlignment(TypedDict):
    itemId: str
    status: str
    requirements: list[RequirementAlignment]
    unresolvedRequirementIds: list[str]


class AlignmentReport(TypedDict):
    version: int
    alignmentVersion: int
    sourceRevision: str
    scopeSnapshot: dict
    extractionCoverage: dict
    alignmentCoverage: dict
    items: list[SupportingItem]
    alignments: list[ItemAlignment]
    sharedContexts: list[dict]
    papers: list[dict]
    topics: list[dict]


class SnapshotMaterial(TypedDict):
    identity: MaterialIdentity
    sourceRevision: str
    reportRevision: str
    analysisId: str
    scopedReportRevision: str


class SupportingSnapshot(TypedDict):
    version: int
    materials: list[SnapshotMaterial]


class SupportingPacket(TypedDict):
    version: int
    purpose: Literal['summary', 'exam', 'flashcards', 'tutor']
    scopeSnapshot: dict
    snapshot: SupportingSnapshot
    academicItems: list[dict]
    qualifiedItems: list[dict]
    structuralPapers: list[dict]
    coverage: dict


class JobHandle(TypedDict):
    id: str
    claimToken: str
    inputRevision: str
    sourceDigest: str | None
    foundationRevision: str


def canonical_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Supporting evidence must be finite JSON data') from exc


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _obj(value, label):
    if not isinstance(value, dict): raise ValueError(f'Invalid {label}')
    return value


def _text(value, label, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()): raise ValueError(f'Invalid {label}')
    return value


def _id(value):
    _text(value, 'identifier')
    if any(c in value for c in '/\\\x00') or value in ('.', '..'):
        raise ValueError('Invalid identifier')
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value): raise ValueError('Invalid revision digest')
    return value


def _number(value, *, integer=False, minimum=0):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value < minimum or (integer and type(value) is not int)):
        raise ValueError('Invalid finite number')
    return value


def _list(value, label):
    if not isinstance(value, list): raise ValueError(f'Invalid {label} list')
    return value


def _unique(values, label, key=lambda x: x):
    values = _list(values, label)
    keys = [canonical_bytes(key(v)) for v in values]
    if len(set(keys)) != len(keys): raise ValueError(f'Duplicate {label}')
    return values


def validate_identity(value):
    _obj(value, 'material identity')
    if set(value) != {'userId', 'courseId', 'kind', 'materialId'} or value['kind'] not in MATERIAL_KINDS:
        raise ValueError('Invalid material identity')
    for key in ('userId', 'courseId', 'materialId'): _id(value[key])
    return deepcopy(value)


def validate_ref(value, *, supporting=None):
    _obj(value, 'source ref')
    is_supporting = 'kind' in value
    expected = {'kind', 'materialId', 'sourceRevision', 'unitId'} if is_supporting else {'documentId', 'sourceRevision', 'unitId'}
    if set(value) != expected or (supporting is not None and supporting != is_supporting):
        raise ValueError('Invalid exact source reference')
    if is_supporting and value['kind'] not in MATERIAL_KINDS: raise ValueError('Invalid supporting kind')
    _id(value['materialId' if is_supporting else 'documentId'])
    _id(value['unitId'])
    _hash(value['sourceRevision'])
    return deepcopy(value)


def _refs(values, *, supporting, nonempty=False):
    _unique(values, 'references')
    if nonempty and not values: raise ValueError('Original source references are required')
    return [validate_ref(v, supporting=supporting) for v in values]


def supporting_revision(original_digest, units, *, extractor_version=EXTRACTOR_VERSION):
    _hash(original_digest)
    if type(extractor_version) is not int or extractor_version != EXTRACTOR_VERSION: raise ValueError('Unknown extractor version')
    return digest({'originalDigest': original_digest, 'extractorVersion': extractor_version, 'units': units})


def source_coverage(units):
    coverage = {'unitIds': [], 'readableUnitIds': [], 'blankUnitIds': [], 'nonacademicUnitIds': [], 'unresolvedUnitIds': []}
    groups = {'readable': 'readableUnitIds', 'blank': 'blankUnitIds', 'nonacademic': 'nonacademicUnitIds'}
    for unit in units:
        coverage['unitIds'].append(unit['unitId'])
        coverage[groups.get(unit['disposition'], 'unresolvedUnitIds')].append(unit['unitId'])
    coverage['complete'] = bool(units) and not coverage['unresolvedUnitIds']
    return coverage


def validate_supporting_manifest(value):
    value = deepcopy(_obj(value, 'manifest'))
    if type(value.get('version')) is not int or value['version'] != VERSION: raise ValueError('Unknown supporting manifest version')
    identity = validate_identity(value.get('identity'))
    file_type = value.get('fileType')
    permitted = {'historical_exam': {'pdf', 'image'}, 'tutorial': {'pdf', 'docx', 'pptx', 'image'}, 'audio': {'audio'}, 'notes': {'notes'}}
    if file_type not in permitted[identity['kind']]: raise ValueError('File type conflicts with material kind')
    units = _unique(value.get('units'), 'source units', lambda u: _obj(u, 'unit').get('unitId'))
    if not units or (file_type in ('pdf', 'pptx', 'image') and len(units) > MAX_SOURCE_PAGES):
        raise ValueError('Split source: missing units or page/slide limit exceeded')
    characters = 0
    for position, unit in enumerate(units, 1):
        _id(unit.get('unitId'))
        if type(unit.get('position')) is not int or unit['position'] != position: raise ValueError('Invalid source unit order')
        if unit.get('kind') not in ('page', 'slide', 'block', 'image', 'transcript', 'notes'): raise ValueError('Invalid unit kind')
        for field in ('text', 'visualText'): characters += len(_text(unit.get(field), field, empty=True))
        if unit.get('disposition') not in DISPOSITIONS: raise ValueError('Invalid source disposition')
        assets = _unique(unit.get('visualAssets'), 'assets', lambda a: _obj(a, 'asset').get('assetId'))
        for asset in assets:
            _id(asset.get('assetId'))
            _text(asset.get('kind'), 'asset kind')
            if asset.get('mimeType') not in ('image/png', 'image/jpeg', 'image/webp'): raise ValueError('Unsupported source image')
            if any(k in asset for k in ('url', 'path', 'imageUri')): raise ValueError('Assets use immutable locators, not paths or URLs')
        if unit['disposition'] == 'blank' and (unit['text'].strip() or unit['visualText'].strip()):
            raise ValueError('Content cannot be labeled blank')
        if unit['disposition'] == 'readable' and not (unit['text'].strip() or unit['visualText'].strip() or assets):
            raise ValueError('Readable unit requires original content')
        timing = unit.get('timing')
        if timing is not None:
            if identity['kind'] != 'audio' or not isinstance(timing, dict) or set(timing) != {'startSeconds', 'endSeconds'}:
                raise ValueError('Only recordings have actual segment timing')
            _number(timing['startSeconds'])
            _number(timing['endSeconds'], minimum=timing['startSeconds'])
    if characters > MAX_SOURCE_CHARACTERS: raise ValueError('Split source: character limit exceeded')
    if value.get('coverage') != source_coverage(units): raise ValueError('Source coverage does not match units')
    if value.get('sourceRevision') != supporting_revision(value.get('originalDigest'), units, extractor_version=value.get('extractorVersion')):
        raise ValueError('Supporting source revision changed')
    canonical_bytes(value)
    return value


def _proof(value, *, supporting):
    _obj(value, 'source proof')
    validate_ref(value.get('ref'), supporting=supporting)
    if value.get('type') == 'text_span':
        if set(value) != {'type', 'ref', 'field', 'start', 'end', 'quote'} or value['field'] not in ('text', 'visualText'):
            raise ValueError('Invalid text proof')
        _number(value['start'], integer=True)
        _number(value['end'], integer=True, minimum=value['start']+1)
        _text(value['quote'], 'source quote')
        if len(value['quote']) != value['end'] - value['start']: raise ValueError('Quote length differs from exact span')
    elif value.get('type') == 'visual_region':
        if set(value) != {'type', 'ref', 'assetId', 'box'}: raise ValueError('Invalid visual proof')
        _id(value['assetId'])
        box = _list(value['box'], 'visual box')
        if len(box) != 4: raise ValueError('Invalid visual region')
        for x in box:
            if _number(x) > 1: raise ValueError('Visual region is outside image')
        if box[0] >= box[2] or box[1] >= box[3]: raise ValueError('Visual region must have positive area')
    else:
        raise ValueError('Unknown source proof')
    return value


def validate_source_proof(value, *, ref, unit):
    """Resolve exact content only; semantic support is assessed independently."""
    _proof(value, supporting='kind' in ref)
    validate_ref(ref)
    if value['ref'] != ref or unit.get('unitId') != ref['unitId']: raise ValueError('Proof source identity changed')
    if value['type'] == 'text_span':
        text = unit.get(value['field'], '')
        if value['end'] > len(text) or text[value['start']:value['end']] != value['quote']:
            raise ValueError('Quote is not present at the original source span')
    elif not any(a.get('assetId') == value['assetId'] for a in unit.get('visualAssets', [])):
        raise ValueError('Original visual asset is unavailable')
    return deepcopy(value)


def _ledger(value, all_key, checked_key, unresolved_key, expected=None):
    _obj(value, 'coverage')
    for key in (all_key, checked_key, unresolved_key):
        for identifier in _unique(value.get(key), key): _id(identifier)
    all_ids, checked, unresolved = (set(value[k]) for k in (all_key, checked_key, unresolved_key))
    if expected is not None and all_ids != set(expected): raise ValueError('Coverage inventory differs from source')
    if not checked <= all_ids or not unresolved <= all_ids: raise ValueError('Coverage contains unknown IDs')
    complete = checked == all_ids and not unresolved
    if type(value.get('complete')) is not bool or value['complete'] != complete: raise ValueError('Coverage complete flag is inconsistent')


def _review_coverage(value):
    _obj(value, 'lecture review coverage')
    _hash(value.get('scopeRevision'))
    for key in ('allowedRefs', 'reviewedRefs', 'unresolvedRefs'): _refs(value.get(key), supporting=False)
    allowed, reviewed, unresolved = ({canonical_bytes(r) for r in value[k]} for k in ('allowedRefs', 'reviewedRefs', 'unresolvedRefs'))
    if not allowed or not reviewed <= allowed or not unresolved <= allowed: raise ValueError('Invalid lecture review coverage')
    if type(value.get('complete')) is not bool or (value['complete'] and (reviewed != allowed or unresolved)):
        raise ValueError('Incomplete lecture review cannot be complete')


def _requirement_alignment(row):
    _obj(row, 'requirement alignment')
    _id(row.get('requirementId'))
    relation = row.get('relation')
    if relation not in RELATIONS: raise ValueError('Invalid evidence relation')
    _text(row.get('reason'), 'alignment reason')
    anchors = _refs(row.get('lectureAnchorRefs'), supporting=False)
    for key, supporting in (('lectureSupportProofs', False), ('supportingSourceProofs', True)):
        for proof in _list(row.get(key), key): _proof(proof, supporting=supporting)
    if not row['supportingSourceProofs']: raise ValueError('Every finding needs original supporting evidence')
    if relation in ('lecture_supported', 'conflicting') and (not anchors or not row['lectureSupportProofs']):
        raise ValueError('Lecture support requires anchors and proofs')
    if relation == 'related_supplementary' and not anchors: raise ValueError('Supplementary teaching requires a lecture anchor')
    _review_coverage(row.get('reviewCoverage'))
    if relation in ('not_found', 'outside_selected_scope') and not row['reviewCoverage']['complete']:
        raise ValueError('Negative finding requires complete lecture review')


def aggregate_item_alignment(requirements, *, item_id):
    _id(item_id)
    _unique(requirements, 'requirement alignments', lambda r: _obj(r, 'alignment').get('requirementId'))
    for row in requirements: _requirement_alignment(row)
    supported = sum(r['relation'] == 'lecture_supported' for r in requirements)
    if not requirements: status = 'nonacademic'
    elif supported == len(requirements): status = 'covered'
    elif supported: status = 'partly_covered'
    elif all(r['relation'] in ('not_found', 'outside_selected_scope') for r in requirements): status = 'not_covered'
    else: status = 'needs_review'
    return {'itemId': item_id, 'status': status, 'requirements': deepcopy(requirements),
            'unresolvedRequirementIds': [r['requirementId'] for r in requirements if r['relation'] in ('unverified', 'conflicting')]}


def validate_alignment_report(value):
    value = deepcopy(_obj(value, 'alignment report'))
    for key in ('version', 'alignmentVersion'):
        if type(value.get(key)) is not int or value[key] != 1: raise ValueError('Unknown alignment version')
    revision = _hash(value.get('sourceRevision'))
    scope = _obj(value.get('scopeSnapshot'), 'scope snapshot')
    _hash(scope.get('scopeRevision'))
    allowed = _refs(scope.get('allowedRefs'), supporting=False, nonempty=True)
    allowed_keys = {canonical_bytes(r) for r in allowed}
    items = _unique(value.get('items'), 'items', lambda r: _obj(r, 'item').get('id'))
    item_ids = {_id(i.get('id')) for i in items}
    contexts = _unique(value.get('sharedContexts'), 'shared contexts', lambda r: _obj(r, 'context').get('id'))
    context_ids = {_id(c.get('id')) for c in contexts}
    papers = _unique(value.get('papers'), 'papers', lambda r: _obj(r, 'paper').get('paperId'))
    paper_ids = {_id(p.get('paperId')) for p in papers}
    _ledger(value.get('extractionCoverage'), 'unitIds', 'accountedUnitIds', 'unresolvedUnitIds')
    units = set(value['extractionCoverage']['unitIds'])
    material = None

    def source_refs(refs):
        nonlocal material
        for ref in _refs(refs, supporting=True, nonempty=True):
            identity = (ref['kind'], ref['materialId'])
            if material is None: material = identity
            if identity != material or ref['sourceRevision'] != revision or ref['unitId'] not in units:
                raise ValueError('Supporting reference conflicts with report source')

    requirement_ids = set()
    requirement_refs = {}
    by_item = {}
    for item in items:
        if item.get('itemType') not in ITEM_TYPES: raise ValueError('Invalid item type')
        _text(item.get('text'), 'item text', empty=item['itemType'] == 'nonacademic')
        if item.get('parentId') is not None and (item['parentId'] not in item_ids or item['parentId'] == item['id']):
            raise ValueError('Unknown or cyclic parent')
        if item.get('paperId') is not None and item['paperId'] not in paper_ids: raise ValueError('Unknown paper')
        if item.get('printedLabel') is not None: _text(item['printedLabel'], 'printed label')
        if item.get('printedMarks') is not None: _number(item['printedMarks'])
        if not set(_unique(item.get('sharedContextIds'), 'context IDs')) <= context_ids: raise ValueError('Unknown shared context')
        for key in ('choices', 'givenData'): _list(item.get(key), key)
        source_refs(item.get('supportingSourceRefs'))
        reqs = _unique(item.get('requirements'), 'requirements', lambda r: _obj(r, 'requirement').get('id'))
        by_item[item['id']] = set()
        for req in reqs:
            rid = _id(req.get('id'))
            if rid in requirement_ids: raise ValueError('Duplicate requirement ID')
            requirement_ids.add(rid)
            by_item[item['id']].add(rid)
            _text(req.get('text'), 'requirement text')
            if req.get('category') not in REQUIREMENT_CATEGORIES: raise ValueError('Invalid requirement category')
            source_refs(req.get('supportingSourceRefs'))
            requirement_refs[rid] = {canonical_bytes(r) for r in req['supportingSourceRefs']}
    parents = {i['id']: i.get('parentId') for i in items}
    for identifier in parents:
        seen, parent = {identifier}, parents[identifier]
        while parent is not None:
            if parent in seen: raise ValueError('Cyclic item parents')
            seen.add(parent)
            parent = parents[parent]
    # Parents expose all descendant requirements. An empty parent heading is
    # allowed only when its children provide the academic requirements.
    direct_requirements = {key: set(value) for key, value in by_item.items()}
    for identifier, requirements in direct_requirements.items():
        parent = parents[identifier]
        while parent is not None:
            by_item[parent].update(requirements)
            parent = parents[parent]
    for item in items:
        if item['itemType'] != 'nonacademic' and not by_item[item['id']]:
            raise ValueError('Academic item is missing requirements')
        if item['itemType'] == 'nonacademic' and by_item[item['id']]:
            raise ValueError('Nonacademic item contains academic requirements')
    for context in contexts:
        _text(context.get('text'), 'shared context', empty=True)
        source_refs(context.get('supportingSourceRefs'))
    for paper in papers:
        _text(paper.get('title'), 'paper title')
        if not set(_unique(paper.get('unitIds'), 'paper units')) <= units: raise ValueError('Unknown paper units')
        questions = _unique(paper.get('questionIds'), 'paper questions')
        if not set(questions) <= item_ids: raise ValueError('Unknown paper questions')
        _number(paper.get('totalQuestions'), integer=True)
        if paper['totalQuestions'] != len(questions): raise ValueError('Original paper question count disagrees')
        if paper.get('totalMarks') is not None: _number(paper['totalMarks'])
    for topic in _unique(value.get('topics'), 'topics', lambda r: _obj(r, 'topic').get('id')):
        _id(topic.get('id'))
        _text(topic.get('text'), 'topic')
        origin_ids = _unique(topic.get('itemIds'), 'topic item IDs')
        if not origin_ids or not set(origin_ids) <= item_ids: raise ValueError('Topic requires originating items or a topic statement')
        source_refs(topic.get('supportingSourceRefs'))
    alignments = _unique(value.get('alignments'), 'item alignments', lambda r: _obj(r, 'alignment').get('itemId'))
    checked = {a.get('itemId') for a in alignments}
    if not checked <= item_ids: raise ValueError('Alignment refers to unknown item')
    canonical_findings = {}
    unfinished_items = set()
    for alignment in alignments:
        findings = alignment.get('requirements')
        expected = aggregate_item_alignment(findings, item_id=alignment['itemId'])
        if expected != alignment: raise ValueError('Parent status disagrees with requirement findings')
        if {r['requirementId'] for r in findings} != by_item[alignment['itemId']]: raise ValueError('Missing or invented requirement alignment')
        for finding in findings:
            rid = finding['requirementId']
            encoded = canonical_bytes(finding)
            if rid in canonical_findings and canonical_findings[rid] != encoded:
                raise ValueError('Parent and child findings disagree')
            canonical_findings[rid] = encoded
            coverage = finding['reviewCoverage']
            # A settled positive proof may stop its search early. Unverified
            # checks interrupted before review finished remain processing work,
            # including every ancestor carrying that requirement.
            if finding['relation'] == 'unverified' and not coverage['complete']:
                unfinished_items.add(alignment['itemId'])
            if coverage['scopeRevision'] != scope['scopeRevision'] or {canonical_bytes(r) for r in coverage['allowedRefs']} != allowed_keys:
                raise ValueError('Review narrowed the selected lecture scope')
            for ref in finding['lectureAnchorRefs']:
                if canonical_bytes(ref) not in allowed_keys: raise ValueError('Lecture anchor outside selected scope')
            for proof in finding['lectureSupportProofs']:
                if canonical_bytes(proof['ref']) not in allowed_keys: raise ValueError('Lecture proof outside selected scope')
            source_refs([p['ref'] for p in finding['supportingSourceProofs']])
            if any(canonical_bytes(p['ref']) not in requirement_refs[rid] for p in finding['supportingSourceProofs']):
                raise ValueError('Proof is not from the requirement source locations')
            if finding['relation'] == 'outside_selected_scope' and not finding['lectureSupportProofs']:
                raise ValueError('Outside-scope finding needs positive evidence of exclusion')
            if material[0] == 'historical_exam' and finding['relation'] == 'related_supplementary':
                raise ValueError('Historical questions cannot authorize supplementary teaching')
    _ledger(value.get('alignmentCoverage'), 'itemIds', 'checkedItemIds', 'unresolvedItemIds', item_ids)
    if set(value['alignmentCoverage']['checkedItemIds']) != checked: raise ValueError('Alignment coverage differs from checked items')
    if not unfinished_items <= set(value['alignmentCoverage']['unresolvedItemIds']):
        raise ValueError('Unfinished requirement reviews must remain unresolved item coverage')
    canonical_bytes(value)
    return value
