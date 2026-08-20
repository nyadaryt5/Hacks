#!/usr/bin/env python3
"""
ULTRON v6.0 — Autonomous Pentest Framework
==========================================
Applied: FSM Core | Event Bus | Vector Memory | Multi-Agent Debate
         Observability | Budget Guardrails | SQLAlchemy ORM | Pydantic Config
Provider: Google AI (Gemini)
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from ultron import __version__
# Re-exported for backwards compatibility with the single-file module.
from ultron.debate import DebateProtocol  # noqa: F401
from ultron.coordinator import ULTRONCoordinator, _BANNER  # noqa: F401
from ultron.config import (  # noqa: F401
    BudgetConfig,
    ConfigurationError,
    DatabaseConfig,
    GoogleAIConfig,
    HAS_PYDANTIC,
    ULTRONSettings,
    load_settings,
)
from ultron.budget import BudgetGovernor  # noqa: F401
from ultron.events import EVENT_BUS, Event, EventBus, EventType  # noqa: F401
from ultron.fsm import (  # noqa: F401
    AgentState,
    FiniteStateMachine,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)
from ultron.json_utils import parse_json_response  # noqa: F401
from ultron.llm import GEMINI_CONTEXT_PREFIX, GoogleAIClient  # noqa: F401
from ultron.safety import FORBIDDEN_PATTERNS, SafetyJail  # noqa: F401
from ultron.tracing import TRACER, Span, SpanType, Tracer  # noqa: F401
from ultron.memory import VectorMemory  # noqa: F401
from ultron.db import (  # noqa: F401
    Base,
    DatabaseManager,
    HAS_SQLALCHEMY,
    SQLiteDatabaseManager,
)

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

_LOGGER = logging.getLogger("ultron")

# ============================================================
# MAIN
# ============================================================


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ultron-v6",
        description=(
            "ULTRON v6.0 - Autonomous penetration testing framework "
            "powered by Google AI (Gemini). For authorized testing only."
        ),
    )
    parser.add_argument(
        "target", help="Target IP address or domain (authorized scope)"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args(argv)

    from ultron.logging_setup import configure_logging

    configure_logging(level=args.log_level)

    try:
        settings = load_settings({"target": args.target})
    except ConfigurationError as exc:
        _LOGGER.error("%s", exc)
        return 1

    print(
        f"\n{_BANNER}\n"
        "  ULTRON v6.0 - Production-Grade Autonomous Pentest Framework\n"
        f"  Target: {settings.target}\n"
        f"  Model: {settings.google_ai.model}\n"
        f"  API Keys: {len(settings.google_ai.api_keys)} configured\n"
        "  Features: FSM | Event Bus | Vector Memory | Debate | Budget Guard\n"
        f"{_BANNER}\n"
    )

    coordinator = ULTRONCoordinator(settings)
    coordinator.launch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
