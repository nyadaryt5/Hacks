"""Tests for ultron.logging_setup and critical-failure logging."""

import json
import logging

import pytest

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


def test_configure_logging_json_mode_emits_one_parseable_object(capsys):
    """Exercise the real --json-logs formatter selection path."""
    configure_logging(level="INFO", json_format=True)
    logging.getLogger("ultron.smoke").warning("structured-smoke")
    for handler in logging.getLogger().handlers:
        handler.flush()

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["message"] == "structured-smoke"
    assert payload.get("level", payload.get("levelname")) == "WARNING"
    assert payload.get("logger", payload.get("name")) == "ultron.smoke"


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


def test_json_mode_prefers_python_json_logger_formatter():
    """json mode must not silently degrade to the stdlib-only fallback.

    structlog and python-json-logger are core runtime dependencies, so a
    default install always exercises the real structured formatter path.
    """
    try:
        from pythonjsonlogger.json import JsonFormatter as RealJsonFormatter
    except ImportError:  # python-json-logger 2.x layout
        from pythonjsonlogger.jsonlogger import (  # noqa: F811
            JsonFormatter as RealJsonFormatter,
        )

    configure_logging(level="INFO", json_format=True)
    stream_formatters = [
        type(handler.formatter)
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    assert RealJsonFormatter in stream_formatters

    # Exercise the installed formatter end to end with the same payload the
    # smoke test uses, proving the third-party backend emits parseable JSON.
    record = logging.LogRecord(
        name="ultron.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="structured-backend",
        args=(),
        exc_info=None,
    )
    payload = json.loads(RealJsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ).format(record))
    assert payload["message"] == "structured-backend"
    assert payload["levelname"] == "WARNING"
    assert payload["name"] == "ultron.test"


def test_json_mode_configures_structlog_pipeline():
    """--json-logs must wire the structlog processor pipeline by default."""
    structlog = pytest.importorskip("structlog")

    configure_logging(level="INFO", json_format=True)
    assert structlog.is_configured()

    processors = list(structlog.get_config()["processors"])
    kinds = [type(p).__name__ for p in processors]
    assert "TimeStamper" in kinds
    assert "JSONRenderer" in kinds
    assert any(p is structlog.processors.add_log_level for p in processors)


def test_noisy_third_party_loggers_are_quieted():
    configure_logging(level="INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
