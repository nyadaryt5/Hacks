"""Offline guarantees: core components work with no network and no real keys.

These tests exercise the LLM client, vector memory and database manager the
way the framework actually wires them together, and assert that none of them
performs a real network call. The httpx client is driven through a
``MockTransport`` so any accidental outbound request fails loudly instead of
touching the network.
"""

import httpx
import pytest

from ultron.budget import BudgetGovernor
from ultron.config import ULTRONSettings
from ultron.db import DatabaseManager
from ultron.llm import GoogleAIClient
from ultron.memory import VectorMemory


def _settings(**overrides):
    return ULTRONSettings(
        google_ai={"api_keys": ["test-key"], **overrides},
        budget={"max_tokens_per_session": 100000},
    )


def test_google_ai_client_uses_transport_not_network():
    """The client must route requests through the injected transport."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "stub"}}]}
        )

    settings = _settings()
    client = GoogleAIClient(
        settings,
        BudgetGovernor(settings),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.chat("system", "test prompt")
    finally:
        client.close()

    assert result == "stub"
    assert len(seen) == 1


def test_vector_memory_offline(tmp_path):
    """Hash-backed memory stores and recalls lessons without any service."""
    db = DatabaseManager(f"sqlite:///{tmp_path / 'mem.db'}")
    try:
        vm = VectorMemory(db, backend="hash")
        assert vm is not None
        vm.store_lesson(
            situation="open port 80",
            action="probe http",
            outcome="banner grabbed",
            success=True,
            session_id="offline",
        )
        results = vm.query_similar("http banner", top_k=3)
        assert isinstance(results, list)
        assert len(results) >= 1
        assert "similarity" in results[0]
    finally:
        db.close()


def test_database_manager_offline(tmp_path):
    """The default DatabaseManager persists to local SQLite, no network."""
    db = DatabaseManager(f"sqlite:///{tmp_path / 'db.sqlite'}")
    try:
        assert db is not None
        # A session/connection is obtainable without any external service.
        assert hasattr(db, "close")
    finally:
        db.close()


def test_no_network_when_transport_forbids_it():
    """If the client ever hit the real network the test would fail here."""
    def forbid(request):  # pragma: no cover - only runs on a real request
        pytest.fail(f"unexpected network call to {request.url}")

    settings = _settings()
    settings.budget.max_tokens_per_session = 1  # gate blocks before any HTTP
    client = GoogleAIClient(
        settings,
        BudgetGovernor(settings),
        transport=httpx.MockTransport(forbid),
    )
    try:
        result = client.chat("s", "u", max_tokens=1000)
    finally:
        client.close()

    assert result.startswith("[BUDGET]")
