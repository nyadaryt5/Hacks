"""Shared pytest fixtures.

Two guarantees for a fresh-clone, no-network test run:

1. The ``ultron-v6`` source tree is importable without installation, so the
   suite runs from a fresh clone with a single ``pytest`` command.
2. A dummy ``GOOGLE_API_KEY`` is present for the whole session, so no test
   depends on a real key or a network call. Individual tests that exercise
   the "missing key" path override this locally with ``monkeypatch.delenv``.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "ultron-v6"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True, scope="session")
def _dummy_google_api_key() -> None:
    """Ensure a placeholder API key exists for the whole test session.

    Uses a session-scoped monkeypatch so the value is set before any test
    imports config and is cleaned up automatically afterwards. Tests never
    reach the real Google AI endpoint because HTTP transports are mocked.
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("GOOGLE_API_KEY", "test-key")
    # Remove any inherited additional keys so key-count assertions are stable.
    for i in range(1, 11):
        mp.delenv(f"GOOGLE_API_KEY_{i}", raising=False)
    yield
    mp.undo()
