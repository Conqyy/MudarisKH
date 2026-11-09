"""Bounded evidence reuse inside one live supporting-analysis claim.

Only immutable, already validated reads are cached. Authorization is checked
again on every use, including cache hits; the cache never survives the job.
"""
from collections import OrderedDict
from copy import deepcopy
import json


class JobEvidenceCache:
    _READS = frozenset(('load_source', 'read_refs', 'render_reference', 'load_units'))

    def __init__(self, library, guard, *, max_bytes=32 * 1024 * 1024):
        self._library, self._guard = library, guard
        self._max_bytes, self._bytes = max_bytes, 0
        self._cache = OrderedDict()

    @staticmethod
    def _key(name, args, kwargs):
        return json.dumps([name, args, kwargs], sort_keys=True, separators=(',', ':'))

    def _remember(self, key, value):
        size = len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
        if size <= self._max_bytes:
            while self._cache and self._bytes + size > self._max_bytes:
                _, (_, removed_size) = self._cache.popitem(last=False)
                self._bytes -= removed_size
            self._cache[key] = (deepcopy(value), size)
            self._bytes += size

    def _read_units(self, method, identity, refs):
        # Alignment packs overlapping target groups. Cache units individually so
        # a different list/order of exact proofs does not reread the same page.
        keys = [self._key('supporting_unit', [identity, ref], {}) for ref in refs]
        resolved, missing = {}, {}
        for key, ref in zip(keys, refs):
            if key in self._cache:
                value = self._cache.pop(key)
                self._cache[key] = value
                resolved[key] = value[0]
            else:
                missing[key] = ref
        if missing:
            values = method(identity, list(missing.values()))
            if not isinstance(values, list) or len(values) != len(missing):
                raise ValueError('Original supporting unit read is incomplete')
            for key, value in zip(missing, values):
                resolved[key] = value
                self._remember(key, value)
        return [deepcopy(resolved[key]) for key in keys]

    def __getattr__(self, name):
        method = getattr(self._library, name)
        if name not in self._READS:
            return method

        def read(*args, **kwargs):
            self._guard()
            if name == 'read_refs' and len(args) == 2 and isinstance(args[1], list) and not kwargs:
                return self._read_units(method, *args)
            key = self._key(name, args, kwargs)
            if key in self._cache:
                value, size = self._cache.pop(key)
                self._cache[key] = (value, size)
                return deepcopy(value)
            value = method(*args, **kwargs)
            self._remember(key, value)
            return value

        return read
