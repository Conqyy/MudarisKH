"""Bounded audio execution; persisted recording state is the recovery queue."""
from concurrent.futures import ThreadPoolExecutor
import logging
import threading

logger = logging.getLogger("MudarisJobs")


class AudioJobRunner:
    def __init__(self, database, run_job, max_workers=2, max_pending=8, executor=None):
        self.database = database
        self.run_job = run_job
        self.capacity = max_pending
        self.executor = executor or ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mudaris-audio")
        self._active = set()
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, rec_id):
        with self._lock:
            if self._closed or rec_id in self._active or len(self._active) >= self.capacity:
                return False
            self._active.add(rec_id)
        try:
            self.executor.submit(self._run, rec_id)
            return True
        except Exception:
            with self._lock:
                self._active.discard(rec_id)
            raise

    def _run(self, rec_id):
        try:
            self.run_job(rec_id)
        except Exception:
            logger.exception("Audio worker failed")
        finally:
            with self._lock:
                self._active.discard(rec_id)
            self.recover()

    def recover(self):
        if self._closed:
            return
        try:
            for record in self.database().get_pending_audio_jobs(limit=1000):
                self.submit(record["id"])
        except Exception:
            logger.exception("Audio queue recovery failed; persisted jobs remain available for retry")

    def close(self):
        with self._lock:
            self._closed = True
        self.executor.shutdown(wait=True, cancel_futures=False)
