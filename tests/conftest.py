"""Shared pytest fixtures.

Makes the ``ultron-v6`` source tree importable without installation so the
test suite runs from a fresh clone with a single command.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "ultron-v6"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
