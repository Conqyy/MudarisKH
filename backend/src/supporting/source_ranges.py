"""Select contiguous original physical lines without asking a model to copy them.

This registry accepts one current evidence window. It does not interpret line
boundaries as questions or authorize previous sources. Canonical original-source
validation remains mandatory after decoding a provider selection.
"""
from copy import deepcopy

from src.supporting.contracts import digest, validate_ref, validate_source_proof_shape


class SourceRanges:
    def __init__(self, source):
        if not isinstance(source, dict) or not isinstance(source.get('ranges'), list):
            raise ValueError('Invalid current source ranges')
        self._ref = validate_ref(source.get('ref'), supporting=True)
        self._ranges = []
        self._lines = {}
        for original in source['ranges']:
            if not isinstance(original, dict):
                raise ValueError('Invalid exact supplied text range')
            span = {key: original.get(key) for key in ('field', 'start', 'end', 'text')}
            if (span['field'] not in ('text', 'visualText') or not isinstance(span['text'], str)
                    or type(span['start']) is not int or type(span['end']) is not int
                    or span['start'] < 0 or span['end'] < span['start']
                    or span['end'] - span['start'] != len(span['text'])):
                raise ValueError('Invalid exact supplied text range')
            range_key = digest({'ref': self._ref, 'range': span})
            span['lines'] = []
            offset = span['start']
            for number, text in enumerate(span['text'].splitlines(keepends=True), 1):
                line_id = 'l_' + digest({'range': range_key, 'start': offset,
                                         'end': offset + len(text)})[:16]
                if line_id in self._lines:
                    raise ValueError('Duplicate source range or physical-line identity collision')
                line = {'id': line_id, 'line': number,
                        'start': offset, 'end': offset + len(text), 'text': text}
                span['lines'].append(line)
                self._lines[line['id']] = (span, line)
                offset += len(text)
            self._ranges.append(span)

    def presentation(self):
        """Raw unchanged ranges and a detached locator table for each range."""
        return deepcopy({'ref': self._ref, 'ranges': self._ranges})

    def schema(self):
        """The decoder also enforces ordering, range identity, and nonblank text."""
        if not any(span['text'].strip() for span in self._ranges):
            return None
        return {'type': 'object', 'properties': {
            key: {'type': 'string', 'enum': list(self._lines)}
            for key in ('firstLine', 'lastLine')},
            'required': ['firstLine', 'lastLine'], 'additionalProperties': False}

    def decode(self, selection):
        """Restore the exact inclusive physical-line run as a canonical proof."""
        if (not isinstance(selection, dict) or set(selection) != {'firstLine', 'lastLine'}
                or any(not isinstance(value, str) or value not in self._lines
                       for value in selection.values())):
            raise ValueError('Unknown or invalid current-source line selection')
        span, first = self._lines[selection['firstLine']]
        last_span, last = self._lines[selection['lastLine']]
        if span is not last_span or first['start'] > last['start']:
            raise ValueError('Line selection must stay ordered within one current source range')
        begin, end = first['start'], last['end']
        return validate_source_proof_shape({'type': 'text_span', 'ref': self._ref,
            'field': span['field'], 'start': begin, 'end': end,
            'quote': span['text'][begin - span['start']:end - span['start']]})
