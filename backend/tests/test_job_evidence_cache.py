from copy import deepcopy

import pytest

from src.supporting.evidence_cache import JobEvidenceCache


def test_repeated_exact_evidence_reuses_io_but_checks_live_authorization():
    events = []

    class Library:
        def read_refs(self, identity, refs):
            events.append('read')
            return [{'text': 'Original', 'ref': deepcopy(refs[0])}]

    live = [True]

    def guard():
        events.append('guard')
        if not live[0]:
            raise RuntimeError('Claim revoked')

    cache = JobEvidenceCache(Library(), guard)
    ref = {'sourceRevision': 'v1', 'unitId': 'p1'}
    first = cache.read_refs({'materialId': 'm'}, [ref])
    first[0]['text'] = 'Changed by consumer'
    assert cache.read_refs({'materialId': 'm'}, [ref])[0]['text'] == 'Original'
    assert events.count('read') == 1
    assert events.count('guard') == 2
    live[0] = False
    with pytest.raises(RuntimeError, match='revoked'):
        cache.read_refs({'materialId': 'm'}, [ref])


def test_revision_identity_and_job_isolation():
    calls = []

    class Library:
        def render_reference(self, identity, ref):
            calls.append((identity, ref))
            return ['data:image/png;base64,original']

    library = Library()
    cache = JobEvidenceCache(library, lambda: None)
    for identity, revision in [('m1', 'v1'), ('m1', 'v2'), ('m2', 'v1')]:
        cache.render_reference(identity, {'sourceRevision': revision})
    JobEvidenceCache(library, lambda: None).render_reference('m1', {'sourceRevision': 'v1'})
    assert len(calls) == 4


def test_overlapping_proof_groups_reuse_each_exact_unit_without_extra_reads():
    requests = []

    class Library:
        def read_refs(self, identity, refs):
            requests.append(deepcopy(refs))
            return [{'text': ref['unitId']} for ref in refs]

    guard_calls = []
    cache = JobEvidenceCache(Library(), lambda: guard_calls.append(True))
    page1, page2 = ({'sourceRevision': 'v1', 'unitId': name} for name in ('p1', 'p2'))
    assert cache.read_refs('owned', [page1, page1]) == [{'text': 'p1'}, {'text': 'p1'}]
    assert cache.read_refs('owned', [page2, page1]) == [{'text': 'p2'}, {'text': 'p1'}]
    assert requests == [[page1], [page2]]
    assert len(guard_calls) == 2


def test_memory_bound_evicts_evidence_and_does_not_cache_failures():
    calls = []

    class Library:
        def render_reference(self, ref):
            calls.append(ref)
            if ref == 'bad':
                raise ValueError('Invalid original')
            return ['data:image/png;base64,' + ref * 50]

    cache = JobEvidenceCache(Library(), lambda: None, max_bytes=160)
    cache.render_reference('a')
    cache.render_reference('b')
    cache.render_reference('c')
    cache.render_reference('a')
    assert calls.count('a') == 2
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.render_reference('bad')
    assert calls.count('bad') == 2
