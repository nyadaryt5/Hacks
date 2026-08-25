"""ULTRON v6 — autonomous penetration testing framework.

Module layout
-------------
config        typed, validated settings (pydantic + stdlib fallback)
logging_setup central logging configuration (text / structured JSON)
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
vulns         CVSS 3.1 scoring engine + persistent finding store
cli           command line interface
api           health and Prometheus metrics HTTP endpoints
"""

__version__ = "6.1.1"

from ultron.api import METRICS, MetricsRegistry, serve_forever, start_server
from ultron.budget import BudgetGovernor
from ultron.config import (
    GEMINI_BASE_URL,
    HAS_PYDANTIC,
    BudgetConfig,
    ConfigurationError,
    DatabaseConfig,
    GoogleAIConfig,
    ULTRONSettings,
    load_settings,
)
from ultron.coordinator import ULTRONCoordinator
from ultron.db import (
    HAS_SQLALCHEMY,
    Base,
    DatabaseManager,
    SQLiteDatabaseManager,
)
from ultron.debate import DebateProtocol
from ultron.events import EVENT_BUS, Event, EventBus, EventType
from ultron.fsm import (
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
from ultron.vulns import (
    Finding,
    FindingStore,
    InvalidVectorError,
    base_score,
    score_of_vector,
    severity_for_score,
)

if HAS_SQLALCHEMY:  # pragma: no branch
    from ultron.db import (  # noqa: F401
        EpisodeModel,
        FindingModel,
        GoalModel,
        LateralTargetModel,
        LessonMemoryModel,
        SQLAlchemyDatabaseManager,
        TargetStateModel,
    )

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
    "METRICS",
    "MetricsRegistry",
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
    "Finding",
    "FindingStore",
    "InvalidVectorError",
    "base_score",
    "score_of_vector",
    "severity_for_score",
    "configure_logging",
    "load_settings",
    "parse_json_response",
    "serve_forever",
    "start_server",
]
