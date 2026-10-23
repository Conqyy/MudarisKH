"""Field-aware provenance checks for generated academic output.

The model selects a JSON Pointer and, optionally, a unique exact quote. Only
the backend determines final offsets and reads cited immutable originals.
"""

from copy import deepcopy
import json
import re

from src.supporting.contracts import validate_ref, validate_source_proof
from src.supporting.alignment_evidence import proof_batch
from src.services.source_evidence import saved_question_identity, exam_shared_context
from src.utils.ai_contracts import validate_supporting_output


_AUTHORITIES = frozenset(('lecture', 'supplementary', 'reported_note'))
_QUALIFIED = frozenset(('outside_selected_scope', 'conflicting', 'unverified', 'not_found'))


def _fields(view, purpose):
    fields = {}
    def add(path, value):
        if not isinstance(value, str): raise ValueError('Academic output field is not text')
        if value.strip(): fields[path] = value
    if purpose == 'summary':
        add('/overview', view.get('overview', ''))
        for i, section in enumerate(view.get('sections', [])):
            for key in ('heading', 'content'):
                add(f'/sections/{i}/{key}', section.get(key, ''))
            for j, point in enumerate(section.get('keyPoints', [])):
                add(f'/sections/{i}/keyPoints/{j}', point)
        for i, term in enumerate(view.get('keyTerms', [])):
            for key in ('term', 'definition'):
                add(f'/keyTerms/{i}/{key}', term.get(key, ''))
        for i, focus in enumerate(view.get('examFocus', [])):
            add(f'/examFocus/{i}', focus)
    elif purpose == 'flashcards':
        for key in ('front', 'back', 'topic'): add('/' + key, view.get(key, ''))
    elif purpose == 'tutor':
        add('/reply', view.get('reply', ''))
    elif purpose == 'exam':
        add('/sharedContext', view.get('sharedContext', ''))
        for qid, row in view.get('questions', {}).items():
            for key in ('text', 'correct_answer', 'criteria', 'explanation'):
                add(f'/questions/{qid}/{key}', row.get(key, ''))
    else:
        raise ValueError('Unknown generated output purpose')
    return fields


def _proofs(value, key):
    """Collect only typed proof fields, never arbitrary matching prose."""
    found = []
    if isinstance(value, dict):
        for field, child in value.items():
            if field == key and isinstance(child, list):
                found.extend(proof for proof in child if isinstance(proof, dict))
            else:
                found.extend(_proofs(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_proofs(child, key))
    return found


def _proof_relations(value, proof):
    """Relations attached to the exact checked proof, not nearby topic labels."""
    found = set()
    if isinstance(value, dict):
        if proof in value.get('supportingSourceProofs', []):
            relation = value.get('relation')
            if isinstance(relation, str): found.add(relation)
            found.update(value.get('relations', []))
        for child in value.values(): found.update(_proof_relations(child, proof))
    elif isinstance(value, list):
        for child in value: found.update(_proof_relations(child, proof))
    return found


def _paired_lecture_proofs(value, proof, anchors):
    """Only an alignment component containing this proof may anchor it."""
    found = []
    if isinstance(value, dict):
        if proof in value.get('supportingSourceProofs', []):
            found.extend(row for row in value.get('lectureSupportProofs', [])
                         if isinstance(row, dict) and row.get('ref') in anchors)
        for child in value.values(): found.extend(_paired_lecture_proofs(child, proof, anchors))
    elif isinstance(value, list):
        for child in value: found.extend(_paired_lecture_proofs(child, proof, anchors))
    return found


def _citation_union(row, claims):
    for key in ('sourceRefs', 'supportingSourceRefs'):
        values = []
        for claim in claims:
            for ref in claim[key]:
                if ref not in values: values.append(deepcopy(ref))
        proposed = row.get(key)
        if proposed is not None and (not isinstance(proposed, list)
                                     or any(ref not in proposed for ref in values)):
            raise ValueError('Claim citation is absent from its enclosing row')
        row[key] = values


def rebase_summary_provenance(before, after):
    """Carry selectors across deterministic pruning only when target text survives."""
    old_fields, new_fields = _fields(before, 'summary'), _fields(after, 'summary')
    mapping = {'/overview': '/overview'}
    for collection, academic_keys in (('sections', ('heading', 'content', 'keyPoints')),
                                      ('keyTerms', ('term', 'definition')),
                                      ('examFocus', None)):
        old_rows, new_rows = before.get(collection, []), after.get(collection, [])
        def signature(row):
            academic = ({key: row.get(key) for key in academic_keys} if academic_keys else row)
            return json.dumps(academic, ensure_ascii=False, sort_keys=True)
        signatures = [signature(row) for row in new_rows]
        for old_index, row in enumerate(old_rows):
            matches = [i for i, current in enumerate(signatures) if current == signature(row)]
            if len(matches) > 1:
                raise ValueError('Summary pruning left ambiguous provenance targets')
            if not matches: continue
            old_prefix = f'/{collection}/{old_index}'
            new_prefix = f'/{collection}/{matches[0]}'
            mapping.update({path: new_prefix + path[len(old_prefix):]
                            for path in old_fields if path == old_prefix or path.startswith(old_prefix + '/')})
    rebased = []
    for selector in before.get('provenance', []):
        if not isinstance(selector, dict) or selector.get('path') not in old_fields:
            raise ValueError('Summary provenance points outside original output')
        old_path = selector['path']
        new_path = mapping.get(old_path)
        if new_path is None: continue
        if new_fields.get(new_path) != old_fields[old_path]:
            raise ValueError('Summary pruning changed a claim target')
        rebased.append({**selector, 'path': new_path})
    after['provenance'] = rebased
    return after


class SupportingOutputVerifier:
    def __init__(self, lecture_reader, library):
        self.lecture_reader = lecture_reader
        self.library = library

    @staticmethod
    def _selected(packet):
        if not isinstance(packet, dict) or packet.get('version') != 1:
            raise ValueError('Checked supporting packet is required')
        snapshot = packet.get('snapshot') or {}
        if snapshot.get('version') != 1 or not isinstance(snapshot.get('materials'), list):
            raise ValueError('Checked supporting snapshot is required')
        return {(row['identity']['kind'], row['identity']['materialId'], row['sourceRevision']): row
                for row in snapshot['materials']}

    def _resolve(self, view, packet, purpose, *, qualified=False, saved=False):
        if purpose != 'exam':
            validate_supporting_output(view, purpose, saved=saved)
        fields = _fields(view, purpose)
        selectors = view.get('provenance')
        if not isinstance(selectors, list):
            raise ValueError('Generated academic output requires provenance')
        if len(selectors) > 1024:
            raise ValueError('Generated provenance exceeds the bounded claim budget; split the request')
        selected = self._selected(packet)
        covered = {path: set() for path in fields}
        canonical = []
        for selector in selectors:
            if not isinstance(selector, dict) or not isinstance(selector.get('path'), str):
                raise ValueError('Invalid provenance selector')
            path = selector['path']
            if path not in fields: raise ValueError('Provenance points outside final academic output')
            target = fields[path]
            if saved:
                start, end = selector.get('start'), selector.get('end')
                if (type(start) is not int or type(end) is not int or start < 0
                        or end > len(target) or start >= end or 'quote' in selector):
                    raise ValueError('Saved provenance span differs from final output')
            else:
                if 'start' in selector or 'end' in selector:
                    raise ValueError('Model-authored offsets are forbidden; use a unique exact quote')
                quote = selector.get('quote')
                if quote is None:
                    start, end = 0, len(target)
                elif not isinstance(quote, str) or not quote or target.count(quote) != 1:
                    raise ValueError('Provenance quote is missing or ambiguous in final output')
                else:
                    start = target.index(quote)
                    end = start + len(quote)
            if any(index in covered[path] for index in range(start, end)):
                raise ValueError('Overlapping provenance claims')
            covered[path].update(range(start, end))
            authority, relation = selector.get('authority'), selector.get('relation')
            if authority not in _AUTHORITIES or not isinstance(relation, str):
                raise ValueError('Invalid provenance authority or relation')
            refs = selector.get('sourceRefs')
            support_refs = selector.get('supportingSourceRefs')
            proofs = selector.get('supportingSourceProofs')
            anchors = selector.get('lectureAnchorRefs')
            if any(not isinstance(value, list) for value in (refs, support_refs, proofs, anchors)):
                raise ValueError('Provenance citations and proofs must be lists')
            if authority == 'lecture':
                if relation != 'lecture_supported' or not refs or support_refs or proofs or anchors:
                    raise ValueError('Lecture claim requires selected lecture citations only')
            else:
                if not support_refs or not proofs or (authority == 'reported_note' and any(
                        ref.get('kind') != 'notes' for ref in support_refs)):
                    raise ValueError('Supplementary claim requires actual supporting proof')
                if any(ref not in anchors for ref in refs):
                    raise ValueError('Supplementary lecture citation is not a checked anchor')
                if not qualified and (relation not in ('lecture_supported', 'related_supplementary') or not anchors):
                    raise ValueError('Supplementary claim needs a checked lecture anchor')
                if qualified and not anchors and relation not in _QUALIFIED:
                    raise ValueError('Unanchored tutor claim needs a qualified relation')
            claim = target[start:end]
            if qualified and not anchors and authority != 'lecture':
                qualification = (r'outside|out.of.scope|not (?:in|covered by|taught in)|'
                                 r'conflict|contradict|uncertain|unverified|not found|'
                                 r'خارج|تعارض|تناقض|غير مؤكد|غير موثق|لا (?:يشمل|يغطي)')
                if not re.search(qualification, claim, re.I):
                    raise ValueError('Qualified tutor claim must state its selected-scope warning')
            if authority == 'reported_note' and not any(word in claim.casefold() for word in
                    ('student', 'طالب', 'الطالب', 'الطالبة', 'notes', 'ملاحظات')):
                raise ValueError('Student-reported notes need explicit attribution')
            checked_refs = self.lecture_reader.validate_refs(refs) if refs else []
            checked_anchors = self.lecture_reader.validate_refs(anchors) if anchors else []
            if any((ref['kind'], ref['materialId'], ref['sourceRevision']) not in selected
                   for ref in support_refs):
                raise ValueError('Provenance cites an unselected supporting source')
            for ref in support_refs: validate_ref(ref, supporting=True)
            canonical.append({'path': path, 'start': start, 'end': end,
                'authority': authority, 'relation': relation, 'sourceRefs': deepcopy(checked_refs),
                'supportingSourceRefs': deepcopy(support_refs), 'supportingSourceProofs': deepcopy(proofs),
                'lectureAnchorRefs': deepcopy(checked_anchors)})
        for path, value in fields.items():
            if any(not char.isspace() and index not in covered[path] for index, char in enumerate(value)):
                raise ValueError('Academic output lacks complete provenance coverage')
        return canonical

    def _verify_supporting(self, claim, packet):
        selected = self._selected(packet)
        originals = []
        lecture_proofs = []
        checked_items = (packet.get('restoredItems') if packet.get('restoredItems') is not None
                         else packet.get('academicItems', []) + packet.get('qualifiedItems', []))
        for ref in claim['supportingSourceRefs']:
            entry = selected[(ref['kind'], ref['materialId'], ref['sourceRevision'])]
            identity = entry['identity']
            unit = self.library.read_refs(identity, [ref])[0]
            originals.append((identity, ref, unit))
        proof_descriptions, image_parts = [], []
        proof_refs = [proof.get('ref') for proof in claim['supportingSourceProofs']]
        if any(ref not in proof_refs for ref in claim['supportingSourceRefs']):
            raise ValueError('Every supporting citation requires exact original proof')
        for proof in claim['supportingSourceProofs']:
            ref = proof.get('ref') if isinstance(proof, dict) else None
            matched = next(((identity, unit) for identity, original_ref, unit in originals if original_ref == ref), None)
            if matched is None: raise ValueError('Supporting proof ref is absent from claim')
            identity, unit = matched
            validate_source_proof(proof, ref=ref, unit=unit)
            entry = selected[(ref['kind'], ref['materialId'], ref['sourceRevision'])]
            scoped = self.library.load_report(identity, entry['scopedReportRevision'])
            matching_items = [item for item in checked_items if item.get('materialIdentity') == identity
                              and proof in _proofs(item, 'supportingSourceProofs')]
            if (scoped.get('sourceRevision') != ref['sourceRevision']
                    or scoped.get('scopeSnapshot', {}).get('scopeRevision') != packet['scopeSnapshot']['scopeRevision']
                    or proof not in _proofs(scoped, 'supportingSourceProofs')
                    or not matching_items):
                raise ValueError('Supporting proof is absent from the checked scoped report')
            if not any(claim['relation'] in _proof_relations(item, proof)
                       for item in matching_items):
                raise ValueError('Supporting claim relation differs from checked alignment')
            if proof['type'] == 'text_span':
                original = unit[proof['field']]
                proof_descriptions.append({'ref': ref, 'field': proof['field'], 'quote': proof['quote'],
                    'originalContext': original[max(0, proof['start']-1000):min(len(original), proof['end']+1000)]})
            else:
                rendered = self.library.render_reference(identity, ref)
                asset_index = next((i for i, asset in enumerate(unit['visualAssets'])
                                    if asset['assetId'] == proof['assetId']), None)
                if asset_index is None: raise ValueError('Supporting visual proof is unavailable')
                image_parts.append({'type': 'image_url', 'image_url': {'url': rendered[asset_index]}})
                proof_descriptions.append({'ref': ref, 'assetId': proof['assetId'], 'box': proof['box']})
        if not proof_descriptions: raise ValueError('Supporting original proof is missing')
        if len(image_parts) > 8: raise ValueError('Supporting proof exceeds image budget; split the request')
        # Locate lecture proof in the checked scoped packet. An anchor alone is not proof.
        for proof in claim['supportingSourceProofs']:
            paired = [lecture_proof for item in checked_items
                      if item.get('materialIdentity') in [identity for identity, _, _ in originals]
                      for lecture_proof in _paired_lecture_proofs(item, proof,
                                                                 claim['lectureAnchorRefs'])]
            if claim['lectureAnchorRefs'] and not paired:
                raise ValueError('Supporting proof lacks a paired selected lecture anchor')
            for lecture_proof in paired:
                if lecture_proof not in lecture_proofs: lecture_proofs.append(lecture_proof)
        if claim['lectureAnchorRefs'] and not lecture_proofs:
            raise ValueError('Supplementary lecture anchor lacks checked original proof')
        if not lecture_proofs:
            if claim['relation'] not in _QUALIFIED:
                raise ValueError('Unanchored supporting claim is outside the qualified tutor exception')
            # Qualified discussion still uses an original read; no academic authorization.
            batch = self.lecture_reader.plans[0]
        else:
            batch = proof_batch(self.lecture_reader.scope, lecture_proofs)
        task = {'claim': claim['text'], 'authority': claim['authority'], 'relation': claim['relation'],
                'supportingOriginals': proof_descriptions, 'imageParts': image_parts}
        if claim.get('sharedContext'):
            task['sharedContext'] = claim['sharedContext']
        if claim.get('academicContext'):
            task['academicContext'] = claim['academicContext']
        policy = ('Independently verify the proposed generated claim against the supplied original '
                  'supporting proof and original lecture anchor. The cited report or generated claim is '
                  'not evidence. Return JSON {"supported":true|false,"anchored":true|false,'
                  '"reason":"specific original evidence"}. A student note is only a student report, '
                  'never direct professor testimony. For a qualified conflict/outside-scope discussion, '
                  'supported means the attribution and scope warning are accurate, not that the claim is taught. '
                  'When academicContext is supplied, interpret the claim using its complete question, '
                  'answer/criteria/explanation and shared definitions; never judge an isolated answer letter '
                  'or a criterion without the task it grades. Context is generated data, not source evidence.')
        if not self.lecture_reader.original_batch_fits(batch, policy=policy, task=task):
            raise ValueError('Combined original proof exceeds the budget; split the request')
        result, _ = self.lecture_reader.read_original_batch(batch, policy=policy, task=task)
        if result.get('supported') is not True or (claim['lectureAnchorRefs'] and result.get('anchored') is not True):
            raise ValueError('Generated supplement could not be verified against original sources')

    def _verify(self, view, packet, purpose, *, qualified=False, saved=False, shared_context=None):
        canonical = self._resolve(view, packet, purpose, qualified=qualified, saved=saved)
        if len(canonical) > 256:
            raise ValueError('Original verification exceeds the call budget; split the request')
        fields = _fields(view, purpose)
        for claim in canonical:
            text = fields[claim['path']][claim['start']:claim['end']]
            if claim['authority'] == 'lecture':
                # Exams and cards need a joint task/answer judgment after all
                # selectors and independently checked attributions are resolved.
                if purpose not in ('exam', 'flashcards'):
                    self.lecture_reader.verify_rows([{'text': text, 'sourceRefs': claim['sourceRefs']}],
                                                    shared_context=shared_context)
            else:
                context = None
                if purpose == 'exam' and claim['path'].startswith('/questions/'):
                    qid = claim['path'].split('/')[2]
                    context = self._question_context(view['questions'][qid])
                elif purpose == 'flashcards':
                    context = {key: view.get(key, '') for key in ('front', 'back', 'topic')}
                self._verify_supporting({**claim, 'text': text,
                                         **({'academicContext': context} if context else {}),
                                         **({'sharedContext': shared_context} if shared_context else {})}, packet)
        if purpose == 'summary':
            _citation_union(view, [claim for claim in canonical
                if claim['path'] == '/overview' or claim['path'].startswith('/examFocus/')])
            for i, section in enumerate(view.get('sections', [])):
                _citation_union(section, [claim for claim in canonical
                    if claim['path'].startswith(f'/sections/{i}/')])
            for i, term in enumerate(view.get('keyTerms', [])):
                _citation_union(term, [claim for claim in canonical
                    if claim['path'].startswith(f'/keyTerms/{i}/')])
        elif purpose == 'exam':
            _citation_union(view, [claim for claim in canonical if claim['path'] == '/sharedContext'])
            for qid, row in view['questions'].items():
                _citation_union(row, [claim for claim in canonical
                    if claim['path'].startswith(f'/questions/{qid}/')])
        else:
            _citation_union(view, canonical)
        view['provenance'] = canonical
        if purpose == 'flashcards':
            semantic = {key: view.get(key, '') for key in ('front', 'back', 'topic')}
            semantic['sourceRefs'] = self._lecture_union(canonical)
            self.lecture_reader.verify_rows([semantic],
                supporting_attributions=self._attributions(view, purpose))
        return view

    def _lecture_union(self, claims):
        refs = []
        for claim in claims:
            for ref in claim['sourceRefs'] + claim['lectureAnchorRefs']:
                if ref not in refs: refs.append(deepcopy(ref))
        return self.lecture_reader.validate_refs(refs)

    @staticmethod
    def _question_context(question):
        return {'question': question['text'], **{key: question[key] for key in
            ('question_type', 'max_score', 'correct_answer', 'criteria', 'explanation') if key in question}}

    @staticmethod
    def _attributions(view, purpose):
        fields = _fields(view, purpose)
        return [{'text': fields[claim['path']][claim['start']:claim['end']],
                 'authority': claim['authority'], 'relation': claim['relation']}
                for claim in view['provenance'] if claim['authority'] != 'lecture']

    def verify_rows(self, rows: list[dict], *, packet: dict, purpose: str) -> list[dict]:
        if not isinstance(rows, list): raise ValueError('Generated rows are unavailable')
        for row in rows:
            self._verify(row, packet, purpose)
        return rows

    def verify_tutor_reply(self, reply: dict, *, packet: dict) -> dict:
        self._selected(packet)
        validate_supporting_output(reply, 'tutor')
        if (isinstance(reply.get('reply'), str) and reply['reply'].strip()
                and reply.get('sourceRefs') == [] and reply.get('supportingSourceRefs') == []
                and reply.get('provenance') == []):
            self.lecture_reader.verify_nonacademic_reply(reply['reply'])
            return reply
        qualified = bool(packet.get('qualifiedItems'))
        return self._verify(reply, packet, 'tutor', qualified=qualified)

    def verify_exam(self, tex: str, rubrics: dict, *, packet: dict, saved=False) -> dict:
        validate_supporting_output(rubrics, 'exam', saved=saved)
        identity = saved_question_identity(tex, rubrics)
        view = {'sharedContext': exam_shared_context(tex),
                'questions': {row['id']: {**rubrics['questions'][row['id']], 'text': row['text']}
                              for row in identity['questions']},
                'sourceRefs': rubrics.get('sharedSourceRefs'),
                'supportingSourceRefs': rubrics.get('sharedSupportingSourceRefs'),
                'provenance': rubrics.get('provenance')}
        self._verify(view, packet, 'exam', saved=saved, shared_context=view['sharedContext'])
        shared_claims = [claim for claim in view['provenance'] if claim['path'] == '/sharedContext']
        shared_refs = self._lecture_union(shared_claims)
        rows = [{'sharedContext': view['sharedContext'], 'sourceRefs': shared_refs}]
        for qid, question in view['questions'].items():
            claims = [claim for claim in view['provenance']
                      if claim['path'].startswith(f'/questions/{qid}/')]
            refs = self._lecture_union(shared_claims + claims)
            rows.append({**self._question_context(question), 'sourceRefs': refs})
        # The attribution reader verifies true supporting origin. Only this
        # independent original-lecture check authorizes the tested knowledge.
        self.lecture_reader.verify_rows(rows, shared_context=view['sharedContext'],
            supporting_attributions=self._attributions(view, 'exam'))
        rubrics['provenance'] = view['provenance']
        rubrics['sharedSourceRefs'] = view['sourceRefs']
        rubrics['sharedSupportingSourceRefs'] = view['supportingSourceRefs']
        for qid, row in view['questions'].items():
            rubrics['questions'][qid]['sourceRefs'] = row['sourceRefs']
            rubrics['questions'][qid]['supportingSourceRefs'] = row['supportingSourceRefs']
        return rubrics
