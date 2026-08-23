"""Configuration validation tests for ULTRONSettings and load_settings."""

import pytest

from ultron_v6 import (
    ConfigurationError,
    ULTRONSettings,
    load_settings,
)


@pytest.fixture(autouse=True)
def _clean_api_key_env(monkeypatch):
    """Ensure no API key environment leaks between tests."""
    for i in range(1, 11):
        monkeypatch.delenv(f"GOOGLE_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def test_settings_defaults():
    settings = ULTRONSettings()
    assert settings.google_ai.model == "gemini-1.5-flash"
    assert settings.google_ai.api_keys == []
    assert settings.google_ai.temperature == pytest.approx(0.3)
    assert settings.google_ai.max_tokens == 3000
    assert settings.budget.max_tokens_per_session == 500000
    assert settings.budget.max_tokens_per_minute == 10000
    assert settings.budget.max_tokens_per_hour == 100000
    assert settings.budget.max_cost_per_session_usd == pytest.approx(1.0)
    assert settings.budget.warn_at_percent == pytest.approx(80.0)
    assert settings.database.url == "sqlite:///ultron_v6.db"
    assert settings.max_iterations == 30
    assert settings.log_level == "INFO"
    assert settings.target == ""


def test_api_keys_loaded_from_primary_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-primary")
    settings = ULTRONSettings()
    assert settings.google_ai.load_keys_from_env() == ["AIza-primary"]


def test_api_keys_loaded_from_numbered_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY_1", "AIza-one")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "AIza-two")
    monkeypatch.setenv("GOOGLE_API_KEY_3", "AIza-three")
    settings = ULTRONSettings()
    assert settings.google_ai.load_keys_from_env() == [
        "AIza-one",
        "AIza-two",
        "AIza-three",
    ]


def test_load_settings_succeeds_with_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-ok")
    settings = load_settings({"target": "example.com"})
    assert settings.google_ai.api_keys == ["AIza-ok"]
    assert settings.target == "example.com"


def test_env_example_documents_required_keys():
    """The committed .env.example must list the documented variables."""
    from pathlib import Path

    example = Path("ultron-v6/.env.example").read_text(encoding="utf-8")
    for name in (
        "GOOGLE_API_KEY",
        "ULTRON_MODEL",
        "ULTRON_MAX_ITERATIONS",
        "ULTRON_MAX_LATERAL_DEPTH",
        "ULTRON_OUTPUT_MAX_CHARS",
        "ULTRON_CACHE_TTL_HOURS",
        "ULTRON_LOG_LEVEL",
        "ULTRON_BUDGET_MAX_TOKENS_PER_SESSION",
        "ULTRON_BUDGET_MAX_TOKENS_PER_MINUTE",
        "ULTRON_BUDGET_MAX_TOKENS_PER_HOUR",
        "ULTRON_BUDGET_MAX_COST_PER_SESSION_USD",
        "ULTRON_BUDGET_WARN_AT_PERCENT",
        "ULTRON_DB_URL",
    ):
        assert name in example, name


def test_load_settings_raises_without_key(caplog):
    with caplog.at_level("CRITICAL", logger="ultron"):
        with pytest.raises(ConfigurationError, match="GOOGLE_API_KEY"):
            load_settings()
    assert any("No GOOGLE_API_KEY configured" in r.message for r in caplog.records)


def test_temperature_out_of_range_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ULTRONSettings(google_ai={"temperature": 3.0})


def test_max_tokens_out_of_range_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ULTRONSettings(google_ai={"max_tokens": 9999})


def test_model_override(monkeypatch):
    monkeypatch.setenv("ULTRON_MODEL", "gemini-2.0-flash")
    settings = ULTRONSettings()
    assert settings.google_ai.model == "gemini-2.0-flash"


def test_budget_env_prefix(monkeypatch):
    monkeypatch.setenv("ULTRON_BUDGET_MAX_TOKENS_PER_SESSION", "1234")
    monkeypatch.setenv("ULTRON_BUDGET_WARN_AT_PERCENT", "55.5")
    settings = ULTRONSettings()
    assert settings.budget.max_tokens_per_session == 1234
    assert settings.budget.warn_at_percent == pytest.approx(55.5)


def test_database_env_prefix(monkeypatch):
    monkeypatch.setenv("ULTRON_DB_URL", "sqlite:///:memory:")
    settings = ULTRONSettings()
    assert settings.database.url == "sqlite:///:memory:"


def test_load_settings_reports_validation_errors(caplog):
    """Invalid values must produce a critical log and ConfigurationError."""
    with pytest.raises(ConfigurationError):
        load_settings({"max_iterations": 1000})


def test_fallback_without_pydantic():
    """Without pydantic installed, load_settings must still work."""
    import subprocess
    import sys

    script = """
import os
import sys

sys.path.insert(0, "ultron-v6")
# Simulate pydantic being unavailable.
sys.modules["pydantic"] = None
sys.modules["pydantic_settings"] = None

import ultron_v6

assert ultron_v6.HAS_PYDANTIC is False
os.environ["GOOGLE_API_KEY"] = "AIza-fallback"
settings = ultron_v6.load_settings({"target": "fallback.example"})
assert settings.google_ai.api_keys == ["AIza-fallback"]
assert settings.target == "fallback.example"
assert settings.budget.max_tokens_per_session == 500000
print("FALLBACK-OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "FALLBACK-OK" in result.stdout
