"""Bounded worker pool for durable supporting-analysis identities."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import logging
import threading
import time

from src.supporting.contracts import validate_identity


logger = logging.getLogger("MudarisSupportingJobs")


def _key(identity):
    value = validate_identity(identity)
    return tuple(value[name] for name in ("userId", "courseId", "kind", "materialId"))


class SupportingJobRunner:
    def __init__(self, repository, run_job, *, max_workers: int = 2,
                 max_pending: int = 8, executor=None):
        if not callable(run_job) or max_workers < 1 or max_pending < 1:
            raise ValueError("Invalid supporting worker configuration")
        self.repository = repository
        self.run_job = run_job
        self.capacity = max_pending
        self.executor = executor or ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="mudaris-supporting")
        self._active = set()
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, identity) -> bool:
        identity = validate_identity(identity)
        key = _key(identity)
        with self._lock:
            if self._closed or key in self._active or len(self._active) >= self.capacity:
                return False
            self._active.add(key)
        try:
            self.executor.submit(self._run, deepcopy(identity), key)
            return True
        except Exception:
            with self._lock:
                self._active.discard(key)
            raise

    def _run(self, identity, key):
        try:
            self.run_job(identity)
        except Exception:
            logger.exception("Supporting worker failed")
        finally:
            with self._lock:
                self._active.discard(key)
            self.recover()

    def recover(self) -> None:
        if self._closed:
            return
        try:
            for identity in self.repository.pending(now_ms=int(time.time() * 1000), limit=1000):
                self.submit(identity)
        except Exception:
            logger.exception("Supporting queue recovery failed; durable jobs remain queued")

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.executor.shutdown(wait=True, cancel_futures=False)

