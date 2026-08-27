"""Command line interface for ULTRON v6."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from ultron import __version__
from ultron.api import serve_forever
from ultron.config import ConfigurationError, load_settings
from ultron.coordinator import _BANNER, ULTRONCoordinator
from ultron.errors import init_error_tracking
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
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run", help="Run the pentest pipeline against a target"
    )
    run_parser.add_argument(
        "target", help="Target IP address or domain (authorized scope)"
    )
    _add_common_flags(run_parser)

    serve_parser = subparsers.add_parser(
        "serve", help="Run the health/metrics HTTP server"
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8080, help="Bind port (default: 8080)"
    )
    _add_common_flags(serve_parser)

    return parser


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    env_level = os.getenv("ULTRON_LOG_LEVEL", "INFO").strip().upper()
    if env_level not in levels:
        env_level = "INFO"
    json_default = os.getenv("ULTRON_JSON_LOGS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    parser.add_argument(
        "--log-level",
        default=env_level,
        choices=levels,
        help="Logging verbosity (default: ULTRON_LOG_LEVEL or INFO)",
    )
    parser.add_argument(
        "--json-logs",
        action=argparse.BooleanOptionalAction,
        default=json_default,
        help="Emit structured JSON logs (default: ULTRON_JSON_LOGS or false)",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    if argv is None:
        argv = sys.argv[1:]
    # Legacy compatibility: 'ultron-v6 TARGET' means 'ultron-v6 run TARGET'.
    if argv and argv[0] not in (
        "run",
        "serve",
        "--help",
        "-h",
        "--version",
    ):
        argv = ["run"] + list(argv)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return 2

    configure_logging(level=args.log_level, json_format=args.json_logs)
    init_error_tracking()

    if args.command == "serve":
        serve_forever(host=args.host, port=args.port)
        return 0

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
