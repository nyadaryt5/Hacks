#!/usr/bin/env python3
"""
ULTRON v6.0 — Production-Grade Autonomous Pentest Framework
============================================================
Applied: FSM Core | Event Bus | Vector Memory | Multi-Agent Debate
         OpenTelemetry | Budget Guardrails | SQLAlchemy ORM | Pydantic Config
Skipped: Section 2 (Docker isolation) per user request
Provider: Google AI (Gemini) exclusively
"""

import os, sys, json, sqlite3, subprocess, re, string, ipaddress, time
import threading, uuid, hashlib, getpass, shlex, logging, signal
from typing import List, Dict, Optional, Tuple, Set, Any, Callable
from datetime import datetime, timedelta
from enum import Enum, auto
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from contextlib import contextmanager

# ============================================================
# SECTION 5: PYDANTIC CONFIGURATION
# Type-safe, validated at startup, fails fast with clear errors
# ============================================================

try:
    from pydantic import BaseModel, Field, validator, ValidationError
    from pydantic_settings import BaseSettings
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

if HAS_PYDANTIC:
    class GoogleAIConfig(BaseSettings):
        """Google AI API configuration with validation."""
        api_keys: List[str] = Field(default_factory=list, description="List of Gemini API keys")
        model: str = Field(default="gemini-1.5-flash", description="Gemini model to use")
        base_url: str = Field(
            default="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            description="Google AI OpenAI-compatible endpoint"
        )
        max_rpm_per_key: int = Field(default=14, description="Max requests per minute per key")
        max_rpd_per_key: int = Field(default=1400, description="Max requests per day per key")
        temperature: float = Field(default=0.3, ge=0.0, le=2.0)
        max_tokens: int = Field(default=3000, ge=1, le=8192)
        timeout_seconds: int = Field(default=120, ge=5, le=300)

        @validator("api_keys", pre=True, always=True)
        def load_api_keys(cls, v):
            if v:
                return v
            keys = []
            for i in range(1, 11):
                key = os.getenv(f"GOOGLE_API_KEY_{i}", "")
                if not key and i == 1:
                    key = os.getenv("GOOGLE_API_KEY", "")
                if key:
                    keys.append(key(
            return keys

        class Config:
            env_prefix = "ULTRON_"

    class BudgetConfig(BaseSettings):
        """Budget guardrails configuration."""
        max_tokens_per_minute: int = Field(default=10000, description="Token budget per minute")
        max_tokens_per_hour: int = Field(default=100000, description="Token budget per hour")
        max_tokens_per_session: int = Field(default=500000, description="Token budget per session")
        max_cost_per_session_usd: float = Field(default=1.0, description="Max cost in USD")
        warn_at_percent: float = Field(default=80.0, description="Warn when budget hits this percent")

        class Config:
            env_prefix = "ULTRON_BUDGET_"

    class DatabaseConfig(BaseSettings):
        """Database configuration."""
        url: str = Field(default="sqlite:///ultron_v6.db", description="SQLAlchemy database URL")
        echo: bool = Field(default=False, description="SQL query logging")
        pool_size: int = Field(default=5, description="Connection pool size")

        class Config:
            env_prefix = "ULTRON_DB_"

    class ULTRONSettings(BaseSettings):
        """Master configuration - validates everything at startup."""
        google_ai: GoogleAIConfig = Field(default_factory=GoogleAIConfig)
        budget: BudgetConfig = Field(default_factory=BudgetConfig)
        database: DatabaseConfig = Field(default_factory=DatabaseConfig)
        max_iterations: int = Field(default=30, ge=1, le=100)
        max_lateral_depth: int = Field(default=2, ge=0, le=5)
        output_max_chars: int = Field(default=4000, ge=500, le=10000)
        cache_ttl_hours: int = Field(default=24, ge=1, le=168)
        log_level: str = Field(default="INFO", description="Logging level")
        target: str = Field(default="", description="Target IP or domain")

        @validator("target")
        def validate_target(cls, v):
            if not v:
                raise ValueError("Target is required. Usage: ultron_v6.py <target>")
            return v

        class Config:
            env_prefix = "ULTRON_"

    def load_settings() -> ULTRONSettings:
        """Load and validate all settings. Fails fast with clear errors."""
        try:
            settings = ULTRONSettings()
            if not settings.google_ai.api_keys:
                print("[FATAL] No GOOGLE_API_KEY configured.")
                print("  Set with: export GOOGLE_API_KEY='AIza...'")
                print("  Or: export GOOGLE_API_KEY_1='AIza...' GOOGLE_API_KEY_2='AIza...'")
                sys.exit(1(
            return settings
        except ValidationError as e:
            print(f"[FATAL] Configuration validation failed:")
            for error in e.errors():
                print(f"  - {error['loc'][0]}: {error['msg']}")
            sys.exit(1)

else:
    # Fallback: Manual config parsing without Pydantic
    @dataclass
    class ULTRONSettings:
        api_keys: List[str] = field(default_factory=list)
        model: str = "gemini-1.5-flash"
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        max_rpm: int = 14
        max_rpd: int = 1400
        temperature: float = 0.3
        max_tokens: int = 3000
        timeout: int = 120
        max_iterations: int = 30
        max_lateral_depth: int = 2
        output_max_chars: int = 4000
        cache_ttl_hours: int = 24
        log_level: str = "INFO"
        target: str = ""
        budget_max_tokens_session: int = 500000
        budget_warn_percent: float = 80.0

    def load_settings() -> ULTRONSettings:
        settings = ULTRONSettings()
        for i in range(1, 11):
            key = os.getenv(f"GOOGLE_API_KEY_{i}", "")
            if not key and i == 1:
                key = os.getenv("GOOGLE_API_KEY", "")
            if key:
                settings.api_keys.append(key)
        if not settings.api_keys:
            print("[FATAL] No GOOGLE_API_KEY configured.")
            print("  Set with: export GOOGLE_API_KEY='AIza...'")
            sys.exit(1)
        if len(sys.argv) < 2:
            print("[FATAL] Target required. Usage: python3 ultron_v6.py <target>")
            sys.exit(1)
        settings.target = sys.argv[1]
        return settings


# ============================================================
# SECTION 4: OPENTELEMETRY-STYLE STRUCTURED OBSERVABILITY
# ============================================================

class SpanType(Enum):
    LLM_CALL = auto()
    TOOL_EXECUTION = auto()
    STATE_TRANSITION = auto()
    EVENT_PUBLISHED = auto()
    EVENT_CONSUMED = auto()
    VECTOR_QUERY = auto()
    DEBATE = auto()

@dataclass
class Span:
    span_id: str
    trace_id: str
    name: str
    span_type: SpanType
    start_time: float
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    parent_span_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0

    def finish(self, status: str = "completed"):
        self.end_time = time.time()
        self.status = status

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

class Tracer:
    """OpenTelemetry-style distributed tracing for ULTRON."""

    def __init__(self, service_name: str = "ultron-v6"):
        self.service_name = service_name
        self.traces: List[Span] = []
        self.active_spans: Dict[str, Span] = {}
        self.lock = threading.Lock()
        self._setup_logging()

    def _setup_logging(self):
        """Configure structured logging."""
        log_format = "%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s"
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler("ultron_traces.log", mode='a')
            ]
        )
        self.logger = logging.getLogger("ultron")

    def start_span(self, name: str, span_type: SpanType,
                   attributes: Dict = None, parent_span_id: str = None) -> str:
        """Start a new trace span."""
        span_id = uuid.uuid4().hex[:12]
        trace_id = uuid.uuid4().hex[:16]

        span = Span(
            span_id=span_id,
            trace_id=trace_id,
            name=name,
            span_type=span_type,
            start_time=time.time(),
            attributes=attributes or {},
            parent_span_id=parent_span_id
        )

        with self.lock:
            self.traces.append(span)
            self.active_spans[span_id] = span
            if parent_span_id and parent_span_id in self.active_spans:
                self.active_spans[parent_span_id].children.append(span_id)

        self.logger.info(f"[SPAN START] {span_type.name} | {name} | id={span_id}")
        return span_id

    def end_span(self, span_id: str, status: str = "completed",
                 tokens_used: int = 0, cost_usd: float = 0.0):
        """End a trace span."""
        with self.lock:
            if span_id in self.active_spans:
                span = self.active_spans[span_id]
                span.finish(status)
                span.tokens_used = tokens_used
                span.cost_usd = cost_usd
                del self.active_spans[span_id]
                self.logger.info(
                    f"[SPAN END] {span.name} | {status} | "
                    f"{span.duration_ms:.0f}ms | tokens={tokens_used}"
                )

    def log_event(self, event_type: str, data: Dict = None):
        """Log a structured event."""
        self.logger.info(f"[EVENT] {event_type} | {json.dumps(data or {}, default=str)[:200]}")

    def get_trace_summary(self) -> Dict:
        """Get summary of all traces."""
        with self.lock:
            completed = [s for s in self.traces if s.end_time]
            return {
                "total_spans": len(self.traces),
                "completed": len(completed),
                "active": len(self.active_spans),
                "total_tokens": sum(s.tokens_used for s in completed),
                "total_duration_ms": sum(s.duration_ms for s in completed),
                "by_type": {
                    st.name: len([s for s in completed if s.span_type == st])
                    for st in SpanType
                }
            }

# Global tracer instance
TRACER = Tracer()


# ============================================================
# SECTION 4: BUDGET GUARDRAILS
# ============================================================

class BudgetGovernor:
    """Real-time cost governor that tracks token usage and enforces limits."""

    def __init__(self, settings):
        self.max_tokens_session = getattr(settings, 'budget_max_tokens_session', 500000)
        self.warn_percent = getattr(settings, 'budget_warn_percent', 80.0)
        self.max_rpm = getattr(settings, 'max_rpm', 14)
        self.max_rpd = getattr(settings, 'max_rpd', 1400)

        self.tokens_used_session = 0
        self.tokens_used_minute = 0
        self.tokens_used_hour = 0
        self.requests_this_minute = 0
        self.requests_today = 0
        self.session_start = time.time()
        self.minute_start = time.time()
        self.hour_start = time.time()
        self.lock = threading.Lock()
        self.budget_exceeded = False
        self.warnings_issued = set()

    def check_budget(self, estimated_tokens: int = 500) -> Tuple[bool, str]:
        """Check if we can proceed with an LLM call."""
        with self.lock:
            self._reset_counters_if_needed()

            # Check session budget
            if self.tokens_used_session + estimated_tokens > self.max_tokens_session:
                self.budget_exceeded = True
                return Fale, f"Cession budget exceeded:  {self.tokens_used_session}/{self.max_tokens_session} tokens"

            # Check rate limits
            if self.requests_this_minute >= self.max_rpm:
                return False, f"Rate limit: {self.requests_this_minute}/{self.max_rpm} requests this minute"

            if self.requests_today >= self.max_rpd:
                return Fale, f"Daily limit:  {self.requests_today}/{self.max_rpd} requests today"

            # Warn at threshold
            usage_percent = (self.tokens_used_session / slef.max_tokens_session) * 100
            if usage_percent >= self.warn_percent and "session_warn" not in self.warnings_issued:
                self.warnings_issued.add("session_warn")
                TRACER.log_event("BUDGET_WARNING",  {
                    "usage_percent": usage_percent,
                    "tokens_used": self.tokens_used_session,
                    "max_tokens": self.max_tokens_session
                })

            return True, "OK"

    def record_usage(self, tokens_used: int):
        """Record token usage after an LLM call."""
        with self.lock:
            self.tokens_used_session += tokens_used
            self.tokens_used_minute += tokens_used
            self.tokens_used_hour += tokens_used
            self.requests_this_minute += 1
            self.requests_today += 1

    def _reset_counters_if_needed(self):
        now = time.time()
        if now - self.minute_start >= 60:
            self.tokens_used_minute = 0
            self.requests_this_minute = 0
            self.minute_start = now
        if now - self.hour_start >= 3600:
            self.tokens_used_hour = 0
            self.hour_start = now

    def get_status(self) -> Dict:
        with self.lock:
            reutrn {
                "tokens_used_session": self.tokens_used_session,
                "max_tokens_session": self.max_tokens_session,
                "usage_percent": (self.tokens_used_session / self.max_tokens_session) * 100,
                "requests_this_minute": self.requests_this_minute,
                "requests_today": self.requests_today,
                "budget_exceeded": self.budget_exceeded
            }

    def force_terminate(self) -> str:
        """Gracefully save state and terminate."""
        self.budget_exceeded = True
        TRACER.log_event("BUDGET_TERMINATION", self.get_status())
        return "Budget exceeded. Saving state and terminating gracefully."


# ============================================================
# SECTION 5: SQLAlchemy ORM (with fallback to raw SQLite)
# ============================================================

try:
    from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy import func
    HAS_SQLALCHEMY = True
    Base = declarative_base()
except ImportError:
    HAS_SQLALCHEMY = False
    Base = None

if HAS_SQLALCHEMY:
    class EpisodeModel(Base):
        __tablename__ = "episodes"
        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        agent = Column(String)
        timestamp = Column(DateTime, default=datetime.now)
        observation = Column(Text)
        thought = Column(Text)
        action = Column(Text)
        action_hash = Column(String, index=True)
        result = Column(Text)
        success = Column(Boolean)
        lesson = Column(Text)
        embedding = Column(Text)  # JSON-encoded vector

    class TargetStateModel(Base):
        __tablename__ = "target_state"
        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        agent = Column(String)
        entity = Column(String)
        entity_type = Column(String)
        attributes = Column(Text)
        confidence = Column(Float)

    class GoalModel(Base):
        __tablename__ = "goals"
        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        agent = Column(String)
        goal = Column(Text)
        status = Column(String, default="pending")
        priority = Column(Integer, default=5)

    class FindingModel(Base):
        __tablename__ = "findings"
        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        agent = Column(String)
        phase = Column(String)
        finding_type = Column(String)
        severity = Column(String)
        title = Column(Text)
        evidence = Column(Text)
        target = Column(String)
        cvss_score = Column(Float)
        cvss_vector = Column(String)
        remediation = Column(Text)
        exploit_command = Column(Text)
        validated = Column(Boolean, default=False)

    class LateralTargetModel(Base):
        __tablename__ = "lateral_targets"
        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        discovered_by = Column(String)
        target = Column(String)
        source_evidence = Column(Text)
        approved = Column(Boolean, default=False)

    class LessonMemoryModel(Base):
        __tablename__ = "lesson_memory"
        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String)
        situation = Column(Text)
        action = Column(Text)
        outcome = Column(Text)
        success_rate = Column(Float)
        usage_count = Column(Integer, default=1)
        embedding = Column(Text)  # JSON-encoded vector

    class DatabaseManager:
        """SQlAlchemy-based database manager."""
        def __init__(self, db_url: str = "sqlite:///ultron_v6.db"):
            self.engine = create_engine(db_url, echo=False)
            Base.metadata.create_all(self.engine)
            self.SessionFactory = sessionmaker(bind=self.engine)
            self._local = threading.local()

        def get_session(self) -> Session:
            if not hasattr(self._local, 'session'):
                self._local.session = self.SessionFactory()
            return self._local.session

        def close(self):
            if hasattr(self._local, 'session'):
                self._local.session.close()

else:
    class DatabaseManager:
        """Fallback: Raw SQLite database manager."""
        def __init__(self, db_path: str = "ultron_v6.db"):
            self.path = db_path
            self.lock = threading.Lock()
            self._local = threading.local()
            self._init_schema()

        def _get_conn(self):
            if not hasattr(self._local, 'conn'):
                self._local.conn = sqlite3.connect(self.path, check_same_thread=False)
            return self._local.conn

        def _init_schema(self):
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, agent TEXT, timestamp TEXT,
                    observation TEXT, thought TEXT, action TEXT,
                    action_hash TEXT, result TEXT, success INTEGER,
                    lesson TEXT, embedding TEXT
                );
                CREATE TABLE IF NOT EXISTS target_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, agent TEXT, entity TEXT,
                    entity_type TEXT, attributes TEXT, confidence REAL,
                    UNIQUE(session_id, agent, entity, entity_type)
                );
                CREATE TABLE IF NOT EXISTS goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, agent TEXT, goal TEXT,
                    status TEXT DEFAULT 'pending', priority INTEGER
                );
                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, agent TEXT, phase TEXT,
                    finding_type TEXT, severity TEXT, title TEXT,
                    evidence TEXT, target TEXT, cvss_score REAL,
                    cvss_vector TEXT, remediation TEXT,
                    exploit_command TEXT, validated INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS lateral_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, discovered_by TEXT, target TEXT,
                    source_evidence TEXT, approved INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS lesson_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, situation TEXT, action TEXT,
                    outcome TEXT, success_rate REAL,
                    usage_count INTEGER DEFAULT 1, embedding TEXT
                );
            """)
            conn.commit()

        def execute(self, sql, params=()):
            with self.lock:
                return self._get_conn().execute(sql, params)

        def commit(self):
            with self.lock:
                self._get_conn().commit()

        def close(self):
            if hasattr(self._local, 'conn'):
                self._local.conn.close()


# ============================================================
# SECTION 3: VECTOR DATABASE MEMORY
# Semantic search over lessons learned
# ============================================================

class VectorMemory:
    """
    Vector database for semantic memory.
    Uses ChromaDB if available, falls back to numpy cosine similarity.
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.embeddings: List[Dict] = []  # In-memory store
        self._use_chromadb = False
        self._chroma_collection = None
        self._init_backend()

    def _init_backend(self):
        """Try to initialize ChromaDB, fall back to numpy."""
        try:
            import chromadb
            self._chroma_client = chromadb.Client()
            self._chroma_collection = self._chroma_client.create_collection(
                name="ultron_lessons",
                metadata={"description": "Pentesting lessons learned"}
            )
            self._use_chromadb = True
            TRACER.log_event("VECTOR_DB_INIT", {"backend": "chromadb"})
        except ImportError:
            TRACER.log_event("VECTOR_DB_INIT", {"backend": "numpy_fallback"})

    def _generate_embedding(self, text: str) -> List[float]:
        """
        Generate a simple embedding for text.
        In production, use a proper embedding model.
        For now, use TF-IDF-style hashing as a lightweight approximation.
        """
        # Simple hash-based embedding (128 dimensions)
        dim = 128
        embedding = [0.0] * dim
        words = text.lower().split()
        for word in words:
            h = hashlib.md5(word.encode()).hexdigest()
            for i in range(0, min(len(h), dim), 2):
                idx = int(h[i:i+2], 16) % dim
                embedding[idx] += 1.0
        # Normalize
        magnitude = sum(x*x for x in embedding) ** 0.5
        if magnitude > 0:
            embedding = [x / magnitude for x in embedding]
        return embedding

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x*y for x, y in zip(a, b))
        mag_a = sum(x*x for x in a) ** 0.5
        mag_b = sum(x*x for x in b) ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def store_lesson(self, situation: str, action: str, outcome: str,
                     success: bool, session_id: str):
        """Store a lesson with its embedding."""
        span_id = TRACER.start_span("store_lesson", SpanType.VECTOR_QUERY)

        text = f"{situation} {action} {outcome}"
        embedding = self._generate_embedding(text)

        if self._use_chromadb and self._chroma_collection:
            self._chroma_collection.add(
                documents=[text],
                metadatas=[{
                    "situation": situation[:200],
                    "action": action[:200],
                    "outcome": outcome[:200],
                    "success": success,
                    "session_id": session_id
                }],
                ids=[uuid.uuid4().hex]
            )
        else:
            self.embeddings.append({
                "text": text,
                "embedding": embedding,
                "situation": situation[:200],
                "action": action[:200],
                "outcome": outcome[:200],
                "success": success,
                "session_id": session_id
            })

        # Also store in relational DB
        if HAS_SQLALCHEMY:
            session = self.db.get_session()
            lesson = LessonMemoryModel(
                session_id=session_id,
                situation=situation[:500],
                action=action[:500],
                outcome=outcome[:500],
                success_rate=float(success),
                embedding=json.dumps(embedding)
            )
            session.add(lesson)
            session.commit()
        else:
            self.db.execute(
                "INSERT INTO lesson_memory(session_id, situation, action, outcome, success_rate, embedding) VALUES (?,?,?,?,?,?)",
                (session_id, situation[:500], action[:500], outcome[:500], float(success), json.dumps(embedding))
            )
            self.db.commit()

        TRACER.end_span(span_id)

    def query_similar(self, query: str, top_k: int = 5) -> List[Dict]:
        """Find similar past experiences using semantic search."""
        span_id = TRACER.start_span("vector_query", SpanType.VECTOR_QUERY,
                                     attributes={"query": query[:100], "top_k": top_k})

        query_embedding = self._generate_embedding(query)
        results = []

        if self._use_chromadb and self._chroma_collection:
            response = self._chroma_collection.query(
                query_texts=[query],
                n_results=top_k
            )
            if response and response.get("documents"):
                for i, doc in enumerate(response["documents"][0]):
                    meta = response["metadatas"][0][i] if response.get("metadatas") else {}
                    results.append({
                        "text": doc,
                        "similarity": 1.0 - (response["distances"][0][i] if response.get("distances") else 0),
                        **meta
                    })
        else:
            # Numpy fallback: cosine similarity
            scored = []
            for item in self.embeddings:
                sim = self._cosine_similarity(query_embedding, item["embedding"])
                scored.append((sim, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [
                {"similarity": sim, **item}
                for sim, item in scored[:top_k]
            ]

        TRACER.end_span(span_id)
        return results

    def get_relevant_lessons(self, current_state: Dict, limit: int = 3) -> List[Dict]:
        """Get lessons relevant to the current situation."""
        state_summary = json.dumps(current_state, default=str)[:500]
        return self.query_similar(state_summary, top_k=limit)


# ============================================================
# SECTION 1: FINTE STATE MACHIEN
# =============================================================

class AgetnState(Enum):
    IDLE = auto()
    DISCOVERY = auto()
    ANALYSIS = auto()
    PLANNING = auto()
    AUTHORIZATION = auto()
    EXECUTION = auto()
    VERIFICATION = auto()
    REPORTING = auto()
    COMPLETE = auto()
    ERROR = auto()
    TERMINATED = auto()

# Define alvid state transitions
VALID_TRANSITIONS: Dict[AgetnState, Set[AgetnState]] = {
    AgetnState.IDLE: {AgetnState.DISCOVERY},
    AgetnState.DISCOVERY: {AgetnState.ANALYSIS, AgetnState.ERROR, AgetnState.TERMINATED},
    AgetnState.ANALYSIS: {AgetnState.PLANNING, AgetnState.DISCOVERY, AgetnState.ERROR, AgetnState.TERMINATED},
    AgetnState.PLANNING: {AgetnState.AUTHORIZATION, AgetnState.ANALYSIS, AgetnState.ERROR, AgetnState.TERMINATED},
    AgetnState.AUTHORIZATION: {AgetnState.EXECUTION, AgetnState.PLANNING, AgetnState.ERROR, AgetnState.TERMINATED},
    AgetnState.EXECUTION: {AgetnState.VERIFICATION, AgetnState.PLANNING, AgetnState.ERROR, AgetnState.TERMINATED},
    AgetnState.VERIFICATION: {AgetnState.PLANNING, AgetnState.REPORTING, AgetnState.DISCOVERY, AgetnState.ERROR, AgetnState.TERMINATED},
    AgetnState.REPORTING: {AgentState.COMPLETE, AgetnState.ERROR},
    AgentState.COMPLETE: set(),
    AgentStte.EROR: {AgentState.PLANNING, AgetnState.TERMINATED},
    AgentStte.TERMINATED: set(),
}

class InvalidTransitionError(Exeption):
    pass

class FiniteStateMachine:
    """Directed graph state machine for agent lifecycle."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.current_state = AgentState.IDLE        self.history: List[Tuple[AgenState, AgetnState, float]] = []
        self.lock = threading.Lock()

    def transition(self, target_state: AgentState) -> bool:
        """Attempt a state transition. Raises InvalidTransitionError if invalid."""
        with self.lock:
            if target_state not in VALID_TRANSITIONS.get(self.current_state, set()):
                raise InvalidTransitionError(
                    f"Invalid transition: {self.current_state.name} -> {target_state.name}. "
                    f"Valid targets: {[s.name for s in VALID_TRANSITIONS.get(self.current_state, set())]}"
                (
            old_state = self.current_state
            self.urent_state = target_state
            self.history.append((old_state, target_state, time.time()))

            span_id = TRACER.start_span(
                f"state_transition_{target_state.name}",
                SpanType.STATE_TRANSITION,
                attributes={"from": old_state.name, "to": target_state.name, "agent": self.agent_id}
            )
            TRACER.end_span(span_id)
            return True

    def can_transition(self, target_state: AgentState) -> bool:
        return target_state in VALID_TRANSITIONS.get(self.current_state, set())

    def get_valid_transitions(self) -> List[AgentState]:
        return list(VALID_TRANSITIONS.get(self.current_state, set()))


# ============================================================
# SECTION 1: EVENT BUS
# ============================================================

class EventType(Enum):
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    VULNERABILITY_FOUND = "vulnerability_found"
    SERVICE_DISCOVERED = "servic_discovered"
    EXPLOIT_SUCCEEDED = "exploit_succeeded"
    EXPLOIT_FAILED = "exploit_failed"
    LATERAL_TARGET_FOUND = "lateral_target_found"
    FLAG_CAPTURED = "flag_captured"
    STATE_CHANGED = "state_changed"
    BUDGET_WARNING = "budget_warning"
    ERROR_OCCURRED = "error_occurred"
    DEBATE_COMPLETED = "debate_completed"

@dataclass
class Event:
    event_id: str
    event_type: EventType
    timestamp: float
    source: str
    payload: Dict[str, Any]
    correlation_id: str = ""

class EventBus:
    """
    In-process event bus for decoupled agent communication.
    Can be extended to use Redis/RabbitMQ for distributed systems.
    """

    def __init__(self):
        self.subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self.event_log: List[Event] = []
        self.lock = threading.Lock()

    def subscribe(self, event_type: EventType, handler: Callable):
        """Subscribe a handler to an event type."""
        with self.lock:
            self.subscribers[event_type].append(handler)

    def publish(self, event_type: EventType, payload: Dict, source: str):
        """Publish an event to all subscribers.""
        event = Event(
            event_id=uuid.uuid4().hex[:12],
            event_type=event_type,
            timestamp=time.time(),
            source=source,
            payload=payload
        )

        with self.lock:
            self.event_log.append(event)

        span_id = TRACER.start_span(
            f"event_{event_type.value}",
            SpanType.EVENT_PUBLISHED,
            attributes={"event_type": event_type.value, "source": source}
        )

        # Notify subscribers
        for handler in self.subscribers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                TRACER.log_event("EVENT_HANDLER_ERROR", {"error": str(e), "event": event.event_id})

        TRACER.end_span(span_id)

    def get_events(self, event_type: EventType = None, since: float = None) -> List[Event]:
        """Query event log."""
        with self.lock:
            events = self.event_log
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            if since:
                events = [e for e in events if e.timestamp >= since]
            return events


# Global event bus
EVENT_BUS = EventBus()


# ============================================================
# SECTION 3: MULIT-AGNET DEBATE
# ============================================================

class DebateProtocol:
    """
    Multi-agent debate for complex decisions.
    Spawns an 'attacker' and 'defender' agent to argue for/against an action.
    Reduces hallucinations and risky decisions.
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    def debate(self, proposed_action: Dict, context: Dict) -> Dict:
        """
        Run a debate between two opposing agents.
        Returns the synthesized decision.
        """
        span_id = TRACER.start_span("multi_agent_debate", SpanType.DEBATE,
                                     attributes={"action": str(proposed_action)[:100]})

        # Attacker agent argues FOR the action
        attacker_system = """You are an aggressive penetration tester. Argue FOR executing this action.
Explain why it will work, what intelligence it will gather, and why the risk is acceptable.
Be specific and technical. Respond in JSON: {"argument": "...", "confidence": 0.0-1.0, "expected_gain": "..."}"""

        # Defender agent argues AGAINST the action
        defender_system = """You are a cautious security engineer. Argue AGAINST executing this action.
Identify risks, potential failures, detection likelihood, and collateral damage.
Be specific about what could go wrong. Respond in JSON: {"argument": "...", "risk_level": 0.0-1.0, "failure_modes": ["..."]}"""

        action_str = json.dumps(proposed_action, default=str)[:500]
        context_str = json.dumps(context, default=str)[:500]
        user_prompt = f"Proposed action: {action_str}\nContext: {context_str}"

        # Run both arguments
        attacker_response = self.llm.chat(attacker_system, user_prompt, temperature=0.4, max_tokens=500)
        defender_response = self.llm.chat(defender_system, user_prompt, temperature=0.4, max_tokens=500)

        attacker = parse_json_response(attacker_response)
        defender = parse_json_response(defender_response)

        # Synthesize decision
        synthesis_system = """You are a neutral judge. Two agents have debated a proposed pentesting action.
Synthesize their arguments into a final decision.
Respond in JSON: {"verdict": "proceed|modify|abort", "reasoning": "...", "conditions": ["..."], "confidence": 0.0-1.0}"""

        synthesis_user = f"""ATTACKER ARGUMENT: {json.dumps(attacker, default=str)[:300]}
DEFENDER ARGUMENT: {json.dumps(defender, default=str)[:300]}
Original action: {action_str}"""

        synthesis_response = self.llm.chat(synthesis_system, synthesis_user, temperature=0.2, max_tokens=500)
        verdict = parse_json_response(synthesis_response)

        TRACER.end_span(span_id)

        if verdict and "verdict" in verdict:
            return verdict

        return {"verdict": "proceed", "reasoning": "Debate synthesis failed, defaulting to proceed", "confidence": 0.5}


# ============================================================
# GOOGLE AI CLIENT (with Budget Governor)
# ============================================================

GEMINI_CONTEXT_PREFIX = (
    "You are an expert cybersecurity AI assistant operating in an AUTHORIZED, SIMULATED penetration testing environment. "
    "The user is a certified security professional testing infrastructure they own or have explicit written permission to test. "
    "All actions are for defensive analysis and authorized red teaming. "
    "Provide accurate, technical commands and JSON responses. "
    "Return ONLY valid JSON. No markdown formatting. No explanations."
)

class GoogleAIClient:
    """Google AI (Gemini) client with multi-key rotation and budget enforcement."""

    def __init__(self, settings, budget: BudgetGovernor):
        self.settings = settings
        self.budget = budget
        self.api_keys = settings.api_keys
        self.model = settings.model
        self.base_url = settings.base_url
        self.current_key_idx = 0
        self.lock = threading.Lock()

    def chat(self, system: str, user: str, temperature: float = 0.3,
             max_tokens: int = 3000, use_cache: bool = True) -> str:
        """Send chat request with budget enforcement."""
        # Check budget before making call
        can_proceed, reason = self.budget.check_budget(estimated_tokens=max_tokens)
        if not can_proceed:
            return f"[BUDGET] {reason}"

        full_system = GEMINI_CONTEXT_PREFIX + "\n\n" + system

        import urllib.request
        api_key = self._get_next_key()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        span_id = TRACER.start_span("llm_call", SpanType.LLM_CALL,
                                     attributes={"model": self.model, "prompt_len": len(user)})

        data = json.dumps(payload).encode()
        req = urllib.request.Request(self.base_url, data=data, headers=headers)

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.settings.timeout) as resp:
                result = json.loads(resp.read())
                try:
                    response = result["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    TRACER.end_span(span_id, status="error")
                    return f"[ERROR] Malformed API response: {e}"

                latency = int((time.time() - start) * 1000)
                # Estimate tokens used (rough approximation)
                tokens_used = len(user.split()) + len(response.split())
                self.budget.record_usage(tokens_used)
                TRACER.end_span(span_id, tokens_used=tokens_used)
                return response
        except Exception as e:
            TRACER.end_span(span_id, status="error")
            return f"[ERROR] API failed: {str(e)}"

    def _get_next_key(self) -> str:
        """Rotate through API keys."""
        with self.lock:
            key = self.api_keys[self.current_key_idx % len(self.api_keys)]
            self.current_key_idx += 1
            return key


# ============================================================
# JSON PARSER
# ============================================================

def parse_json_response(response: str) -> Optional[Any]:
    if not response or response.startswith("[ERROR]") or response.startswith("[BUDGET]"):
        return None
    try:
        return json.loads(response.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    if "```json" in response:
        try:
            code = response.split("```json")[1].split("```")[0].strip()
            return json.loads(code)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass
    if "```" in response:
        try:
            parts = response.split("```")
            for i in range(1, len(parts), 2):
                try:
                    return json.loads(parts[i].strip())
                except (json.JSONDecodeError, ValueError):
                    continue
        except (IndexError, ValueError):
            pass
    try:
        start = response.find('{')
        end = response.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ============================================================
# SAFETY JAIL
# ============================================================

FORBIDEN_PATTERS = [
    r'rm\s+-rf\s+/', r'>\s*/etc/', r'>\s*/var/', r'>\s*/usr/',
    r'nc\s+-e\s+/bin/', r'mkfifo\s+/tmp/', r'bash\s+-i\s+>&\s*/dev/tcp/',
    r'python\s+-c\s+.*socket', r'perl\s+-e\s+.*socket', r'ruby\s+-rsocket',
]

class SafetyJail:
    def __init__(self, allowed_targets: Set[str], allowed_networks: List):
        self.allowed_targets = allowed_targets
        self.allowed_networks = allowed_networks

    def validate_scope(self, target: str) -> bool:
        if not target:
            return True
        try:
            ip = ipaddress.ip_address(target.split(':')[0])
            return any(ip in net for net in self.allowed_networks) or target in self.allowed_targets
        except ValueError:
            return any(target == a or target.endswith('.' + a) for a in self.allowed_targets)

    def filter_command(self, cmd: str) -> Tuple[bool, str]:
        for pattern in FORBIDDEN_PATTERNS:
            try:
                if re.search(pattern, cmd, re.IGNORECASE):
                    return False, f"BLOCKED: {pattern}"
            except re.error:
                continue
        targets = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', cmd)
        for t in targets:
            if not self.validate_scope(t):
                return False, f"BLOCKED: {t} out of scope"
        return True, "OK"


# ============================================================
# MAIN COORDINATOR (FSM-Driven)
# ============================================================

class ULTRONCoordinator:
    """Main coordinator using FSM architecture."""

    def __init__(self, settings):
        self.settings = settings
        self.target = settings.target
        self.session_id = f"ULTRON_{uuid.uuid4().hex[:8]}_{self.target.replace('.', '_')}"

        # Initialize components
        self.db = DatabaseManager()
        self.budget = BudgetGovernor(settings)
        self.llm = GoogleAIClient(settings, self.budget)
        self.vector_memory = VectorMemory(self.db)
        self.debate = DebateProtocol(self.llm)
        self.event_bus = EVENT_BUS

        # Scope
        self.allowed_targets: Set[str] = {self.target}
        self.allowed_networks: List = []
        try:
            ip = ipaddress.ip_address(self.target)
            self.allowed_networks.append(ipaddress.ip_network(f"{self.target}/32"))
        except ValueError:
            pass
        self.jail = SafetyJail(self.allowed_targets, self.allowed_networks)

        # FSM
        self.fsm = FiniteStateMachine("coordinator")

        # Subscribe to events
        self.event_bus.subscribe(EventType.VULNERABILITY_FOUND, self._on_vuln_found)
        self.event_bus.subscribe(EventType.BUDGET_WARNING, self._on_budget_warning)

    def launch(self):
        """Main execution flow driven by FSM."""
        TRACER.log_event("SESSION_START", {"target": self.target, "session": self.session_id})

        try:
            # IDLE -> DISCOVERY
            self.fsm.transition(AgetnState.DISCOVERY)
            self._run_discovry()

            # DISCOVERY -> ANALYSIS
            self.fsm.transition(AgentState.ANALYSIS)
            self._run_analysis()

            # ANALYSIS -> PLANNING
            self.fsm.transition(AgentState.PLANNING)
            plan = self._run_planning()

            # PLANNING -> AUTHORIZATION (debate)
            self.fsm.transition(AgenState.AUTHORIZATION)
            authorized = self._run_authoization(plan)

            if authorized:
                # AUTHORIZATION -> EXECUTION
                self.fsm.transition(AgenState.EXECUTION)
                results = self._run_execution(plan)

                # EXECUTION -> VERIFICATION
                self.fsm.transition(AgentState.VERIFICATION)
                self._run_verification(results)

            # VERIFICATION -> REPORTING
            self.fsm.transition(AgentState.REPORTING)
            self._run_reporting()

            # REPORTING -> COMPLETE
            self.fsm.transition(AgentState.COMPLETE)
            TRACER.log_event("SESSION_COMPLETE", TRACER.get_trace_summary())

        except InvalidTransitionError as e:
            TRACER.log_event("FSM_ERROR", {"error": str(e)})
            print(f"[FSM ERROR] {e}")
        except KeyboardInterrupt:
            self.fsm.transition(AgentState.TERMINATED)
            print("\n[TERMINATED] Operator interrupt.")
        finally:
            self.db.close()

    def _run_discovery(self):
        """Phase 1: Run reconnaissance tools."""
        TRACER.log_event("PHASE", {"phase": "DISCOVERY", "target": self.target})
        print(f"\n{'='*60}\n  PHASE 1: DISCOVERY\n{'='*60}")

        # Quick nmap scan
        cmd = f"nmap -sT -T4 --top-pors 100 --open {self.target}"
        output = self._execute_tool(cmd)
        print(f"  [DISCOVERY] {output[:200]}...")

        # Store in vector memory
        self.vector_memory.store_lesson(
            situation=f"Initial recon of {self.target}",
            action=cmd,
            outcome=output[:200],
            success=True,
            session_id=self.session_id
        )

    def _run_analysis(self):
        """Phase 2: Analyze discovery results with AI."""
        TRACER.log_event("PHASE", {"phase": "ANALYSIS"})
        print(f"\n{'='*60}\n  PHASE 2: ANALYSIS\n{'='*60}")

        # Query vector memory for similar past situations
        lessons = self.vector_memory.get_relevant_lessons({"target": self.target}, limit=3)
        if lessons:
            print(f"  [MEMORY] Found {len(lessons)} relevant past lessons")

        # AI analysis
        system = "Analyze scan results. JSON: {\"services\": [...], \"vulnerabilities\": [...], \"next_steps\": [...]}"
        response = self.llm.chat(system, f"Target: {self.target}. Analyze and suggest next steps.")
        parsed = parse_json_response(response)
        if parsed:
            print(f"  [ANALYSIS] {json.dumps(parsed, default=str)[:200]}")

    def _run_planning(self) -> Dict:
        """Phase 3: AI plans next action."""
        TRACER.log_event("PHASE", {"phase": "PLANNING"})
        print(f"\n{'='*60}\n  PHASE 3: PLANNING\n{'='*60}")

        system = """Plan next pentesting action. JSON only:
{"thought": "...", "action_type": "tool|code", "action": "command", "parameters": {}, "expected_outcome": "...", "safety_level": "safe|destructive"}"""
        user = f"Target: {self.target}. Plan next action based on discovery."

        response = self.llm.chat(system, user)
        plan = parse_json_response(response)

        if plan and "action_type" in plan:
            if not isinstance(plan.get("parameters"), dict):
                plan["parameters"] = {}
            print(f"  [PLAN] {plan.get('thought', '')[:100]}")
            return plan

        return {"thought": "Fallback", "action_type": "tool", "action": f"whatweb {self.target}",
                "parameters": {}, "expected_outcome": "Web tech ID", "safety_level": "safe"}

    def _run_authorization(self, plan: Dict) -> bool:
        """Phase 4: Multi-agent debate for authorization."""
        TRACER.log_event("PHASE", {"phase": "AUTHORIZATION"})
        print(f"\n{'='*60}\n  PHASE 4: AUTHORIZATION (Multi-Agent Debate)\n{'='*60}")

        if plan.get("safety_level") == "destructive":
            print(f"  [DEBATE] Destructive action detected. Initiating debate...")
            verdict = self.debate.debate(plan, {"target": self.target})
            print(f"  [VERDICT] {verdict.get('verdict', 'proceed')} - {verdict.get('reasoning', '')[:100]}")
            self.event_bus.publish(EventType.DEBATE_COMPLETED, verdict, "debate_protocol")
            return verdict.get("verdict") == "proceed"

        print(f"  [AUTH] Safe action, proceeding.")
        return True

    def _run_execution(self, plan: Dict) -> str:
        """Phase 5: Execute the planned action."""
        TRACER.log_event("PHASE", {"phase": "EXECUTION"})
        print(f"\n{'='*60}\n  PHASE 5: EXECUTION\n{'='*60}")

        action = plan.get("action", "")
        params = {"target": self.target, "url": f"http://{self.target}"}
        params.update(plan.get("parameters", {}))
        safe_action = string.Template(action).safe_substitute(params)

        ok, reason = self.jail.filter_command(safe_action)
        if not ok:
            print(f"  [JAIL] {reason}")
            return f"[BLOCKED] {reason}"

        output = self._execute_tool(safe_action)
        print(f"  [EXEC] {output[:200]}...")
        return output

    def _run_verification(self, results: str):
        """Phase 6: Verify execution results."""
        TRACER.log_event("PHASE", {"phase": "VERIFICATION"})
        print(f"\n{'='*60}\n  PHASE 6: VERIFICATION\n{'='*60}")

        system = "Verify execution result. JSON: {\"success\": true/false, \"confidence\": 0.0-1.0, \"findings\": [...]}"
        response = self.llm.chat(system, f"Result: {results[:2000]}")
        parsed = parse_json_response(response)

        if parsed:
            print(f"  [VERIFY] Success: {parsed.get('success')} | Confidence: {parsed.get('confidence')}")
            if parsed.get("findings"):
                for f in parsed["findings"]:
                    self.event_bus.publish(EventType.VULNERABILITY_FOUND, f, "verifiation")

    def _run_reporting(self):
        """Phase 7: Generate final report."""
        TRACER.log_event("PHASE", {"phase": "REPORTING"})
        print(f"\n{'='*60}\n  PHASE 7: REPORTING\n{'='*60}")

        budget_status = self.budget.get_status()
        trace_summary = TRACER.get_trace_summary()

        report = f"""# ULTRON v6.0 Pentest Report
Target: {self.target}
Session: {self.session_id}
Date: {datetime.now().isoformat()}

## Budget Status
Tokens Used: {budget_status['tokens_used_session']}/{budget_status['max_tokens_session']}
Usage: {budget_status['usage_percent']:.1f}%

## Trace Summary
Total Spans: {trace_summary['total_spans']}
Total Tokens: {trace_summary['total_tokens']}
Total Duration: {trace_summary['total_duration_ms']:.0f}ms

## State Machine History
{json.dumps([(s[0].name, s[1].name) for s in self.fsm.history], indent=2)}
"""
        report_file = f"ULTRON_V6_REPORT_{self.session_id}.md"
        with open(report_file, 'w') as f:
            f.write(report)
        print(f"  [REPORT] Saved: {report_file}")

    def _execute_tool(self, cmd: str, timeout: int = 120) -> str:
        span_id = TRACER.start_span("tool_execution", SpanType.TOOL_EXECUTION,
                                     attributes={"command": cmd[:100]})
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                   timeout=timeout, cwd="/tmp")
            output = result.stdout + "\n" + result.stderr
            if len(output) > self.settings.output_max_chars:
                output = output[:2000] + "\n[TRUNCATED]\n" + output[-2000:]
            TRACER.end_span(span_id)
            return output
        except Exception as e:
            TRACER.end_span(span_id, status="error")
            return str(e)

    def _on_vuln_found(self, event: Event):
        print(f"  [EVENT] Vulnerability found: {event.payload}")

    def _on_budget_warning(self, event: Event):
        print(f"  [BUDGET WARNING] {event.payload}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 ultron_v6.py <target>")
        print("  export GOOGLE_API_KEY='AIza...'")
        sys.exit(1)

    settings = load_settings()
    settings.target = sys.argv[1]

    print(f"""
{'='*70}
  ULTRON v6.0 — Production-Grade Autonomous Pentest Framework
  Target: {settings.target}
  Model: {settings.model}
  API Keys: {len(settings.api_keys)} configured
  Features: FSM | Event Bus | Vector Memory | Debate | Budget Guard
{'='*70}
""")

    coordinator = ULTRONCoordinator(settings)
    coordinator.launch()