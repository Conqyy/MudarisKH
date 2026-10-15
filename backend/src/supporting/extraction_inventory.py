"""Validate original anchors, join fragments, and reconcile independent inventories."""
from copy import deepcopy
import math

from src.supporting.contracts import (canonical_bytes, digest, validate_source_proof,
    ITEM_TYPES, REQUIREMENT_CATEGORIES, DISPOSITIONS)
from src.supporting.extraction_source import reference
from src.utils.ai_contracts import QUESTION_TYPES


def text(value, label, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError('Missing or invalid ' + label)
    return value


def array(value, label):
    if not isinstance(value, list):
        raise ValueError('Missing or invalid ' + label)
    return value


def object_row(value, label):
    if not isinstance(value, dict):
        raise ValueError('Missing or invalid ' + label)
    return value


def enum(value, choices, label):
    if not isinstance(value, str) or value not in choices:
        raise ValueError('Missing or invalid ' + label)
    return value


def anchor(proof):
    """Identity is location, not a generated label or the chosen quote length."""
    if proof['type'] == 'text_span':
        return {k: proof[k] for k in ('type', 'ref', 'field', 'start')}
    return {k: proof[k] for k in ('type', 'ref', 'assetId', 'box')}


def identifier(origin, kind):
    return kind + '-' + digest(anchor(origin))[:32]


def requirement_id(row):
    return 'requirement-' + digest({'origin': anchor(row['origin']), 'text': row['text'], 'category': row['category']})[:32]


def unique(values):
    found = {}
    for value in values:
        found[canonical_bytes(value)] = value
    return list(found.values())


def _marks(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        raise ValueError('Invalid printed marks')


def validate_response(value, manifest, source, previous, earlier):
    """Only exact supplied originals authorize new content; old anchors authorize joins."""
    value = deepcopy(value)
    object_row(value, 'inventory response')
    enum(value.get('disposition'), DISPOSITIONS, 'original readability disposition')
    enum(value.get('pageRole'), ('questions', 'answer_key', 'cover', 'blank', 'other', 'uncertain'), 'original page role')
    units = {u['unitId']: u for u in manifest['units']}
    known = set()
    for old in earlier:
        for collection in ('items', 'sharedContexts'):
            for row in old[collection]:
                known.add(canonical_bytes(anchor(row['origin'])))
                for req in row.get('requirements', []):
                    known.add(canonical_bytes(anchor(req['origin'])))

    def check(proof, *, origin=False, current=False):
        object_row(proof, 'exact original proof')
        ref = object_row(proof.get('ref'), 'exact original proof reference')
        for key in ('kind', 'materialId', 'sourceRevision', 'unitId'):
            text(ref.get(key), 'original proof reference ' + key)
        enum(proof.get('type'), ('text_span', 'visual_region'), 'original proof type')
        unit = units.get(ref['unitId'])
        if unit is None:
            raise ValueError('Unknown original proof unit')
        validate_source_proof(proof, ref=reference(manifest, unit), unit=unit)
        if origin and canonical_bytes(anchor(proof)) in known:
            return
        for record in [source] if current else [source, previous]:
            if not record or record['ref'] != proof['ref']:
                continue
            if proof['type'] == 'visual_region' and proof['assetId'] in record['assetIds']:
                return
            if proof['type'] == 'text_span' and any(r['field'] == proof['field'] and
                    r['start'] <= proof['start'] < proof['end'] <= r['end'] for r in record['ranges']):
                return
        raise ValueError('Proof was not supplied in this original evidence window')

    def proofs(row):
        values = array(row.get('proofs'), 'original proofs')
        if not values:
            raise ValueError('Every extracted claim requires original proofs')
        for proof in values:
            check(proof)
        if not any(p['ref'] == source['ref'] for p in values):
            raise ValueError('Context-only content cannot become a new fragment')
        # At least one location must actually be in the current (not previous) range.
        for proof in values:
            try:
                check(proof, current=True)
                break
            except ValueError:
                continue
        else:
            raise ValueError('Fragment has no current original evidence')

    for collection in ('items', 'sharedContexts', 'topics'):
        array(value.get(collection), collection)
        for row in value[collection]:
            object_row(row, 'inventory record')
    paper = value.get('paper')
    if manifest['identity']['kind'] == 'historical_exam':
        object_row(paper, 'historical boundary decision')
        for key in ('examType', 'totalMarks'):
            paper.setdefault(key, None)
        if type(paper.get('startsPaper')) is not bool or type(paper.get('uncertain')) is not bool:
            raise ValueError('Invalid original boundary decision')
        confidence = paper.get('confidence')
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('Invalid original boundary confidence')
        text(paper.get('title'), 'paper title')
        text(paper.get('evidence'), 'boundary evidence')
        if paper.get('examType') not in (None, 'quiz', 'midterm', 'final'):
            raise ValueError('Invalid paper type')
        _marks(paper.get('totalMarks'))
    else:
        value['paper'] = None
    for row in value['sharedContexts']:
        check(row.get('origin'), origin=True)
        text(row.get('text'), 'shared context')
        proofs(row)
    for row in value['items']:
        enum(row.get('itemType'), ITEM_TYPES, 'extracted item type')
        for key in ('parent', 'printedLabel', 'printedMarks', 'questionType'):
            row.setdefault(key, None)
        if row['questionType'] is not None:
            enum(row['questionType'], QUESTION_TYPES, 'observed question type; use null when unknown')
        check(row.get('origin'), origin=True)
        text(row.get('text'), 'question text', empty=row['itemType'] == 'nonacademic')
        if row.get('textJoin', '\n') not in ('', ' ', '\n'):
            raise ValueError('Invalid original continuation separator')
        if row.get('printedLabel') is not None:
            text(row['printedLabel'], 'printed label')
        _marks(row.get('printedMarks'))
        for key in ('choices', 'givenData', 'contextOrigins', 'requirements'):
            array(row.get(key), key)
        parent = row.get('parent')
        if parent is not None:
            object_row(parent, 'parent origin')
            enum(parent.get('itemType'), ('question', 'subpart'), 'parent item type')
            check(parent.get('origin'), origin=True)
        for origin in row['contextOrigins']:
            check(origin, origin=True)
        proofs(row)
        for requirement in row['requirements']:
            object_row(requirement, 'atomic requirement')
            text(requirement.get('text'), 'requirement')
            enum(requirement.get('category'), REQUIREMENT_CATEGORIES, 'requirement category')
            check(requirement.get('origin'), origin=True)
            proofs(requirement)
        ids = [requirement_id(r) for r in row['requirements']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate original atomic requirement')
    for row in value['topics']:
        text(row.get('text'), 'topic claim')
        if not array(row.get('items'), 'topic origins') or not array(row.get('requirements'), 'topic requirements'):
            raise ValueError('Topic requires originating items and exact requirements')
        for origin in row['items']:
            object_row(origin, 'topic item origin')
            enum(origin.get('itemType'), ITEM_TYPES, 'topic item type')
            check(origin.get('origin'), origin=True)
        for req in row['requirements']:
            object_row(req, 'topic requirement')
            check(req.get('origin'), origin=True)
            text(req.get('text'), 'topic requirement')
            enum(req.get('category'), REQUIREMENT_CATEGORIES, 'topic requirement category')
        proofs(row)
    for collection in ('items', 'sharedContexts'):
        identities = [identifier(row['origin'], row['itemType'] if collection == 'items' else 'context') for row in value[collection]]
        if len(identities) != len(set(identities)):
            raise ValueError('Duplicate original origin in one response')
    if value['pageRole'] == 'answer_key' and any(i['itemType'] != 'nonacademic' for i in value['items']):
        raise ValueError('Answer keys cannot create new academic questions')
    if value['disposition'] in ('blank', 'nonacademic') and any(i['itemType'] != 'nonacademic' for i in value['items']):
        raise ValueError('Nonacademic disposition conflicts with extracted questions')
    if value['disposition'] == 'readable' and value['pageRole'] not in ('answer_key', 'cover') and not (value['items'] or value['sharedContexts']):
        raise ValueError('Readable question evidence has no extracted items')
    canonical_bytes(value)
    return value


def inventory(manifest, plan, responses):
    """Rebuild deterministic joins from accepted source-ordered checkpoint rows."""
    items, contexts, topics, papers, errors = {}, {}, {}, {}, {}
    current_paper = None
    def issue(unit, reason):
        errors.setdefault(unit, []).append(reason)

    def evidence(row):
        return {'supportingSourceProofs': unique(row['proofs']),
                'supportingSourceRefs': unique([p['ref'] for p in row['proofs']])}

    def merge(target, row, unit, separator='\n'):
        existing = target.get(row['id'])
        if existing is None:
            target[row['id']] = row
            return
        for field in ('parentId', 'paperId', 'printedLabel', 'printedMarks', 'itemType', 'questionType'):
            if field in row and existing[field] != row[field]:
                issue(unit, 'Continuation changes ' + field)
        fresh = [p for p in row['supportingSourceProofs'] if p not in existing['supportingSourceProofs']]
        if fresh:
            existing['text'] += separator + row['text']
        elif row['text'] != existing['text']:
            issue(unit, 'Same original origin has contradictory text')
        for field in ('supportingSourceProofs', 'supportingSourceRefs', 'choices', 'givenData', 'sharedContextIds'):
            if field in row:
                existing[field] = unique(existing[field] + row[field])
        if 'requirements' in row:
            requirements = {r['id']: r for r in existing['requirements']}
            for requirement in row['requirements']:
                original = requirements.get(requirement['id'])
                if original is None:
                    requirements[requirement['id']] = requirement
                    continue
                if any(original[key] != requirement[key] for key in ('text', 'category')):
                    issue(unit, 'Continued atomic requirement has contradictory content')
                    continue
                for field in ('supportingSourceRefs', 'supportingSourceProofs'):
                    original[field] = unique(original[field] + requirement[field])
            existing['requirements'] = list(requirements.values())

    for index, response in sorted(responses.items(), key=lambda pair: int(pair[0])):
        source = plan[int(index)]
        unit = source['ref']['unitId']
        paper = response['paper']
        if response['disposition'] in ('uncertain', 'unsupported') or response['pageRole'] == 'uncertain':
            issue(unit, 'Original readability or page role is unresolved')
        if paper:
            if paper['uncertain'] or paper['confidence'] < .75:
                issue(unit, 'Paper boundary is uncertain')
            if paper['startsPaper']:
                current_paper = 'paper-' + digest(source['ref'])[:32]
                papers.setdefault(current_paper, {'paperId': current_paper, 'title': paper['title'], 'unitIds': [],
                    'questionIds': [], 'totalQuestions': 0, 'totalMarks': paper['totalMarks'],
                    'examType': paper['examType'], 'boundaryEvidence': paper['evidence'],
                    'boundaryConfidence': paper['confidence']})
            if current_paper is None:
                if manifest['fileType'] == 'image':
                    current_paper = 'paper-' + digest(source['ref'])[:32]
                    papers[current_paper] = {'paperId': current_paper, 'title': paper['title'], 'unitIds': [],
                        'questionIds': [], 'totalQuestions': 0, 'totalMarks': None, 'examType': None,
                        'boundaryEvidence': 'Individual photo input', 'boundaryConfidence': None}
                else:
                    issue(unit, 'Original begins mid-paper or lacks a supported boundary')
            if current_paper:
                papers[current_paper]['unitIds'] = unique(papers[current_paper]['unitIds'] + [unit])
                papers[current_paper]['supportingSourceRefs'] = unique(papers[current_paper].get('supportingSourceRefs', []) + [source['ref']])
        for row in response['sharedContexts']:
            merge(contexts, {'id': identifier(row['origin'], 'context'), 'text': row['text'], **evidence(row)}, unit)
        for row in response['items']:
            parent = row.get('parent')
            new = {'id': identifier(row['origin'], row['itemType']), 'parentId': identifier(parent['origin'], parent['itemType']) if parent else None,
                'paperId': current_paper, **{k: row[k] for k in ('itemType', 'text', 'printedLabel', 'printedMarks', 'choices', 'givenData')},
                'questionType': row.get('questionType'),
                'sharedContextIds': [identifier(p, 'context') for p in row['contextOrigins']],
                'requirements': [{'id': requirement_id(req), 'text': req['text'], 'category': req['category'], **evidence(req)} for req in row['requirements']],
                **evidence(row)}
            merge(items, new, unit, row.get('textJoin', '\n'))
        for row in response['topics']:
            iid = [identifier(r['origin'], r['itemType']) for r in row['items']]
            rid = [requirement_id(r) for r in row['requirements']]
            tid = 'topic-' + digest({'text': row['text'], 'requirementIds': sorted(rid)})[:32]
            topics[tid] = {'id': tid, 'text': row['text'], 'itemIds': unique(iid), 'requirementIds': unique(rid), **evidence(row)}
    for item in items.values():
        unit = item['supportingSourceRefs'][0]['unitId']
        ancestors, parent = {item['id']}, item['parentId']
        while parent:
            if parent in ancestors or parent not in items:
                issue(unit, 'Missing or cyclic parent origin')
                break
            ancestors.add(parent)
            if items[parent]['paperId'] != item['paperId']:
                issue(unit, 'Parent belongs to a different original paper')
            parent = items[parent]['parentId']
        if not set(item['sharedContextIds']) <= contexts.keys():
            issue(unit, 'Unresolved shared context origin')
        if item['itemType'] != 'nonacademic' and not item['requirements'] and not any(i['parentId'] == item['id'] for i in items.values()):
            issue(unit, 'Academic item has no requirements')
        if item['itemType'] == 'nonacademic' and item['requirements']:
            issue(unit, 'Nonacademic item has academic requirements')
        if item['itemType'] == 'question' and item['paperId'] in papers:
            papers[item['paperId']]['questionIds'].append(item['id'])
    requirements = {}
    for item in items.values():
        for req in item['requirements']:
            if req['id'] in requirements and requirements[req['id']] != item['id']:
                issue(item['supportingSourceRefs'][0]['unitId'], 'Atomic requirement is duplicated across original items')
            requirements[req['id']] = item['id']
    for topic in topics.values():
        unit = topic['supportingSourceRefs'][0]['unitId']
        if (not set(topic['itemIds']) <= items.keys() or not set(topic['requirementIds']) <= requirements.keys() or
                any(requirements.get(r) not in topic['itemIds'] for r in topic['requirementIds'])):
            issue(unit, 'Topic requirement is missing or belongs to an unrelated item')
    for paper in papers.values():
        paper['questionIds'] = unique(paper['questionIds'])
        paper['totalQuestions'] = len(paper['questionIds'])
        formats = {}
        paper['unknownQuestionTypeIds'] = []
        for qid in paper['questionIds']:
            question_type = items[qid]['questionType']
            if question_type is None:
                paper['unknownQuestionTypeIds'].append(qid)
            else:
                formats.setdefault(question_type, []).append(qid)
        paper['questionTypes'] = [{'type': kind, 'count': len(ids), 'questionIds': ids} for kind, ids in formats.items()]
    return {'items': list(items.values()), 'sharedContexts': list(contexts.values()), 'papers': list(papers.values()),
            'topics': list(topics.values())}, errors


def comparable(response):
    value = deepcopy(response)
    if value.get('paper'):
        # Reason wording/confidence can vary; academic facts and identities cannot.
        for key in ('evidence', 'confidence'):
            value['paper'].pop(key, None)
    return value


def coverage(manifest, plan, extracted, reconciled, errors):
    unresolved = set(errors)
    accounted = []
    for unit in manifest['units']:
        indices = [str(i) for i, source in enumerate(plan) if source['ref']['unitId'] == unit['unitId']]
        for index in indices:
            if index not in extracted or index not in reconciled:
                unresolved.add(unit['unitId'])
            elif comparable(extracted[index]) != comparable(reconciled[index]):
                unresolved.add(unit['unitId'])
                errors.setdefault(unit['unitId'], []).append('Independent original reconciliation disagrees')
        if unit['disposition'] in ('uncertain', 'unsupported'):
            unresolved.add(unit['unitId'])
        if all(i in extracted and i in reconciled for i in indices):
            accounted.append(unit['unitId'])
    ids = [u['unitId'] for u in manifest['units']]
    def submitted(rows):
        records = [deepcopy(plan[int(i)]) for i in rows]
        for record in records:
            for span in record['ranges']:
                span.pop('text')
        return records
    return {'unitIds': ids, 'accountedUnitIds': accounted, 'unresolvedUnitIds': [u for u in ids if u in unresolved],
            'complete': len(accounted) == len(ids) and not unresolved, 'reasons': errors,
            'dispositions': {u: unique([r['disposition'] for i, r in extracted.items() if plan[int(i)]['ref']['unitId'] == u]) for u in ids},
            'pageRoles': {u: unique([r['pageRole'] for i, r in extracted.items() if plan[int(i)]['ref']['unitId'] == u]) for u in ids},
            'submitted': {'extract': submitted(extracted), 'reconcile': submitted(reconciled)}}
