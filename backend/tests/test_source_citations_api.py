"""Preview references cannot drift to replacement pages or disclose private artifacts."""
from fastapi.testclient import TestClient
import pytest
from tests.test_saved_exam_source_versions import (
    database, cloud_database, job_db, library, source_api, saved, replace,
)


def test_exact_old_page_preview_survives_replacement(saved):
    api, library, doc, _, exam = saved
    revision = exam['sourceScope']['documents'][0]['sourceRevision']
    client = TestClient(api.app)
    url = f'/api/documents/{doc}/sources/p0001'
    before = client.get(url, params={'source_revision': revision})
    replace(api, library, doc)
    after = client.get(url, params={'source_revision': revision})
    assert after.status_code == 200 and after.json() == before.json()
    assert after.json()['images'] and 'REPLACEMENT SENTINEL' not in after.text
    assert all(key not in after.text for key in ('originalPath', 'manifestPath', 'sourceVersions', 'storagePath'))
    assert client.get(url).status_code == 422


@pytest.mark.parametrize('damage', ['original', 'manifest', 'revision', 'unit'])
def test_owned_stale_preview_is_actionable_409(saved, damage):
    api, library, doc, _, exam = saved
    revision = exam['sourceScope']['documents'][0]['sourceRevision']
    if damage in ('original', 'manifest'):
        path = library.database.get_document(doc)['sourceVersions'][revision][damage + 'Path']
        library.database.delete_file_from_storage(path, 'u')
    if damage == 'revision': revision = 'f' * 64
    unit = 'p0099' if damage == 'unit' else 'p0001'
    response = TestClient(api.app).get(f'/api/documents/{doc}/sources/{unit}', params={'source_revision': revision})
    assert response.status_code == 409
    assert 'restore' in response.text.lower() and 'regenerate' in response.text.lower()


def test_foreign_preview_is_404(saved):
    api, _, doc, _, exam = saved
    api.app.dependency_overrides[api.require_uid] = lambda: 'foreign'
    response = TestClient(api.app).get(f'/api/documents/{doc}/sources/p0001',
        params={'source_revision': exam['sourceScope']['documents'][0]['sourceRevision']})
    assert response.status_code == 404
