"""Helper to call OpenRouter chat completions with retry/backoff.

Free models on OpenRouter are shared and frequently return transient
429 (rate-limited) or 5xx errors. This wraps the call so those are retried
with exponential backoff instead of failing the whole request.
"""

import time
import logging
import random

logger = logging.getLogger("MudarisAIRetry")

def _retryable(error):
    status = getattr(error, 'status_code', None)
    if status is not None:
        return status in (408, 409, 429) or 500 <= status < 600
    return isinstance(error, (TimeoutError, ConnectionError)) or type(error).__name__ in ('APITimeoutError', 'APIConnectionError')


def chat_with_retry(client, *, max_retries: int = 3, base_delay: float = 1.0, **kwargs):
    """Call client.chat.completions.create(**kwargs), retrying transient errors."""
    return call_with_retry(client.chat.completions.create, max_retries=max_retries, base_delay=base_delay, **kwargs)


def call_with_retry(call, *, max_retries: int = 3, base_delay: float = 1.0, **kwargs):
    kwargs.setdefault('timeout', 90.0)
    attempts = max(1, min(int(max_retries), 4))
    last_err = None
    for attempt in range(attempts):
        try:
            uploaded = kwargs.get('file')
            if uploaded is not None and hasattr(uploaded, 'seek'):
                uploaded.seek(0)
            return call(**kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if not _retryable(e) or attempt == attempts - 1:
                raise
            delay = min(10.0, base_delay * (2 ** attempt)) + random.uniform(0, 0.5)
            logger.warning('Provider transient failure type=%s status=%s attempt=%d/%d delay=%.1fs',
                           type(e).__name__, getattr(e, 'status_code', None), attempt + 1, attempts, delay)
            time.sleep(delay)
    raise last_err
