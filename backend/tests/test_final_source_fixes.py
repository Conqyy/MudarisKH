"""Regressions for the final source-first integration review."""
import asyncio
from io import BytesIO
import threading

import pytest
from fastapi import UploadFile

from tests.test_source_generation_integration import source_api


@pytest.mark.parametrize('kind', ['tutorial', 'historical'])
@pytest.mark.parametrize('stage', ['foundation', 'resolve', 'prepare', 'tag'])
def test_supporting_source_work_allows_event_loop_progress(source_api, monkeypatch, kind, stage):
    api, db, docs, scope, calls = source_api
    import src.services.source_evidence as evidence_module
    entered, progressed = threading.Event(), threading.Event()
    observed = []
    event_loop_thread = threading.get_ident()
    target, method = (api, '_require_document_foundation' if stage == 'foundation' else '_source_reader') if stage in ('foundation', 'resolve') else (evidence_module, 'chat_with_retry')
    original = getattr(target, method)

    def delayed(*args, **kwargs):
        policy = kwargs.get('messages', [{'content': ''}])[0]['content']
        if stage in ('foundation', 'resolve') or (stage == 'prepare' and 'Read EVERY' in policy) or (stage == 'tag' and 'Assess whether' in policy):
            entered.set()
            # Block the actual injected synchronous source-provider call. A
            # bounded wait makes an event-loop deadlock fail, not hang.
            observed.append(progressed.wait(1) and threading.get_ident() != event_loop_thread)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, method, delayed)
    agent = api.doc_processor if kind == 'tutorial' else api.hist_analyzer
    agent.extract_text.return_value = agent.extract_exam_text.return_value = 'The original sum formula is n(n+1)/2 and is worth five marks.'
    agent.analyze_tutorial.return_value = {'topics': ['ORIGINAL_FORMULA'], 'problems': [], 'problemCount': 2}
    agent.analyze_pdf.return_value = {'topicWeights': [{'topic': 'ORIGINAL_FORMULA'}], 'totalQuestions': 12}
    upload = UploadFile(filename='source.docx' if kind == 'tutorial' else 'source.pdf', file=BytesIO(b'synthetic'))
    route = api.upload_tutorial if kind == 'tutorial' else api.upload_historical_exam

    async def other_task():
        for _ in range(2000):
            if entered.is_set():
                progressed.set()
                return
            await asyncio.sleep(0.001)
        pytest.fail('The expected synchronous source stage was never reached')

    async def run():
        result, _ = await asyncio.gather(route(upload, 'untrusted-owner', 'course', title='Source', uid='owner'), other_task())
        return result

    assert asyncio.run(run())['status'] == 'success'
    assert observed and all(observed), f'{stage} blocked the ASGI event loop'
    update = db.update_tutorial if kind == 'tutorial' else db.update_historical_exam
    completed = [c for c in update.call_args_list if c.args[1].get('status') == 'completed']
    assert completed[0].kwargs['expected_foundation_revision']
    assert completed[0].args[1]['analysis']['sourceScope']['allowedRefs'] == scope['allowedRefs']


@pytest.mark.parametrize('selection', [['missing'], ['doc', 'missing'], ['foreign'], ['wrong-course']])
def test_tutor_rejects_original_invalid_selection_before_provider(source_api, monkeypatch, selection):
    api, db, docs, scope, calls = source_api
    from src.database.firebase_client import FirebaseClient
    from tests.foundation_fixtures import confirm_lecture_foundation, lecture_document
    confirm_lecture_foundation(db, [*docs, lecture_document('other'),
        lecture_document('foreign', userId='someone-else'), lecture_document('wrong-course', courseId='other-course')])
    monkeypatch.setattr(db, '_select_sources', FirebaseClient._select_sources)
    monkeypatch.setattr(db, 'get_tutor_resources', lambda *a, **kw: FirebaseClient.get_tutor_resources(db, *a, **kw))
    api.tutor_agent.reply_grounded.return_value = {'reply': 'n(n+1)/2', 'sourceRefs': scope['allowedRefs']}
    with pytest.raises(api.HTTPException) as exc:
        api.tutor_chat(api.TutorChatRequest(course_id='course', user_id='untrusted-owner', document_ids=selection,
            messages=[{'role': 'user', 'content': 'Explain sum'}]), uid='owner')
    assert exc.value.status_code == 422
    assert calls == []
    api.tutor_agent.reply_grounded.assert_not_called()


@pytest.mark.parametrize('selection, expected', [(['doc'], ['doc']), ([], ['doc', 'other']), (None, ['doc', 'other']), ('omitted', ['doc', 'other'])])
def test_tutor_valid_subset_and_deliberate_foundation_fallback(source_api, monkeypatch, selection, expected):
    api, db, docs, scope, calls = source_api
    from src.database.firebase_client import FirebaseClient
    from tests.foundation_fixtures import confirm_lecture_foundation, lecture_document
    confirm_lecture_foundation(db, [*docs, lecture_document('other')])
    monkeypatch.setattr(db, '_select_sources', FirebaseClient._select_sources)
    monkeypatch.setattr(db, 'get_tutor_resources', lambda *a, **kw: FirebaseClient.get_tutor_resources(db, *a, **kw))
    api.tutor_agent.reply_grounded.return_value = {'reply': 'n(n+1)/2', 'sourceRefs': scope['allowedRefs']}
    selection_args = {} if selection == 'omitted' else {'document_ids': selection}
    api.tutor_chat(api.TutorChatRequest(course_id='course', user_id='untrusted-owner', **selection_args,
        messages=[{'role': 'user', 'content': 'Explain sum'}]), uid='owner')
    turn = db.save_tutor_chat.call_args.args[2]['sourceTurns'][0]
    assert [d['id'] for d in turn['sourceScope']['documents']] == expected
    assert [d['id'] for d in api.tutor_agent.reply_grounded.call_args.args[0]['documents']] == expected
