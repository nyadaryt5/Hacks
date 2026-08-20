"""Tests for ultron.budget — token budgets, rate limits and warnings."""

import pytest

from ultron.budget import BudgetGovernor
from ultron.config import ULTRONSettings


@pytest.fixture()
def settings():
    """Settings with small budgets for fast deterministic tests."""
    return ULTRONSettings(
        google_ai={"api_keys": ["k1"], "max_rpm_per_key": 2, "max_rpd_per_key": 3},
        budget={
            "max_tokens_per_session": 1000,
            "warn_at_percent": 50.0,
        },
    )


@pytest.fixture()
def governor(settings):
    return BudgetGovernor(settings)


def test_initial_budget_is_ok(governor):
    assert governor.check_budget(estimated_tokens=100) == (True, "OK")
    assert governor.budget_exceeded is False


def test_session_budget_enforced(governor):
    ok, reason = governor.check_budget(estimated_tokens=1001)
    assert ok is False
    assert "Session budget exceeded" in reason
    assert governor.budget_exceeded is True


def test_session_budget_boundary_is_allowed(governor):
    assert governor.check_budget(estimated_tokens=1000) == (True, "OK")


def test_rate_limit_per_key(governor):
    for _ in range(2):
        governor.record_usage(1, api_key="k1")
    ok, reason = governor.check_budget(api_key="k1")
    assert ok is False
    assert "Rate limit" in reason


def test_rate_limits_are_independent_per_key(governor):
    for _ in range(2):
        governor.record_usage(1, api_key="k1")
    # A second key still has headroom.
    assert governor.check_budget(api_key="k2") == (True, "OK")


def test_daily_limit_enforced(settings):
    settings.google_ai.max_rpm_per_key = 100  # isolate the daily limit
    governor = BudgetGovernor(settings)
    for _ in range(3):
        governor.record_usage(1, api_key="k1")
    ok, reason = governor.check_budget(api_key="k1")
    assert ok is False
    assert "Daily limit" in reason


def test_record_usage_updates_status(governor):
    governor.record_usage(250, api_key="k1")
    status = governor.get_status()
    assert status["tokens_used_session"] == 250
    assert status["requests_this_minute"] == 1
    assert status["requests_today"] == 1
    assert status["usage_percent"] == pytest.approx(25.0)


def test_warning_emitted_once_at_threshold(governor):
    # 50% threshold at 1000 tokens: 500 tokens crosses it.
    governor.record_usage(500)
    governor.check_budget()
    governor.check_budget()
    assert governor.warnings_issued == {"session_warn"}


def test_no_warning_below_threshold(governor):
    governor.record_usage(100)
    governor.check_budget()
    assert governor.warnings_issued == set()


def test_force_terminate(governor):
    message = governor.force_terminate()
    assert "Budget exceeded" in message
    assert governor.budget_exceeded is True


def test_reset_counters_after_a_minute(governor):
    from ultron.budget import _KeyRateLimiter

    limiter = governor.key_limiters.setdefault("k1", _KeyRateLimiter())
    limiter.requests_this_minute = 5
    limiter.minute_start = 0.0  # force reset on next check
    governor.minute_start = 0.0
    governor.check_budget(api_key="k1")
    assert limiter.requests_this_minute == 0
