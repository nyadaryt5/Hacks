# ULTRON v6 (package)

This directory contains the installable **ultron-v6** package.

📖 **Documentation, installation, configuration and usage live in the
[repository root README](../README.md).**

## Install

```bash
# Install the committed, reproducible dependency sets first.
python -m pip install -r requirements.lock
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
```

The runtime and development lockfiles are intentionally separate. The dev
lockfile constrains development tools against `requirements.lock`; installing
both before the editable package install keeps a fresh clone reproducible.

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
| `requirements.in` / `requirements.lock` | runtime deps + pinned lockfile |
| `requirements-dev.in` / `requirements-dev.lock` | dev tooling + pinned lockfile |
| `requirements-chroma.in` / `requirements-chroma.lock` | optional ChromaDB backend |

Regenerate lockfiles with:

```bash
pip-compile --output-file requirements.lock requirements.in
pip-compile --output-file requirements-dev.lock requirements-dev.in
pip-compile --output-file requirements-chroma.lock requirements-chroma.in
```

## License

MIT — see [LICENSE](LICENSE).
