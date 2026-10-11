"""Bounded document execution; durable records are the only recovery queue."""
from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time

logger = logging.getLogger('MudarisDocuments')


class DocumentJobRunner:
    def __init__(self, database, run_job, max_workers: int = 2, max_pending: int = 8):
        if max_workers < 1 or max_pending < 1:
            raise ValueError('Worker and pending bounds must be positive')
        self.database, self.run_job, self.capacity = database, run_job, max_pending
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='mudaris-document')
        self._active, self._lock, self._closed = set(), threading.Lock(), False

    def submit(self, doc_id) -> bool:
        with self._lock:
            if self._closed or doc_id in self._active or len(self._active) >= self.capacity:
                return False
            self._active.add(doc_id)
        try:
            self.executor.submit(self._run, doc_id)
        except Exception:
            with self._lock:
                self._active.discard(doc_id)
            raise
        return True

    def _run(self, doc_id):
        try:
            self.run_job(doc_id)
        except Exception:
            logger.exception('Document worker failed')
        finally:
            with self._lock:
                self._active.discard(doc_id)
            self.recover()

    def recover(self) -> None:
        if self._closed:
            return
        try:
            db = self.database() if callable(self.database) else self.database
            for row in db.get_pending_document_jobs(limit=1000, now_ms=int(time.time() * 1000)):
                self.submit(row['id'])
        except Exception:
            logger.exception('Document queue discovery failed; persisted work remains recoverable')

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.executor.shutdown(wait=True, cancel_futures=False)
