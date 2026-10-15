"""Restart-safe complete supporting extraction with independent original reconciliation."""
from copy import deepcopy

from src.config.supporting_prompts import EXTRACTION, RECONCILIATION
from src.supporting.contracts import (canonical_bytes, digest, validate_supporting_manifest,
    DEFAULT_MODEL_CALL_BUDGET, MAX_TEXT_PER_CALL, MAX_IMAGES_PER_CALL)
from src.supporting.extraction_source import (prepare_pages, lecture_context, source_plan,
    previous_evidence, materialize, request_messages)
from src.supporting.extraction_inventory import validate_response, inventory, coverage
from src.utils.ai_retry import chat_with_retry
from src.utils.ai_contracts import response_text
from src.utils.json_parse import extract_json_object


class SupportingExtractor:
    def __init__(self, client, model):
        self.client, self.model = client, model

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
        state['modelCallBudget'] = model_call_budget
        if model_calls is not None and model_calls < state.get('modelCalls', 0):
            state['countedResponses'] = 0  # explicit retry starts a new job call budget
            old_result = self._result(manifest, plan, state)
            unresolved = list(old_result['extractionCoverage']['reasons'])
            if unresolved:
                first = next(i for i, row in enumerate(plan) if row['ref']['unitId'] in unresolved)
                # Retain only a fully checked prefix; downstream continuations may
                # depend on a corrected boundary/item and must be rebuilt.
                for phase in ('extract', 'reconcile'):
                    state['responses'][phase] = {k: v for k, v in state['responses'][phase].items() if int(k) < first}
                state['stage'], state['cursor'], state['pending'] = 'extract', first, None
        state['modelCalls'] = state.get('modelCalls', 0) if model_calls is None else model_calls
        if state['modelCalls'] > model_call_budget:
            raise ValueError('Recovered calls exceed the configured budget')
        # A new invocation may retry a failed window, but never clears its accepted ledger.
        state['error'] = None
        def save():
            canonical_bytes(state)
            checkpoint(deepcopy(state))

        while state['stage'] != 'complete':
            stage, cursor = state['stage'], state['cursor']
            if cursor == len(plan):
                state['stage'], state['cursor'] = ('reconcile', len(state['responses']['reconcile'])) if stage == 'extract' else ('complete', len(plan))
                save()
                continue
            source = plan[cursor]
            previous = previous_evidence(plan, cursor)
            accepted = state['responses'][stage]
            earlier = list(accepted.values())
            policy = (RECONCILIATION if stage == 'reconcile' else '') + EXTRACTION[kind]
            envelope = {'stage': stage, 'courseTitle': course_title, 'sourceKind': kind,
                'source': source, 'previous': previous, 'previousIsContextOnly': True,
                'continuity': self._continuity(earlier), 'lectureNavigation': {}}
            attempts = 0
            while attempts < 2:
                if state['pending'] is None:
                    if state['modelCalls'] >= model_call_budget:
                        state['error'] = 'Successful model-call budget exhausted; retry with a fresh budget or split the source'
                        save()
                        return self._result(manifest, plan, state)
                    try:
                        images = materialize(manifest, [previous, source], render)
                        envelope['lectureNavigation'] = {}
                        available = MAX_TEXT_PER_CALL - len(policy) - len(canonical_bytes(envelope).decode('utf-8'))
                        lecture, lecture_images = lecture_context(lecture_reader, course_title,
                            text_budget=available, image_budget=min(1, MAX_IMAGES_PER_CALL-len(images)))
                        envelope['lectureNavigation'] = lecture
                        images += lecture_images
                        messages = request_messages(policy, envelope, images)
                        answer = chat_with_retry(self.client, model=self.model, messages=messages,
                                                 temperature=0, max_tokens=16000)
                    except Exception as exc:
                        state['error'] = (str(exc) if isinstance(exc, (ValueError, RuntimeError)) else
                                          f'Supporting provider failure ({type(exc).__name__}); retry with a compatible model')
                        save()
                        return self._result(manifest, plan, state)
                    # Persist the returned completion BEFORE parsing, including invalid/truncated ones.
                    state['modelCalls'] += 1
                    state['countedResponses'] += 1
                    try:
                        raw, error = response_text(answer), None
                    except ValueError as exc:
                        raw, error = None, str(exc)
                    state['pending'] = {'text': raw, 'error': error, 'stage': stage, 'cursor': cursor}
                    save()
                try:
                    pending = state['pending']
                    if pending['error']:
                        raise ValueError(pending['error'])
                    value = validate_response(extract_json_object(pending['text']), manifest, source, previous, earlier)
                except (ValueError, TypeError, KeyError) as exc:
                    state['pending'] = None
                    state['error'] = 'Invalid original inventory: ' + str(exc)
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
        result = self._result(manifest, plan, state)
        state['extractionCoverage'] = result['extractionCoverage']
        save()
        return result

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
                    'responses': {'extract': {}, 'reconcile': {}}, 'pending': None, 'modelCalls': 0, 'countedResponses': 0}
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
        responses = state.get('responses')
        if not isinstance(responses, dict) or set(responses) != {'extract', 'reconcile'}:
            raise ValueError('Invalid checkpoint response ledger')
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
                row = validate_response(rows[str(index)], manifest, plan[index], previous_evidence(plan, index), earlier)
                if row != rows[str(index)]:
                    raise ValueError('Checkpoint response changed')
                earlier.append(row)
        pending = state.get('pending')
        if pending is not None and (not isinstance(pending, dict) or pending.get('stage') != stage or pending.get('cursor') != cursor or stage == 'complete'):
            raise ValueError('Pending response belongs to another checkpoint cursor')
        return state

    @staticmethod
    def _result(manifest, plan, state):
        extracted, reconciled = (state['responses'][phase] for phase in ('extract', 'reconcile'))
        result, errors = inventory(manifest, plan, extracted)
        _, reconcile_errors = inventory(manifest, plan, reconciled)
        for unit, reasons in reconcile_errors.items():
            errors.setdefault(unit, []).extend(reasons)
        result['extractionCoverage'] = coverage(manifest, plan, extracted, reconciled, errors)
        result['extractionCoverage']['modelCalls'] = state['modelCalls']
        if state.get('error'):
            result['extractionCoverage']['error'] = state['error']
        return result
