"""Tests for ultron.cli — argument handling and exit codes."""

import pytest

from ultron import __version__
from ultron.cli import build_parser, main


@pytest.fixture(autouse=True)
def _clean_api_key_env(monkeypatch):
    for i in range(1, 11):
        monkeypatch.delenv(f"GOOGLE_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "usage: ultron-v6" in out
    assert "--json-logs" in out


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_missing_target_exits_two():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_missing_api_key_returns_one_without_crashing(capsys):
    assert main(["example.com"]) == 1
    captured = capsys.readouterr()
    assert "GOOGLE_API_KEY" in captured.out + captured.err


def test_run_launches_coordinator(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")

    launched = {}

    class FakeCoordinator:
        def __init__(self, settings):
            self.settings = settings

        def launch(self):
            launched["target"] = self.settings.target

    monkeypatch.setattr("ultron.cli.ULTRONCoordinator", FakeCoordinator)
    assert main(["192.0.2.1"]) == 0
    assert launched["target"] == "192.0.2.1"
    out = capsys.readouterr().out
    assert "Target: 192.0.2.1" in out
    assert "API Keys: 1 configured" in out


def test_json_logs_flag_is_accepted(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")

    class FakeCoordinator:
        def __init__(self, settings):
            pass

        def launch(self):
            pass

    monkeypatch.setattr("ultron.cli.ULTRONCoordinator", FakeCoordinator)
    assert main(["example.com", "--json-logs"]) == 0


def test_invalid_log_level_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        main(["example.com", "--log-level", "LOUD"])
    assert excinfo.value.code == 2


def test_build_parser_prog_name():
    assert build_parser().prog == "ultron-v6"
