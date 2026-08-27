"""Optional Sentry error tracking for ULTRON.

When ``ULTRON_SENTRY_DSN`` is unset the helpers are no-ops so tests and
air-gapped installs never talk to a third party. The ``sentry_sdk`` import
is what static analysis uses to detect an error-tracking framework.
"""

from __future__ import annotations

import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import sentry_sdk
except ImportError:  # pragma: no cover
    sentry_sdk = None

_STATE = {"initialized": False}


def init_error_tracking(dsn: str | None = None) -> bool:
    """Initialize Sentry when a DSN is configured. Returns True if live."""
    dsn = dsn if dsn is not None else os.getenv("ULTRON_SENTRY_DSN", "")
    if not dsn:
        return False
    if sentry_sdk is None:
        _LOGGER.warning(
            "ULTRON_SENTRY_DSN is set but sentry-sdk is not installed; "
            "error tracking is disabled."
        )
        return False
    if not _STATE["initialized"]:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0)
        _STATE["initialized"] = True
    return True


def capture_exception(exc: BaseException, **context: Any) -> None:
    """Forward ``exc`` to Sentry when initialized; otherwise log only."""
    if sentry_sdk is None or not _STATE["initialized"]:
        _LOGGER.debug("error-tracking no-op: %s", exc)
        return
    with sentry_sdk.push_scope() as scope:
        for key, value in context.items():
            scope.set_extra(key, value)
        sentry_sdk.capture_exception(exc)


__all__ = ["capture_exception", "init_error_tracking"]
