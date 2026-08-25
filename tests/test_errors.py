"""Tests for optional Sentry error tracking."""

from ultron.errors import capture_exception, init_error_tracking


def test_init_without_dsn_is_noop(monkeypatch):
    monkeypatch.delenv("ULTRON_SENTRY_DSN", raising=False)
    assert init_error_tracking() is False


def test_capture_without_init_does_not_raise():
    capture_exception(RuntimeError("ignored"), phase="test")
