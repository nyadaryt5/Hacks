"""Smoke tests: the main module must import cleanly and expose its API."""

import importlib
import os


PUBLIC_SYMBOLS = [
    "__version__",
    "ULTRONSettings",
    "GoogleAIConfig",
    "BudgetConfig",
    "DatabaseConfig",
    "load_settings",
    "ConfigurationError",
    "Tracer",
    "Span",
    "SpanType",
    "TRACER",
    "BudgetGovernor",
    "DatabaseManager",
    "SQLAlchemyDatabaseManager",
    "SQLiteDatabaseManager",
    "EpisodeModel",
    "FindingModel",
    "LessonMemoryModel",
    "VectorMemory",
    "AgentState",
    "VALID_TRANSITIONS",
    "InvalidTransitionError",
    "FiniteStateMachine",
    "EventType",
    "Event",
    "EventBus",
    "EVENT_BUS",
    "DebateProtocol",
    "GEMINI_CONTEXT_PREFIX",
    "GoogleAIClient",
    "parse_json_response",
    "FORBIDDEN_PATTERNS",
    "SafetyJail",
    "ULTRONCoordinator",
    "main",
]


def test_module_imports_without_side_effects(tmp_path, monkeypatch):
    """Importing the module must not write files or need API keys."""
    monkeypatch.chdir(tmp_path)
    module = importlib.import_module("ultron_v6")
    assert module is not None
    # The legacy version opened a log file at import time; the fix must not.
    assert os.listdir(tmp_path) == []


def test_public_api_symbols_exist():
    module = importlib.import_module("ultron_v6")
    missing = [name for name in PUBLIC_SYMBOLS if not hasattr(module, name)]
    assert missing == [], f"missing public symbols: {missing}"


def test_version_is_semver():
    import ultron_v6

    parts = ultron_v6.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_main_guard_present():
    """The console-script entry point (ultron_v6:main) must exist."""
    import ultron_v6

    assert callable(ultron_v6.main)


def test_agent_state_machine_declaration_is_consistent():
    """Every state referenced by the transition table must exist."""
    import ultron_v6

    names = {state.name for state in ultron_v6.AgentState}
    assert names == {
        "IDLE",
        "DISCOVERY",
        "ANALYSIS",
        "PLANNING",
        "AUTHORIZATION",
        "EXECUTION",
        "VERIFICATION",
        "REPORTING",
        "COMPLETE",
        "ERROR",
        "TERMINATED",
    }
    for state, targets in ultron_v6.VALID_TRANSITIONS.items():
        assert isinstance(state, ultron_v6.AgentState)
        assert all(
            isinstance(t, ultron_v6.AgentState) for t in targets
        ), f"non-state target in {state}"
