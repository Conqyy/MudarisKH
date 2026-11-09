"""Strict provider schemas and a lossless, request-local original-reference wire format.

Only transport identities change. Decoded claims still pass the existing canonical
proof, window, inventory and coverage validators before entering saved reports.
"""
from copy import deepcopy

from src.supporting.contracts import DISPOSITIONS, ITEM_TYPES, REQUIREMENT_CATEGORIES
from src.utils.ai_contracts import QUESTION_TYPES
from src.supporting.exact_quotes import resolve_text_span
from src.supporting.text_anchors import TextAnchors


WIRE_VERSION = 4
WIRE_PROMPT = '''\nReturn schema JSON only. Text proofs SELECT supplied spanIds: never invent IDs,
copy quotes or calculate offsets. [t_...] markers (some end [/t_...]) are citation
locations, NOT item boundaries. Use distinct first origins; reuse continuation origins.
proofs.current cites the CURRENT window; context holds additional necessary proofs.
Choose the smallest sufficient accurate set, retaining all necessary evidence.
Visual refs use sourceReferences IDs. Preserve complete printed exercises, multiline
code/data and choice labels; split only printed subparts. Strip markers from strings.
Unknown=null; absent arrays=[]. contextOrigins links actual current/prior sharedContexts,
never bare headings; otherwise []. Whole-window cover/nonacademic/answer-key exclusion
retains nonacademic items, requirements=[], and ALL current text IDs/full-page visuals.
Empty blank output requires a truly empty source. Only uncertain audit judgments may
use proofs={"current":null,"context":[]} when no exact evidence can be established.
'''


def structured_options(name, schema):
    """Unsupported providers must fail explicitly, never silently drop the schema."""
    return {'response_format': {'type': 'json_schema', 'json_schema': {
        'name': name, 'strict': True, 'schema': deepcopy(schema)}},
        'extra_body': {'reasoning': {'enabled': False}, 'provider': {'require_parameters': True}}}


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def _array(items):
    return {'type': 'array', 'items': items}


def _enum(values):
    return {'type': 'string', 'enum': list(values)}


def _nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


def _in_current(proof, source):
    if not isinstance(source, dict) or proof.get('ref') != source.get('ref'):
        return False
    if proof.get('type') == 'visual_region':
        return proof.get('assetId') in source.get('assetIds', [])
    if proof.get('type') != 'text_span':
        return False
    return any(span['field'] == proof.get('field') and
               span['start'] <= proof.get('start', -1) < proof.get('end', -1) <= span['end'] and
               span['text'][proof['start'] - span['start']:proof['end'] - span['start']] == proof.get('quote')
               for span in source.get('ranges', []))


def proof_definitions(references, text_anchors=None, *, current_source=None):
    ref = _enum(references)
    text_proof = (text_anchors.schema() if text_anchors is not None else
        object_schema({'type': _enum(['text_span']), 'ref': ref,
                       'field': _enum(['text', 'visualText']), 'quote': {'type': 'string', 'minLength': 1}}))
    result = {
        'visualProof': object_schema({'type': _enum(['visual_region']), 'ref': ref,
            'assetId': {'type': 'string'}, 'box': {'type': 'array', 'minItems': 4, 'maxItems': 4,
                'items': {'type': 'number', 'minimum': 0, 'maximum': 1}}}),
        'proof': {'anyOf': [{'$ref': '#/$defs/visualProof'}]},
    }
    if text_proof is not None:
        result['textProof'] = text_proof
        result['proof']['anyOf'].insert(0, {'$ref': '#/$defs/textProof'})
    if current_source is not None:
        if text_anchors is None:
            raise ValueError('Current-window proof schema requires exact text anchors')
        current_ids = [key for key, proof in text_anchors.proofs.items() if _in_current(proof, current_source)]
        context_ids = [key for key in text_anchors.proofs if key not in current_ids]
        text_choices, current_choices = [], []
        for name, selected in (('currentTextProof', current_ids), ('contextTextProof', context_ids)):
            if selected:
                result[name] = text_anchors.schema(selected)
                text_choices.append({'$ref': '#/$defs/' + name})
        if text_choices:
            result['textProof'] = {'anyOf': text_choices}
        if current_ids:
            current_choices.append({'$ref': '#/$defs/currentTextProof'})
        if current_source.get('assetIds'):
            aliases = [key for key, ref in references.items() if ref == current_source['ref']]
            if len(aliases) != 1:
                raise ValueError('Current source has no unique supplied reference')
            result['currentVisualProof'] = deepcopy(result['visualProof'])
            result['currentVisualProof']['properties'].update(ref=_enum(aliases), assetId=_enum(current_source['assetIds']))
            current_choices.append({'$ref': '#/$defs/currentVisualProof'})
        result['currentProof'] = {'anyOf': current_choices} if current_choices else {'type': 'null'}
        result['claimProofs'] = object_schema({'current': {'$ref': '#/$defs/currentProof'},
                                               'context': _array({'$ref': '#/$defs/proof'})})
    return result


def inventory_schema(references, kind, text_anchors=None, *, current_source=None):
    proof = {'$ref': '#/$defs/proof'}
    proofs = _array(proof)
    claim_proofs = {'$ref': '#/$defs/claimProofs'} if current_source is not None else proofs
    item_types = sorted(ITEM_TYPES)
    requirement = object_schema({'origin': proof, 'text': {'type': 'string'},
                                 'category': _enum(sorted(REQUIREMENT_CATEGORIES))})
    definitions = proof_definitions(references, text_anchors, current_source=current_source)
    definitions['requirementLink'] = requirement
    definitions['requirement'] = object_schema({**requirement['properties'], 'proofs': claim_proofs})
    definitions['itemLink'] = object_schema({'origin': proof, 'itemType': _enum(item_types)})
    definitions['item'] = object_schema({'origin': proof, 'itemType': _enum(item_types),
        'parent': _nullable(object_schema({'origin': proof, 'itemType': _enum(['question', 'subpart'])})),
        'text': {'type': 'string'}, 'textJoin': _enum(['', ' ', '\n']),
        'printedLabel': _nullable({'type': 'string'}), 'printedMarks': _nullable({'type': 'number', 'minimum': 0}),
        'questionType': _nullable(_enum(sorted(QUESTION_TYPES))),
        'choices': _array({'type': 'string'}), 'givenData': _array({'type': 'string'}),
        'contextOrigins': proofs, 'proofs': claim_proofs, 'requirements': _array({'$ref': '#/$defs/requirement'})})
    definitions['context'] = object_schema({'origin': proof, 'text': {'type': 'string'}, 'proofs': claim_proofs})
    definitions['topic'] = object_schema({'text': {'type': 'string'},
        'items': _array({'$ref': '#/$defs/itemLink'}),
        'requirements': _array({'$ref': '#/$defs/requirementLink'}), 'proofs': claim_proofs})
    paper = object_schema({'startsPaper': {'type': 'boolean'}, 'title': {'type': 'string'},
        'examType': _nullable(_enum(['quiz', 'midterm', 'final'])),
        'totalMarks': _nullable({'type': 'number', 'minimum': 0}), 'evidence': {'type': 'string'},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'uncertain': {'type': 'boolean'}})
    result = {**object_schema({'disposition': _enum(sorted(DISPOSITIONS)),
        'pageRole': _enum(['questions', 'answer_key', 'cover', 'blank', 'other', 'uncertain']),
        'paper': paper if kind == 'historical_exam' else {'type': 'null'},
        'items': _array({'$ref': '#/$defs/item'}), 'sharedContexts': _array({'$ref': '#/$defs/context'}),
        'topics': _array({'$ref': '#/$defs/topic'})}), '$defs': definitions}
    if current_source is not None and definitions['currentProof'] == {'type': 'null'}:
        for collection in ('items', 'sharedContexts', 'topics'):
            result['properties'][collection]['maxItems'] = 0
    return result


def audit_schema(references, obligations, text_anchors=None, *, current_source=None):
    proofs = _array({'$ref': '#/$defs/proof'})
    definitions = proof_definitions(references, text_anchors, current_source=current_source)
    if current_source is not None:
        proofs = {'$ref': '#/$defs/claimProofs'}
    judgment = object_schema({'obligationId': _enum(obligations),
        'decision': _enum(['faithful', 'represented', 'nonacademic', 'incorrect', 'uncertain']),
        'firstIds': _array(_enum(key for key in obligations if key.startswith('A/'))),
        'proofs': proofs, 'reason': {'type': 'string'}})
    if current_source is not None:
        uncertain = deepcopy(judgment)
        uncertain['properties']['decision'] = _enum(['uncertain'])
        uncertain['properties']['proofs'] = object_schema({'current': {'type': 'null'},
            'context': {**_array({'$ref': '#/$defs/proof'}), 'maxItems': 0}})
        judgment = {'anyOf': [judgment, uncertain]} if definitions['currentProof'] != {'type': 'null'} else uncertain
    result = {**object_schema({'verdict': _enum(['accept_first', 'reject', 'uncertain']),
        'missingContent': _array(object_schema({'text': {'type': 'string'}, 'proofs': proofs})),
        'judgments': _array(judgment)}), '$defs': definitions}
    if current_source is not None and definitions['currentProof'] == {'type': 'null'}:
        result['properties']['verdict'] = _enum(['reject', 'uncertain'])
        result['properties']['missingContent']['maxItems'] = 0
    return result


def source_references(source, previous, continuity=None, *, known_proofs=()):
    """Register only physically supplied records and explicit prior origin anchors."""
    refs = {}
    def add(ref):
        if ref not in refs.values():
            refs['s' + str(len(refs))] = deepcopy(ref)
    for record in (source, previous):
        if record is not None:
            add(record['ref'])
    for collection in ('items', 'sharedContexts'):
        for row in (continuity or {}).get(collection, []):
            add(row['origin']['ref'])
    for proof in known_proofs:
        add(proof['ref'])
    return refs


def encode_proof(proof, references, text_anchors=None):
    if proof.get('type') == 'text_span' and text_anchors is not None:
        return text_anchors.encode(proof)
    result = deepcopy(proof)
    for key, ref in references.items():
        if result['ref'] == ref:
            result['ref'] = key
            return result
    raise ValueError('Original proof reference was not supplied to this request')


def transport_envelope(envelope, references, text_anchors=None):
    result = deepcopy(envelope)
    result['sourceReferences'] = deepcopy(references)
    for name in ('source', 'previous'):
        record = result.get(name)
        if record is not None:
            record['sourceId'] = next(key for key, ref in references.items() if ref == record['ref'])
            if text_anchors is not None:
                result[name] = text_anchors.annotate([record])[0]
            result[name]['ref'] = record['sourceId']
    for collection in ('items', 'sharedContexts'):
        for row in result.get('continuity', {}).get(collection, []):
            row['origin'] = encode_proof(row['origin'], references, text_anchors)
    return result


def _decode_proof(proof, references, records, known_origins=(), text_anchors=None):
    if not isinstance(proof, dict):
        raise ValueError('Missing or invalid compact original proof reference')
    if proof.get('type') == 'text_span' and 'spanId' in proof:
        if text_anchors is None:
            raise ValueError('Exact text anchor registry is unavailable')
        canonical = text_anchors.decode(proof)
        proof.clear()
        proof.update(canonical)
        return
    reference = proof.get('ref')
    if not isinstance(reference, str) or reference not in references:
        raise ValueError('Unknown or invalid compact original proof reference')
    proof['ref'] = deepcopy(references[reference])
    if proof.get('type') == 'text_span':
        proof.update(resolve_text_span(proof, records, known_origins=known_origins))


def _decode_row(row, references, records, known_origins, text_anchors, *, origin=False,
                wire_version=None, allow_empty_current=False):
    if not isinstance(row, dict):
        raise ValueError('Invalid original inventory record')
    if origin:
        _decode_proof(row.get('origin'), references, records, known_origins, text_anchors)
    if wire_version == 4:
        claims = row.get('proofs')
        if not isinstance(claims, dict) or set(claims) != {'current', 'context'} or not isinstance(claims['context'], list):
            raise ValueError('Missing or invalid current claim proof')
        if claims['current'] is None:
            if not allow_empty_current or claims['context']:
                raise ValueError('Claim needs current-window proof')
            row['proofs'] = []
            return
        _decode_proof(claims['current'], references, records, text_anchors=text_anchors)
        if not records or not _in_current(claims['current'], records[0]):
            raise ValueError('Claim current proof was not supplied in the current source window')
        row['proofs'] = [claims['current']]
        for proof in claims['context']:
            _decode_proof(proof, references, records, text_anchors=text_anchors)
            if proof not in row['proofs']:
                row['proofs'].append(proof)
        return
    if not isinstance(row.get('proofs'), list):
        raise ValueError('Missing or invalid original proofs')
    for proof in row['proofs']:
        _decode_proof(proof, references, records, text_anchors=text_anchors)


def decode_inventory(value, references, *, records=(), known_origins=(), text_anchors=None, wire_version=None):
    """Transform only schema proof positions; original data and strings are untouched."""
    result = deepcopy(value)
    if not isinstance(result, dict):
        raise ValueError('Invalid compact inventory response')
    for collection in ('items', 'sharedContexts', 'topics'):
        if not isinstance(result.get(collection), list):
            raise ValueError('Missing inventory ' + collection)
        for row in result[collection]:
            _decode_row(row, references, records, known_origins, text_anchors,
                        origin=collection != 'topics', wire_version=wire_version)
            if collection == 'items':
                if row.get('parent') is not None:
                    if not isinstance(row['parent'], dict):
                        raise ValueError('Invalid original parent')
                    _decode_proof(row['parent'].get('origin'), references, records, known_origins, text_anchors)
                if not isinstance(row.get('contextOrigins'), list):
                    raise ValueError('Invalid original context origins')
                for proof in row['contextOrigins']:
                    _decode_proof(proof, references, records, known_origins, text_anchors)
                if not isinstance(row.get('requirements'), list):
                    raise ValueError('Invalid original requirements')
                for requirement in row['requirements']:
                    _decode_row(requirement, references, records, known_origins, text_anchors,
                                origin=True, wire_version=wire_version)
            elif collection == 'topics':
                for links in ('items', 'requirements'):
                    if not isinstance(row.get(links), list):
                        raise ValueError('Invalid original topic links')
                    for link in row[links]:
                        if not isinstance(link, dict):
                            raise ValueError('Invalid original topic link')
                        _decode_proof(link.get('origin'), references, records, known_origins, text_anchors)
    return result


def decode_audit(value, references, *, records=(), text_anchors=None, wire_version=None):
    result = deepcopy(value)
    if not isinstance(result, dict):
        raise ValueError('Invalid compact audit response')
    for name in ('missingContent', 'judgments'):
        if not isinstance(result.get(name), list):
            raise ValueError('Invalid audit ' + name)
        for row in result[name]:
            _decode_row(row, references, records, (), text_anchors, wire_version=wire_version,
                        allow_empty_current=name == 'judgments' and isinstance(row, dict) and row.get('decision') == 'uncertain')
    return result
