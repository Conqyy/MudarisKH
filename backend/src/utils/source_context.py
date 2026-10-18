"""Private immutable source scope, bounded plans, and evidence-bound citations.

Plans contain original text ranges and render locators, never provider URLs or
executed coverage. Consumers must render images and record successful reads.
"""
from copy import deepcopy
import hashlib
import json
import re

from src.utils.course_foundation import (hydrate_document_source, build_foundation_status,
                                         foundation_material_revision)
from src.utils.source_contracts import (
    validate_manifest, MAX_SOURCE_PLAN_BATCHES, MAX_SOURCE_PLAN_UNITS, SOURCE_SCOPE_STATUSES,
)
from src.utils.generation_context import source_bundle_text
from src.utils.storage_paths import validate_component
from src.utils.topic_scope import scope_words


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _key(ref):
    if (not isinstance(ref, dict) or set(ref) != {'documentId', 'sourceRevision', 'unitId'}
            or any(not isinstance(value, str) or not value for value in ref.values())):
        raise ValueError('Invalid exact source reference')
    return ref['documentId'], ref['sourceRevision'], ref['unitId']


def resolve_source_scope(database, library, user_id: str, course_id: str,
                         document_ids: list[str] | None) -> dict:
    """None selects ready owned sources; explicit IDs fail as a whole if invalid.

    Returns a detached JSON snapshot, not mutable database records. The caller
    must still fence publication against current foundation authorization.
    """
    validate_component(user_id, 'user ID')
    validate_component(course_id, 'course ID')
    foundation_rows = database.get_course_documents(course_id, user_id)
    if document_ids is not None:
        if not isinstance(document_ids, list):
            raise ValueError('Document selection must be a list or None')
        ids = list(dict.fromkeys(validate_component(i, 'document ID') for i in document_ids))
        rows = [database.get_owned_document(user_id, course_id, identifier) for identifier in ids]
        if any(not row or row.get('id') != identifier for identifier, row in zip(ids, rows)):
            raise ValueError('Selected source is unavailable')
    else:
        rows = foundation_rows
    documents, manifests, refs = [], [], []
    seen = set()
    for row in rows:
        row = deepcopy(row)
        owned = row.get('userId') == user_id and row.get('courseId') == course_id
        if not owned:
            if document_ids is not None:
                raise ValueError('Selected source is unavailable')
            continue
        ready = hydrate_document_source(database, row, library=library)
        if build_foundation_status([ready])['completedCount'] != 1:
            if document_ids is not None:
                raise ValueError('Selected source is not ready. Prepare or replace it before selection.')
            continue
        if row['id'] in seen:
            continue
        seen.add(row['id'])
        manifest = ready['_sourceManifest']
        documents.append({'id': row['id'], 'title': row.get('title', ''),
                          'sourceRevision': manifest['sourceRevision'],
                          'guideRevision': row['guideRevision'], 'guide': deepcopy(row['guide'])})
        manifests.append(deepcopy(manifest))
        refs.extend({'documentId': row['id'], 'sourceRevision': manifest['sourceRevision'], 'unitId': u['unitId']}
                    for u in manifest['units'])
    revision = hashlib.sha256(_json([{'id': d['id'], 'sourceRevision': d['sourceRevision'],
                                     'guideRevision': d['guideRevision']} for d in documents]).encode()).hexdigest()
    return {'documents': documents, 'manifests': manifests, 'allowedRefs': refs,
            'scopeRevision': revision,
            'foundationRevision': foundation_material_revision(foundation_rows)}


def _units(scope):
    """Reject expanded/stale ref sets even when called outside the resolver."""
    result = {}
    for source in scope['manifests']:
        manifest = validate_manifest(source)
        if not manifest['coverage']['complete']:
            raise ValueError('Source preparation is incomplete')
        for unit in manifest['units']:
            key = (manifest['documentId'], manifest['sourceRevision'], unit['unitId'])
            if key in result:
                raise ValueError('Duplicate source unit')
            result[key] = unit
    if list(result) != [_key(ref) for ref in scope['allowedRefs']]:
        raise ValueError('Allowed references do not match selected complete sources')
    return result


def _entry(ref, unit, *, ranges=None, images=None, include_blank_assets=False):
    return {'ref': deepcopy(ref), 'kind': unit['kind'], 'position': unit['position'], 'label': unit['label'],
            'ranges': ranges or [], 'images': images or [],
            'disposition': 'candidate' if include_blank_assets and images else
                           'excluded_blank' if unit['blank'] else 'candidate'}


def _bundle(scope, purpose, entries):
    refs = list({_key(e['ref']): e['ref'] for e in entries}.values())
    blank = [e['ref'] for e in entries if e['disposition'] == 'excluded_blank']
    return {'scope': {'scopeRevision': scope['scopeRevision'], 'allowedRefs': deepcopy(refs)},
            # Guides remain available on the resolved scope. Batch navigation is
            # deliberately optional; omissions must never define source scope.
            'guide': [], 'evidence': deepcopy(entries),
            'coverage': {'state': 'planned', 'mode': 'partial' if purpose == 'focused' else 'all_units',
                         'selectedUnitCount': len(scope['allowedRefs']), 'plannedRefs': deepcopy(refs),
                         'plannedExcludedRefs': deepcopy(blank), 'processedRefs': [], 'includedRefs': [],
                         'excludedRefs': [], 'unavailableRefs': [], 'complete': False}}


def navigation_guides(documents, batch):
    """Keep complete guide rows linked to supplied units as partial navigation."""
    selected = {}
    for entry in batch['evidence']:
        selected.setdefault(entry['ref']['documentId'], set()).add(entry['ref']['unitId'])
    result = []
    for source in documents:
        units = selected.get(source['id'])
        if not units:
            continue
        document = deepcopy(source)
        guide = document['guide']
        for key in ('sections', 'concepts', 'visualReferences'):
            guide[key] = [row for row in guide[key] if units.intersection(row['unitIds'])]
        for key, value in guide.get('unitCoverage', {}).items():
            if isinstance(value, list):
                guide['unitCoverage'][key] = [unit for unit in value if unit in units]
        if 'unitCoverage' in guide:
            guide['unitCoverage']['complete'] = False
        result.append(document)
    return result


def build_source_plan(scope: dict, purpose: str, query: str = '',
                      text_budget: int = 30000, image_budget: int = 8,
                      include_blank_assets: bool = False) -> list[dict]:
    """Bound each canonical JSON bundle, including metadata, in characters.

    Broad purposes cover every character in both text fields and every original
    image locator in source order. Focused retrieval ranks complete-source
    windows, then supplies one bounded partial bundle. Ranking is not matching.
    """
    if purpose not in {'summary', 'exam', 'flashcards', 'focused'}:
        raise ValueError('Unknown source plan purpose')
    if (type(text_budget) is not int or text_budget <= 0 or type(image_budget) is not int
            or image_budget < 0 or type(include_blank_assets) is not bool):
        raise ValueError('Invalid source budget. Select fewer sources or split the file.')
    if len(scope['allowedRefs']) > MAX_SOURCE_PLAN_UNITS:
        raise ValueError(f"Source plan has {len(scope['allowedRefs'])} units; limit {MAX_SOURCE_PLAN_UNITS}. Select fewer sources or split the file.")
    units = _units(scope)
    batches, entries = [], []

    def fits(items):
        return (sum(len(e['images']) for e in items) <= image_budget
                and len(source_bundle_text(_bundle(scope, purpose, items))) <= text_budget)

    def flush():
        if entries:
            if len(batches) >= MAX_SOURCE_PLAN_BATCHES:
                raise ValueError(f'Source plan needs at least {len(batches) + 1} batches; limit {MAX_SOURCE_PLAN_BATCHES}. Select fewer sources or split the file.')
            batches.append(_bundle(scope, purpose, entries))
            entries.clear()

    def append(entry):
        if not fits(entries + [entry]):
            flush()
        if not fits([entry]):
            raise ValueError('Source metadata/images exceed budget. Select fewer sources or split the file.')
        entries.append(entry)

    candidates = []
    terms = scope_words(query)
    for ref in scope['allowedRefs']:
        unit = units[_key(ref)]
        if unit['blank']:
            if purpose != 'focused':
                if include_blank_assets and unit['visualAssets']:
                    for index, asset in enumerate(unit['visualAssets']):
                        append(_entry(ref, unit, images=[{'ref': deepcopy(ref), 'assetIndex': index,
                            'asset': deepcopy(asset)}], include_blank_assets=True))
                else:
                    append(_entry(ref, unit))
            continue
        for field in ('text', 'visualText'):
            text = unit.get(field, '')
            if purpose == 'focused':
                # Overlap protects terms crossing a candidate window boundary.
                # These are candidates only; returned ranges remain exact.
                for start in range(0, len(text), 600):
                    end = min(len(text), start + 1200)
                    score = len(terms & scope_words(text[start:end]))
                    if score:
                        candidates.append((score, ref, unit, field, start, end))
                continue
            start = 0
            while start < len(text):
                low, high = 0, len(text) - start
                while low < high:
                    size = (low + high + 1) // 2
                    candidate = _entry(ref, unit, ranges=[{'textField': field, 'start': start,
                                                         'end': start + size, 'text': text[start:start + size]}])
                    if fits(entries + [candidate]): low = size
                    else: high = size - 1
                if not low:
                    if entries:
                        flush()
                        continue
                    raise ValueError('Source metadata exceed budget. Select fewer sources or split the file.')
                entries.append(_entry(ref, unit, ranges=[{'textField': field, 'start': start,
                                                         'end': start + low, 'text': text[start:start + low]}]))
                start += low
        if purpose != 'focused':
            for index, asset in enumerate(unit['visualAssets']):
                append(_entry(ref, unit, images=[{'ref': deepcopy(ref), 'assetIndex': index, 'asset': deepcopy(asset)}]))
    if purpose == 'focused':
        for _, ref, unit, field, start, end in sorted(candidates, key=lambda c: -c[0]):
            entry = _entry(ref, unit, ranges=[{'textField': field, 'start': start, 'end': end,
                                              'text': unit[field][start:end]}])
            # Preserve a matching token while shrinking context on either side.
            # Offsets always refer to the unnormalized original Unicode text.
            hits = [m for m in re.finditer(r'\S+', unit[field][start:end]) if terms & scope_words(m.group())]
            if not hits:
                continue
            anchor_start, anchor_end = start + hits[0].start(), start + hits[0].end()
            part = entry['ranges'][0]
            while not fits(entries + [entry]) and part['end'] - part['start'] > anchor_end - anchor_start:
                if anchor_start - part['start'] > part['end'] - anchor_end:
                    part['start'] += 1
                else:
                    part['end'] -= 1
                part['text'] = unit[field][part['start']:part['end']]
            if fits(entries + [entry]) and part['text'] and terms & scope_words(part['text']):
                entries.append(entry)
                for index, asset in enumerate(unit['visualAssets']):
                    image_entry = _entry(ref, unit, images=[{'ref': deepcopy(ref), 'assetIndex': index, 'asset': deepcopy(asset)}])
                    if fits(entries + [image_entry]): entries.append(image_entry)
                break
        if not entries and candidates:
            raise ValueError('Source evidence exceeds budget. Select fewer sources or split the file.')
    flush()
    return batches


def validate_source_refs(refs: list[dict], scope: dict, supplied_evidence: list[dict]) -> list[dict]:
    """Validate selected citations and exact actually-supplied ranges/locators.

    supplied_evidence is trusted orchestration input, not model-reported reads.
    An image locator counts only after the consumer adds image['supplied']=True
    following successful original rendering and supply to the provider.
    """
    units = _units(scope)
    if not isinstance(refs, list) or not isinstance(supplied_evidence, list):
        raise ValueError('References and supplied evidence must be lists')
    supplied = set()
    for evidence in supplied_evidence:
        key = _key(evidence.get('ref'))
        if key not in units:
            raise ValueError('Supplied evidence is outside the selected source scope')
        unit = units[key]
        supported = False
        for part in evidence.get('ranges', []):
            field, start, end = part.get('textField'), part.get('start'), part.get('end')
            if (field not in ('text', 'visualText') or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(unit.get(field, ''))
                    or part.get('text') != unit[field][start:end]):
                raise ValueError('Supplied source range does not match the exact original evidence')
            supported = True
        for image in evidence.get('images', []):
            index = image.get('assetIndex')
            if (_key(image.get('ref')) != key or type(index) is not int
                    or not 0 <= index < len(unit['visualAssets']) or image.get('asset') != unit['visualAssets'][index]):
                raise ValueError('Supplied image locator does not match the exact source')
            supported |= image.get('supplied') is True
        if supported and not unit['blank'] and evidence.get('disposition') != 'excluded_blank':
            supplied.add(key)
    result, seen = [], set()
    for ref in refs:
        key = _key(ref)
        if key not in units or key not in supplied:
            raise ValueError('Citation is outside selected and actually supplied source evidence')
        if key not in seen:
            result.append(deepcopy(ref))
            seen.add(key)
    return result


def match_supporting_topics(topics: list[dict], scope: dict, read_evidence) -> list[dict]:
    """Use a trusted semantic reader; lexical candidates never grant support.

    Synchronous callback: read_evidence(topic_copy, planned_bundles_copy) ->
      {scopeStatus, suppliedEvidence, proofs} or None on failed/no evidence.
    suppliedEvidence contains only entries/ranges/images actually supplied from
    the plan. Images require supplied=True after original render and provider
    supply. Proofs are {ref,textField,start,end,text,relation,reason}: an exact
    nonempty quote within supplied ranges, and a semantic reason. The reader
    must establish supports_topic or explicit_exclusion by reading that source,
    never by keyword overlap, guide omission, or an unsupported model flag.

    This function verifies provenance and quotes, not semantic truth; the
    callback is trusted orchestration, never client/model-supplied executable
    code. Outside verdicts require selected-source explicit exclusion evidence.
    Reader failures/invalid proof return unverified, without carrying stale tags.
    """
    if not isinstance(topics, list):
        raise ValueError('Supporting topics must be a list')
    _units(scope)
    result = []
    for topic in topics:
        if not isinstance(topic, dict):
            raise ValueError('Supporting topic must be an object')
        row = deepcopy(topic)
        row.update(scopeStatus='unverified', sourceRefs=[], scopeEvidence=[], inScope=False)
        query = topic.get('topic') or topic.get('name') or ''
        batches = build_source_plan(scope, 'focused', query=query)
        if not batches or not callable(read_evidence):
            result.append(row)
            continue
        try:
            decision = read_evidence(deepcopy(topic), deepcopy(batches))
            if not isinstance(decision, dict):
                raise ValueError('No verified reading')
            status = decision.get('scopeStatus')
            if status not in SOURCE_SCOPE_STATUSES:
                raise ValueError('Invalid source scope status')
            relation = {'matched': 'supports_topic', 'outside_selected_scope': 'explicit_exclusion'}.get(status)
            supplied, proofs = decision.get('suppliedEvidence'), decision.get('proofs')
            if relation is None or not isinstance(supplied, list) or not isinstance(proofs, list) or not proofs:
                raise ValueError('No semantic proof')
            planned = [e for batch in batches for e in batch['evidence']]
            for item in supplied:
                candidates = [e for e in planned if e['ref'] == item.get('ref')]
                if not candidates:
                    raise ValueError('Reader supplied unplanned evidence')
                for part in item.get('ranges', []):
                    if not any(part in e['ranges'] for e in candidates):
                        raise ValueError('Reader supplied an unplanned range')
                for image in item.get('images', []):
                    locator = {k: v for k, v in image.items() if k != 'supplied'}
                    if not any(locator in e['images'] for e in candidates):
                        raise ValueError('Reader supplied an unplanned image')
            refs = validate_source_refs([proof['ref'] for proof in proofs], scope, supplied)
            for proof in proofs:
                if (proof.get('relation') != relation or not isinstance(proof.get('reason'), str)
                        or not proof['reason'].strip() or not isinstance(proof.get('text'), str)
                        or not proof['text'].strip() or type(proof.get('start')) is not int
                        or type(proof.get('end')) is not int):
                    raise ValueError('Invalid semantic source proof')
                containing = [part for item in supplied if item['ref'] == proof['ref'] for part in item.get('ranges', [])
                              if part['textField'] == proof.get('textField')
                              and part['start'] <= proof['start'] < proof['end'] <= part['end']
                              and part['text'][proof['start'] - part['start']:proof['end'] - part['start']] == proof['text']]
                if not containing:
                    raise ValueError('Semantic quote was not actually supplied')
            row.update(scopeStatus=status, sourceRefs=refs, scopeEvidence=deepcopy(proofs), inScope=status == 'matched')
        except Exception:
            # An unavailable provider or invalid proof is not evidence of absence.
            pass
        result.append(row)
    return result
