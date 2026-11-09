"""Request-local, deterministic IDs for exact text spans in supplied originals.

Models select an ID instead of copying whitespace or calculating offsets. IDs
bind the complete canonical proof; they never authorize a different source. The
original proof/window validators remain mandatory after transport decoding.
"""
from copy import deepcopy
import hashlib
import re

from src.supporting.contracts import canonical_bytes, validate_source_proof_shape


def _ranges(record):
    if not isinstance(record, dict):
        return
    for span in record.get('ranges', []):
        field = span.get('field', span.get('textField'))
        text, start, end = span.get('text'), span.get('start'), span.get('end')
        if (field not in ('text', 'visualText') or not isinstance(text, str)
                or type(start) is not int or type(end) is not int
                or start < 0 or end < start or end - start != len(text)):
            raise ValueError('Invalid exact supplied text range')
        yield span, field, text, start, end


def _segments(text):
    """Mechanical line/clause boundaries, with no interpretation or lost text."""
    offset = 0
    for line in text.splitlines(keepends=True):
        # Numbered/list entries can share a physical line. Mechanical printed
        # separators give each entry an exact origin without interpreting it.
        entries = [match.start() for match in re.finditer(
            r'(?<=\s)(?:\d+[.)]|\([^\W_]{1,4}\)|[^\W\d_][.)])(?=\s)', line)]
        boundaries = sorted({0, *entries, *[match.end() for match in
            re.finditer(r'[!?;؟؛](?=\s+\S)', line)], len(line)})
        for start, end in zip(boundaries, boundaries[1:]):
            if line[start:end].strip():
                yield offset + start, offset + end
        offset += len(line)


class TextAnchors:
    def __init__(self, records, *, known_origins=()):
        self.proofs = {}
        self._segments = set()
        for record in records:
            for _, field, text, start, _ in _ranges(record):
                for begin, end in _segments(text):
                    self._segments.add(self.add({'type': 'text_span', 'ref': deepcopy(record['ref']), 'field': field,
                              'start': start + begin, 'end': start + end, 'quote': text[begin:end]}))
        for proof in known_origins:
            if isinstance(proof, dict) and proof.get('type') == 'text_span':
                self.add(proof)

    def add(self, proof):
        if not isinstance(proof, dict) or proof.get('type') != 'text_span':
            raise ValueError('Only exact text proofs can receive a text anchor')
        validate_source_proof_shape(proof, supporting='kind' in (proof.get('ref') or {}))
        if proof['end'] - proof['start'] != len(proof['quote']):
            raise ValueError('Exact text anchor quote length differs from its span')
        anchor_id = 't_' + hashlib.sha256(canonical_bytes(proof)).hexdigest()[:16]
        if anchor_id in self.proofs and self.proofs[anchor_id] != proof:
            raise ValueError('Exact text anchor identity collision')
        self.proofs[anchor_id] = deepcopy(proof)
        return anchor_id

    def add_ranges(self, records):
        """Register complete context ranges without duplicating line-ID metadata."""
        for record in records:
            for _, field, text, start, end in _ranges(record):
                if text.strip():
                    self.add({'type': 'text_span', 'ref': deepcopy(record['ref']), 'field': field,
                              'start': start, 'end': end, 'quote': text})

    def encode(self, proof):
        anchor_id = 't_' + hashlib.sha256(canonical_bytes(proof)).hexdigest()[:16]
        if self.proofs.get(anchor_id) != proof:
            raise ValueError('Exact text proof was not registered in this request')
        return {'type': 'text_span', 'spanId': anchor_id}

    def decode(self, value):
        if (not isinstance(value, dict) or set(value) != {'type', 'spanId'}
                or value['type'] != 'text_span' or not isinstance(value['spanId'], str)
                or value['spanId'] not in self.proofs):
            raise ValueError('Unknown or invalid exact text anchor')
        return deepcopy(self.proofs[value['spanId']])

    def schema(self, ids=None):
        selected = list(self.proofs if ids is None else ids)
        if not selected:
            return None
        if any(anchor_id not in self.proofs for anchor_id in selected):
            raise ValueError('Text anchor schema contains an unknown identity')
        return {'type': 'object', 'properties': {'type': {'type': 'string', 'enum': ['text_span']},
                'spanId': {'type': 'string', 'enum': selected}},
                'required': ['type', 'spanId'], 'additionalProperties': False}

    def annotate(self, records):
        """Mark registered physical spans while retaining each source character."""
        result = deepcopy(records)
        for record in result:
            for span, field, text, start, end in _ranges(record):
                events = {}
                for anchor_id, proof in self.proofs.items():
                    if (proof['ref'] != record['ref'] or proof['field'] != field
                            or not start <= proof['start'] < proof['end'] <= end):
                        continue
                    begin, finish = proof['start'] - start, proof['end'] - start
                    if text[begin:finish] != proof['quote']:
                        continue
                    events.setdefault(begin, []).append((1, '[' + anchor_id + ']'))
                    # Line/clause IDs need only one marker; the application owns
                    # their exact endpoints. Additional prior multi-line spans
                    # receive closing markers to show their larger extent.
                    if anchor_id not in self._segments:
                        events.setdefault(finish, []).append((0, '[/' + anchor_id + ']'))
                pieces, cursor = [], 0
                for position in sorted(events):
                    pieces.append(text[cursor:position])
                    pieces.extend(marker for _, marker in sorted(events[position]))
                    cursor = position
                pieces.append(text[cursor:])
                span['text'] = ''.join(pieces)
        return result
