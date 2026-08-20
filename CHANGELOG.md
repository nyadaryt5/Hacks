# Changelog

All notable changes to ULTRON v6 are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [6.1.0] - 2026-08-20

### Added

- `ultron` package: the 1151-LOC monolith is split into focused modules
  (config, logging_setup, tracing, budget, fsm, events, db, memory,
  json_utils, safety, llm, debate, coordinator, api, cli).
- Health and Prometheus metrics HTTP server (`ultron-v6 serve`):
  `/healthz`, `/readyz` (injectable readiness probe), `/metrics`.
- Structured JSON logging via `ultron.logging_setup` and `--json-logs`.
- httpx-based Gemini client with retries/backoff, per-key rate limits and
  API key rotation on HTTP 429.
- CLI subcommands (`run`, `serve`) with legacy `ultron-v6 TARGET` shorthand.
- Full pytest suite (140+ tests) with an 85% coverage gate.
- CI pipeline (GitHub Actions): Python 3.10–3.12 matrix, flake8, ruff,
  strict mypy, bandit, pip-audit, wheel/sdist build smoke test.
- pip-compile lockfiles: `requirements.lock`, `requirements-dev.lock`,
  `requirements-chroma.lock`.
- Dockerfile + docker-compose for one-command startup.
- Root README with architecture diagrams, `ultron-v6/.env.example`,
  `docs/architecture.md`, pre-commit config, Dependabot and issue/PR
  templates.

### Fixed

- Repaired every syntax error that blocked importing the module
  (unclosed f-strings, unterminated call parens, stray parens, nested-quote
  f-strings, and typo'd names raising `NameError` at import time).
- Fixed runtime bugs in `BudgetGovernor` (`False`/`Session`/`self`
  typos) and added regression tests.
- Fixed FSM transition table typos and added the missing
  `AUTHORIZATION → REPORTING` transition so vetoed plans finish cleanly.
- Fixed `EventType.SERVICE_DISCOVERED` value, the `--top-pors` nmap
  typo, and the report-generation f-string bug.
- Hardened execution: `shell=False`, system temp dir, localhost-bound
  metrics server, `md5(usedforsecurity=False)`.

### Changed

- `load_settings()` logs CRITICAL records and raises `ConfigurationError`
  instead of calling `sys.exit`, so failures are testable and callers
  control exit codes.
- `DatabaseManager` and `SQLiteDatabaseManager` are always importable;
  the factory selects the ORM backend only when SQLAlchemy is present.
- `VectorMemory` accepts an explicit backend selector (`auto|chroma|hash`).
- Bumped version to 6.1.0; `ultron_v6.py` remains as a backwards
  compatible entry module.

## [6.0.0] - 2026-08-20

### Added

- Initial release: FSM core, event bus, vector memory, multi-agent debate,
  budget guardrails, SQLAlchemy models and Gemini provider (prototype,
  single-file).
