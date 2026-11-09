"""Resolve model quotes against exact supplied text, without model arithmetic.

This is a transport decoder, not evidence validation. Callers must still run the
canonical source/window validators after decoding. No text is normalized, joined,
searched outside the supplied ranges, or replaced with a similar substring.
"""
from copy import deepcopy


def resolve_text_span(proof, records, *, known_origins=()):
    """Return one exact canonical span, preserving already valid legacy offsets.

    ``known_origins`` must come from an accepted ledger and may be used only for
    origin/continuation fields. They do not authorize a new claim's evidence.
    """
    if (not isinstance(proof, dict) or proof.get('type') != 'text_span'
            or not isinstance(proof.get('ref'), dict)
            or proof.get('field') not in ('text', 'visualText')
            or not isinstance(proof.get('quote'), str) or not proof['quote']):
        raise ValueError('Invalid exact original text quote')
    quote, field, reference = proof['quote'], proof['field'], proof['ref']
    matches = set()
    for record in records:
        if not isinstance(record, dict) or record.get('ref') != reference:
            continue
        for span in record.get('ranges', []):
            if not isinstance(span, dict) or span.get('field') != field:
                continue
            text, start, end = span.get('text'), span.get('start'), span.get('end')
            if (not isinstance(text, str) or type(start) is not int or type(end) is not int
                    or start < 0 or end < start or end - start != len(text)):
                raise ValueError('Invalid exact supplied text range')
            offset = text.find(quote)
            while offset >= 0:
                matches.add((start + offset, start + offset + len(quote)))
                offset = text.find(quote, offset + 1)
    for known in known_origins:
        if (not isinstance(known, dict) or known.get('type') != 'text_span'
                or known.get('ref') != reference or known.get('field') != field
                or known.get('quote') != quote):
            continue
        start, end = known.get('start'), known.get('end')
        if type(start) is int and type(end) is int and 0 <= start < end and end - start == len(quote):
            matches.add((start, end))
    provided = (proof.get('start'), proof.get('end'))
    valid_offsets = all(type(value) is int for value in provided)
    if valid_offsets and provided in matches:
        selected = provided
    elif len(matches) == 1:
        selected = next(iter(matches))
    elif matches:
        raise ValueError('Ambiguous exact original quote; include enough original text to identify one occurrence')
    else:
        raise ValueError('Exact original quote was not found in the supplied evidence')
    result = deepcopy(proof)
    result['start'], result['end'] = selected
    return result
