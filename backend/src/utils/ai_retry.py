"""Helper to call OpenRouter chat completions with retry/backoff.

Free models on OpenRouter are shared and frequently return transient
429 (rate-limited) or 5xx errors. This wraps the call so those are retried
with exponential backoff instead of failing the whole request.
"""

import time
import logging

logger = logging.getLogger("MudarisAIRetry")

_RETRYABLE = ("429", "rate", "500", "502", "503", "504", "overloaded", "timeout")


def chat_with_retry(client, *, max_retries: int = 4, base_delay: float = 2.5, **kwargs):
    """Call client.chat.completions.create(**kwargs), retrying transient errors."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e).lower()
            is_retryable = any(tok in msg for tok in _RETRYABLE)
            if not is_retryable or attempt == max_retries - 1:
                raise
            delay = base_delay * (attempt + 1)
            logger.warning(
                f"AI call transient error (attempt {attempt + 1}/{max_retries}): "
                f"{str(e)[:120]} — retrying in {delay:.0f}s"
            )
            time.sleep(delay)
    raise last_err
