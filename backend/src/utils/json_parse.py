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


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def _loads(value):
    return json.loads(value, object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))


def _repair_trailing_commas(value):
    output, in_string, escaped = [], False, False
    for index, char in enumerate(value):
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        if char == ',' and value[index + 1:].lstrip().startswith(('}', ']')):
            continue
        output.append(char)
    return ''.join(output)


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
        result = _loads(s)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strip only surrounding fences. Backticks inside JSON text are content.
    stripped = re.sub(r"^```(?:json|JSON)?\s*\n?", "", s)
    stripped = re.sub(r"\n?```\s*$", "", stripped).strip()
    if stripped != s:
        try:
            result = _loads(stripped)
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
            result = _loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 4. Strip trailing commas, retry
        repaired = _repair_trailing_commas(candidate)
        try:
            result = _loads(repaired)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Never close missing brackets or discard unfinished elements: a valid
    # prefix is not a complete analysis and must be retried.
    raise ValueError("The AI response is incomplete or is not a valid JSON object")


def parse_with_retry(
    call: Callable[[str], Any],
    *,
    required_keys: tuple = (),
    label: str = "analysis",
    validator: Callable[[dict], dict] = None,
) -> dict:
    """Call an AI function that returns raw text, parse JSON, retry once on failure.

    Args:
        call: A function (reminder_suffix: str) -> raw_text. The reminder is
              appended to the system prompt on the retry attempt to nudge the
              model toward strict JSON.
        required_keys: Required fields; missing or incorrectly typed fields retry and then fail.
        label: A human-readable label for log messages ("document analysis", etc.).

    Returns:
        The parsed dict.

    Raises:
        RuntimeError if neither attempt produces a parseable object.
    """
    reminder = ''
    for attempt in range(2):
        try:
            raw = call(reminder)
            result = extract_json_object(raw)
            for key in required_keys:
                if key not in result:
                    raise ValueError('Required AI output field missing')
                if key in ('keyConceptCount', 'totalQuestions', 'problemCount'):
                    if type(result[key]) is not int or result[key] < 0:
                        raise ValueError('AI count must be a nonnegative integer')
                elif key in ('summary', 'gradingBlueprint'):
                    if not isinstance(result[key], str):
                        raise ValueError('AI output field must be text')
                elif not isinstance(result[key], list):
                    raise ValueError('AI output field must be an array')
            return validator(result) if validator else result
        except (ValueError, TypeError, KeyError) as error:
            logger.warning('%s: invalid or incomplete structured output (attempt %d/2)', label, attempt + 1)
            if attempt == 1:
                raise RuntimeError(f'The AI did not produce a complete, valid {label}. Please retry.') from error
            reminder = ('\n\nCRITICAL: Return one COMPLETE JSON object matching ALL required schema fields '
                        'and their types/counts. Do not omit items, truncate, add prose, or use fences.')
