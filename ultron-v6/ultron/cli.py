"""Command line interface for ULTRON v6."""

from __future__ import annotations

import argparse
import logging
from typing import List, Optional

from ultron import __version__
from ultron.config import ConfigurationError, load_settings
from ultron.coordinator import _BANNER, ULTRONCoordinator
from ultron.logging_setup import configure_logging

_LOGGER = logging.getLogger(__name__)

_BANNER_TEXT = (
    f"\n{_BANNER}\n"
    "  ULTRON v6.0 - Production-Grade Autonomous Pentest Framework\n"
    "  Target: {target}\n"
    "  Model: {model}\n"
    "  API Keys: {keys} configured\n"
    "  Features: FSM | Event Bus | Vector Memory | Debate | Budget Guard\n"
    f"{_BANNER}\n"
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (kept separate for testability)."""
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
    parser.add_argument(
        "--json-logs",
        action="store_true",
        help="Emit structured JSON log records",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = build_parser().parse_args(argv)

    configure_logging(level=args.log_level, json_format=args.json_logs)

    try:
        settings = load_settings({"target": args.target})
    except ConfigurationError as exc:
        _LOGGER.error("%s", exc)
        return 1

    print(
        _BANNER_TEXT.format(
            target=settings.target,
            model=settings.google_ai.model,
            keys=len(settings.google_ai.api_keys),
        )
    )

    coordinator = ULTRONCoordinator(settings)
    coordinator.launch()
    return 0


__all__ = ["build_parser", "main"]
