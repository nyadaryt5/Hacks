"""Budget guardrails: token budgets and per-key rate limits.

:class:`BudgetGovernor` enforces session token budgets plus
requests-per-minute / requests-per-day limits for each API key, and raises
warnings through the shared tracer when usage crosses the warning threshold.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Set, Tuple

from ultron.tracing import TRACER

if TYPE_CHECKING:  # pragma: no cover
    from ultron.config import ULTRONSettings


class _KeyRateLimiter:
    """Per-API-key requests-per-minute / requests-per-day tracking."""

    def __init__(self) -> None:
        self.requests_this_minute = 0
        self.requests_today = 0
        self.minute_start = time.time()
        self.day_start = time.time()

    def reset_if_needed(self) -> None:
        now = time.time()
        if now - self.minute_start >= 60:
            self.requests_this_minute = 0
            self.minute_start = now
        if now - self.day_start >= 86400:
            self.requests_today = 0
            self.day_start = now


class BudgetGovernor:
    """Real-time cost governor that tracks token usage and enforces limits."""

    def __init__(self, settings: "ULTRONSettings"):
        self.max_tokens_session = getattr(
            settings.budget, "max_tokens_per_session", 500000
        )
        self.warn_percent = getattr(settings.budget, "warn_at_percent", 80.0)
        self.max_rpm = getattr(settings.google_ai, "max_rpm_per_key", 14)
        self.max_rpd = getattr(settings.google_ai, "max_rpd_per_key", 1400)

        self.tokens_used_session = 0
        self.tokens_used_minute = 0
        self.tokens_used_hour = 0
        self.session_start = time.time()
        self.minute_start = time.time()
        self.hour_start = time.time()
        self.lock = threading.Lock()
        self.budget_exceeded = False
        self.warnings_issued: Set[str] = set()
        self.key_limiters: Dict[str, _KeyRateLimiter] = {}

    def check_budget(
        self, estimated_tokens: int = 500, api_key: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Check if we can proceed with an LLM call."""
        with self.lock:
            self._reset_counters_if_needed()

            if (
                self.tokens_used_session + estimated_tokens
                > self.max_tokens_session
            ):
                self.budget_exceeded = True
                return (
                    False,
                    f"Session budget exceeded: "
                    f"{self.tokens_used_session}/{self.max_tokens_session} tokens",
                )

            if api_key:
                limiter = self.key_limiters.setdefault(api_key, _KeyRateLimiter())
                limiter.reset_if_needed()
                if limiter.requests_this_minute >= self.max_rpm:
                    return (
                        False,
                        f"Rate limit: {limiter.requests_this_minute}/{self.max_rpm} "
                        "requests this minute",
                    )
                if limiter.requests_today >= self.max_rpd:
                    return (
                        False,
                        f"Daily limit: {limiter.requests_today}/{self.max_rpd} "
                        "requests today",
                    )

            usage_percent = (
                self.tokens_used_session / self.max_tokens_session
            ) * 100
            if (
                usage_percent >= self.warn_percent
                and "session_warn" not in self.warnings_issued
            ):
                self.warnings_issued.add("session_warn")
                TRACER.log_event(
                    "BUDGET_WARNING",
                    {
                        "usage_percent": usage_percent,
                        "tokens_used": self.tokens_used_session,
                        "max_tokens": self.max_tokens_session,
                    },
                )

            return True, "OK"

    def record_usage(
        self, tokens_used: int, api_key: Optional[str] = None
    ) -> None:
        """Record token usage after an LLM call."""
        with self.lock:
            self.tokens_used_session += tokens_used
            self.tokens_used_minute += tokens_used
            self.tokens_used_hour += tokens_used
            if api_key:
                limiter = self.key_limiters.setdefault(api_key, _KeyRateLimiter())
                limiter.reset_if_needed()
                limiter.requests_this_minute += 1
                limiter.requests_today += 1

    def _reset_counters_if_needed(self) -> None:
        now = time.time()
        if now - self.minute_start >= 60:
            self.tokens_used_minute = 0
            self.minute_start = now
        if now - self.hour_start >= 3600:
            self.tokens_used_hour = 0
            self.hour_start = now

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "tokens_used_session": self.tokens_used_session,
                "max_tokens_session": self.max_tokens_session,
                "usage_percent": (
                    self.tokens_used_session / self.max_tokens_session
                )
                * 100,
                "requests_this_minute": sum(
                    k.requests_this_minute for k in self.key_limiters.values()
                ),
                "requests_today": sum(
                    k.requests_today for k in self.key_limiters.values()
                ),
                "budget_exceeded": self.budget_exceeded,
            }

    def force_terminate(self) -> str:
        """Gracefully save state and terminate."""
        self.budget_exceeded = True
        TRACER.log_event("BUDGET_TERMINATION", self.get_status())
        return "Budget exceeded. Saving state and terminating gracefully."


__all__ = ["BudgetGovernor"]
