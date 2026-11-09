"""Restart-safe complete supporting extraction with independent original reconciliation."""
from copy import deepcopy

from src.config.supporting_prompts import EXTRACTION, RECONCILIATION
from src.supporting.contracts import (canonical_bytes, digest, validate_supporting_manifest,
    DEFAULT_MODEL_CALL_BUDGET, MAX_TEXT_PER_CALL, MAX_IMAGES_PER_CALL)
from src.supporting.extraction_source import (prepare_pages, lecture_context, source_plan,
    previous_evidence, materialize, request_messages, image_caption_size)
from src.supporting.extraction_inventory import (validate_response, inventory, coverage, comparable,
                                                ExclusionCoverageError)
from src.supporting.inventory_references import InventoryReferenceError
from src.supporting.reconciliation import audit_disagreements, validate_certificate
from src.utils.ai_retry import chat_with_retry
from src.utils.ai_contracts import response_text
from src.utils.json_parse import extract_json_object
from src.utils.completion_diagnostics import completion_diagnostics
from src.supporting.structured_output import (WIRE_VERSION, WIRE_PROMPT, source_references,
    transport_envelope, inventory_schema, structured_options, decode_inventory, TextAnchors)
from src.supporting.native_inventory import (NativeInventory, NeedsRichExtraction,
    NATIVE_WIRE_VERSION, NATIVE_PROMPT, eligible as native_eligible)


class SupportingExtractor:
    def __init__(self, client, model, *, native_tutorials=False, field_audits=False):
        self.client, self.model = client, model
        self.native_tutorials = native_tutorials
        self.field_audits = field_audits

    prepare_pages = staticmethod(prepare_pages)

    def extract(self, manifest, *, course_title, lecture_reader, render, checkpoint,
                resume=None, model_call_budget=DEFAULT_MODEL_CALL_BUDGET, model_calls=None):
        manifest = validate_supporting_manifest(manifest)
        kind = manifest['identity']['kind']
        if kind not in EXTRACTION:
            raise ValueError('No inventory prompt for this supporting source kind')
        if not isinstance(course_title, str):
            raise ValueError('Invalid course title')
        if type(model_call_budget) is not int or model_call_budget < 1:
            raise ValueError('Invalid successful model-call budget')
        if model_calls is not None and (type(model_calls) is not int or not 0 <= model_calls <= model_call_budget):
            raise ValueError('Invalid spent model-call count')
        plan = source_plan(manifest, 1)  # reserve one original lecture navigation image
        bindings = {'version': 1, 'sourceRevision': manifest['sourceRevision'], 'identity': manifest['identity'],
                    'planDigest': digest(plan), 'policyDigest': digest(EXTRACTION[kind] + RECONCILIATION),
                    'contextDigest': digest({'courseTitle': course_title, 'lectureScope': lecture_reader.snapshot()})}
        state = self._restore(resume, bindings, manifest, plan)
        state['fieldAuditRequired'] = (self.field_audits or state.get('fieldAuditRequired', False)
            or (state.get('resolutionPending') or {}).get('auditProtocol') == 2
            or any(row.get('bindings', {}).get('version') == 2 for row in state.get('resolutions', {}).values()))
        state['modelCallBudget'] = model_call_budget
        if model_calls is not None and model_calls < state.get('modelCalls', 0):
            state['countedResponses'] = 0  # explicit retry starts a new job call budget
            old_result = self._result(manifest, plan, state)
            unresolved = list(old_result['extractionCoverage']['reasons'])
            first = next((i for i, row in enumerate(plan) if row['ref']['unitId'] in unresolved), None)
            if (state.get('fieldAuditRequired') and state['stage'] == 'complete'
                    and all(set(rows) == {str(i) for i in range(len(plan))}
                            for rows in state['responses'].values())):
                # A failed review is not evidence that its two valid source
                # passes need rebuilding. Re-read originals only for assembly
                # errors or a validated definite finding against the first pass.
                repair, repair_second = set(), set()
                for rows in state['responses'].values():
                    _, errors = inventory(manifest, plan, rows)
                    repair.update(i for i, source in enumerate(plan) if source['ref']['unitId'] in errors)
                for key, certificate in state.get('resolutions', {}).items():
                    if certificate['accepted']:
                        continue
                    response = certificate['response']
                    first_incorrect = any(
                        row['obligationId'].startswith('A/') and row['decision'] == 'incorrect'
                        and any(finding['kind'] != 'uncertain' for finding in row.get('findings', []))
                        for row in response['judgments'])
                    missing = any(
                        finding.get('kind') != 'uncertain'
                        and (finding.get('obligationId') is None or finding['obligationId'].startswith('A/'))
                        for finding in (row.get('finding', {}) for row in response['missingContent']))
                    if (certificate['bindings']['version'] == 1 or first_incorrect or missing
                            or response.get('sourceCompleteness', {}).get('status') == 'incomplete'):
                        repair.add(int(key))
                    elif any(row['obligationId'].startswith('B/') and row['decision'] == 'incorrect'
                             and any(finding['kind'] != 'uncertain' for finding in row.get('findings', []))
                             for row in response['judgments']):
                        repair_second.add(int(key))
                # A definite defect in only the independent second pass cannot be
                # fixed by reviewing that unchanged pass again. Each pass restarts
                # at its own earliest defect; the second pass also restarts wherever
                # the first does, because its checked prefix is paired with it.
                first = min(repair) if repair else None
                boundaries = repair_second | ({first} if first is not None else set())
                rebuild = min(boundaries) if boundaries else None
                # Accepted certificates are exact-source/digest bound and were
                # replay-validated above. Uncertain/failed reviews are retried.
                state['resolutions'] = {key: value for key, value in state.get('resolutions', {}).items()
                                        if value['accepted']}
                pending_review = state.get('resolutionPending')
                if pending_review and pending_review.get('error'):
                    state['resolutionPending'] = None
                if rebuild is not None:
                    # Retain every first-pass window checked before its own defect
                    # and the second pass's checked prefix, with their spent calls.
                    if first is not None:
                        state['responses']['extract'] = {key: value for key, value
                            in state['responses']['extract'].items() if int(key) < first}
                    state['responses']['reconcile'] = {key: value for key, value
                        in state['responses']['reconcile'].items() if int(key) < rebuild}
                    state['resolutions'] = {key: value for key, value
                        in state['resolutions'].items() if int(key) < rebuild}
                    state['stage'], state['cursor'] = (('extract', first) if first is not None
                                                       else ('reconcile', rebuild))
                    state['pending'], state['resolutionPending'] = None, None
                first = None  # This branch rebuilt exactly the affected suffixes.
            if first is not None:
                # Retain only a fully checked prefix; downstream continuations may
                # depend on a corrected boundary/item and must be rebuilt.
                for phase in ('extract', 'reconcile'):
                    state['responses'][phase] = {k: v for k, v in state['responses'][phase].items() if int(k) < first}
                state['resolutions'] = {k: v for k, v in state.get('resolutions', {}).items() if int(k) < first}
                state['resolutionPending'] = None
                state['stage'], state['cursor'], state['pending'] = 'extract', first, None
        state['modelCalls'] = state.get('modelCalls', 0) if model_calls is None else model_calls
        if state['modelCalls'] > model_call_budget:
            raise ValueError('Recovered calls exceed the configured budget')
        # A new invocation may retry a failed window, but never clears its accepted ledger.
        state['error'] = None
        def save():
            current_coverage = self._result(manifest, plan, state)['extractionCoverage']
            state['progress'] = {'completedUnits': len(set(current_coverage['accountedUnitIds']) -
                                                       set(current_coverage['unresolvedUnitIds'])),
                                 'totalUnits': len(manifest['units'])}
            canonical_bytes(state)
            checkpoint(deepcopy(state))

        # Publish the resumed/new phase before rendering or waiting for the first
        # provider response, so a long request does not appear stuck preparing.
        save()
        while state['stage'] != 'complete':
            stage, cursor = state['stage'], state['cursor']
            if cursor == len(plan):
                state['stage'], state['cursor'] = ('reconcile', len(state['responses']['reconcile'])) if stage == 'extract' else ('complete', len(plan))
                save()
                continue
            source = plan[cursor]
            previous = previous_evidence(plan, cursor)
            accepted = state['responses'][stage]
            # Canonical checkpoint JSON sorts string keys lexically (0, 1, 10,
            # 2, ...). Continuity and request-local span IDs require original
            # source order, including when a returned response is replayed.
            earlier = [accepted[str(index)] for index in range(cursor)]
            policy = (RECONCILIATION if stage == 'reconcile' else '') + EXTRACTION[kind]
            # The semantic policy and canonical checkpoint contract stay unchanged;
            # short request-local ids replace repeated opaque hashes on the wire only.
            # The strict schema already specifies every response field. Avoid
            # paying for its duplicate JSON example inside the instruction text.
            shape_start = policy.index('Return JSON: {')
            proof_start = policy.index('PROOF is ', shape_start)
            parent_start = policy.index('parent is null or ', proof_start)
            policy = (policy[:shape_start] + 'Use the supplied response schema. Paper titles must be original '
                      'or descriptive unknown titles; printed values remain unknown when absent.\n'
                      'Use nonzero normalized visual boxes and exact supplied text span IDs.\n'
                      + policy[parent_start:])
            policy = policy.replace('at the given offsets', 'within the supplied source ranges') + WIRE_PROMPT
            continuity = self._continuity(earlier)
            known_origins = [row['origin'] for collection in ('items', 'sharedContexts')
                             for row in continuity[collection]]
            envelope = {'stage': stage, 'courseTitle': course_title, 'sourceKind': kind,
                'source': source, 'previous': previous, 'previousIsContextOnly': True,
                'continuity': continuity, 'lectureNavigation': {}}
            references = source_references(source, previous, envelope['continuity'])
            text_anchors = TextAnchors([source], known_origins=known_origins)
            text_anchors.add_ranges([previous])
            envelope = transport_envelope(envelope, references, text_anchors)
            schema = inventory_schema(references, kind, text_anchors, current_source=source)
            # A persisted completion keeps its original transport even if the
            # caller's rollout preference has changed since the request.
            pending = state['pending']
            native_requested = (pending.get('wireVersion') == NATIVE_WIRE_VERSION if pending else
                self.native_tutorials and cursor not in state.get('nativeFallbackWindows', [])
                and native_eligible(manifest, source))
            native = NativeInventory(manifest, source, earlier=earlier) if native_requested else None
            request_version = NATIVE_WIRE_VERSION if native else WIRE_VERSION
            if native:
                policy = (RECONCILIATION if stage == 'reconcile' else '') + NATIVE_PROMPT
                envelope = {'stage': stage, 'courseTitle': course_title, 'sourceKind': kind,
                    'source': deepcopy(source), 'previous': previous, 'previousIsContextOnly': True,
                    'native': native.envelope(), 'lectureNavigation': {}}
                # Native presentation owns the intact text and its line lookup;
                # the outer record is only needed for image-role metadata.
                for span in envelope['source']['ranges']:
                    span.pop('text')
                schema = native.schema()
            schema_size = len(canonical_bytes(schema).decode('utf-8'))
            if native and pending is None and (schema_size + len(policy) + len(canonical_bytes(envelope).decode('utf-8'))
                           + image_caption_size(envelope) > MAX_TEXT_PER_CALL):
                self._native_fallback(state, cursor)
                save()
                continue
            attempts, token_limit, rejected_response = 0, 16000, None
            while attempts < 2:
                if state['pending'] is None:
                    if state['modelCalls'] >= model_call_budget:
                        state['error'] = 'Successful model-call budget exhausted; retry with a fresh budget or split the source'
                        save()
                        return self._result(manifest, plan, state)
                    try:
                        images = materialize(manifest, [previous, source], render)
                        envelope['lectureNavigation'] = {}
                        if attempts and state.get('error'):
                            envelope['contractFeedback'] = state['error'][:1200 if native else 500]
                            if native and rejected_response is not None:
                                # A repair needs the answer that failed, but it is
                                # never source evidence or input to the other pass.
                                envelope['rejectedResponse'] = rejected_response
                                repair_size = (schema_size + len(policy)
                                    + len(canonical_bytes(envelope).decode('utf-8'))
                                    + image_caption_size(envelope))
                                if repair_size > MAX_TEXT_PER_CALL:
                                    envelope.pop('rejectedResponse')
                        available = (MAX_TEXT_PER_CALL - schema_size - len(policy)
                                     - len(canonical_bytes(envelope).decode('utf-8')) - image_caption_size(envelope))
                        if native is None:
                            # Lecture navigation is optional context, never source
                            # evidence. When the strict schema, captions and
                            # originals leave no room for it, send the window
                            # without navigation instead of failing the whole
                            # source read on an optional lecture budget.
                            try:
                                if available <= 0:
                                    raise ValueError('Invalid source budget. Select fewer sources or split the file.')
                                lecture, lecture_images = lecture_context(lecture_reader, course_title,
                                    text_budget=available,
                                    image_budget=max(0, min(1, MAX_IMAGES_PER_CALL-len(images))))
                            except ValueError as exc:
                                if not str(exc).startswith(('Invalid source budget', 'Source plan needs at least',
                                                            'Indivisible lecture guide/metadata exceeds')):
                                    raise
                            else:
                                envelope['lectureNavigation'] = lecture
                                images += lecture_images
                        messages = request_messages(policy, envelope, images, schema_size=schema_size)
                        answer = chat_with_retry(self.client, model=self.model, messages=messages,
                                                 temperature=0, max_tokens=token_limit,
                                                 **structured_options('supporting_inventory', schema))
                    except Exception as exc:
                        state['error'] = (str(exc) if isinstance(exc, (ValueError, RuntimeError)) else
                                          f'Supporting provider failure ({type(exc).__name__}); retry with a compatible model')
                        save()
                        return self._result(manifest, plan, state)
                    # Persist the returned completion BEFORE parsing, including invalid/truncated ones.
                    state['modelCalls'] += 1
                    state['countedResponses'] += 1
                    state['lastCompletion'] = completion_diagnostics(answer)
                    try:
                        raw, error = response_text(answer), None
                    except ValueError as exc:
                        raw, error = None, str(exc)
                    state['pending'] = {'text': raw, 'error': error, 'stage': stage, 'cursor': cursor,
                                        'diagnostics': deepcopy(state['lastCompletion']), 'maxTokens': token_limit,
                                        'wireVersion': request_version}
                    save()
                native_response = None
                try:
                    pending = state['pending']
                    if pending['error']:
                        raise ValueError(pending['error'])
                    value = extract_json_object(pending['text'])
                    if pending.get('wireVersion') == NATIVE_WIRE_VERSION:
                        native_response = deepcopy(value)
                        value = native.decode(value)
                    elif pending.get('wireVersion') is not None:
                        if pending['wireVersion'] not in (1, 2, 3, WIRE_VERSION):
                            raise ValueError('Unsupported original inventory transport version')
                        value = decode_inventory(value, references, records=[source, previous],
                                                 known_origins=known_origins,
                                                 text_anchors=text_anchors if pending['wireVersion'] >= 3 else None,
                                                 wire_version=pending['wireVersion'])
                    value = validate_response(value, manifest, source, previous, earlier)
                except NeedsRichExtraction:
                    # If independent review needs richer evidence, neither pass
                    # may retain this window's earlier compact interpretation.
                    self._native_fallback(state, cursor)
                    save()
                    break
                except (ValueError, TypeError, KeyError) as exc:
                    if pending.get('diagnostics', {}).get('truncated') is True and pending.get('maxTokens') == 16000:
                        token_limit = 32000
                    feedback = str(exc)
                    if native and pending.get('wireVersion') == NATIVE_WIRE_VERSION:
                        feedback = native.repair_feedback(native_response, exc)
                        rejected_response = native_response
                    state['pending'] = None
                    state['error'] = 'Invalid original inventory: ' + feedback
                    attempts += 1
                    save()
                    if attempts == 2:
                        return self._result(manifest, plan, state)
                    continue
                accepted[str(cursor)] = value
                state['pending'], state['error'] = None, None
                state['cursor'] += 1
                save()
                break
        _, first_errors = inventory(manifest, plan, state['responses']['extract'])
        _, second_errors = inventory(manifest, plan, state['responses']['reconcile'])
        audit_disagreements(state, manifest, plan, client=self.client, model=self.model,
                            render=render, save=save, comparable=comparable,
                            structural_errors=set(first_errors) | set(second_errors),
                            field_audits=state['fieldAuditRequired'])
        result = self._result(manifest, plan, state)
        state['extractionCoverage'] = result['extractionCoverage']
        save()
        return result

    @staticmethod
    def _native_fallback(state, cursor):
        state['nativeFallbackWindows'] = sorted(set(state.get('nativeFallbackWindows', [])) | {cursor})
        for phase in ('extract', 'reconcile'):
            state['responses'][phase] = {key: row for key, row in state['responses'][phase].items()
                                         if int(key) < cursor}
        state['resolutions'] = {key: row for key, row in state.get('resolutions', {}).items()
                                if int(key) < cursor}
        state.update(stage='extract', cursor=cursor, pending=None, resolutionPending=None, error=None)

    @staticmethod
    def _continuity(earlier):
        paper = next((r['paper'] for r in reversed(earlier) if r['paper'] and r['paper']['startsPaper']), None)
        previous = earlier[-1] if earlier else {'items': [], 'sharedContexts': []}
        return {'currentPaper': paper,
                'items': [{'origin': i['origin'], 'itemType': i['itemType'], 'printedLabel': i['printedLabel']} for i in previous['items']],
                'sharedContexts': [{'origin': c['origin']} for c in previous['sharedContexts']]}

    @staticmethod
    def _restore(resume, bindings, manifest, plan):
        if resume is None:
            return {**deepcopy(bindings), 'stage': 'extract', 'cursor': 0,
                    'responses': {'extract': {}, 'reconcile': {}}, 'pending': None,
                    'resolutions': {}, 'resolutionPending': None, 'modelCalls': 0, 'countedResponses': 0,
                    'nativeFallbackWindows': []}
        state = deepcopy(resume)
        canonical_bytes(state)
        if not isinstance(state, dict):
            raise ValueError('Invalid extraction checkpoint')
        if any(state.get(key) != value for key, value in bindings.items()):
            raise ValueError('Extraction checkpoint belongs to different source/context/plan')
        stage, cursor = state.get('stage'), state.get('cursor')
        if stage not in ('extract', 'reconcile', 'complete') or type(cursor) is not int or not 0 <= cursor <= len(plan):
            raise ValueError('Invalid extraction checkpoint cursor')
        if type(state.get('modelCalls')) is not int or state['modelCalls'] < 0:
            raise ValueError('Invalid checkpoint spent calls')
        if type(state.get('countedResponses')) is not int or not 0 <= state['countedResponses'] <= state['modelCalls']:
            raise ValueError('Checkpoint omitted successful model calls')
        if type(state.get('fieldAuditRequired', False)) is not bool:
            raise ValueError('Invalid independent field-audit requirement')
        fallbacks = state.setdefault('nativeFallbackWindows', [])
        if (not isinstance(fallbacks, list) or any(type(index) is not int or not 0 <= index < len(plan)
                                                 for index in fallbacks)
                or fallbacks != sorted(set(fallbacks))):
            raise ValueError('Invalid native fallback checkpoint windows')
        responses = state.get('responses')
        if not isinstance(responses, dict) or set(responses) != {'extract', 'reconcile'}:
            raise ValueError('Invalid checkpoint response ledger')
        invalid_reference_window = None
        for phase in ('extract', 'reconcile'):
            expected = cursor if phase == stage else (len(plan) if phase == 'extract' or stage == 'complete' else 0)
            if phase == 'extract' and stage == 'extract':
                expected = cursor
            rows = responses[phase]
            if phase == 'reconcile' and stage == 'extract' and isinstance(rows, dict):
                expected = len(rows)
                if expected > cursor:
                    raise ValueError('Reconciliation checkpoint skipped extraction')
            if not isinstance(rows, dict) or set(rows) != {str(i) for i in range(expected)}:
                raise ValueError('Checkpoint skipped original source windows')
            earlier = []
            for index in range(expected):
                try:
                    row = validate_response(rows[str(index)], manifest, plan[index], previous_evidence(plan, index), earlier)
                except (InventoryReferenceError, ExclusionCoverageError):
                    # Old checkpoints accepted unresolved topic links and empty
                    # whole-window exclusions. Re-read the earliest invalid
                    # window and all dependent continuations; never grandfather
                    # those references into a complete inventory. All other
                    # schema and original-proof failures still reject recovery.
                    invalid_reference_window = min(index, invalid_reference_window) if invalid_reference_window is not None else index
                    row = rows[str(index)]
                if row != rows[str(index)]:
                    raise ValueError('Checkpoint response changed')
                earlier.append(row)
        pending = state.get('pending')
        if pending is not None and (not isinstance(pending, dict) or pending.get('stage') != stage or pending.get('cursor') != cursor or stage == 'complete'):
            raise ValueError('Pending response belongs to another checkpoint cursor')
        if pending and pending.get('wireVersion') == NATIVE_WIRE_VERSION and cursor in fallbacks:
            raise ValueError('Native pending response conflicts with rich fallback')
        state.setdefault('resolutions', {})
        state.setdefault('resolutionPending', None)
        if not isinstance(state['resolutions'], dict):
            raise ValueError('Invalid reconciliation audit ledger')
        for key, certificate in state['resolutions'].items():
            if key not in responses['extract'] or key not in responses['reconcile']:
                raise ValueError('Reconciliation audit has no independent inventories')
            validate_certificate(certificate, manifest, plan[int(key)], previous_evidence(plan, int(key)),
                                 responses['extract'][key], responses['reconcile'][key])
        audit_pending = state['resolutionPending']
        if audit_pending is not None:
            if (not isinstance(audit_pending, dict) or type(audit_pending.get('cursor')) is not int or
                    not 0 <= audit_pending['cursor'] < len(plan) or stage != 'complete'):
                raise ValueError('Invalid pending reconciliation audit')
            key = str(audit_pending['cursor'])
            if key in state['resolutions'] or key not in responses['extract'] or key not in responses['reconcile']:
                raise ValueError('Pending reconciliation audit belongs to another cursor')
        if invalid_reference_window is not None:
            for phase in ('extract', 'reconcile'):
                state['responses'][phase] = {key: value for key, value in responses[phase].items()
                                              if int(key) < invalid_reference_window}
            state['resolutions'] = {key: value for key, value in state['resolutions'].items()
                                      if int(key) < invalid_reference_window}
            state['resolutionPending'], state['pending'] = None, None
            state['stage'], state['cursor'] = 'extract', invalid_reference_window
        return state

    @staticmethod
    def _result(manifest, plan, state):
        extracted, reconciled = (state['responses'][phase] for phase in ('extract', 'reconcile'))
        result, errors = inventory(manifest, plan, extracted)
        _, reconcile_errors = inventory(manifest, plan, reconciled)
        for unit, reasons in reconcile_errors.items():
            errors.setdefault(unit, []).extend(reasons)
        result['extractionCoverage'] = coverage(manifest, plan, extracted, reconciled, errors,
            state.get('resolutions'), require_audit=state.get('fieldAuditRequired', False))
        result['extractionCoverage']['modelCalls'] = state['modelCalls']
        if state.get('error'):
            result['extractionCoverage']['error'] = state['error']
        return result
