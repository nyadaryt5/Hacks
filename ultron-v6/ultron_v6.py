#!/usr/bin/env python3
"""
ULTRON v6 — Autonomous Pentest Framework
========================================
Backwards-compatible entry module.

The implementation lives in the :mod:`ultron` package. This module
re-exports the public API and the CLI entry point so legacy usages
(``python ultron_v6.py <target>``, ``python -m ultron_v6`` and the
``ultron-v6`` console script) keep working unchanged.
"""

from __future__ import annotations

import sys

from ultron import __version__
from ultron.budget import BudgetGovernor
from ultron.cli import main
from ultron.config import (  # noqa: F401
    GEMINI_BASE_URL,
    HAS_PYDANTIC,
    BudgetConfig,
    ConfigurationError,
    DatabaseConfig,
    GoogleAIConfig,
    ULTRONSettings,
    load_settings,
)
from ultron.db import (  # noqa: F401
    HAS_SQLALCHEMY,
    Base,
    DatabaseManager,
    SQLiteDatabaseManager,
)
from ultron.debate import DebateProtocol
from ultron.events import EVENT_BUS, Event, EventBus, EventType
from ultron.fsm import (  # noqa: F401
    VALID_TRANSITIONS,
    AgentState,
    FiniteStateMachine,
    InvalidTransitionError,
)
from ultron.json_utils import parse_json_response
from ultron.llm import GEMINI_CONTEXT_PREFIX, GoogleAIClient
from ultron.logging_setup import JsonFormatter, configure_logging
from ultron.memory import VectorMemory
from ultron.safety import FORBIDDEN_PATTERNS, SafetyJail
from ultron.tracing import TRACER, Span, SpanType, Tracer

if HAS_SQLALCHEMY:  # ORM models only exist when SQLAlchemy is installed
    from ultron.db import (  # noqa: F401
        EpisodeModel,
        FindingModel,
        GoalModel,
        LateralTargetModel,
        LessonMemoryModel,
        SQLAlchemyDatabaseManager,
        TargetStateModel,
    )

from ultron.coordinator import ULTRONCoordinator  # noqa: E402,F401 (shim re-export)

__all__ = [
    "AgentState",
    "Base",
    "BudgetConfig",
    "BudgetGovernor",
    "ConfigurationError",
    "DatabaseConfig",
    "DatabaseManager",
    "DebateProtocol",
    "EVENT_BUS",
    "Event",
    "EventBus",
    "EventType",
    "FORBIDDEN_PATTERNS",
    "FiniteStateMachine",
    "GEMINI_BASE_URL",
    "GEMINI_CONTEXT_PREFIX",
    "GoogleAIClient",
    "GoogleAIConfig",
    "HAS_PYDANTIC",
    "HAS_SQLALCHEMY",
    "InvalidTransitionError",
    "JsonFormatter",
    "SQLAlchemyDatabaseManager",
    "SQLiteDatabaseManager",
    "SafetyJail",
    "Span",
    "SpanType",
    "TRACER",
    "Tracer",
    "ULTRONCoordinator",
    "ULTRONSettings",
    "VALID_TRANSITIONS",
    "VectorMemory",
    "__version__",
    "configure_logging",
    "load_settings",
    "main",
    "parse_json_response",
]

if __name__ == "__main__":
    sys.exit(main())
