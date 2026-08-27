# Changelog

All notable changes to ULTRON v6 are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Secret-manager selection now fails closed on unknown backends, missing SDKs
  or configuration, provider errors, and empty payloads; a managed value
  replaces stale environment state instead of silently falling back to it.
- Child pentest tools no longer inherit Gemini, Vault, cloud, or telemetry
  credentials from the coordinator environment.
- Scope checks now cover ordinary two-label domains and IPv6 literals/URLs.
- Removed the global Bandit `B101` skip; only the two reviewed subprocess
  boundaries retain narrow inline suppressions.
- Constrained optional ChromaDB below the unpatched CVE-2026-45829,
  CVE-2026-45830, CVE-2026-45831, and CVE-2026-45833 ranges; compatible
  transitive caps, disabled telemetry, and local embeddings keep its supported
  Python 3.10/3.11 path offline.

### Changed

- Structured JSON logging is now a core runtime dependency: `structlog` and
  `python-json-logger` moved from the `observability`/`all` extras into the
  base install, so `--json-logs` always uses the real structured formatter
  path instead of a stdlib-only fallback; both are pinned in every committed
  lockfile, including `requirements.lock`.
- Packaging and dependency metadata now has one scanner-visible source at the
  repository-root `pyproject.toml`; CI performs a real re-resolution and
  byte-comparison drift check plus strict vulnerability audits for build,
  runtime, development, Chroma, and cross-version production-extra sets.
- Root lockfiles are now regular byte-identical mirrors rather than symlinks,
  and root/package `.env.example` templates enumerate every setting.
- CI actions are pinned to immutable SHAs, strict mypy is green again, optional
  integrations get fresh-install smoke jobs, and CycloneDX SBOM artifacts cover
  both production dependency graphs.

### Documentation

- Added `THREAT_MODEL.md` with assets, actors, assumptions, trust boundaries,
  abuse cases, secret failure behavior, residual risks, deployment controls,
  and a test verification map.

## [6.2.1] - 2026-08-25

### Added

- Secret-manager backends in `ultron/secrets.py`: AWS Secrets Manager
  (`boto3`), HashiCorp Vault (`hvac`), and GCP Secret Manager, selected
  by `ULTRON_SECRETS_BACKEND` and wired into `load_settings()`.
- Optional Sentry error tracking (`ultron/errors.py`) behind
  `ULTRON_SENTRY_DSN`, hooked from the coordinator exception paths.
- Detectable structured logging via `structlog` / `python-json-logger`.
- Threat-model table in `docs/architecture.md`.
- Dedicated `security-audit` CI job name for pip-audit + bandit.

## [6.2.0] - 2026-08-23

### Added

- **CVSS 3.1 scoring engine** (`ultron/vulns.py`): official base-score
  equations (ISC/ESC, 1.08x scope-changed multiplier, scope-dependent
  Privileges-Required weights), severity bands, canonical suggested
  vectors. Verified against a reference implementation across all 2592
  base-metric combinations with zero mismatches.
- **FindingStore** (`ultron/vulns.py`): normalizes raw verification
  payloads into deduplicated, CVSS-scored `Finding` records and persists
  them to the `findings` table on both the SQLAlchemy and stdlib-SQLite
  backends (best-effort).
- **ScopeManager** (`ultron/scope.py`): lateral-movement approval flow —
  depth-limited requests, `LATERAL_TARGET_FOUND` events, persistence to
  `lateral_targets`, and explicit `approve()`/`reject()` before any target
  becomes jail-legal.
- **Iterative agent loop** (`ultron/coordinator.py`): the single
  plan/execute pass is now a bounded plan → authorize → execute → verify
  loop (`ULTRON_MAX_ITERATIONS`) that stops on success, veto, jail block,
  token-budget exhaustion, a repeated action, or no new progress. Planning
  prompts carry executed-action history and the finding count.
- **Hardened safety jail** (`ultron/safety.py`): shell-metacharacter
  blocklist (`; | & \` $ < >`), out-of-scope URL hosts and bare FQDNs are
  now scope-validated (previously only IP literals), empty commands are
  rejected, and the discovery scan passes through the jail.
- **FSM**: `PLANNING → REPORTING` edge so a stalled planner can still
  produce a report (mirrors the plan-vetoed skip).
- **Report**: Agent Loop, Findings table (severity + CVSS) and Scope
  sections.
- **CI**: active `.github/workflows/ci.yml` with Python 3.10–3.12 lint,
  typecheck, 85% coverage, Bandit, pip-audit and package-build gates on
  every push and pull request, plus a `lockfile-check` job that runs
  `make lockfile-check` so pip-compile drift against the committed
  lockfiles fails CI.
- Explicit pytest `network` marker; network-dependent tests are opt-in and
  excluded from the default offline suite.

### Changed

- Coverage gate holds at 85%; measured suite coverage is 91.3%
  (250 offline tests).
- CONTRIBUTING: PRs must include tests for their behavior change.

### Fixed

- Updated the committed runtime and development pins to remain installable on
  the full supported Python 3.10–3.12 matrix (`greenlet` and `stevedore`).
- Documented a lockfile-first fresh-clone install path and expanded the
  threat model with key rotation, budget controls and secret-manager examples.

## [6.1.1] - 2026-08-21

### Added

- `test_smoke.py`: fresh-clone smoke test asserting `ultron-v6 --version`
  exits 0 and `ultron.cli` imports with no network access.
- Session-wide `GOOGLE_API_KEY` fixture in `tests/conftest.py` so the whole
  suite runs from a fresh clone with no real key and no external services.
- PEP 621 `[project]` metadata in `ultron-v6/pyproject.toml` with explicit
  runtime and dev dependencies (previously only declared in `setup.py`).

### Fixed

- Activated the CI pipeline: the workflow was stashed in
  `.github/_workflows_backup/` and never ran; it now lives at
  `.github/workflows/ci.yml` and runs lint, typecheck, a 3.10–3.12 test
  matrix and security scans on every push and PR.
- Repaired `tests/test_offline_mode.py`, which called removed APIs and left
  the suite red; rewritten against the real `GoogleAIClient`,
  `VectorMemory` and `DatabaseManager` interfaces with mocked HTTP transport.

### Changed

- Removed `ultron-v6/setup.py` in favour of a single `pyproject.toml` source
  of truth; the package version is derived dynamically from
  `ultron.__version__`.
- CI now pins `actions/checkout@v4` / `actions/setup-python@v5` and caches
  pip keyed on the lockfiles.
- Documented an explicit threat model and secret-management guidance in
  `SECURITY.md`.

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
