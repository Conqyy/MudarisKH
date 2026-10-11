"""Confirmation remains private, owned, atomic, and covered by lifecycle fences."""
from copy import deepcopy

import pytest

from tests.test_atomic_data import cloud_database, database


def foundation_rows(client):
    if client.use_local:
        return client._read_local_db().get('document_foundations', {})
    return {key.split('/')[-1]: value for key, value in client.db.rows.items()
            if key.startswith('document_foundations/')}


def seed_foundation(client, identity, row):
    if client.use_local:
        data = client._read_local_db()
        data.setdefault('document_foundations', {})[identity] = row
        client._write_local_db(data)
    else:
        client.db.rows[f'document_foundations/{identity}'] = row


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
def test_confirmation_writes_only_private_metadata_and_preserves_browser_course_schema(request, backend):
    client = request.getfixturevalue(backend)
    before = deepcopy(client.get_owned_course('u', 'c'))
    assert client.get_document_foundation('u', 'c') == {}
    assert client.confirm_document_foundation('u', 'c', 'a' * 64) is True
    assert foundation_rows(client) == {'c': {'userId': 'u', 'courseId': 'c', 'revision': 'a' * 64}}
    assert client.get_owned_course('u', 'c') == before
    assert client.get_document_foundation('u', 'c')['revision'] == 'a' * 64
    assert client.confirm_document_foundation('u', 'c', 'b' * 64) is True
    assert client.get_document_foundation('u', 'c')['revision'] == 'b' * 64
    assert client.get_owned_course('u', 'c') == before


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
@pytest.mark.parametrize('revision', [None, '', '   ', 'x' * 129, ['revision']])
def test_confirmation_rejects_empty_or_oversized_revision_before_writes(request, backend, revision):
    client = request.getfixturevalue(backend)
    with pytest.raises(ValueError):
        client.confirm_document_foundation('u', 'c', revision)
    assert foundation_rows(client) == {}


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
def test_confirmation_rejects_foreign_or_missing_course_without_overwriting_owner(request, backend):
    client = request.getfixturevalue(backend)
    client.confirm_document_foundation('u', 'c', 'original')
    for owner, course in [('v', 'c'), ('u', 'missing')]:
        with pytest.raises(ValueError):
            client.confirm_document_foundation(owner, course, 'forged')
        assert client.get_document_foundation(owner, course) == {}
    assert client.get_document_foundation('u', 'c')['revision'] == 'original'


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
@pytest.mark.parametrize('changes', [{'userId': 'v'}, {'courseId': 'foreign'}])
def test_private_confirmation_records_are_filtered_by_owner_and_course(request, backend, changes):
    client = request.getfixturevalue(backend)
    row = {'userId': 'u', 'courseId': 'c', 'revision': 'old', **changes}
    seed_foundation(client, 'c', row)
    assert client.get_document_foundation('u', 'c') == {}
    with pytest.raises(ValueError):
        client.confirm_document_foundation('u', 'c', 'new')
    assert foundation_rows(client)['c'] == row


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
@pytest.mark.parametrize('marker', ['account', 'course'])
def test_deletion_marker_prevents_new_and_existing_confirmation_writes(request, backend, marker):
    client = request.getfixturevalue(backend)
    client.confirm_document_foundation('u', 'c', 'original')
    if marker == 'account':
        client.begin_account_deletion('u')
    else:
        client._begin_course_deletion('u', 'c')
    with pytest.raises(ValueError):
        client.confirm_document_foundation('u', 'c', 'late')
    assert foundation_rows(client)['c']['revision'] == 'original'
    assert client.get_document_foundation('u', 'c') == {}


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
@pytest.mark.parametrize('cleanup', ['course', 'account'])
def test_cleanup_removes_private_confirmation_and_retains_other_owner(request, backend, cleanup, monkeypatch):
    client = request.getfixturevalue(backend)
    client.confirm_document_foundation('u', 'c', 'original')
    foreign = {'userId': 'v', 'courseId': 'v', 'revision': 'foreign'}
    seed_foundation(client, 'v', foreign)
    monkeypatch.setattr(client, '_cleanup_storage_namespace', lambda *args, **kwargs: 0)
    if cleanup == 'course':
        counts = client.delete_course_data('u', 'c')
    else:
        client.begin_account_deletion('u')
        counts = client.delete_user_data('u')
    assert counts['document_foundations'] == 1
    assert foundation_rows(client) == {'v': foreign}
    with pytest.raises(ValueError):
        client.confirm_document_foundation('u', 'c', 'late')


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
def test_tutor_append_saves_revision_with_the_same_atomic_turn_and_preserves_it_on_conflict(request, backend):
    client = request.getfixturevalue(backend)
    turn = [{'role': 'user', 'content': 'Explain trees'}, {'role': 'assistant', 'content': 'Trees split inputs.'}]
    result = client.append_tutor_messages('u', 'c', 'chat', [], turn, 10, foundation_revision='a' * 64)
    assert result['messages'] == turn
    assert result['foundationRevision'] == 'a' * 64
    assert client.get_tutor_chat('chat')['foundationRevision'] == 'a' * 64
    with pytest.raises(ValueError):
        client.append_tutor_messages('u', 'c', 'chat', [], turn, 20, foundation_revision='b' * 64)
    assert client.get_tutor_chat('chat')['messages'] == turn
    assert client.get_tutor_chat('chat')['foundationRevision'] == 'a' * 64


@pytest.mark.parametrize('backend', ['database', 'cloud_database'])
def test_tutor_append_without_revision_keeps_the_original_optional_contract(request, backend):
    client = request.getfixturevalue(backend)
    turn = [{'role': 'user', 'content': 'Explain trees'}, {'role': 'assistant', 'content': 'Trees split inputs.'}]
    result = client.append_tutor_messages('u', 'c', 'chat', [], turn, 10)
    assert result['messages'] == turn
    assert 'foundationRevision' not in result
