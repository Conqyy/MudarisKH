"""Strict syntax for alignment judgments; original proof checks stay authoritative."""
from copy import deepcopy

from src.supporting.contracts import validate_ref, validate_source_proof_shape
from src.supporting.structured_output import object_schema, structured_options


ALIGNMENT_STAGES = frozenset(('source_check', 'search', 'verify', 'context_verify'))
QUOTE_POLICY = (
    '\nText in the originals is marked with application-generated span IDs. '
    'Return text proofs only as {"type":"text_span","spanId":"the exact supplied ID"}. '
    'Do not retype quotes, references, fields or character positions. The application '
    'restores the original proof without changing any source characters. For source '
    'checks use only the named target\'s supportingProofs IDs; for verification use '
    'only its nominatedProofs IDs. For search, select relevant lecture span IDs. '
    'Do not treat span markers as academic content. Visual proofs retain the exact '
    'reference, original asset ID and region required by the response schema.'
)


def alignment_request_policy(policy, task):
    return policy + QUOTE_POLICY if task.get('stage') in ALIGNMENT_STAGES else policy


def _enum(values):
    return {'type': 'string', 'enum': list(values)}


def _reference_schema(references, *, supporting):
    variants = []
    for reference in references:
        validate_ref(reference, supporting=supporting)
        variant = object_schema({key: _enum([value]) for key, value in reference.items()})
        if variant not in variants:
            variants.append(variant)
    if not variants:
        raise ValueError('Alignment requires physically supplied original references')
    return variants[0] if len(variants) == 1 else {'anyOf': variants}


def _text_anchors(batch, task):
    from src.supporting.exact_quotes import resolve_text_span
    from src.supporting.text_anchors import TextAnchors
    lectures = [entry for entry in batch.get('evidence', [])
                if entry.get('disposition') != 'excluded_blank']
    supporting = task.get('supportingEvidence', [])
    records = [*lectures, *supporting]
    anchors = TextAnchors(records)
    normalized = [{**entry, 'ranges': [{**span, 'field': span.get('field', span.get('textField'))}
        for span in entry.get('ranges', [])]} for entry in records]
    known = {}
    if task.get('stage') in ('source_check', 'context_verify'):
        known = task.get('supportingProofs') or {}
    elif task.get('stage') == 'verify':
        known = {target: row.get('lectureProofs', [])
                 for target, row in (task.get('nominatedProofs') or {}).items()}
    all_known = [proof for proofs in (task.get('supportingProofs') or {}).values() for proof in proofs]
    all_known += [proof for row in (task.get('nominatedProofs') or {}).values()
                  for proof in row.get('lectureProofs', [])]
    for proof in all_known:
        if proof.get('type') != 'text_span':
            continue
        validate_source_proof_shape(proof, supporting='kind' in proof.get('ref', {}))
        if resolve_text_span(proof, normalized) != proof:
            raise ValueError('Prior alignment anchor differs from physically supplied text')
        anchors.add(proof)
    target_ids = {target: {anchors.encode(proof)['spanId'] for proof in proofs
                           if proof.get('type') == 'text_span'} for target, proofs in known.items()}
    if task.get('stage') == 'search':
        lecture_refs = [entry['ref'] for entry in lectures]
        allowed = [span_id for span_id, proof in anchors.proofs.items() if proof['ref'] in lecture_refs]
    else:
        allowed = list(dict.fromkeys(span_id for span_ids in target_ids.values() for span_id in sorted(span_ids)))
    return anchors, allowed, target_ids


def encode_alignment_packet(packet):
    """Annotate source text once while keeping the private canonical ledger intact."""
    task = packet.get('task') or {}
    if task.get('stage') not in ALIGNMENT_STAGES:
        return packet
    anchors, _, _ = _text_anchors(packet, task)
    result = deepcopy(packet)
    result['evidence'] = anchors.annotate(result.get('evidence', []))
    result['task']['supportingEvidence'] = anchors.annotate(task.get('supportingEvidence', []))
    if 'supportingProofs' in task:
        result['task']['supportingProofs'] = {
            target: [anchors.encode(proof) if proof.get('type') == 'text_span' else deepcopy(proof)
                     for proof in proofs] for target, proofs in task['supportingProofs'].items()}
    if 'nominatedProofs' in task:
        result['task']['nominatedProofs'] = {
            target: {**deepcopy(row), 'lectureProofs': [
                anchors.encode(proof) if proof.get('type') == 'text_span' else deepcopy(proof)
                for proof in row.get('lectureProofs', [])]}
            for target, row in task['nominatedProofs'].items()}
    return result


def alignment_response_options(batch, task):
    """Leave non-alignment original readers unchanged, including output review."""
    stage = task.get('stage')
    if stage not in ALIGNMENT_STAGES:
        return {}
    targets = task.get('targets')
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(target, dict) or not isinstance(target.get('id'), str)
                   or not target['id'] for target in targets)
            or len({target['id'] for target in targets}) != len(targets)):
        raise ValueError('Alignment requires distinct target identities')
    supporting = stage in ('source_check', 'context_verify')
    evidence = task.get('supportingEvidence', []) if supporting else batch.get('evidence', [])
    references = [entry['ref'] for entry in evidence if entry.get('disposition') != 'excluded_blank']
    anchors, allowed, _ = _text_anchors(batch, task)
    definitions = {'sourceReference': _reference_schema(references, supporting=supporting)}
    ref = {'$ref': '#/$defs/sourceReference'}
    text_schema = anchors.schema(allowed)
    if text_schema is not None:
        definitions['textProof'] = text_schema
    definitions['visualProof'] = object_schema({'type': _enum(['visual_region']), 'ref': ref,
        'assetId': {'type': 'string'}, 'box': {'type': 'array', 'minItems': 4, 'maxItems': 4,
            'items': {'type': 'number', 'minimum': 0, 'maximum': 1}}})
    definitions['proof'] = ({'anyOf': [{'$ref': '#/$defs/textProof'}, {'$ref': '#/$defs/visualProof'}]}
                            if text_schema is not None else {'$ref': '#/$defs/visualProof'})
    proofs = {'type': 'array', 'items': {'$ref': '#/$defs/proof'}}

    def judgment_schema(group, *, context=False):
        fields = {'targetId': _enum(target['id'] for target in group)}
        if supporting:
            fields.update(sourceVerdict=_enum(['established', 'uncertain', 'not_established']),
                          sourceProofs=proofs)
            if stage == 'source_check':
                fields.update(queries={'type': 'array', 'items': {'type': 'string'}, 'maxItems': 3},
                              explicitTeaching={'type': 'boolean'})
            if context or stage == 'context_verify':
                fields.update(decision=_enum(['required', 'not_required', 'unresolved']),
                    contentKind=_enum(['academic_claim', 'hypothetical_data', 'procedural_instruction', 'uncertain']),
                    methodRequired={'type': 'boolean'})
        else:
            verdicts = ['support', 'premise', 'no_support', 'related_anchor', 'conflict', 'explicit_exclusion', 'uncertain']
            if stage == 'verify':
                verdicts = ['support', 'related_anchor', 'conflict', 'explicit_exclusion', 'reject', 'uncertain']
            fields.update(verdict=_enum(verdicts), lectureProofs=proofs)
        fields['reason'] = {'type': 'string'}
        return object_schema(fields)

    if stage == 'source_check':
        regular = [target for target in targets if 'contextForItemId' not in target]
        contextual = [target for target in targets if 'contextForItemId' in target]
        rows = ([judgment_schema(regular)] if regular else []) + (
            [judgment_schema(contextual, context=True)] if contextual else [])
        row = rows[0] if len(rows) == 1 else {'anyOf': rows}
    else:
        row = judgment_schema(targets)
    schema = {**object_schema({'judgments': {'type': 'array', 'minItems': len(targets),
        'maxItems': len(targets), 'items': row}}), '$defs': definitions}
    return structured_options('alignment_' + stage, schema)


def decode_alignment_response(value, batch, task):
    """Restore positions from exact supplied text, never from model arithmetic."""
    if task.get('stage') not in ALIGNMENT_STAGES:
        return value
    from src.supporting.exact_quotes import resolve_text_span
    anchors, allowed, target_ids = _text_anchors(batch, task)
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('judgments'), list):
        raise ValueError('Original response omitted target judgments')
    supporting = task['stage'] in ('source_check', 'context_verify')
    evidence = task.get('supportingEvidence', []) if supporting else batch.get('evidence', [])
    evidence = [entry for entry in evidence if entry.get('disposition') != 'excluded_blank']
    # Lecture source packets call this key textField; supporting packets use
    # field. Both contain the same exact original coordinates and text.
    if not supporting:
        evidence = [{**entry, 'ranges': [{**span, 'field': span.get('textField')}
            for span in entry.get('ranges', [])]} for entry in evidence]
    field = 'sourceProofs' if supporting else 'lectureProofs'
    for row in result['judgments']:
        if not isinstance(row, dict) or not isinstance(row.get(field), list):
            raise ValueError('Invalid original proof list')
        known = []
        if supporting:
            known = (task.get('supportingProofs') or {}).get(row.get('targetId'), [])
        elif task['stage'] == 'verify':
            known = ((task.get('nominatedProofs') or {}).get(row.get('targetId')) or {}).get('lectureProofs', [])
        restored = []
        for proof in row[field]:
            if not isinstance(proof, dict):
                raise ValueError('Invalid original proof')
            if proof.get('type') == 'text_span' and 'spanId' in proof:
                permitted = allowed if task['stage'] == 'search' else target_ids.get(row.get('targetId'), set())
                if proof.get('spanId') not in permitted:
                    raise ValueError('Text span is not an allowed anchor for this alignment target')
                proof = anchors.decode(proof)
            validate_ref(proof.get('ref'), supporting=supporting)
            if proof['ref'] not in [entry['ref'] for entry in evidence]:
                raise ValueError('Original proof reference was not supplied to this request')
            if proof.get('type') == 'text_span':
                matches = [anchor for anchor in known if isinstance(anchor, dict)
                    and all(anchor.get(key) == proof.get(key) for key in ('type', 'ref', 'field', 'quote'))]
                # A nomination or previously established source anchor identifies
                # one occurrence even when its short quote repeats nearby. Its
                # original coordinates must still match physically supplied text.
                if len(matches) == 1:
                    proof = {**proof, 'start': matches[0].get('start'), 'end': matches[0].get('end')}
                restored.append(resolve_text_span(proof, evidence))
            else:
                restored.append(proof)
        row[field] = restored
    return result
