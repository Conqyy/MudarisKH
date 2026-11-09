"""Deterministic, source-bound facts for a separate semantic inventory review.

Pairing identifies review obligations, never accepts an extraction. Every source
value stays byte-exact, and a literal-presence fact makes no semantic judgment.
Callers must still validate extraction contracts and independently check source
completeness, including material that neither inventory retained.
"""
from collections import defaultdict
from copy import deepcopy

from src.supporting.contracts import canonical_bytes, digest, validate_source_proof
from src.supporting.extraction_source import reference


_FIELDS = {
    'classification': ('disposition', 'pageRole', 'paper'),
    'item': ('origin', 'itemType', 'parent', 'text', 'textJoin', 'printedLabel',
             'printedMarks', 'questionType', 'choices', 'givenData', 'contextOrigins', 'proofs'),
    'requirement': ('origin', 'text', 'category', 'proofs'),
    'sharedContexts': ('origin', 'text', 'proofs'),
    'topics': ('text', 'items', 'requirements', 'proofs'),
}
_UNORDERED_FIELDS = {'proofs', 'contextOrigins'}
_TEXT_FIELDS = {'text', 'printedLabel', 'choices', 'givenData', 'requirements'}


class InventoryComparison:
    """Compare already contract-validated inventories without providers or I/O.

    IDs follow the existing A/B reconciliation obligation addresses. Requirement
    order is immaterial because each requirement is reviewed separately under its
    matched owner. Ambiguous locations stay unmatched, including their children.
    """

    def __init__(self, manifest, source, first, second):
        self._manifest = deepcopy(manifest)
        self._source = deepcopy(source)
        self._units = {unit['unitId']: unit for unit in self._manifest['units']}
        self._validate_source()
        self._records = {}
        for prefix, value in (('A', first), ('B', second)):
            self._add_records(prefix, deepcopy(value))
        if len(self._records) > 512:
            raise ValueError('Inventory comparison exceeds the bounded obligation count')
        for record in self._records.values():
            self._validate_nested_proofs(record['value'])
        self._bindings = {
            'sourceRevision': manifest['sourceRevision'],
            'sourceDigest': digest(source),
            'firstDigest': digest(first),
            'secondDigest': digest(second),
        }
        self._pairs = self._pair_records()

    def _validate_source(self):
        unit = self._units.get(self._source.get('ref', {}).get('unitId'))
        if unit is None or self._source['ref'] != reference(self._manifest, unit):
            raise ValueError('Comparison source identity changed')
        for entry in self._source.get('ranges', []):
            self._validate_proof({'type': 'text_span', 'ref': self._source['ref'],
                'field': entry['field'], 'start': entry['start'], 'end': entry['end'], 'quote': entry['text']})
        available = {asset['assetId'] for asset in unit.get('visualAssets', [])}
        if not set(self._source.get('assetIds', [])) <= available:
            raise ValueError('Comparison source contains unavailable original assets')

    def _validate_proof(self, proof):
        unit = self._units.get(proof.get('ref', {}).get('unitId')) if isinstance(proof, dict) else None
        if unit is None:
            raise ValueError('Proof is outside the original supporting source')
        return validate_source_proof(proof, ref=reference(self._manifest, unit), unit=unit)

    def _validate_nested_proofs(self, value):
        if isinstance(value, dict):
            if value.get('type') in ('text_span', 'visual_region'):
                self._validate_proof(value)
            else:
                for nested in value.values():
                    self._validate_nested_proofs(nested)
        elif isinstance(value, list):
            for nested in value:
                self._validate_nested_proofs(nested)

    def _add_records(self, prefix, value):
        self._records[prefix + '/classification'] = {'family': 'classification',
            'value': {key: value[key] for key in _FIELDS['classification']}, 'owner': None}
        for index, row in enumerate(value['items']):
            owner = f'{prefix}/items/{index}'
            self._records[owner] = {'family': 'item:' + row['itemType'], 'value': row, 'owner': None}
            for number, requirement in enumerate(row['requirements']):
                self._records[f'{owner}/requirements/{number}'] = {
                    'family': 'requirement', 'value': requirement, 'owner': owner}
        for collection in ('sharedContexts', 'topics'):
            for index, row in enumerate(value[collection]):
                self._records[f'{prefix}/{collection}/{index}'] = {'family': collection, 'value': row, 'owner': None}

    def _address(self, proof):
        """Use a proven source location; never rewrite its quote or any field.

        Removing whitespace at the edge of an original text proof merely makes
        two addresses candidates for comparison. Differing field text and proof
        ranges remain visible and still require review.
        """
        self._validate_proof(proof)
        if proof['type'] == 'text_span':
            start = proof['start']
            if proof['quote'].strip():
                start += len(proof['quote']) - len(proof['quote'].lstrip())
            return {'type': proof['type'], 'ref': proof['ref'], 'field': proof['field'], 'start': start}
        return {key: proof[key] for key in ('type', 'ref', 'assetId', 'box')}

    def _link_address(self, value):
        return {'itemType': value.get('itemType'), 'origin': self._address(value['origin'])}

    def _key(self, identifier, owner_pairs):
        record = self._records[identifier]
        family, value = record['family'], record['value']
        if family == 'classification':
            return canonical_bytes(['classification'])
        if family == 'requirement':
            owner = record['owner']
            # B requirements may pair only inside a uniquely paired A owner.
            if identifier.startswith('B/'):
                owner = owner_pairs.get(owner)
            elif owner not in owner_pairs.values():
                owner = None
            if owner is None:
                return None
            return canonical_bytes([family, owner, self._address(value['origin'])])
        if family.startswith('item:'):
            parent = self._link_address(value['parent']) if value.get('parent') else None
            return canonical_bytes([family, self._address(value['origin']), parent])
        if family == 'sharedContexts':
            return canonical_bytes([family, self._address(value['origin'])])
        if family == 'topics':
            # Semantic names and categories stay fields to review. Links identify
            # a possible pair only when that ownership signature is unique.
            items = [self._topic_link(identifier[0], link, 'item:' + link['itemType'], owner_pairs)
                     for link in value['items']]
            requirements = [self._topic_link(identifier[0], link, 'requirement', owner_pairs)
                            for link in value['requirements']]
            if None in items or None in requirements:
                return None
            return canonical_bytes([family, sorted(items), sorted(requirements)])
        raise ValueError('Unsupported comparison family')

    def _targets(self, prefix, link, family):
        address = self._address(link['origin'])
        result = []
        for identifier, record in self._records.items():
            if not identifier.startswith(prefix + '/') or record['family'] != family:
                continue
            value = record['value']
            if self._address(value['origin']) != address:
                continue
            if family == 'requirement' and any(value[key] != link[key] for key in ('text', 'category')):
                continue
            result.append(identifier)
        return result

    def _topic_link(self, prefix, link, family, paired):
        targets = self._targets(prefix, link, family)
        if not targets:
            # Earlier, already validated inventory links retain their full
            # identity; there is no local owner to infer or silently replace.
            return 'external:' + canonical_bytes([family, link]).decode('utf-8')
        if len(targets) != 1:
            return None
        target = targets[0]
        if prefix == 'B':
            return paired.get(target)
        return target if target in paired.values() else None

    def _parent_paired(self, left, right, paired):
        a, b = self._records[left]['value'].get('parent'), self._records[right]['value'].get('parent')
        if not a and not b:
            return True
        if not a or not b:
            return False
        targets_a = self._targets('A', a, 'item:' + a['itemType'])
        targets_b = self._targets('B', b, 'item:' + b['itemType'])
        if not targets_a and not targets_b:
            return True  # Same source-bound external parent is already in the pair key.
        return len(targets_a) == len(targets_b) == 1 and paired.get(targets_b[0]) == targets_a[0]

    def _pair_records(self):
        pairs, paired = [], {}
        for stage in ('owners', 'requirement', 'topics'):
            grouped = {'A': defaultdict(list), 'B': defaultdict(list)}
            for identifier, record in self._records.items():
                family_stage = record['family'] if record['family'] in ('requirement', 'topics') else 'owners'
                if family_stage != stage:
                    continue
                key = self._key(identifier, paired)
                if key is not None:
                    grouped[identifier[0]][key].append(identifier)
            pending = []
            for key, identifiers in grouped['A'].items():
                candidates = grouped['B'].get(key, [])
                if len(identifiers) == len(candidates) == 1:
                    pending.append((identifiers[0], candidates[0]))
            # Providers may emit subparts before their parent. Resolve those
            # dependencies without accepting ambiguous or missing local owners.
            while pending:
                waiting = []
                for left, right in pending:
                    if self._records[left]['family'].startswith('item:') and not self._parent_paired(left, right, paired):
                        waiting.append((left, right))
                        continue
                    pairs.append(self._describe_pair(left, right))
                    paired[right] = left
                if len(waiting) == len(pending):
                    break
                pending = waiting
        return pairs

    def _describe_pair(self, left, right):
        equal, differing = [], []
        for field in self.field_names(left):
            if self._records[left]['family'].startswith('item:') and field == 'requirements':
                continue  # Child obligations carry these values and ownership.
            a, b = self.field_value(left, field), self.field_value(right, field)
            if field in _UNORDERED_FIELDS and isinstance(a, list) and isinstance(b, list):
                same = sorted(map(canonical_bytes, a)) == sorted(map(canonical_bytes, b))
            else:
                same = canonical_bytes(a) == canonical_bytes(b)
            (equal if same else differing).append(field)
        return {'firstId': left, 'secondId': right, 'family': self._records[left]['family'],
                'equalFields': equal, 'differingFields': differing}

    def _record(self, obligation_id):
        if obligation_id not in self._records:
            raise ValueError('Unknown comparison obligation')
        return self._records[obligation_id]

    def field_names(self, obligation_id):
        """Whitelisted fields available as exact facts for this obligation."""
        family = self._record(obligation_id)['family']
        return _FIELDS['item'] + ('requirements',) if family.startswith('item:') else _FIELDS[family]

    def field_value(self, obligation_id, field):
        """Return a copy of one saved field; classification is never an item."""
        if field not in self.field_names(obligation_id):
            raise ValueError('Unknown comparison field for this obligation')
        return deepcopy(self._record(obligation_id)['value'].get(field))

    def obligations(self):
        """Return audit-compatible IDs, values, families and explicit owners."""
        return deepcopy(self._records)

    def describe(self):
        left = {pair['firstId'] for pair in self._pairs}
        right = {pair['secondId'] for pair in self._pairs}
        return {'version': 1, 'bindings': deepcopy(self._bindings), 'pairs': deepcopy(self._pairs),
                'unmatchedFirst': [key for key in self._records if key.startswith('A/') and key not in left],
                'unmatchedSecond': [key for key in self._records if key.startswith('B/') and key not in right]}

    def _current_text_proof(self, proof):
        self._validate_proof(proof)
        if proof['type'] != 'text_span' or not proof['quote'].strip():
            raise ValueError('Literal presence requires a nonempty original text proof')
        if proof['ref'] != self._source['ref'] or not any(
                entry['field'] == proof['field'] and entry['start'] <= proof['start'] < proof['end'] <= entry['end']
                for entry in self._source.get('ranges', [])):
            raise ValueError('Literal-presence proof is outside the current supplied source')

    @staticmethod
    def _retained(value, proofs, proof):
        strings = value if isinstance(value, list) else [value]
        if not any(isinstance(text, str) and proof['quote'] in text for text in strings):
            return False
        return any(saved['type'] == 'text_span' and saved['ref'] == proof['ref'] and saved['field'] == proof['field']
                   and saved['start'] <= proof['start'] < proof['end'] <= saved['end'] for saved in proofs)

    def claim_present(self, obligation_id, field, proof):
        """Is this exact source quote retained and evidenced in THIS field?

        A true answer contradicts literal absence only. It cannot establish the
        correct meaning, category, ownership, completeness or suitability of a
        field. Text found only in another field/item never satisfies this check.
        A false answer means presence was not mechanically proven; it does not
        establish absence (for example, the field may retain a paraphrase).
        """
        value = self.field_value(obligation_id, field)
        if field not in _TEXT_FIELDS:
            raise ValueError('This comparison field cannot establish literal source-text presence')
        self._current_text_proof(proof)
        record = self._record(obligation_id)
        if field in ('printedLabel', 'requirements') or (field == 'text' and record['family'] == 'requirement'):
            # Only a proven original proof's empty margins may be ignored when
            # disproving absence of a retained label/task. The exact inner span
            # must still be covered by this field's own evidence. Never rewrite
            # saved values, interior whitespace, code/data, choices or item text.
            quote = proof['quote']
            trimmed = quote.strip()
            start = proof['start'] + len(quote) - len(quote.lstrip())
            proof = {**proof, 'start': start, 'end': start + len(trimmed), 'quote': trimmed}
        if field == 'requirements':
            if not record['family'].startswith('item:'):
                raise ValueError('Requirement presence requires a named item owner')
            return any(self._retained(row['text'], row['proofs'], proof) for row in value)
        return self._retained(value, record['value'].get('proofs', []), proof)
