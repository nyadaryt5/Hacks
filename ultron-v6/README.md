# ULTRON v6 (package)

This directory contains the installable **ultron-v6** package.

📖 **Documentation, installation, configuration and usage live in the
[repository root README](../README.md).**

## Install

From the repository root:

```bash
# Install the committed, hash-pinned dependency sets first.
python -m pip install -r ultron-v6/requirements-build.lock
python -m pip install -r ultron-v6/requirements.lock
python -m pip install -r ultron-v6/requirements-dev.lock
python -m pip install --no-build-isolation --no-deps -e .
```

The runtime and development lockfiles are intentionally separate. The dev
lock includes the runtime plus development tools; installing the committed
pins before the editable package keeps a fresh clone reproducible.

## Run

```bash
ultron-v6 --version
ultron-v6 run example.com       # run the pipeline
ultron-v6 serve --port 8080     # health + metrics API
python -m ultron_v6 --help      # legacy entry point
```

## Package layout

```
ultron/
├── config.py         # pydantic settings + stdlib fallback
├── logging_setup.py  # text / structured JSON logging
├── tracing.py        # span-based observability
├── budget.py         # token & per-key rate-limit governor
├── fsm.py            # state machine + transition table
├── events.py         # event bus
├── db.py             # SQLAlchemy ORM models / SQLite fallback
├── memory.py         # vector memory (ChromaDB or hash fallback)
├── json_utils.py     # tolerant LLM JSON parsing
├── safety.py         # scope validation + command jail
├── llm.py            # Gemini client (httpx, retries, key rotation)
├── debate.py         # multi-agent debate protocol
├── coordinator.py    # FSM-driven pipeline
├── api.py            # /healthz /readyz /metrics server
└── cli.py            # command line interface
```

## Dependency files

| File | Purpose |
|------|---------|
| `../pyproject.toml` | single source of packaging and direct dependencies |
| `requirements-build.lock` | PEP 517 build backend/tooling, fully pinned |
| `requirements.lock` | core runtime, fully pinned |
| `requirements-dev.lock` | core runtime + test/lint/type/security tooling |
| `requirements-chroma.lock` | core + constrained Chroma (Python 3.10/3.11) |
| `requirements-all.lock` | cross-version secret-manager + observability integrations |

The same locks are committed as regular files at repository root for tooling
that scans only the top-level project. `scripts/lockfiles.py` keeps both
locations byte-identical. Lock resolution deliberately uses Python 3.11 as a
fixed environment-marker baseline. From the repository root with Python 3.11:

```bash
make lockfiles          # preserve compatible existing pins
make lockfile-upgrade   # intentionally resolve newest compatible versions
make lockfile-check     # fail on pyproject drift or mismatched mirrors
```

The Chroma upper bound is intentional: releases 0.4.17 and newer remain in
unpatched CVE-2026-45829, CVE-2026-45830, CVE-2026-45831, and CVE-2026-45833
ranges. Chroma 0.4.16's native extension does not publish Python 3.12 wheels,
so Python 3.12 uses the built-in hash-memory backend. ULTRON supplies local
embeddings and disables Chroma telemetry, so this path does not download an
embedding model at runtime. CI audits all locks and runs an offline Chroma
round trip on Python 3.10/3.11.

## License

MIT — see [LICENSE](LICENSE).
