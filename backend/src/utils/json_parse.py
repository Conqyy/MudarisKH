"""Robust JSON extraction from AI responses.

Free/cheap LLMs frequently break the "respond with ONLY JSON" rule in subtle
ways — leading prose, trailing commas, code fences mid-output, or extra text
after the closing brace. A naive `json.loads(raw)` silently fails on any of
these, which previously caused documents/exams/audio to be marked "completed"
with an empty analysis. This module recovers the JSON whenever possible and
raises a clear error otherwise, so callers can fail loudly instead of
silently producing empty results.
"""

import json
import re
import logging
from typing import Callable, Any

logger = logging.getLogger("MudarisJSONParse")


def extract_json_object(raw: str) -> dict:
    """Best-effort extraction of a JSON object from an AI response.

    Strategies tried in order:
      1. Direct parse of the (trimmed) string.
      2. Strip code fences (```json ... ``` anywhere) and retry.
      3. Slice from the first `{` to the last `}` and retry.
      4. Repair trailing commas before `}`/`]` and retry.

    Raises ValueError if no parseable object can be recovered.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty AI response")

    s = raw.strip()

    # 1. Direct
    try:
        result = json.loads(s)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 2. Strip code fences anywhere
    stripped = re.sub(r"```(?:json|JSON|tex|latex)?\s*", "", s)
    stripped = stripped.replace("```", "").strip()
    if stripped != s:
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 3. Slice between first `{` and last `}`
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidate = stripped[start : end + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 4. Strip trailing commas, retry
        repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 5. Recover TRUNCATED JSON (output cut off by the token limit). Roll back to
    #    the last complete element and auto-close the open arrays/objects, so a
    #    partial-but-valid result (e.g. the first N problems) still succeeds.
    recovered = _recover_truncated_json(stripped)
    if isinstance(recovered, dict):
        logger.warning("Recovered a truncated JSON object (output was likely cut off).")
        return recovered

    raise ValueError(
        f"Could not extract a JSON object from the AI response. "
        f"First 300 chars: {raw[:300]!r}"
    )


def _recover_truncated_json(s: str):
    """Best-effort recovery of a JSON object whose output was cut off mid-stream.

    Walks the text tracking string state and the bracket stack, recording a
    checkpoint after every completed value (closing quote / `}` / `]`). On
    failure it rolls back to the latest checkpoint that parses cleanly after the
    open brackets are closed — dropping the half-written tail. Returns a dict or
    None.
    """
    start = s.find("{")
    if start == -1:
        return None
    candidate = s[start:]

    stack = []          # open closers, in the order they were opened
    in_str = False
    esc = False
    checkpoints = []    # (exclusive_index, tuple(stack)) after each complete value

    for i, ch in enumerate(candidate):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                checkpoints.append((i + 1, tuple(stack)))
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in "}]":
                if stack:
                    stack.pop()
                checkpoints.append((i + 1, tuple(stack)))

    # Try the most-complete checkpoints first.
    for idx, stk in reversed(checkpoints):
        prefix = re.sub(r"[\s,]*$", "", candidate[:idx])
        fixed = prefix + "".join(reversed(stk))
        try:
            obj = json.loads(fixed)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def parse_with_retry(
    call: Callable[[str], Any],
    *,
    required_keys: tuple = (),
    label: str = "analysis",
) -> dict:
    """Call an AI function that returns raw text, parse JSON, retry once on failure.

    Args:
        call: A function (reminder_suffix: str) -> raw_text. The reminder is
              appended to the system prompt on the retry attempt to nudge the
              model toward strict JSON.
        required_keys: Keys that must exist in the parsed object (defaults are
              set to empty values if missing — they won't trigger failure).
        label: A human-readable label for log messages ("document analysis", etc.).

    Returns:
        The parsed dict.

    Raises:
        RuntimeError if neither attempt produces a parseable object.
    """
    # Attempt 1
    raw = call("")
    try:
        result = extract_json_object(raw)
    except ValueError as e:
        logger.warning(
            f"{label}: first attempt unparseable ({e}); retrying with stricter prompt."
        )
        # Attempt 2 — append a strict reminder
        reminder = (
            "\n\nCRITICAL: Your previous reply was not valid JSON. "
            "Reply with ONLY the JSON object — no prose, no fences, no explanations. "
            "Begin your reply with `{` and end with `}`. Nothing else."
        )
        raw = call(reminder)
        try:
            result = extract_json_object(raw)
        except ValueError as e2:
            logger.error(f"{label}: both attempts unparseable: {e2}")
            raise RuntimeError(
                f"The AI didn't produce a valid {label}. This is usually a "
                "transient issue — please try again."
            ) from e2

    # Ensure required keys exist with empty defaults
    for key in required_keys:
        result.setdefault(key, [] if key != "keyConceptCount" and key != "totalQuestions" else 0)

    return result
