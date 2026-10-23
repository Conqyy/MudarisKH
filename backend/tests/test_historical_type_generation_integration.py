"""Category isolation through real storage, readiness, compilation and providers."""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from src.agents.summary_generator import SummaryGeneratorAgent
from src.supporting.contracts import supporting_revision
from tests.foundation_fixtures import source_refs, stub_source_provider
from tests.supporting_fixtures import supporting_manifest
from tests.test_atomic_data import database, cloud_database
from tests.test_document_job_storage import job_db
from tests.test_exam_prediction_integration import _install_generation
from tests.test_supporting_job_storage import repository, identity, queue_claim
from tests.test_supporting_storage import library, report_for


CATEGORIES = ('quiz', 'midterm', 'final')


@pytest.fixture(autouse=True)
def source_provider_boundary(monkeypatch):
    stub_source_provider(monkeypatch)


@pytest.fixture
def categorized_papers(library):
    """Migrate opaque legacy IDs without rewriting their adopted evidence."""
    db = library.repository.database
    papers = {}
    for category in CATEGORIES:
        source_id = f'legacy_{category}_collection'
        material = identity(material=source_id)
        marker = f'EXCLUSIVE_{category.upper()}_MATERIAL'
        raw = marker.encode()
        manifest = supporting_manifest(texts=[f'Explain trees {marker}'])
        manifest['identity'] = material
        manifest['originalDigest'] = sha256(raw).hexdigest()
        manifest['sourceRevision'] = supporting_revision(manifest['originalDigest'], manifest['units'])
        _, claim, _ = queue_claim(library.repository, material=material,
                                 original=manifest['originalDigest'])
        library.save_source(material, claim, raw, manifest)
        report = report_for(library, manifest, count=4)

        def bind_refs(value):
            if isinstance(value, dict):
                if value.get('kind') == 'historical_exam' and value.get('materialId') == 'source':
                    value['materialId'] = source_id
                for child in value.values():
                    bind_refs(child)
            elif isinstance(value, list):
                for child in value:
                    bind_refs(child)

        bind_refs(report)
        template = deepcopy(report['papers'][0])
        report['papers'] = []
        for index, question_type in enumerate(('mcq', 'written')):
            paper_id = f'paper{index + 1}'
            ids = [item['id'] for item in report['items'][index * 2:index * 2 + 2]]
            for item in report['items'][index * 2:index * 2 + 2]:
                item.update(paperId=paper_id, text=f'Explain trees {marker}')
            # One matches the user choice; the other deliberately disagrees.
            # Both belong to this uploaded collection and must affect structure.
            detected = category if index == 0 else CATEGORIES[(CATEGORIES.index(category) + 1) % 3]
            report['papers'].append({**template, 'paperId': paper_id,
                'examType': detected, 'questionIds': ids, 'totalQuestions': 2,
                'unknownQuestionTypeIds': [], 'questionTypes': [
                    {'type': question_type, 'count': 2, 'percentage': 100, 'questionIds': ids}]})
        version = library.save_report(material, claim, report)
        before = library.repository.get_owned(material)
        db.classify_historical_exam(source_id, category, 'u', 'c')
        assert library.repository.get_owned(material) == {**before, 'examType': category}
        assert library.load_source(material) == manifest
        assert library.load_report(material, version['revision']) == report
        papers[category] = {'id': source_id, 'marker': marker, 'report': version['revision'],
                            'source': manifest['sourceRevision']}
    return papers


def _watch_reads(monkeypatch, library):
    """Observe the real read boundaries after publication/classification."""
    log = {'queries': [], 'source': [], 'report': [], 'queue': []}
    db = library.repository.database
    query = db.get_course_historical_exams
    def get_historical(*args, **kwargs):
        log['queries'].append(kwargs.get('exam_type', args[2] if len(args) > 2 else None))
        return query(*args, **kwargs)
    monkeypatch.setattr(db, 'get_course_historical_exams', get_historical)
    for method, key in (('load_source', 'source'), ('load_report', 'report')):
        original = getattr(library, method)
        def read(material, *args, _method=original, _key=key, **kwargs):
            log[_key].append(material['materialId'])
            return _method(material, *args, **kwargs)
        monkeypatch.setattr(library, method, read)
    queue = library.repository.queue
    def enqueue(*args, **kwargs):
        log['queue'].append(deepcopy(args))
        return queue(*args, **kwargs)
    monkeypatch.setattr(library.repository, 'queue', enqueue)
    return log


def _assert_isolated(log, messages, papers, category):
    selected = papers[category]
    assert log['queries'] and set(log['queries']) == {category}
    assert log['source'] and set(log['source']) == {selected['id']}
    assert log['report'] and set(log['report']) == {selected['id']}
    assert not log['queue']
    text = json.dumps(messages, ensure_ascii=False)
    assert selected['marker'] in text
    assert selected['id'] in text
    assert selected['report'] in text
    for other_category, other in papers.items():
        if other_category != category:
            assert other['marker'] not in text
            assert other['id'] not in text
            assert other['report'] not in text


@pytest.mark.parametrize('category', CATEGORIES)
@pytest.mark.parametrize('selection', ['all', 'explicit', 'derived'])
def test_exam_category_scopes_every_read_and_keeps_all_merged_papers(
        monkeypatch, api_module, library, categorized_papers, category, selection):
    api = api_module
    seen = _install_generation(monkeypatch, api, library)
    reads = _watch_reads(monkeypatch, library)
    source_id = categorized_papers[category]['id']
    historical_type = {} if selection == 'derived' else {'historical_exam_type': category}
    result = api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(
        user_id='u', course_id='c', total_marks=5, exam_type=category.title(),
        historical_exam_ids=[source_id] if selection == 'explicit' else None,
        tutorial_ids=[], audio_ids=[], **historical_type), uid='u')
    _assert_isolated(reads, seen, categorized_papers, category)
    blueprint = result['exam_blueprint']
    assert blueprint['totalQuestions'] == 2
    assert [(row['type'], row['count']) for row in blueprint['questionTypes']] == [('mcq', 1), ('written', 1)]
    assert blueprint['evidence']['paperCount'] == 2
    assert blueprint['evidence']['sourceCount'] == 1
    assert all(row['usedForStructure'] for row in blueprint['evidence']['sources'])
    assert {row['sourceId'] for row in blueprint['evidence']['sources']} == {source_id}
    saved = library.repository.database.get_exam(result['doc_id'])
    assert saved['examBlueprint'] == blueprint
    snapshot = saved['supportingSnapshot']
    assert snapshot['historicalExamType'] == category
    assert [row['identity']['materialId'] for row in snapshot['materials']] == [source_id]
    assert snapshot['materials'][0]['reportRevision'] == categorized_papers[category]['report']


@pytest.mark.parametrize('endpoint', ['exam', 'summary'])
def test_explicit_wrong_category_rejects_before_source_report_model_or_autoqueue(
        monkeypatch, api_module, library, categorized_papers, endpoint):
    api = api_module
    seen = _install_generation(monkeypatch, api, library)
    reads = _watch_reads(monkeypatch, library)
    request = dict(user_id='u', course_id='c', historical_exam_type='quiz',
        historical_exam_ids=[categorized_papers['midterm']['id']], tutorial_ids=[], audio_ids=[])
    if endpoint == 'exam':
        payload = api.EnhancedExamGenerateRequest(**request, exam_type='Quiz', total_marks=5)
        generate = api.generate_enhanced_exam_endpoint
    else:
        payload = api.SummaryGenerateRequest(**request)
        generate = api.generate_summary_endpoint
        monkeypatch.setattr(api.summary_agent, 'generate_summary', lambda **kwargs: pytest.fail('Wrong category reached summary model'))
    with pytest.raises(api.HTTPException) as error:
        generate(payload, uid='u')
    assert error.value.status_code in (404, 409, 422)
    assert reads['queries'] and set(reads['queries']) == {'quiz'}
    assert not reads['source'] and not reads['report'] and not reads['queue']
    assert not seen
    assert library.repository.database.get_course_exams('c', 'u') == []
    assert library.repository.database.get_course_summaries('c', 'u') == []


def test_empty_historical_selection_does_not_expand_to_all_category_materials(
        monkeypatch, api_module, library, categorized_papers):
    api = api_module
    seen = _install_generation(monkeypatch, api, library)
    reads = _watch_reads(monkeypatch, library)
    result = api.generate_enhanced_exam_endpoint(api.EnhancedExamGenerateRequest(
        user_id='u', course_id='c', total_marks=5, exam_type='Quiz',
        historical_exam_type='quiz', historical_exam_ids=[], tutorial_ids=[], audio_ids=[]), uid='u')
    assert not reads['source'] and not reads['report'] and not reads['queue']
    assert not reads['queries'] or set(reads['queries']) == {'quiz'}
    assert result['exam_blueprint'] is None
    snapshot = library.repository.database.get_exam(result['doc_id'])['supportingSnapshot']
    assert snapshot['historicalExamType'] == 'quiz'
    assert snapshot['materials'] == []
    text = json.dumps(seen)
    for paper in categorized_papers.values():
        assert paper['id'] not in text and paper['marker'] not in text


@pytest.mark.parametrize('requested_category', (*CATEGORIES, None))
def test_summary_hands_only_the_chosen_category_to_the_real_model_prompt(
        monkeypatch, api_module, library, categorized_papers, requested_category):
    api = api_module
    category = requested_category or 'final'
    _install_generation(monkeypatch, api, library)
    agent = SummaryGeneratorAgent.__new__(SummaryGeneratorAgent)
    agent.client, agent.model_id = object(), 'fake'
    monkeypatch.setattr(api, 'summary_agent', agent)
    refs = source_refs([library.repository.test_lecture])
    summary = {'title': 'Trees', 'overview': 'Trees have nodes.',
        'sections': [{'heading': 'Trees', 'content': 'A root has children.',
                      'keyPoints': [], 'sourceRefs': refs, 'examLikelihood': 'high',
                      'examWeight': 100}],
        'keyTerms': [], 'examFocus': [], 'sourceRefs': refs}
    summary['provenance'] = [{'path': path, 'authority': 'lecture',
        'relation': 'lecture_supported', 'sourceRefs': refs, 'supportingSourceRefs': [],
        'supportingSourceProofs': [], 'lectureAnchorRefs': []} for path in
        ('/overview', '/sections/0/heading', '/sections/0/content')]
    seen = []
    def provider(*args, **kwargs):
        seen.append(deepcopy(kwargs['messages']))
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(summary)))])
    monkeypatch.setattr('src.agents.summary_generator.chat_with_retry', provider)
    reads = _watch_reads(monkeypatch, library)
    historical_type = {} if requested_category is None else {'historical_exam_type': category}
    result = api.generate_summary_endpoint(api.SummaryGenerateRequest(
        user_id='u', course_id='c', historical_exam_ids=None, tutorial_ids=[],
        audio_ids=[], **historical_type), uid='u')
    _assert_isolated(reads, seen, categorized_papers, category)
    saved = library.repository.database.get_summary(result['doc_id'])
    snapshot = saved['supportingSnapshot']
    assert snapshot['historicalExamType'] == category
    assert [row['identity']['materialId'] for row in snapshot['materials']] == [categorized_papers[category]['id']]
