"""Selection validates actual exact-version artifacts, not persisted flags."""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from tests.foundation_fixtures import lecture_document, install_source_artifacts
from src.services.document_library import DocumentLibrary


def fixture_database(rows):
    db = MagicMock()
    install_source_artifacts(db, rows)
    return db


def resolve(db, ids=None, library=None):
    from src.utils.source_context import resolve_source_scope
    return resolve_source_scope(db, library or DocumentLibrary(db), 'owner', 'course', ids)


def test_scope_preserves_order_deduplicates_and_ignores_guide_topic_omissions():
    rows = [lecture_document('a'), lecture_document('b', 'Other')]
    rows[0]['analysis'] = None
    db = fixture_database(rows)
    scope = resolve(db, ['b', 'a', 'b'])
    assert [d['id'] for d in scope['documents']] == ['b', 'a']
    assert [(r['documentId'], r['unitId']) for r in scope['allowedRefs']] == [('b', 'b0001'), ('a', 'b0001')]
    assert scope == resolve(db, ['b', 'a'])
    assert scope['documents'][1]['guide'] == rows[0]['guide']
    scope['manifests'][0]['units'][0]['text'] = 'mutated'
    assert 'mutated' not in resolve(db, ['b'])['manifests'][0]['units'][0]['text']
    assert 'sourceVersions' not in scope['documents'][0]


@pytest.mark.parametrize('ids', [['missing'], ['a', 'missing'], ['foreign'], ['wrong-course'], ['pending'], ['../a'], [None], 'a'])
def test_invalid_explicit_selection_is_never_silently_dropped(ids):
    rows = [lecture_document('a'), lecture_document('foreign', userId='other'),
            lecture_document('wrong-course', courseId='other'), lecture_document('pending', guideStatus='pending')]
    with pytest.raises(ValueError):
        resolve(fixture_database(rows), ids)


def test_none_selects_only_owned_ready_sources_and_empty_excludes_all():
    rows = [lecture_document('a'), lecture_document('foreign', userId='other'),
            lecture_document('wrong-course', courseId='other'), lecture_document('pending', guideStatus='pending')]
    db = fixture_database(rows)
    assert [d['id'] for d in resolve(db)['documents']] == ['a']
    assert resolve(db, [])['allowedRefs'] == []
    assert resolve(db, [])['manifests'] == []


@pytest.mark.parametrize('artifact', ['upload', 'manifest', 'exact'])
def test_flags_cannot_unlock_missing_or_corrupt_artifacts(artifact):
    row = lecture_document()
    version = row['sourceVersions'][row['sourceRevision']]
    path = {'upload': row['storagePath'], 'manifest': version['manifestPath'], 'exact': version['originalPath']}[artifact]
    row['_artifactFiles'][path].write_bytes(b'corrupt')
    db = fixture_database([row])
    assert resolve(db)['documents'] == []
    with pytest.raises(ValueError):
        resolve(db, ['doc'])


def test_supplied_library_is_used_without_weakening_artifact_validation():
    row = lecture_document()
    db = fixture_database([row])
    class UnavailableLibrary(DocumentLibrary):
        def load_manifest(self, *args, **kwargs):
            raise FileNotFoundError('intentionally unavailable boundary')
    with pytest.raises(ValueError):
        resolve(db, ['doc'], UnavailableLibrary(db))


def test_change_during_original_read_cannot_leave_ready_scope():
    row = lecture_document()
    db = fixture_database([row])
    download = db.download_file_from_storage.side_effect
    def changed(path, uid):
        result = download(path, uid)
        row['guideStatus'] = 'pending'
        return result
    db.download_file_from_storage.side_effect = changed
    with pytest.raises(ValueError):
        resolve(db, ['doc'])


def semantic_reader(status='matched', relation='supports_topic'):
    def read(topic, batches):
        evidence = deepcopy([e for b in batches for e in b['evidence']])
        item = evidence[0]
        return {'scopeStatus': status, 'suppliedEvidence': evidence,
                'proofs': [{'ref': item['ref'], **item['ranges'][0], 'relation': relation,
                            'reason': 'The cited statement explicitly supports this semantic judgment.'}]}
    return read


def test_semantic_evidence_matches_guide_omitted_topic_without_mutation():
    from src.utils.source_context import match_supporting_topics
    from tests.test_source_context import source_scope
    scope = source_scope(['Café search trees; أَشجار البحث are covered in detail.'])
    topics = [{'topic': 'اشجار البحث', 'weight': 100, 'scopeStatus': 'outside_selected_scope'}]
    before = deepcopy(topics)
    result = match_supporting_topics(topics, scope, semantic_reader())
    assert result[0]['scopeStatus'] == 'matched'
    assert result[0]['sourceRefs'] == scope['allowedRefs']
    assert result[0]['scopeEvidence'][0]['text'] in scope['manifests'][0]['units'][0]['text']
    assert topics == before


@pytest.mark.parametrize('reader', [lambda topic, batches: None,
                                    lambda topic, batches: {'scopeStatus': 'matched'},
                                    lambda topic, batches: {'scopeStatus': 'outside_selected_scope', 'selectedScopeReviewed': True}])
def test_failed_or_self_asserted_lookup_is_unverified_never_outside(reader):
    from src.utils.source_context import match_supporting_topics
    from tests.test_source_context import source_scope
    result = match_supporting_topics([{'topic': 'Trees', 'inScope': True, 'sourceRefs': [{'old': 'stale'}]}],
                                     source_scope(['Trees are mentioned.']), reader)
    assert result[0]['scopeStatus'] == 'unverified'
    assert result[0]['sourceRefs'] == [] and result[0]['inScope'] is False


def test_raw_word_overlap_is_only_candidate_retrieval_not_semantic_support():
    from src.utils.source_context import match_supporting_topics
    from tests.test_source_context import source_scope
    def unrelated(topic, batches):
        assert batches  # Retrieval finds the word but semantic reading rejects the meaning.
        return {'scopeStatus': 'unverified', 'suppliedEvidence': batches[0]['evidence'], 'proofs': []}
    result = match_supporting_topics([{'topic': 'binary search trees'}], source_scope(['A binary star lit up the trees.']), unrelated)
    assert result[0]['scopeStatus'] == 'unverified' and result[0]['sourceRefs'] == []


def test_outside_verdict_requires_explicit_selected_source_exclusion_statement():
    from src.utils.source_context import match_supporting_topics
    from tests.test_source_context import source_scope
    scope = source_scope(['This lecture covers trees only; graph algorithms are excluded from this chapter.'])
    result = match_supporting_topics([{'topic': 'graph algorithms'}], scope,
                                     semantic_reader('outside_selected_scope', 'explicit_exclusion'))
    assert result[0]['scopeStatus'] == 'outside_selected_scope'
    assert result[0]['sourceRefs'] == scope['allowedRefs']
    assert result[0]['inScope'] is False


@pytest.mark.parametrize('corruption', ['quote', 'range', 'foreign', 'revision', 'unsupplied', 'relation'])
def test_fabricated_or_unsupplied_semantic_proof_cannot_pass(corruption):
    from src.utils.source_context import match_supporting_topics
    from tests.test_source_context import source_scope
    scope = source_scope(['Trees are explained here.', 'Trees elsewhere.'])
    def reader(topic, batches):
        result = semantic_reader()(topic, batches)
        proof = result['proofs'][0]
        if corruption == 'quote': proof['text'] = 'fabricated exclusion'
        if corruption == 'range': proof['end'] += 100
        if corruption == 'foreign': proof['ref']['documentId'] = 'foreign'
        if corruption == 'revision': proof['ref']['sourceRevision'] = 'a'*64
        if corruption == 'unsupplied': result['suppliedEvidence'] = []
        if corruption == 'relation': proof['relation'] = 'word_overlap'
        return result
    assert match_supporting_topics([{'topic': 'Trees'}], scope, reader)[0]['scopeStatus'] == 'unverified'


def test_paper_structure_survives_unverified_topics_and_semantic_retagging():
    from src.utils.topic_scope import retag_topic_weights
    from src.utils.exam_blueprint import build_exam_blueprint
    from tests.test_source_context import source_scope
    from tests.test_exam_blueprint import paper, source
    rows = [source('past', [paper('one', topic='Trees'), paper('two', count=40, marks=80, topic='Unknown')])]
    before = deepcopy(rows)
    def read(topic, batches):
        return semantic_reader()(topic, batches) if topic['topic'] == 'Trees' else None
    matched = retag_topic_weights(rows, [], source_scope=source_scope(['Trees are covered.']), read_evidence=read)
    assert rows == before
    assert matched[0]['papers'][1]['topicWeights'][0]['scopeStatus'] == 'unverified'
    baseline, actual = build_exam_blueprint(rows, 30), build_exam_blueprint(matched, 30)
    assert [t['topic'] for t in actual['topicWeights']] == ['Trees']
    for key in ('totalQuestions', 'questionTypes', 'targetMarks', 'difficultyDistribution', 'patterns'):
        assert actual[key] == baseline[key]
    for key, value in baseline['evidence'].items():
        if key != 'topicEvidencePaperCount':
            assert actual['evidence'][key] == value


def test_blueprint_never_admits_new_contract_unverified_or_unreferenced_topic():
    from src.utils.exam_blueprint import build_exam_blueprint
    from tests.test_exam_blueprint import paper, source
    p = paper('one')
    p['topicWeights'] = [{'topic': 'Unverified', 'weight': 100, 'inScope': True, 'scopeStatus': 'unverified'},
                        {'topic': 'Unreferenced', 'weight': 100, 'scopeStatus': 'matched', 'sourceRefs': []}]
    result = build_exam_blueprint([source('past', [p])])
    assert result['topicWeights'] == []
    assert result['totalQuestions'] == 20


def intelligence(db, **kwargs):
    from src.database.firebase_client import FirebaseClient
    db._select_sources = FirebaseClient._select_sources
    for name in ('get_course_audio_recordings', 'get_course_historical_exams', 'get_course_tutorials'):
        getattr(db, name).return_value = []
    return FirebaseClient.get_course_intelligence(db, 'course', **kwargs)


def test_intelligence_includes_ready_originals_without_old_rich_analysis():
    rows = [lecture_document('a', analysis=None, extractedText='stale legacy text'), lecture_document('b', 'Trees')]
    db = fixture_database(rows)
    result = intelligence(db, user_id='owner', document_ids=['b', 'a', 'b'])
    assert result['source_ids']['document_ids'] == ['b', 'a']
    assert result['counts']['documents'] == 2
    assert [d['id'] for d in result['source_scope']['documents']] == ['b', 'a']
    assert result['source_manifests'] == result['source_scope']['manifests']
    assert result['document_guides'][1]['guide'] == rows[0]['guide']
    assert result['document_analyses'][1]['topics'] == ['Limits']
    assert 'stale legacy text' not in result['document_texts']
    assert any('Lecture material about Limits.' in text for text in result['document_texts'])
    assert 'sourceVersions' not in result['source_scope']['documents'][0]


def test_intelligence_rejects_explicit_invalid_sources_and_excludes_unready_defaults():
    rows = [lecture_document('a', preparationStatus='pending'), lecture_document('b')]
    db = fixture_database(rows)
    assert intelligence(db, user_id='owner')['source_ids']['document_ids'] == ['b']
    with pytest.raises(ValueError): intelligence(db, user_id='owner', document_ids=['b', 'a'])
    assert intelligence(db, user_id='owner', document_ids=[])['source_scope']['allowedRefs'] == []


def test_intelligence_legacy_internal_caller_has_no_authorized_source_scope():
    db = fixture_database([{'id': 'legacy', 'status': 'completed', 'analysis': {'topics': ['Old']}}])
    result = intelligence(db)
    assert result['source_ids']['document_ids'] == ['legacy']
    assert result['source_scope'] is None and result['source_manifests'] == []


def test_intelligence_http_projects_metadata_without_internal_source_bodies(api_module, monkeypatch):
    row = lecture_document(analysis=None)
    db = fixture_database([row])
    db.get_owned_course.return_value = {'id': 'course', 'userId': 'owner'}
    db._flat_get.return_value = db.get_owned_course.return_value
    internal = intelligence(db, user_id='owner')
    internal['_futurePrivateArtifact'] = 'never public'
    internal['document_guides'][0]['privatePath'] = 'never public'
    db.get_course_intelligence.return_value = internal
    monkeypatch.setattr(api_module, 'db_client', db)
    result = api_module.get_course_intelligence_endpoint('course', uid='owner')
    assert 'source_scope' not in result and 'source_manifests' not in result
    assert result['source_ids']['document_ids'] == ['doc']
    assert result['document_guides'][0] == {'documentId': 'doc', 'sourceRevision': row['sourceRevision'],
                                           'guideRevision': row['guideRevision'], 'unitCount': 1}
    assert 'never public' not in str(result)
    assert 'Lecture material about Limits.' not in str(result)
    assert 'sourceVersions' not in str(result)
