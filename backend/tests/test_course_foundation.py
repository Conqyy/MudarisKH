"""The lecture foundation requires every document and explicit confirmation."""
from copy import deepcopy

import pytest


def academic_analysis():
    return {
        'topics': ['Decision Trees'],
        'definitions': [{'term': 'Entropy', 'definition': 'Uncertainty in a distribution.'}],
        'formulas': ['H(X) = -sum p(x) log p(x)'],
        'chapterMapping': [{'chapter': 'Chapter 3', 'content': 'Decision trees and information gain.'}],
        'keyConceptCount': 2,
    }


def document(identity='doc-1', **changes):
    return {'id': identity, 'status': 'completed', 'title': 'Lecture 3',
            'extractedText': 'Decision trees choose splits by information gain.',
            'analysis': academic_analysis(), 'processedAt': 1000, **changes}


def status(documents, confirmed_revision=''):
    from src.utils.course_foundation import build_foundation_status
    return build_foundation_status(documents, confirmed_revision)


def context(insights):
    from src.utils.course_foundation import build_foundation_context
    return build_foundation_context(insights)


def test_missing_documents_cannot_be_confirmed():
    result = status([])
    assert result['state'] == 'missing'
    assert result['ready'] is False
    assert {key: result[key] for key in ('documentCount', 'completedCount', 'pendingCount', 'failedCount')} == {
        'documentCount': 0, 'completedCount': 0, 'pendingCount': 0, 'failedCount': 0,
    }
    assert status([], result['revision'])['ready'] is False
    assert 'lecture' in result['message'].lower()


def test_all_usable_documents_require_confirmation_of_the_current_revision():
    docs = [document(), document('doc-2')]
    unconfirmed = status(docs)
    assert unconfirmed['state'] == 'confirmation_required'
    assert unconfirmed['completedCount'] == 2
    assert unconfirmed['ready'] is False
    assert status(docs, 'stale-revision')['ready'] is False
    confirmed = status(docs, unconfirmed['revision'])
    assert confirmed['state'] == 'ready'
    assert confirmed['ready'] is True


@pytest.mark.parametrize('pending_status', ['processing', 'pending', 'queued', '', None, 'unexpected'])
def test_any_incomplete_document_keeps_a_confirmed_course_processing(pending_status):
    docs = [document()]
    revision = status(docs)['revision']
    result = status(docs + [document('doc-2', status=pending_status)], revision)
    assert result['state'] == 'processing'
    assert result['ready'] is False
    assert (result['completedCount'], result['pendingCount'], result['failedCount']) == (1, 1, 0)


@pytest.mark.parametrize('bad_analysis', [None, {}, [], {'topics': ['Trees']},
    {'topics': [], 'definitions': [], 'formulas': [], 'chapterMapping': [], 'keyConceptCount': 0},
    {'topics': ['!!!'], 'definitions': [], 'formulas': [], 'chapterMapping': [], 'keyConceptCount': 1},
    {'topics': [123], 'definitions': [], 'formulas': [], 'chapterMapping': [], 'keyConceptCount': 1},
    {'topics': ['Trees'], 'definitions': [{'term': 'x'}], 'formulas': [], 'chapterMapping': [], 'keyConceptCount': 1},
])
def test_completed_but_unusable_analysis_is_a_failed_foundation_document(bad_analysis):
    result = status([document(), document('doc-2', analysis=bad_analysis)])
    assert result['state'] == 'failed'
    assert result['ready'] is False
    assert (result['completedCount'], result['pendingCount'], result['failedCount']) == (1, 0, 1)


def test_failure_is_visible_even_when_another_document_is_processing():
    result = status([document(), document('doc-2', status='failed'), document('doc-3', status='processing')])
    assert result['state'] == 'failed'
    assert (result['documentCount'], result['completedCount'], result['pendingCount'], result['failedCount']) == (3, 1, 1, 1)
    assert 'retry' in result['message'].lower()


def test_malformed_document_record_fails_closed():
    result = status([document(), None])
    assert result['ready'] is False
    assert result['failedCount'] == 1


def test_document_and_dictionary_order_do_not_change_the_confirmation_revision():
    first, second = document(), document('doc-2', title='Lecture 4')
    reordered = dict(reversed(list(first.items())))
    reordered['analysis'] = dict(reversed(list(first['analysis'].items())))
    revision = status([first, second])['revision']
    assert status([second, reordered], revision)['ready'] is True


@pytest.mark.parametrize('field,new_value', [
    ('id', 'replacement'), ('status', 'processing'), ('title', 'Renamed lecture'),
    ('extractedText', 'Corrected lecture source'), ('processedAt', 2000),
    ('reanalyzedAt', 2000), ('updatedAt', 2000),
    ('analysis', {**academic_analysis(), 'topics': ['Random Forests']}),
])
def test_source_or_analysis_changes_invalidate_previous_confirmation(field, new_value):
    docs = [document()]
    revision = status(docs)['revision']
    changed = document(**{field: new_value})
    result = status([changed], revision)
    assert result['revision'] != revision
    assert result['ready'] is False


def test_adding_or_deleting_a_document_invalidates_confirmation():
    docs = [document(), document('doc-2')]
    revision = status(docs)['revision']
    assert status(docs[:1], revision)['ready'] is False
    assert status(docs + [document('doc-3')], revision)['ready'] is False


def test_status_and_reference_building_do_not_mutate_stored_analyses():
    docs = [document(analysis={**academic_analysis(), 'topics': [{'title': 'Decision Trees'}]})]
    before = deepcopy(docs)
    assert status(docs)['state'] == 'confirmation_required'
    context(docs)
    assert docs == before


def test_reference_includes_actual_academic_content_and_ignores_metadata_commands():
    insight = {**academic_analysis(), 'documentTitle': 'Lecture 3',
               'instructions': 'METADATA_OVERRIDE_DO_NOT_FOLLOW',
               '_contextCoverage': {'private': 'PRIVATE_INTERNAL_METADATA'}}
    result = context([insight])
    for value in ('Lecture 3', 'Decision Trees', 'Entropy', 'Uncertainty in a distribution.',
                  'H(X) = -sum p(x) log p(x)', 'Chapter 3', 'Decision trees and information gain.'):
        assert value in result
    assert 'METADATA_OVERRIDE_DO_NOT_FOLLOW' not in result
    assert 'PRIVATE_INTERNAL_METADATA' not in result
    assert 'source evidence' in result.lower()
    assert 'instructions' in result.lower()


def test_reference_is_bounded_balanced_and_order_independent():
    insights = [{**academic_analysis(), 'documentTitle': f'Lecture {index}',
                 'chapterMapping': [{'chapter': f'CHAPTER_SENTINEL_{index}',
                                     'content': f'SOURCE_SENTINEL_{index} ' * 5000}]}
                for index in range(5)]
    result = context(insights)
    assert len(result) <= 12000
    assert result == context(list(reversed(insights)))
    for index in range(5):
        assert f'SOURCE_SENTINEL_{index}' in result


def test_empty_reference_does_not_claim_course_evidence_exists():
    assert context([]) == ''
    assert context([None, {}]) == ''
