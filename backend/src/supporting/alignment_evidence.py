"""Pure exact-evidence ledgers shared by alignment and publication checks."""
from copy import deepcopy
import hashlib
import json


def ref_key(ref):
    return json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def compact_supplied(entries):
    """Union accepted intervals/assets without copying original source text."""
    grouped = {}
    for entry in entries:
        key = ref_key(entry['ref'])
        current = grouped.setdefault(key, {'ref': deepcopy(entry['ref']), 'ranges': [], 'assetIds': []})
        for part in entry.get('ranges', []):
            current['ranges'].append({k: part[k] for k in ('textField', 'start', 'end')})
        for image in entry.get('images', []):
            asset = image['asset']['assetId']
            if asset not in current['assetIds']:
                current['assetIds'].append(asset)
        for asset in entry.get('assetIds', []):
            if asset not in current['assetIds']:
                current['assetIds'].append(asset)
    for current in grouped.values():
        ranges = sorted(current['ranges'], key=lambda p: (p['textField'], p['start'], p['end']))
        merged = []
        for part in ranges:
            if merged and merged[-1]['textField'] == part['textField'] and part['start'] <= merged[-1]['end']:
                merged[-1]['end'] = max(merged[-1]['end'], part['end'])
            else:
                merged.append(deepcopy(part))
        current['ranges'] = merged
        current['assetIds'].sort()
    return [grouped[key] for key in sorted(grouped)]


def validate_review_ledger(coverage, *, units=None):
    """Check canonical per-ref supply and derive fully reviewed original units."""
    if not isinstance(coverage, dict):
        raise ValueError('Lecture review coverage must be an object')
    entries = coverage.get('suppliedEvidence')
    blank = coverage.get('excludedBlankRefs')
    if not isinstance(entries, list) or not isinstance(blank, list):
        raise ValueError('Lecture review needs a supplied evidence ledger')
    if coverage.get('checkState') not in ('pending', 'complete', 'uncertain'):
        raise ValueError('Invalid lecture review check state')
    allowed = {ref_key(ref) for ref in coverage['allowedRefs']}
    seen, supplied, blank_keys = set(), {}, set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'ref', 'ranges', 'assetIds'}:
            raise ValueError('Invalid supplied evidence ledger entry')
        key = ref_key(entry['ref'])
        if key not in allowed or key in seen:
            raise ValueError('Supplied evidence is duplicate or outside selected scope')
        seen.add(key)
        ranges, assets = entry['ranges'], entry['assetIds']
        if not isinstance(ranges, list) or not isinstance(assets, list):
            raise ValueError('Invalid supplied intervals or assets')
        previous = None
        for part in ranges:
            if (not isinstance(part, dict) or set(part) != {'textField', 'start', 'end'}
                    or part['textField'] not in ('text', 'visualText')
                    or type(part['start']) is not int or type(part['end']) is not int
                    or not 0 <= part['start'] < part['end']):
                raise ValueError('Invalid supplied original interval')
            position = (part['textField'], part['start'], part['end'])
            if previous and (position[0] < previous[0] or
                             (position[0] == previous[0] and position[1] <= previous[2])):
                raise ValueError('Supplied intervals must be normalized and nonoverlapping')
            previous = position
        if any(not isinstance(asset, str) or not asset for asset in assets) or assets != sorted(set(assets)):
            raise ValueError('Invalid supplied asset identifiers')
        supplied[key] = entry
    for ref in blank:
        key = ref_key(ref)
        if key not in allowed or key in blank_keys or key in supplied:
            raise ValueError('Invalid excluded blank reference')
        blank_keys.add(key)
    if units is None:
        return supplied
    fully_reviewed = set()
    for key in allowed:
        unit = units.get(key)
        if unit is None:
            raise ValueError('Lecture review unit is unavailable')
        if key in blank_keys:
            if any(unit.get(field, '') for field in ('text', 'visualText')) or unit['visualAssets']:
                raise ValueError('Excluded blank reference has original content or assets')
            fully_reviewed.add(key)
            continue
        entry = supplied.get(key)
        if entry is None:
            continue
        for part in entry['ranges']:
            if part['end'] > len(unit.get(part['textField'], '')):
                raise ValueError('Supplied interval exceeds original text')
        actual_assets = sorted(asset['assetId'] for asset in unit['visualAssets'])
        if any(asset not in actual_assets for asset in entry['assetIds']):
            raise ValueError('Supplied asset is absent from original')
        complete = entry['assetIds'] == actual_assets
        for field in ('text', 'visualText'):
            length = len(unit.get(field, ''))
            intervals = [p for p in entry['ranges'] if p['textField'] == field]
            complete &= (not intervals if not length else
                         bool(intervals) and intervals[0]['start'] == 0 and
                         intervals[-1]['end'] == length and
                         all(a['end'] == b['start'] for a, b in zip(intervals, intervals[1:])))
        if complete:
            fully_reviewed.add(key)
    reviewed = {ref_key(ref) for ref in coverage['reviewedRefs']}
    unresolved = {ref_key(ref) for ref in coverage['unresolvedRefs']}
    if reviewed != fully_reviewed or unresolved != allowed - fully_reviewed:
        raise ValueError('Lecture reviewed/unresolved refs disagree with exact supplied ledger')
    if coverage['complete'] != (reviewed == allowed and not unresolved):
        raise ValueError('Lecture review completeness disagrees with original evidence')
    return supplied


def proof_in_supplied(proof, supplied):
    entry = supplied.get(ref_key(proof['ref']))
    if entry is None:
        raise ValueError('Proof was not supplied in this review')
    if proof['type'] == 'text_span':
        if not any(part['textField'] == proof['field'] and part['start'] <= proof['start']
                   and proof['end'] <= part['end'] for part in entry['ranges']):
            raise ValueError('Proof quote falls outside supplied original ranges')
    elif proof['type'] == 'visual_region' and proof['assetId'] not in entry['assetIds']:
        raise ValueError('Proof image was not supplied in this review')


def context_components(items, shared_contexts):
    """Enumerate every potentially copied shared/ancestor component per item."""
    by_item = {row['id']: row for row in items}
    by_context = {row['id']: row for row in shared_contexts}
    result = {}
    for item in items:
        ancestors, current, seen = [], item, set()
        while current is not None:
            if current['id'] in seen:
                raise ValueError('Cyclic item context')
            seen.add(current['id'])
            if current is not item:
                ancestors.append(current)
            parent = current.get('parentId')
            current = by_item.get(parent) if parent else None
            if parent and current is None:
                raise ValueError('Missing original context ancestor')
        shared_ids = list(dict.fromkeys(cid for owner in [item, *ancestors]
                                            for cid in owner['sharedContextIds']))
        components = []

        def append(owner_type, owner, field, index, value):
            proofs = owner.get('supportingSourceProofs')
            if not proofs:
                raise ValueError('Original context component has no supporting proof')
            identity = {'ownerType': owner_type, 'ownerId': owner['id'],
                        'field': field, 'index': index, 'contentDigest':
                        hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':')).encode('utf-8')).hexdigest()}
            component_id = 'context-' + hashlib.sha256(json.dumps(
                {'itemId': item['id'], **identity}, ensure_ascii=False, sort_keys=True,
                separators=(',', ':')).encode('utf-8')).hexdigest()[:32]
            components.append({'id': component_id, 'contextForItemId': item['id'], **identity,
                'value': deepcopy(value), 'supportingSourceProofs': deepcopy(proofs)})

        for cid in shared_ids:
            if cid not in by_context:
                raise ValueError('Missing original shared context')
            append('shared_context', by_context[cid], 'text', None, by_context[cid]['text'])
        for ancestor in ancestors:
            append('item', ancestor, 'text', None, ancestor['text'])
            for field in ('choices', 'givenData'):
                for index, value in enumerate(ancestor[field]):
                    append('item', ancestor, field, index, value)
        result[item['id']] = components
    return result
