"""Requirement-level checks against selected immutable lecture originals."""
from copy import deepcopy

from src.config.supporting_prompts import (ALIGNMENT_CONTEXT_VERIFY, ALIGNMENT_SOURCE_CHECK,
    ALIGNMENT_SEARCH, ALIGNMENT_VERIFY)
from src.supporting.alignment_evidence import (compact_supplied, context_components,
    exact_review_coverage, proof_batch, proof_in_supplied, ref_key, validate_review_ledger)
from src.supporting.contracts import (DEFAULT_MODEL_CALL_BUDGET, canonical_bytes, digest,
    aggregate_item_alignment, validate_alignment_report, validate_identity, validate_source_proof)
from src.utils.source_context import build_source_plan
from src.utils.source_context import resolve_source_scope
from src.services.source_evidence import SourceEvidence


def _judgments(value, target_ids):
    rows = value.get('judgments') if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) != len(target_ids):
        raise ValueError('Original response omitted target judgments')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('targetId') not in target_ids or row['targetId'] in result:
            raise ValueError('Original response duplicated or invented a target')
        result[row['targetId']] = row
    if set(result) != set(target_ids):
        raise ValueError('Original response did not independently assess every target')
    return result


def _proofs(identity, library, proofs):
    if not isinstance(proofs, list) or not proofs:
        raise ValueError('Original supporting proofs are required')
    units = library.read_refs(identity, [proof['ref'] for proof in proofs])
    for proof, unit in zip(proofs, units):
        validate_source_proof(proof, ref=proof['ref'], unit=unit)
    return units


def _supporting_packet(identity, library, proofs):
    """Give the model the actual original range or rendered image behind each proof."""
    units = _proofs(identity, library, proofs)
    evidence, images, seen = [], [], set()
    for proof, unit in zip(proofs, units):
        ref, key = proof['ref'], (ref_key(proof['ref']), proof['type'],
                                  proof.get('start'), proof.get('end'), proof.get('assetId'))
        if key in seen:
            continue
        seen.add(key)
        entry = {'ref': deepcopy(ref), 'ranges': [], 'assetIds': []}
        if proof['type'] == 'text_span':
            field = proof['field']
            text = unit[field]
            start = max(0, proof['start'] - 1500)
            end = min(len(text), max(proof['end'], start + 3000))
            if end - start > 4000:
                end = min(len(text), proof['end'] + 1500)
                start = max(0, end - 4000)
            entry['ranges'].append({'field': field, 'start': start, 'end': end,
                                    'text': text[start:end]})
        else:
            rendered = library.render_reference(identity, ref)
            assets = unit['visualAssets']
            if len(rendered) != len(assets):
                raise ValueError('Original supporting image rendering is incomplete')
            index = next(i for i, asset in enumerate(assets) if asset['assetId'] == proof['assetId'])
            uri = rendered[index]
            if not isinstance(uri, str) or not uri.startswith('data:image/'):
                raise ValueError('Original supporting image is unavailable')
            entry['assetIds'].append(proof['assetId'])
            entry['assets'] = [deepcopy(assets[index])]
            images.append({'type': 'image_url', 'image_url': {'url': uri}})
        evidence.append(entry)
    return evidence, images


class SupportingAligner:
    def __init__(self, lecture_reader, supporting_library):
        self.lecture_reader = lecture_reader
        self.supporting_library = supporting_library

    def align(self, identity, inventory: dict, *, scope: dict, checkpoint,
              resume=None, resume_revision=None,
              model_call_budget=DEFAULT_MODEL_CALL_BUDGET, model_calls=None):
        identity = validate_identity(identity)
        if scope != self.lecture_reader.scope:
            raise ValueError('Selected lecture scope differs from original reader')
        if not callable(checkpoint) or not isinstance(inventory, dict):
            raise ValueError('Inventory and checkpoint callback are required')
        if type(model_call_budget) is not int or model_call_budget < 1:
            raise ValueError('Invalid successful model-call budget')
        if model_calls is not None and (type(model_calls) is not int or not 0 <= model_calls <= model_call_budget):
            raise ValueError('Invalid spent model-call count')
        if resume is not None and resume_revision is not None:
            raise ValueError('Choose raw or owned checkpoint resume, not both')
        authenticated_resume = resume_revision is not None
        if authenticated_resume:
            if (not isinstance(resume_revision, str) or len(resume_revision) != 64
                    or any(character not in '0123456789abcdef' for character in resume_revision)):
                raise ValueError('Invalid owned checkpoint revision')
            resume = self.supporting_library.load_checkpoint(identity, resume_revision)
        manifest = self.supporting_library.load_source(identity)
        if manifest['identity'] != identity:
            raise ValueError('Supporting source identity changed')
        if not scope['allowedRefs']:
            raise ValueError('Selected lecture scope is empty')
        targets = self._targets(inventory)
        bindings = {'version': 1, 'identity': deepcopy(identity), 'sourceRevision': manifest['sourceRevision'],
                    'scopeRevision': scope['scopeRevision'], 'alignmentVersion': 1,
                    'inventoryDigest': digest(inventory),
                    'scopeDigest': digest(scope)}
        state = self._restore(resume, bindings, targets, scope=scope, identity=identity,
                              authenticated=authenticated_resume)
        state['modelCallBudget'] = model_call_budget
        if model_calls is not None:
            state['modelCalls'] = model_calls
        if state['modelCalls'] > model_call_budget:
            raise ValueError('Recovered calls exceed the configured budget')

        def save():
            canonical_bytes(state)
            checkpoint(deepcopy(state))

        def original_call(stage, batch, active, *, nominated=None, reader=None):
            try:
                policy = {'source_check': ALIGNMENT_SOURCE_CHECK, 'search': ALIGNMENT_SEARCH,
                          'verify': ALIGNMENT_VERIFY, 'context_verify': ALIGNMENT_CONTEXT_VERIFY}[stage]
                source_reader = reader or self.lecture_reader

                def request_task(target_group):
                    proofs = [proof for target in target_group
                              for proof in target['supportingSourceProofs']]
                    support, images = _supporting_packet(identity, self.supporting_library, proofs)
                    task = {'stage': stage, 'targets': [{k: deepcopy(target[k]) for k in
                        ('id', 'text', 'category', 'itemType', 'itemText', 'choices', 'givenData',
                         'sharedContexts', 'ancestorContexts')}
                        | ({'contextForItemId': target['contextForItemId'],
                            'component': deepcopy(target['component'])}
                           if 'contextForItemId' in target else {})
                        for target in target_group],
                        'supportingEvidence': support, 'imageParts': images}
                    if nominated is not None:
                        task['nominatedProofs'] = {target['id']: deepcopy(nominated[target['id']])
                                                   for target in target_group}
                    return task

                packed, current = [], []
                for target in active:
                    candidate = [*current, target]
                    candidate_task = request_task(candidate)
                    if source_reader.original_batch_fits(batch, policy=policy, task=candidate_task):
                        current = candidate
                        continue
                    if not current:
                        raise ValueError('One alignment target exceeds the complete request bound; split its source context')
                    packed.append(current)
                    current = [target]
                    single_task = request_task(current)
                    if not source_reader.original_batch_fits(batch, policy=policy, task=single_task):
                        raise ValueError('One alignment target exceeds the complete request bound; split its source context')
                if current:
                    packed.append(current)

                combined, accepted_supply = {}, None
                for target_group in packed:
                    if state['modelCalls'] >= model_call_budget:
                        state['error'] = ('Successful model-call budget exhausted; retry with a fresh '
                                          'budget or split the source')
                        save()
                        return None, None
                    task = request_task(target_group)

                    def returned():
                        state['modelCalls'] += 1
                        save()

                    value, supplied = source_reader.read_original_batch(
                        batch, policy=policy, task=task, on_response=returned)
                    rows = _judgments(value, [target['id'] for target in target_group])
                    combined.update(rows)
                    accepted_supply = supplied
                return combined, accepted_supply
            except Exception as exc:
                state['error'] = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                save()
                return None, None

        # Stage 1: independently establish what each supporting original says.
        groups = [targets[i:i+16] for i in range(0, len(targets), 16)]
        for group in groups:
            pending = [target for target in group if target['id'] not in state['sourceChecks']]
            if not pending:
                continue
            query = ' '.join(target['text'] for target in pending)
            try:
                candidates = build_source_plan(scope, 'focused', query=query, text_budget=8000,
                                               image_budget=4, include_blank_assets=True)
                if not candidates:
                    candidates = build_source_plan(scope, 'summary', text_budget=8000,
                                                   image_budget=4, include_blank_assets=True)
            except ValueError as exc:
                state['error'] = str(exc)
                save()
                return self._report(identity, inventory, scope, targets, state)
            rows, _ = original_call('source_check', candidates[0], pending)
            if rows is None:
                return self._report(identity, inventory, scope, targets, state)
            try:
                for target in pending:
                    row = rows[target['id']]
                    if row.get('sourceVerdict') not in ('established', 'uncertain', 'not_established'):
                        raise ValueError('Invalid supporting original judgment')
                    source_proofs = row.get('sourceProofs')
                    if row['sourceVerdict'] == 'established':
                        _proofs(identity, self.supporting_library, source_proofs)
                        if not set(map(canonical_bytes, source_proofs)) <= set(map(canonical_bytes, target['supportingSourceProofs'])):
                            raise ValueError('Source check proof was not supplied')
                    queries = row.get('queries', [])
                    if not isinstance(queries, list) or len(queries) > 3 or any(not isinstance(q, str) for q in queries):
                        raise ValueError('Invalid semantic candidate queries')
                    if 'contextForItemId' in target:
                        if row.get('decision') not in ('required', 'not_required', 'unresolved'):
                            raise ValueError('Original context dependency was not judged for this item')
                        if row.get('contentKind') not in ('academic_claim', 'hypothetical_data',
                                                          'procedural_instruction', 'uncertain'):
                            raise ValueError('Original context kind is uncertain')
                        if type(row.get('methodRequired')) is not bool:
                            raise ValueError('Original context method dependency was not checked')
                    state['sourceChecks'][target['id']] = {'verdict': row['sourceVerdict'],
                        'proofs': deepcopy(source_proofs) if row['sourceVerdict'] == 'established' else [],
                        'queries': queries, 'explicitTeaching': row.get('explicitTeaching') is True,
                        'reason': str(row.get('reason', ''))[:500],
                        **({'decision': row['decision'], 'contentKind': row['contentKind'],
                            'methodRequired': row['methodRequired']}
                           if 'contextForItemId' in target else {})}
                save()
            except (ValueError, TypeError, KeyError) as exc:
                state['error'] = str(exc)
                save()
                return self._report(identity, inventory, scope, targets, state)

        # An independent second judgment certifies omission and neutral source
        # data before either can authorize an item or be copied downstream.
        for group in groups:
            pending = [target for target in group if 'contextForItemId' in target
                       and target['id'] not in state['verifiedContext']
                       and state['sourceChecks'][target['id']]['verdict'] == 'established']
            if not pending:
                continue
            try:
                batches = build_source_plan(scope, 'focused', query=' '.join(t['itemText'] for t in pending),
                                             text_budget=8000, image_budget=4,
                                             include_blank_assets=True)
                if not batches:
                    batches = build_source_plan(scope, 'summary', text_budget=8000, image_budget=4,
                                                include_blank_assets=True)
            except ValueError as exc:
                state['error'] = str(exc)
                save()
                return self._report(identity, inventory, scope, targets, state)
            rows, _ = original_call('context_verify', batches[0], pending)
            if rows is None:
                return self._report(identity, inventory, scope, targets, state)
            for target in pending:
                source = state['sourceChecks'][target['id']]
                row = rows[target['id']]
                consistent = (row.get('sourceVerdict') == 'established'
                    and row.get('decision') == source['decision']
                    and row.get('contentKind') == source['contentKind']
                    and row.get('methodRequired') is source['methodRequired']
                    and row.get('sourceProofs') == source['proofs'])
                if consistent:
                    state['verifiedContext'][target['id']] = {
                        'sourceProofs': deepcopy(row['sourceProofs']), 'decision': row['decision'],
                        'contentKind': row['contentKind'], 'methodRequired': row['methodRequired'],
                        'reason': str(row.get('reason', ''))[:500]}
                else:
                    state['uncertain'][target['id']] = True
            save()

        # Focused candidates are navigation. Every unresolved target then gets the
        # complete selected-source sweep, independent of lexical or guide matches.
        for group in groups:
            live = [target for target in group if state['sourceChecks'][target['id']]['verdict'] == 'established'
                    and (target.get('contextForItemId') is None or
                         (target['id'] in state['verifiedContext'] and
                          state['verifiedContext'][target['id']]['decision'] == 'required' and
                          (state['verifiedContext'][target['id']]['contentKind'] == 'academic_claim' or
                           state['verifiedContext'][target['id']]['methodRequired'])))
                    and target['id'] not in state['verified']]
            if not live:
                continue
            queries = list(dict.fromkeys([target['text'] for target in live] +
                [q for target in live for q in state['sourceChecks'][target['id']]['queries']]))
            candidates = []
            try:
                for query in queries:
                    candidates += build_source_plan(scope, 'focused', query=query, text_budget=8000,
                                                    image_budget=4, include_blank_assets=True)
                candidates += build_source_plan(scope, 'summary', text_budget=8000, image_budget=4,
                                                include_blank_assets=True)
            except ValueError as exc:
                state['error'] = str(exc)
                save()
                return self._report(identity, inventory, scope, targets, state)
            visited = set()
            for batch in candidates:
                active = [target for target in live if target['id'] not in state['verified']]
                if not active:
                    break
                key = digest(batch['evidence'])
                if key in visited:
                    continue
                visited.add(key)
                rows, supplied = original_call('search', batch, active)
                if rows is None:
                    return self._report(identity, inventory, scope, targets, state)
                try:
                    blank_refs = [entry['ref'] for entry in supplied
                                  if entry.get('disposition') == 'excluded_blank']
                    ledger = compact_supplied([entry for entry in supplied
                                               if entry.get('disposition') != 'excluded_blank'])
                    selected = {ref_key(ref): unit for manifest_row in scope['manifests']
                                for unit in manifest_row['units']
                                for ref in [{'documentId': manifest_row['documentId'],
                                    'sourceRevision': manifest_row['sourceRevision'], 'unitId': unit['unitId']} ]}
                    nominations = {}
                    premise_updates = {}
                    accepted_rows = []
                    for target in active:
                        row = rows[target['id']]
                        verdict = row.get('verdict')
                        if verdict not in ('support', 'premise', 'no_support', 'related_anchor', 'conflict',
                                           'explicit_exclusion', 'uncertain'):
                            raise ValueError('Invalid lecture original judgment')
                        proofs = row.get('lectureProofs', [])
                        if not isinstance(proofs, list):
                            raise ValueError('Invalid lecture proof list')
                        supplied_map = {ref_key(entry['ref']): entry for entry in ledger}
                        for proof in proofs:
                            unit = selected.get(ref_key(proof['ref']))
                            if unit is None:
                                raise ValueError('Lecture proof is outside selected originals')
                            validate_source_proof(proof, ref=proof['ref'], unit=unit)
                            proof_in_supplied(proof, supplied_map)
                        if verdict in ('support', 'premise', 'related_anchor', 'conflict',
                                       'explicit_exclusion') and not proofs:
                            raise ValueError('Positive lecture judgment needs exact original proof')
                        accepted_rows.append((target['id'], verdict))
                        if verdict == 'premise':
                            previous = state['premiseCandidates'].get(target['id'], {})
                            combined = {canonical_bytes(proof): deepcopy(proof)
                                        for proof in [*previous.get('lectureProofs', []), *proofs]}
                            premise_updates[target['id']] = {
                                'verdict': 'premise', 'lectureProofs': list(combined.values()),
                                'reason': str(row.get('reason', ''))[:500]}
                        elif proofs and verdict != 'no_support':
                            nominations[target['id']] = {'verdict': verdict, 'lectureProofs': proofs,
                                'reason': str(row.get('reason', ''))[:500]}
                    # A returned group is one acceptance unit. Validate every row
                    # before recording any of its original-read coverage.
                    state['premiseCandidates'].update(premise_updates)
                    for target_id, verdict in accepted_rows:
                        state['ledgers'][target_id] = compact_supplied([
                            *state['ledgers'][target_id], *ledger])
                        state['excludedBlankRefs'][target_id] = list({
                            ref_key(ref): deepcopy(ref) for ref in [
                                *state['excludedBlankRefs'][target_id], *blank_refs]}.values())
                        state['acceptedReads'][target_id].append({
                            'suppliedEvidence': deepcopy(ledger),
                            'excludedBlankRefs': deepcopy(blank_refs)})
                        if verdict == 'uncertain':
                            state['uncertain'][target_id] = True
                    save()
                    if nominations:
                        verify_targets = [target for target in active if target['id'] in nominations]
                        verified, _ = original_call('verify', batch, verify_targets, nominated=nominations)
                        if verified is None:
                            return self._report(identity, inventory, scope, targets, state)
                        for target in verify_targets:
                            nominated = nominations[target['id']]
                            row = verified[target['id']]
                            verdict = row.get('verdict')
                            if verdict not in ('support', 'related_anchor', 'conflict', 'explicit_exclusion',
                                               'reject', 'uncertain'):
                                raise ValueError('Invalid independent verification judgment')
                            if verdict in ('support', 'related_anchor', 'conflict', 'explicit_exclusion'):
                                if row.get('lectureProofs') != nominated['lectureProofs']:
                                    raise ValueError('Independent verification changed nominated proofs')
                                finding = {'verdict': verdict,
                                    'lectureProofs': deepcopy(row['lectureProofs']),
                                    'reason': str(row.get('reason', ''))[:500]}
                                if verdict == 'related_anchor':
                                    state['anchorCandidates'][target['id']] = finding
                                elif verdict == 'explicit_exclusion':
                                    state['explicitExclusions'][target['id']] = finding
                                else:
                                    state['verified'][target['id']] = finding
                            elif verdict == 'uncertain':
                                state['uncertain'][target['id']] = True
                        save()
                except (ValueError, TypeError, KeyError) as exc:
                    state['error'] = str(exc)
                    save()
                    return self._report(identity, inventory, scope, targets, state)
            joint_targets = [target for target in live if target['id'] not in state['verified']
                             and target['id'] in state['premiseCandidates']]
            bundles = {}
            try:
                for target in joint_targets:
                    candidate = state['premiseCandidates'][target['id']]
                    batch = proof_batch(scope, candidate['lectureProofs'])
                    key = digest(batch['evidence'])
                    bundles.setdefault(key, {'batch': batch, 'targets': []})['targets'].append(target)
                for bundle in bundles.values():
                    candidates = bundle['targets']
                    nominated = {target['id']: {'verdict': 'support',
                        'lectureProofs': deepcopy(state['premiseCandidates'][target['id']]['lectureProofs']),
                        'reason': state['premiseCandidates'][target['id']]['reason']}
                        for target in candidates}
                    verified, _ = original_call('verify', bundle['batch'], candidates,
                                                nominated=nominated)
                    if verified is None:
                        for target in candidates:
                            state['uncertain'][target['id']] = (state.get('error') or
                                'Combined original evidence could not be independently verified')
                        save()
                        return self._report(identity, inventory, scope, targets, state)
                    for target in candidates:
                        row = verified[target['id']]
                        proof_set = nominated[target['id']]['lectureProofs']
                        if row.get('verdict') == 'support' and row.get('lectureProofs') == proof_set:
                            state['verified'][target['id']] = {'verdict': 'support',
                                'lectureProofs': deepcopy(proof_set),
                                'reason': str(row.get('reason', ''))[:500]}
                            state['uncertain'].pop(target['id'], None)
                        elif row.get('verdict') == 'uncertain':
                            state['uncertain'][target['id']] = str(row.get('reason', ''))[:500] or True
                        elif row.get('verdict') != 'reject':
                            raise ValueError('Invalid combined-premise verification judgment')
                    save()
            except (ValueError, TypeError, KeyError) as exc:
                state['error'] = str(exc)
                for target in joint_targets:
                    state['uncertain'][target['id']] = str(exc)
                save()
                return self._report(identity, inventory, scope, targets, state)
        selected_report = self._report(identity, inventory, scope, targets, state)
        missing = {finding['requirementId'] for row in selected_report['alignments']
                   for finding in row['requirements'] if finding['relation'] == 'not_found'}
        missing.update(topic['alignment']['topicId'] for topic in selected_report['topics']
                       if topic['alignment']['relation'] == 'not_found')
        if missing:
            try:
                database = self.supporting_library.database
                try:
                    whole = resolve_source_scope(database, self.lecture_reader.library,
                        identity['userId'], identity['courseId'], None)
                except AttributeError:
                    if database is not None:
                        raise
                    whole = None
                if whole is None:
                    return selected_report
                selected_ids = {doc['id'] for doc in scope['documents']}
                whole_docs = {doc['id']: doc for doc in whole['documents']}
                if any(whole_docs.get(doc['id'], {}).get('sourceRevision') != doc['sourceRevision']
                       or whole_docs.get(doc['id'], {}).get('guideRevision') != doc['guideRevision']
                       for doc in scope['documents']):
                    raise ValueError('Selected lectures differ from the current foundation')
                excluded = {**whole,
                    'documents': [doc for doc in whole['documents'] if doc['id'] not in selected_ids],
                    'manifests': [m for m in whole['manifests'] if m['documentId'] not in selected_ids],
                    'allowedRefs': [ref for ref in whole['allowedRefs'] if ref['documentId'] not in selected_ids]}
                excluded['scopeRevision'] = digest([{key: doc[key] for key in
                    ('id', 'sourceRevision', 'guideRevision')} for doc in excluded['documents']])
                if excluded['allowedRefs']:
                    excluded_reader = SourceEvidence(excluded, self.lecture_reader.library,
                        identity['userId'], identity['courseId'], self.lecture_reader.client,
                        self.lecture_reader.model)
                    excluded_units = {ref_key({'documentId': m['documentId'],
                        'sourceRevision': m['sourceRevision'], 'unitId': unit['unitId']}): unit
                        for m in excluded['manifests'] for unit in m['units']}
                    for group in groups:
                        active = [target for target in group if target['id'] in missing
                                  and target['id'] not in state['excludedVerified']]
                        if not active:
                            continue
                        batches = build_source_plan(excluded, 'summary', text_budget=8000, image_budget=4,
                                                    include_blank_assets=True)
                        for batch in batches:
                            active = [target for target in active if target['id'] not in state['excludedVerified']]
                            if not active:
                                break
                            rows, supplied = original_call('search', batch, active, reader=excluded_reader)
                            if rows is None:
                                break
                            supplied_map = {ref_key(e['ref']): e for e in compact_supplied(supplied)}
                            nominations = {}
                            for target in active:
                                row = rows[target['id']]
                                proofs = row.get('lectureProofs', [])
                                if row.get('verdict') != 'support':
                                    continue
                                if not isinstance(proofs, list) or not proofs:
                                    raise ValueError('Excluded candidate needs exact positive proof')
                                for proof in proofs:
                                    unit = excluded_units.get(ref_key(proof['ref']))
                                    if unit is None:
                                        raise ValueError('Excluded proof is not in an owned original')
                                    validate_source_proof(proof, ref=proof['ref'], unit=unit)
                                    proof_in_supplied(proof, supplied_map)
                                nominations[target['id']] = {'verdict': 'support', 'lectureProofs': proofs}
                            if not nominations:
                                continue
                            candidates = [target for target in active if target['id'] in nominations]
                            verified, _ = original_call('verify', batch, candidates,
                                nominated=nominations, reader=excluded_reader)
                            if verified is None:
                                break
                            for target in candidates:
                                proof_set = nominations[target['id']]['lectureProofs']
                                if (verified[target['id']].get('verdict') == 'support'
                                        and verified[target['id']].get('lectureProofs') == proof_set):
                                    proof_docs = {p['ref']['documentId'] for p in proof_set}
                                    state['excludedVerified'][target['id']] = {
                                        'version': 1, 'foundationRevision': whole.get('foundationRevision') or
                                            digest([{key: doc[key] for key in
                                                ('id', 'sourceRevision', 'guideRevision')}
                                                for doc in whole['documents']]),
                                        'documents': [{key: deepcopy(doc[key]) for key in
                                            ('id', 'sourceRevision', 'guideRevision')}
                                            for doc in excluded['documents'] if doc['id'] in proof_docs],
                                        'proofs': deepcopy(proof_set),
                                        'suppliedEvidence': compact_supplied(supplied),
                                        'reason': str(verified[target['id']].get('reason', ''))[:500] or
                                            'Independently checked excluded lecture original'}
                            save()
            except (ValueError, TypeError, KeyError) as exc:
                state['error'] = str(exc)
                save()
        return self._report(identity, inventory, scope, targets, state)

    def rescope(self, identity, report, *, scope, checkpoint, resume=None, resume_revision=None,
                model_call_budget=DEFAULT_MODEL_CALL_BUDGET, model_calls=None):
        # The immutable original inventory is retained; every selected-scope
        # judgment is recomputed from original evidence.
        inventory = {key: deepcopy(report[key]) for key in
                     ('items', 'sharedContexts', 'papers', 'topics', 'extractionCoverage')}
        return self.align(identity, inventory, scope=scope, checkpoint=checkpoint,
                          resume=resume, resume_revision=resume_revision,
                          model_call_budget=model_call_budget, model_calls=model_calls)

    @staticmethod
    def _targets(inventory):
        items = inventory.get('items')
        contexts = {row['id']: row for row in inventory.get('sharedContexts', [])}
        if not isinstance(items, list):
            raise ValueError('Supporting inventory items are missing')
        by_id = {item['id']: item for item in items}
        targets = []
        for item in items:
            ancestors = []
            parent = item.get('parentId')
            while parent is not None:
                if parent not in by_id or parent in [a['id'] for a in ancestors]:
                    raise ValueError('Invalid supporting item ancestor')
                ancestor = by_id[parent]
                ancestors.append({'id': parent, 'text': ancestor['text'], 'choices': ancestor['choices'],
                                  'givenData': ancestor['givenData']})
                parent = ancestor.get('parentId')
            shared = [deepcopy(contexts[cid]) for cid in item['sharedContextIds']]
            for requirement in item['requirements']:
                proofs = requirement.get('supportingSourceProofs')
                if not proofs:
                    raise ValueError('Atomic requirement has no original supporting proof')
                targets.append({'id': requirement['id'], 'text': requirement['text'],
                    'category': requirement['category'], 'itemId': item['id'],
                    'itemType': item['itemType'], 'itemText': item['text'],
                    'choices': deepcopy(item['choices']), 'givenData': deepcopy(item['givenData']),
                    'sharedContexts': shared, 'ancestorContexts': ancestors,
                    'supportingSourceProofs': deepcopy(proofs)})
        for topic in inventory.get('topics', []):
            if (not isinstance(topic.get('requirementIds'), list) or not topic['requirementIds']
                    or not topic.get('supportingSourceProofs')):
                raise ValueError('Topic needs linked requirements and original supporting proof')
            origins = [by_id[item_id] for item_id in topic['itemIds']]
            targets.append({'id': topic['id'], 'text': topic['text'], 'category': 'concept',
                'itemId': None, 'itemType': 'topic_statement', 'itemText': topic['text'],
                'choices': [], 'givenData': [], 'sharedContexts': [], 'ancestorContexts': [],
                'supportingSourceProofs': deepcopy(topic['supportingSourceProofs']),
                'originRequirementIds': deepcopy(topic['requirementIds']),
                'originItemIds': [item['id'] for item in origins]})
        for item_id, components in context_components(items, inventory.get('sharedContexts', [])).items():
            item = by_id[item_id]
            for component in components:
                targets.append({'id': component['id'], 'text': str(component['value']),
                    'category': 'concept', 'itemId': None, 'itemType': 'context_dependency',
                    'itemText': item['text'], 'choices': deepcopy(item['choices']),
                    'givenData': deepcopy(item['givenData']), 'sharedContexts': [],
                    'ancestorContexts': [], 'contextForItemId': item_id,
                    'component': {k: deepcopy(component[k]) for k in
                        ('ownerType', 'ownerId', 'field', 'index', 'contentDigest', 'value')},
                    'supportingSourceProofs': deepcopy(component['supportingSourceProofs'])})
        if len({target['id'] for target in targets}) != len(targets):
            raise ValueError('Duplicate requirement identity')
        return targets

    @staticmethod
    def _empty_state(bindings, targets, *, model_calls=0):
        return {**bindings, 'stage': 'align', 'modelCalls': model_calls,
                'modelCallBudget': DEFAULT_MODEL_CALL_BUDGET,
                'sourceChecks': {}, 'ledgers': {target['id']: [] for target in targets},
                'excludedBlankRefs': {target['id']: [] for target in targets},
                'acceptedReads': {target['id']: [] for target in targets},
                'verified': {}, 'anchorCandidates': {}, 'premiseCandidates': {},
                'explicitExclusions': {}, 'verifiedContext': {}, 'excludedVerified': {},
                'uncertain': {}, 'error': None}

    def _restore(self, resume, bindings, targets, *, scope, identity, authenticated):
        if resume is None:
            return self._empty_state(bindings, targets)
        state = deepcopy(resume)
        canonical_bytes(state)
        if any(state.get(key) != value for key, value in bindings.items()):
            raise ValueError('Alignment checkpoint belongs to another source, scope or inventory')
        ids = {target['id'] for target in targets}
        if (not isinstance(state.get('sourceChecks'), dict) or not isinstance(state.get('ledgers'), dict)
                or set(state['ledgers']) != ids or not set(state['sourceChecks']) <= ids
                or not isinstance(state.get('excludedBlankRefs'), dict)
                or set(state['excludedBlankRefs']) != ids
                or not isinstance(state.get('acceptedReads'), dict)
                or set(state['acceptedReads']) != ids
                or not isinstance(state.get('verified'), dict) or not set(state['verified']) <= ids
                or not isinstance(state.get('anchorCandidates'), dict)
                or not set(state['anchorCandidates']) <= ids
                or not isinstance(state.get('premiseCandidates'), dict)
                or not set(state['premiseCandidates']) <= ids
                or not isinstance(state.get('explicitExclusions'), dict)
                or not set(state['explicitExclusions']) <= ids
                or not isinstance(state.get('verifiedContext'), dict) or not set(state['verifiedContext']) <= ids
                or not isinstance(state.get('excludedVerified'), dict) or not set(state['excludedVerified']) <= ids
                or not isinstance(state.get('uncertain'), dict) or not set(state['uncertain']) <= ids
                or type(state.get('modelCalls')) is not int or state['modelCalls'] < 0):
            raise ValueError('Invalid alignment checkpoint')
        target_map = {target['id']: target for target in targets}
        selected_units = {ref_key({'documentId': manifest['documentId'],
            'sourceRevision': manifest['sourceRevision'], 'unitId': unit['unitId']}): unit
            for manifest in scope['manifests'] for unit in manifest['units']}
        supplied_by_target = {}
        for target_id in ids:
            reads = state['acceptedReads'][target_id]
            if not isinstance(reads, list) or any(not isinstance(read, dict)
                    or set(read) != {'suppliedEvidence', 'excludedBlankRefs'}
                    or not isinstance(read['suppliedEvidence'], list)
                    or not isinstance(read['excludedBlankRefs'], list) for read in reads):
                raise ValueError('Invalid accepted original-read checkpoint')
            reconstructed = compact_supplied([entry for read in reads
                                               for entry in read['suppliedEvidence']])
            reconstructed_blank = list({ref_key(ref): deepcopy(ref) for read in reads
                                        for ref in read['excludedBlankRefs']}.values())
            if (canonical_bytes(reconstructed) != canonical_bytes(state['ledgers'][target_id])
                    or canonical_bytes(reconstructed_blank) !=
                       canonical_bytes(state['excludedBlankRefs'][target_id])):
                raise ValueError('Alignment checkpoint ledger was not produced by accepted original reads')
            coverage = exact_review_coverage(scope, reconstructed, reconstructed_blank)
            supplied_by_target[target_id] = validate_review_ledger(coverage, units=selected_units)

        for target_id, source in state['sourceChecks'].items():
            if not isinstance(source, dict) or source.get('verdict') not in (
                    'established', 'uncertain', 'not_established'):
                raise ValueError('Invalid supporting-source checkpoint')
            proofs = source.get('proofs')
            queries = source.get('queries')
            if (not isinstance(proofs, list) or not isinstance(queries, list) or len(queries) > 3
                    or any(not isinstance(query, str) for query in queries)
                    or type(source.get('explicitTeaching')) is not bool
                    or not isinstance(source.get('reason'), str)):
                raise ValueError('Invalid supporting-source checkpoint fields')
            if source['verdict'] == 'established':
                _proofs(identity, self.supporting_library, proofs)
                if not set(map(canonical_bytes, proofs)) <= set(map(
                        canonical_bytes, target_map[target_id]['supportingSourceProofs'])):
                    raise ValueError('Checkpoint source proof was not in the original target')
            elif proofs:
                raise ValueError('Unestablished checkpoint target has source proofs')
            if 'contextForItemId' in target_map[target_id]:
                if (source.get('decision') not in ('required', 'not_required', 'unresolved')
                        or source.get('contentKind') not in ('academic_claim', 'hypothetical_data',
                                                            'procedural_instruction', 'uncertain')
                        or type(source.get('methodRequired')) is not bool):
                    raise ValueError('Invalid context source checkpoint')

        def validate_lecture_candidates(rows, verdicts):
            for target_id, row in rows.items():
                if (not isinstance(row, dict) or row.get('verdict') not in verdicts
                        or not isinstance(row.get('lectureProofs'), list)
                        or not row['lectureProofs'] or not isinstance(row.get('reason'), str)):
                    raise ValueError('Invalid lecture-candidate checkpoint')
                for proof in row['lectureProofs']:
                    unit = selected_units.get(ref_key(proof.get('ref', {})))
                    if unit is None:
                        raise ValueError('Checkpoint lecture proof is outside selected originals')
                    validate_source_proof(proof, ref=proof['ref'], unit=unit)
                    proof_in_supplied(proof, supplied_by_target[target_id])

        validate_lecture_candidates(state['verified'], {'support', 'conflict'})
        validate_lecture_candidates(state['anchorCandidates'], {'related_anchor'})
        validate_lecture_candidates(state['premiseCandidates'], {'premise'})
        validate_lecture_candidates(state['explicitExclusions'], {'explicit_exclusion'})

        for target_id, certificate in state['verifiedContext'].items():
            source = state['sourceChecks'].get(target_id)
            if ('contextForItemId' not in target_map[target_id] or source is None
                    or not isinstance(certificate, dict)
                    or certificate.get('sourceProofs') != source['proofs']
                    or certificate.get('decision') != source.get('decision')
                    or certificate.get('contentKind') != source.get('contentKind')
                    or certificate.get('methodRequired') is not source.get('methodRequired')
                    or not isinstance(certificate.get('reason'), str)):
                raise ValueError('Invalid independently verified context checkpoint')

        if state['excludedVerified']:
            database = self.supporting_library.database
            if database is None:
                raise ValueError('Excluded checkpoint cannot be validated without owned course sources')
            whole = resolve_source_scope(database, self.lecture_reader.library,
                identity['userId'], identity['courseId'], None)
            whole_docs = {document['id']: document for document in whole['documents']}
            selected_ids = {document['id'] for document in scope['documents']}
            whole_units = {ref_key({'documentId': manifest['documentId'],
                'sourceRevision': manifest['sourceRevision'], 'unitId': unit['unitId']}): unit
                for manifest in whole['manifests'] for unit in manifest['units']}
            for envelope in state['excludedVerified'].values():
                if (not isinstance(envelope, dict) or envelope.get('version') != 1
                        or envelope.get('foundationRevision') != whole['foundationRevision']
                        or not isinstance(envelope.get('documents'), list)
                        or not isinstance(envelope.get('proofs'), list)
                        or not envelope['proofs'] or not isinstance(envelope.get('suppliedEvidence'), list)
                        or not isinstance(envelope.get('reason'), str)):
                    raise ValueError('Invalid excluded-evidence checkpoint')
                descriptors = {document.get('id'): document for document in envelope['documents']
                               if isinstance(document, dict)}
                if (len(descriptors) != len(envelope['documents']) or set(descriptors) & selected_ids
                        or any(set(document) != {'id', 'sourceRevision', 'guideRevision'}
                               or whole_docs.get(doc_id) is None
                               or any(document[key] != whole_docs[doc_id][key]
                                      for key in ('sourceRevision', 'guideRevision'))
                               for doc_id, document in descriptors.items())):
                    raise ValueError('Excluded checkpoint source differs from current owned foundation')
                supplied = validate_review_ledger({'allowedRefs': [entry['ref'] for entry in
                    envelope['suppliedEvidence']], 'suppliedEvidence': envelope['suppliedEvidence'],
                    'excludedBlankRefs': [], 'checkState': 'complete'})
                for entry in envelope['suppliedEvidence']:
                    unit = whole_units.get(ref_key(entry['ref']))
                    if unit is None or entry['ref']['documentId'] not in descriptors:
                        raise ValueError('Excluded checkpoint range is outside owned originals')
                    if (any(part['end'] > len(unit.get(part['textField'], ''))
                            for part in entry['ranges'])
                            or any(asset not in {row['assetId'] for row in unit['visualAssets']}
                                   for asset in entry['assetIds'])):
                        raise ValueError('Excluded checkpoint range or image differs from original')
                for proof in envelope['proofs']:
                    unit = whole_units.get(ref_key(proof.get('ref', {})))
                    if unit is None or proof['ref']['documentId'] not in descriptors:
                        raise ValueError('Excluded checkpoint proof is outside owned originals')
                    validate_source_proof(proof, ref=proof['ref'], unit=unit)
                    proof_in_supplied(proof, supplied)

        if any(type(value) is not bool and not isinstance(value, str)
               for value in state['uncertain'].values()):
            raise ValueError('Invalid uncertain checkpoint reason')
        if not authenticated:
            # A raw JSON object has no owned immutable descriptor. Preserve only
            # safe accounting and rerun every semantic decision.
            return self._empty_state(bindings, targets, model_calls=state['modelCalls'])
        return state

    @staticmethod
    def _report(identity, inventory, scope, targets, state):
        by_requirement = {target['id']: target for target in targets}
        findings = {}
        for rid, target in by_requirement.items():
            supplied = state['ledgers'][rid]
            excluded_blank = state['excludedBlankRefs'][rid]
            coverage = exact_review_coverage(scope, supplied, excluded_blank)
            verified = state['verified'].get(rid)
            anchor = state['anchorCandidates'].get(rid)
            exclusion = state['explicitExclusions'].get(rid)
            source = state['sourceChecks'].get(rid)
            relation, reason, proofs = 'unverified', state.get('error') or 'Original check is unfinished', []
            if verified:
                proofs = verified['lectureProofs']
                if verified['verdict'] == 'support':
                    relation = 'lecture_supported'
                elif verified['verdict'] == 'conflict':
                    relation = 'conflicting'
                reason = verified['reason'] or 'Independently checked original lecture evidence'
                coverage['checkState'] = 'complete'
            elif (exclusion and source and source['verdict'] == 'established'
                    and coverage['complete'] and not state['uncertain'].get(rid)):
                relation = 'outside_selected_scope'
                proofs = exclusion['lectureProofs']
                reason = exclusion['reason'] or 'Selected originals explicitly exclude the requirement'
                coverage['checkState'] = 'complete'
            elif (anchor and source and source['verdict'] == 'established'
                    and source['explicitTeaching'] and identity['kind'] in ('tutorial', 'audio', 'notes')
                    and target['itemType'] not in ('question', 'subpart') and coverage['complete']):
                relation = 'related_supplementary'
                proofs = anchor['lectureProofs']
                reason = anchor['reason'] or 'Explicit current teaching is related to a checked lecture anchor'
                coverage['checkState'] = 'complete'
            elif source and source['verdict'] == 'established' and coverage['complete']:
                relation = 'unverified' if state['uncertain'].get(rid) else 'not_found'
                uncertain_reason = state['uncertain'].get(rid)
                reason = ((uncertain_reason if isinstance(uncertain_reason, str) else
                           'Semantic relation remains uncertain') if relation == 'unverified'
                          else 'No selected original supports the requirement')
                coverage['checkState'] = 'uncertain' if relation == 'unverified' else 'complete'
                if relation == 'not_found' and rid in state['excludedVerified']:
                    relation = 'outside_selected_scope'
            elif source and source['verdict'] != 'established':
                reason = 'Supporting original did not independently establish the extracted requirement'
            findings[rid] = {'requirementId': rid, 'relation': relation, 'reason': reason,
                'lectureAnchorRefs': list({ref_key(p['ref']): p['ref'] for p in proofs}.values()),
                'lectureSupportProofs': deepcopy(proofs),
                'supportingSourceProofs': deepcopy(source['proofs'] if source and source['proofs'] else
                                                   target['supportingSourceProofs']),
                'reviewCoverage': coverage}
            if relation == 'outside_selected_scope' and rid in state['excludedVerified']:
                findings[rid]['excludedLectureEvidence'] = deepcopy(state['excludedVerified'][rid])
        by_item = {item['id']: [] for item in inventory['items']}
        parents = {item['id']: item.get('parentId') for item in inventory['items']}
        for target in targets:
            if target['itemId'] is None:
                continue
            item_id = target['itemId']
            while item_id is not None:
                by_item[item_id].append(deepcopy(findings[target['id']]))
                item_id = parents[item_id]
        dependencies = {}
        for item_id, components in context_components(inventory['items'], inventory.get('sharedContexts', [])).items():
            dependencies[item_id] = []
            for component in components:
                source = state['sourceChecks'].get(component['id'])
                certificate = state['verifiedContext'].get(component['id'])
                finding = findings[component['id']]
                decision = certificate['decision'] if certificate else 'unresolved'
                content_kind = certificate['contentKind'] if certificate else 'uncertain'
                method_required = certificate['methodRequired'] if certificate else None
                relation = finding['relation']
                if decision == 'not_required':
                    relation = 'not_applicable'
                elif decision == 'required' and content_kind in ('hypothetical_data', 'procedural_instruction') and method_required is False:
                    relation = 'source_only'
                elif not certificate:
                    relation = 'unverified'
                usable = decision == 'required' and relation in ('lecture_supported', 'source_only')
                coverage = deepcopy(finding['reviewCoverage'])
                if relation in ('not_applicable', 'source_only'):
                    coverage['checkState'] = 'complete'
                dependencies[item_id].append({
                    'componentId': component['id'],
                    **{key: deepcopy(component[key]) for key in
                       ('ownerType', 'ownerId', 'field', 'index', 'contentDigest')},
                    'supportingSourceProofs': deepcopy(certificate['sourceProofs'] if certificate else
                                                        component['supportingSourceProofs']),
                    'decision': decision, 'contentKind': content_kind, 'relation': relation,
                    'methodRequired': method_required,
                    'verification': deepcopy(certificate),
                    'lectureSupportProofs': deepcopy(finding['lectureSupportProofs']),
                    'reviewCoverage': coverage, 'usable': usable})
        alignments = [aggregate_item_alignment(by_item[item['id']], item_id=item['id'],
                        context_dependencies=dependencies[item['id']]) for item in inventory['items']]
        unfinished = [item['id'] for item in inventory['items'] if any(
            row['relation'] == 'unverified' and row['reviewCoverage']['checkState'] == 'pending'
            for row in by_item[item['id']]) or any(
            dep['decision'] == 'unresolved' or (dep['decision'] == 'required' and
                dep['relation'] == 'unverified' and dep['reviewCoverage']['checkState'] == 'pending')
            for dep in dependencies[item['id']])]
        topic_rows = []
        unfinished_topics = []
        for topic in inventory.get('topics', []):
            finding = deepcopy(findings[topic['id']])
            finding['topicId'] = finding.pop('requirementId')
            finding['originRequirementIds'] = deepcopy(topic['requirementIds'])
            topic_rows.append({**deepcopy(topic), 'alignment': finding})
            if finding['relation'] == 'unverified' and finding['reviewCoverage']['checkState'] == 'pending':
                unfinished_topics.append(topic['id'])
        ids = [item['id'] for item in inventory['items']]
        topic_ids = [topic['id'] for topic in topic_rows]
        report = {'version': 1, 'alignmentVersion': 1, 'sourceRevision': state['sourceRevision'],
            'scopeSnapshot': {'version': 1, 'scopeRevision': scope['scopeRevision'],
                'documents': deepcopy(scope['documents']), 'allowedRefs': deepcopy(scope['allowedRefs'])},
            'extractionCoverage': deepcopy(inventory['extractionCoverage']),
            'alignmentCoverage': {'itemIds': ids, 'checkedItemIds': ids,
                'unresolvedItemIds': unfinished, 'topicIds': topic_ids,
                'checkedTopicIds': topic_ids, 'unresolvedTopicIds': unfinished_topics,
                'complete': not unfinished and not unfinished_topics},
            'items': deepcopy(inventory['items']), 'alignments': alignments,
            'sharedContexts': deepcopy(inventory.get('sharedContexts', [])),
            'papers': deepcopy(inventory.get('papers', [])),
            'topics': topic_rows}
        return validate_alignment_report(report)
