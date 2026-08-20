"""Tests for ultron.logging_setup and critical-failure logging."""

import json
import logging

from ultron.config import ConfigurationError, load_settings
from ultron.logging_setup import JsonFormatter, configure_logging


def test_configure_logging_installs_root_handler():
    root = configure_logging(level="INFO")
    assert root is logging.getLogger()
    assert root.level == logging.INFO
    assert len(root.handlers) >= 1


def test_configure_logging_is_idempotent():
    configure_logging()
    configure_logging()
    # Only the stream handler remains; repeated calls must not duplicate.
    assert len(logging.getLogger().handlers) == 1


def test_configure_logging_respects_level():
    root = configure_logging(level="DEBUG")
    assert root.level == logging.DEBUG


def test_configure_logging_writes_log_file(tmp_path):
    log_file = tmp_path / "ultron.log"
    configure_logging(level="INFO", log_file=str(log_file))
    logging.getLogger("ultron.test").warning("hello-file")
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_file.read_text()
    assert "hello-file" in content


def test_json_formatter_emits_parseable_json():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="ultron.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="something %s",
        args=("bad",),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "ultron.test"
    assert payload["message"] == "something bad"
    assert "timestamp" in payload


def test_json_formatter_merges_structured_extra():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="ultron.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="event",
        args=(),
        exc_info=None,
    )
    record.structured = {"session_id": "s1", "target": "example.com"}
    payload = json.loads(formatter.format(record))
    assert payload["session_id"] == "s1"
    assert payload["target"] == "example.com"


def test_missing_api_key_emits_critical_log_record(caplog, monkeypatch):
    """A fatal config failure must produce a CRITICAL log record."""
    # Override the session-wide dummy key so we exercise the missing-key path.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    for i in range(1, 11):
        monkeypatch.delenv(f"GOOGLE_API_KEY_{i}", raising=False)
    with caplog.at_level(logging.CRITICAL, logger="ultron.config"):
        try:
            load_settings()
        except ConfigurationError:
            pass
    criticals = [
        r for r in caplog.records if r.levelno == logging.CRITICAL
    ]
    assert criticals, "expected at least one CRITICAL record"
    assert any(
        "No GOOGLE_API_KEY configured" in r.message for r in criticals
    )


def test_invalid_config_emits_critical_log_record(caplog):
    with caplog.at_level(logging.CRITICAL, logger="ultron.config"):
        try:
            load_settings({"max_iterations": 100000})
        except ConfigurationError:
            pass
    criticals = [
        r for r in caplog.records if r.levelno == logging.CRITICAL
    ]
    assert criticals
    assert any(
        "Configuration validation failed" in r.message for r in criticals
    )


def test_noisy_third_party_loggers_are_quieted():
    configure_logging(level="INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
