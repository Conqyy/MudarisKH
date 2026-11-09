"""Completion metadata is useful for retries without retaining provider content."""
import json
from types import SimpleNamespace

import pytest

from src.utils.completion_diagnostics import completion_diagnostics


def completion(*, reason='stop', content='result', usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=reason, message=SimpleNamespace(content=content))],
        usage=usage,
    )


def test_sdk_metadata_excludes_content_reasoning_and_provider_private_fields():
    response = completion(content='PRIVATE SOURCE TEXT', usage=SimpleNamespace(
        prompt_tokens=120, completion_tokens=80,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=35, private='PRIVATE DETAILS'),
        total_tokens=200, api_key='PRIVATE KEY',
    ))
    response.choices[0].message.reasoning = 'PRIVATE REASONING'
    response.provider_metadata = {'token': 'PRIVATE TOKEN'}

    result = completion_diagnostics(response)

    assert result == {
        'responsePresent': True, 'contentPresent': True, 'finishReason': 'stop',
        'truncated': False, 'inputTokens': 120, 'outputTokens': 80, 'reasoningTokens': 35,
    }
    assert 'PRIVATE' not in json.dumps(result)


def test_mapping_responses_support_nested_reasoning_usage():
    result = completion_diagnostics({
        'choices': [{'finish_reason': 'length', 'message': {'content': '{unfinished'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 16000,
                  'completion_tokens_details': {'reasoning_tokens': 15500}},
    })
    assert result['truncated'] is True
    assert result['finishReason'] == 'length'
    assert result['contentPresent'] is True
    assert (result['inputTokens'], result['outputTokens'], result['reasoningTokens']) == (10, 16000, 15500)


def test_absent_response_is_distinct_from_a_truncated_response():
    assert completion_diagnostics(None) == {
        'responsePresent': False, 'contentPresent': False, 'finishReason': None,
        'truncated': False, 'inputTokens': None, 'outputTokens': None, 'reasoningTokens': None,
    }


@pytest.mark.parametrize('choices', [None, [], [None]])
def test_missing_choice_metadata_does_not_imply_truncation(choices):
    result = completion_diagnostics(SimpleNamespace(choices=choices))
    assert result['responsePresent'] is True
    assert result['contentPresent'] is False
    assert result['finishReason'] is None
    assert result['truncated'] is False


@pytest.mark.parametrize('content', [None, '', ' \n\t ', [{'text': 'unsupported content shape'}]])
def test_missing_or_invalid_text_is_reported_without_inventing_a_token_limit(content):
    result = completion_diagnostics(completion(content=content))
    assert result['contentPresent'] is False
    assert result['finishReason'] == 'stop'
    assert result['truncated'] is False


def test_length_is_recorded_even_when_the_provider_returns_no_visible_text():
    result = completion_diagnostics(completion(reason='length', content=None))
    assert result['truncated'] is True
    assert result['contentPresent'] is False
    assert result['reasoningTokens'] is None


@pytest.mark.parametrize('reason', ['stop', 'length', 'tool_calls', 'function_call', 'content_filter', 'error'])
def test_known_finish_reasons_are_retained(reason):
    result = completion_diagnostics(completion(reason=reason))
    assert result['finishReason'] == reason
    assert result['truncated'] is (reason == 'length')


@pytest.mark.parametrize('reason', ['PRIVATE PROVIDER ERROR', 123, {'token': 'PRIVATE TOKEN'}])
def test_arbitrary_provider_values_cannot_leak_through_finish_reason(reason):
    result = completion_diagnostics(completion(reason=reason))
    assert result['finishReason'] == 'unknown'
    assert result['truncated'] is False
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('invalid', [-1, 1.5, True, '123', {'token': 'PRIVATE TOKEN'}])
def test_usage_counters_only_accept_nonnegative_integers(invalid):
    result = completion_diagnostics(completion(usage=SimpleNamespace(
        prompt_tokens=invalid, completion_tokens=invalid,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=invalid),
    )))
    assert (result['inputTokens'], result['outputTokens'], result['reasoningTokens']) == (None, None, None)


def test_zero_usage_is_preserved_and_missing_reasoning_usage_stays_unknown():
    result = completion_diagnostics(completion(usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0)))
    assert result['inputTokens'] == 0
    assert result['outputTokens'] == 0
    assert result['reasoningTokens'] is None
