# ULTRON v6.0 — Production-Grade Autonomous Pentest Framework

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**ULTRON v6.0** is a production-grade autonomous penetration testing framework powered by Google AI (Gemini). It orchestrates LLM-driven security analysis through a finite state machine (FSM) architecture, with built-in budget guardrails, vector memory, multi-agent debate for decision validation, and comprehensive observability.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      ULTRON Coordinator                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │   FSM    │  │ Event Bus│  │  Vector  │  │   Budget   │  │
│  │  Engine  │  │   Pub/Sub│  │  Memory  │  │  Governor  │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │  Google  │  │  Debate  │  │  Safety  │  │    ORM     │  │
│  │ AI Client│  │ Protocol │  │   Jail   │  │  (SQLite)  │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Phases (FSM-Driven Pipeline)

| Phase | State | Description |
|-------|-------|-------------|
| 1 | **DISCOVERY** | Reconnaissance — nmap scans, service enumeration |
| 2 | **ANALYSIS** | AI-powered analysis of scan results with vector memory recall |
| 3 | **PLANNING** | LLM generates next action plan (tool or code execution) |
| 4 | **AUTHORIZATION** | Multi-agent debate validates plan before execution |
| 5 | **EXECUTION** | Sandboxed command/tool execution with safety jail |
| 6 | **VERIFICATION** | AI verifies execution results and extracts findings |
| 7 | **REPORTING** | Generates structured markdown report |

## Features

### Core Systems

- **Finite State Machine (FSM)** — Directed-graph state transitions with validation and full history tracking
- **Event Bus** — In-process pub/sub for decoupled agent communication (extensible to Redis/RabbitMQ)
- **Vector Memory** — Semantic search over past lessons using ChromaDB (with numpy fallback)
- **Multi-Agent Debate** — Attacker/defender/synthesizer debate cycle for high-risk decisions
- **Budget Governor** — Real-time token cost tracking with RPM/RPD limits and graceful termination
- **Safety Jail** — Regex-based command filtering and target scope validation

### Observability

- **OpenTelemetry-Style Tracing** — Span-based distributed tracing with timing, token tracking, and cost attribution
- **Structured Logging** — JSON-format event log with severity levels
- **Trace Summary** — Aggregate metrics per session

### Data Persistence

- **SQLAlchemy ORM** (with SQLite fallback) — Episodes, findings, lateral targets, lesson memory
- **Thread-safe** — Per-thread database sessions with connection pooling

## Requirements

- Python 3.10+
- Google AI (Gemini) API key

### Dependencies

| Package | Purpose | Optional |
|---------|----------|----------|
| `pydantic` | Configuration validation | Yes (fallback provided) |
| `pydantic-settings` | Env-based settings | Yes (fallback provided) |
| `sqlalchemy` | ORM database layer | Yes (fallback to raw SQLite) |
| `chromadb` | Vector embeddings backend | Yes (fallback to numpy) |

## Installation

```bash
# Clone the repository
git clone https://github.com/nyadaryt5/ultron-v6.git
cd ultron-v6

# Install dependencies
pip install -r requirements.txt

# Set your Google AI API key
export GOOGLE_API_KEY='AIzaSy...'

# Run against a target
python3 ultron_v6.py <target-ip-or-domain>
```

### Multiple API Keys (Key Rotation)

```bash
export GOOGLE_API_KEY_1='AIzaSy...'
export GOOGLE_API_KEY_2='AIzaSy...'
export GOOGLE_API_KEY_3='AIzaSy...'
```

## Usage

```bash
# Basic scan
python3 ultron_v6.py 192.168.1.100

# Domain target
python3 ultron_v6.py example.com

# With custom model
export ULTRON_MODEL='gemini-2.0-flash'
python3 ultron_v6.py 10.0.0.50
```

### Configuration via Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | — | Primary Gemini API key |
| `GOOGLE_API_KEY_{1-10}` | — | Additional keys for rotation |
| `ULTRON_MODEL` | `gemini-1.5-flash` | Gemini model |
| `ULTRON_MAX_ITERATIONS` | `30` | Max FSM cycles |
| `ULTRON_MAX_LATERAL_DEPTH` | `2` | Max lateral movement depth |
| `ULTRON_LOG_LEVEL` | `INFO` | Logging verbosity |
| `ULTRON_BUDGET_MAX_TOKENS_PER_SESSION` | `500000` | Token budget per session |

## Output Artifacts

- `ultron_v6.db` — SQLite database with all findings, episodes, and memory
- `ultron_traces.log` — Structured trace log
- `ULTRON_V6_REPORT_*.md` — Markdown penetration test report
- `query_results/` — Raw tool output artifacts

## Security & Ethics

ULTRON v6.0 includes **multiple safety layers**:

1. **System Prompt Jail** — Forces the LLM into authorized testing context
2. **Safety Jail** — Regex blocks destructive commands (rm -rf, reverse shells, etc.)
3. **Scope Validation** — All target IPs must be in the authorized scope
4. **Multi-Agent Debate** — High-risk actions require adversarial approval
5. **Budget Guardrails** — Prevents runaway API costs

**Always ensure you have written authorization before testing any infrastructure.**

## License

MIT License — See [LICENSE](LICENSE) for details.

---

*Built for authorized security professionals and defensive red teams.*