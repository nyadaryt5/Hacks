"""Tests for ultron.llm — budget gates, key rotation, retries, error paths."""

import httpx
import pytest

from ultron.budget import BudgetGovernor
from ultron.config import ConfigurationError, ULTRONSettings
from ultron.llm import GoogleAIClient


def _settings(keys=("k1", "k2"), **overrides):
    return ULTRONSettings(
        google_ai={
            "api_keys": list(keys),
            "max_rpm_per_key": 100,
            "max_rpd_per_key": 10000,
            **overrides,
        },
        budget={"max_tokens_per_session": 100000},
    )


def _ok_json(handler):
    """httpx MockTransport that returns a successful chat completion."""

    def _handler(request):
        handler(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"verdict": "proceed"}'}}
                ]
            },
        )

    return httpx.MockTransport(_handler)


def _client(transport, settings=None, **kwargs):
    settings = settings or _settings()
    return GoogleAIClient(
        settings, BudgetGovernor(settings), transport=transport, **kwargs
    )


def test_chat_returns_content_and_records_usage():
    seen = []

    def handler(request):
        seen.append(request)

    client = _client(_ok_json(handler))
    try:
        result = client.chat("system", "hello world")
    finally:
        client.close()
    assert result == '{"verdict": "proceed"}'
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer k1"
    assert client.budget.tokens_used_session > 0


def test_keys_rotate_across_calls():
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])

    client = _client(_ok_json(handler))
    try:
        client.chat("s", "one")
        client.chat("s", "two")
    finally:
        client.close()
    assert seen == ["Bearer k1", "Bearer k2"]


def test_budget_gate_blocks_call_without_http():
    settings = _settings()
    settings.budget.max_tokens_per_session = 10
    client = GoogleAIClient(
        settings,
        BudgetGovernor(settings),
        transport=httpx.MockTransport(
            lambda request: pytest.fail("no HTTP call expected")
        ),
    )
    try:
        result = client.chat("s", "u", max_tokens=100)
    finally:
        client.close()
    assert result.startswith("[BUDGET] Session budget exceeded")


def test_missing_keys_raise_configuration_error():
    settings = _settings(keys=[])
    with pytest.raises(ConfigurationError, match="No API keys"):
        GoogleAIClient(settings, BudgetGovernor(settings)).chat("s", "u")


def test_malformed_response_returns_error_string():
    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client(httpx.MockTransport(handler))
    try:
        result = client.chat("s", "u")
    finally:
        client.close()
    assert result.startswith("[ERROR] Malformed API response")


def test_rate_limit_rotates_key_and_retries():
    calls = []

    def handler(request):
        calls.append(request.headers["authorization"])
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "quota"})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = _client(httpx.MockTransport(handler))
    try:
        result = client.chat("s", "u")
    finally:
        client.close()
    assert result == "ok"
    assert calls == ["Bearer k1", "Bearer k2"]


def test_server_error_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "recovered"}}]}
        )

    client = _client(httpx.MockTransport(handler))
    try:
        result = client.chat("s", "u")
    finally:
        client.close()
    assert result == "recovered"
    assert len(calls) == 2


def test_network_error_returns_error_string():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = _client(httpx.MockTransport(handler), retry_backoff=0.0)
    try:
        result = client.chat("s", "u")
    finally:
        client.close()
    assert result.startswith("[ERROR] API failed")


def test_context_prefix_describes_authorized_testing():
    import ultron.llm as llm_module

    assert "AUTHORIZED" in llm_module.GEMINI_CONTEXT_PREFIX
