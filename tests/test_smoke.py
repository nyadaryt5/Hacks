"""Fresh-clone smoke test.

Proves that the packaged CLI imports and reports its version with exit code 0
and without any network access — the minimum a buyer expects to work from a
clean checkout.
"""

import importlib

import pytest

from ultron import __version__


def test_cli_module_imports():
    """``ultron.cli`` must import cleanly (no side effects, no network)."""
    module = importlib.import_module("ultron.cli")
    assert hasattr(module, "main")
    assert callable(module.main)


def test_version_flag_exits_zero(capsys):
    """``ultron-v6 --version`` exits 0 and prints the package version."""
    from ultron.cli import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_version_matches_semver():
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
