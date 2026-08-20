"""ULTRON v6 — autonomous penetration testing framework.

Module layout
-------------
config        typed, validated settings (pydantic + stdlib fallback)
tracing       span-based observability
budget        token / rate-limit budget governor
fsm           finite state machine driving the agent lifecycle
events        in-process event bus
db            SQLAlchemy ORM models with a raw-SQLite fallback
memory        vector memory (ChromaDB with hash-based fallback)
json_utils    tolerant JSON parsing of LLM output
safety        scope validation and destructive-command jail
llm           Google AI (Gemini) client with key rotation
debate        multi-agent debate protocol
coordinator   FSM-driven orchestration of the pentest phases
cli           command line interface
api           health and Prometheus metrics HTTP endpoints
"""

from ultron.config import (
    BudgetConfig,
    ConfigurationError,
    DatabaseConfig,
    GEMINI_BASE_URL,
    GoogleAIConfig,
    HAS_PYDANTIC,
    ULTRONSettings,
    load_settings,
)

__version__ = "6.0.0"

__all__ = [
    "BudgetConfig",
    "ConfigurationError",
    "DatabaseConfig",
    "GEMINI_BASE_URL",
    "GoogleAIConfig",
    "HAS_PYDANTIC",
    "ULTRONSettings",
    "load_settings",
    "__version__",
]
