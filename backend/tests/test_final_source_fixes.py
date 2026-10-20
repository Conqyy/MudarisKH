"""Regressions for the final source-first integration review."""
import asyncio
from io import BytesIO
import threading
from unittest.mock import MagicMock

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
    api.supporting_repository = MagicMock()
    api.supporting_repository.queue.return_value = {'id': 'job'}
    api._supporting_runner = MagicMock()
    agent = api.doc_processor if kind == 'tutorial' else api.hist_analyzer
    upload = UploadFile(filename='source.docx' if kind == 'tutorial' else 'source.pdf', file=BytesIO(b'synthetic'))
    route = api.upload_tutorial if kind == 'tutorial' else api.upload_historical_exam

    async def other_task():
        if stage != 'foundation':
            await asyncio.sleep(0)
            progressed.set()
            return
        for _ in range(2000):
            if entered.is_set():
                progressed.set()
                return
            await asyncio.sleep(0.001)
        pytest.fail('The expected synchronous source stage was never reached')

    async def run():
        result, _ = await asyncio.gather(route(upload, 'untrusted-owner', 'course', title='Source', uid='owner'), other_task())
        return result

    result = asyncio.run(run())
    assert result['status'] == 'queued'
    if stage == 'foundation':
        assert observed and all(observed), 'foundation validation blocked the ASGI event loop'
    else:
        assert observed == [], f'{stage} ran before the durable worker'
    assert db.upload_file_to_storage.call_args.args[0] == b'synthetic'
    assert api.supporting_repository.queue.call_args.kwargs['foundation_revision'] == scope['foundationRevision']
    api._supporting_runner.submit.assert_called_once_with(result['identity'])
    agent.extract_text.assert_not_called()
    agent.extract_exam_text.assert_not_called()
    agent.analyze_tutorial.assert_not_called()
    agent.analyze_pdf.assert_not_called()
    update = db.update_tutorial if kind == 'tutorial' else db.update_historical_exam
    update.assert_not_called()


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
    checked = api.tutor_agent.reply_grounded.call_args.kwargs['supporting_context']
    assert [d['id'] for d in checked['scopeSnapshot']['documents']] == expected
    assert set(api.tutor_agent.reply_grounded.call_args.args[0]) == {'course'}
