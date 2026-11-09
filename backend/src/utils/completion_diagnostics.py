"""Content-free completion metadata for persisted analysis diagnostics."""
from collections.abc import Mapping


_FINISH_REASONS = frozenset({
    'stop', 'length', 'tool_calls', 'function_call', 'content_filter', 'error',
})


def _field(value, key):
    return value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)


def _counter(value):
    # bool is an int subclass; provider metadata must contain actual counters.
    return value if type(value) is int and value >= 0 else None


def completion_diagnostics(response) -> dict:
    """Return only fixed status values and token counts, never provider content.

    Supports OpenAI SDK objects and equivalent decoded mappings. Missing usage
    stays unknown, and only an explicit length finish reason proves truncation.
    """
    choices = _field(response, 'choices')
    choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
    reason = _field(choice, 'finish_reason')
    if reason is not None and (not isinstance(reason, str) or reason not in _FINISH_REASONS):
        reason = 'unknown'
    content = _field(_field(choice, 'message'), 'content')
    usage = _field(response, 'usage')
    return {
        'responsePresent': response is not None,
        'contentPresent': isinstance(content, str) and bool(content.strip()),
        'finishReason': reason,
        'truncated': reason == 'length',
        'inputTokens': _counter(_field(usage, 'prompt_tokens')),
        'outputTokens': _counter(_field(usage, 'completion_tokens')),
        'reasoningTokens': _counter(_field(_field(usage, 'completion_tokens_details'), 'reasoning_tokens')),
    }
