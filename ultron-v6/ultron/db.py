"""Persistence layer: SQLAlchemy ORM models with a raw-SQLite fallback.

When SQLAlchemy is installed, ``DatabaseManager`` is the ORM-backed manager
and the declarative models (:class:`EpisodeModel`, :class:`FindingModel`,
:class:`LessonMemoryModel`, ...) are available. When it is not, the
stdlib-only :class:`SQLiteDatabaseManager` provides the same tables, so the
framework never hard-fails on a missing optional dependency.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Any, Tuple

try:  # pragma: no cover - exercised via both paths in tests
    from sqlalchemy import (  # type: ignore[import-untyped]
        Boolean,
        Column,
        DateTime,
        Float,
        Integer,
        String,
        Text,
        create_engine,
    )
    from sqlalchemy.orm import (  # type: ignore[import-untyped]
        Session,
        declarative_base,
        sessionmaker,
    )

    HAS_SQLALCHEMY = True
    Base = declarative_base()
except ImportError:  # pragma: no cover - exercised via both paths in tests
    HAS_SQLALCHEMY = False
    Base = None  # type: ignore[assignment]


if HAS_SQLALCHEMY:

    class EpisodeModel(Base):  # type: ignore[misc, valid-type]
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

    class TargetStateModel(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "target_state"

        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        agent = Column(String)
        entity = Column(String)
        entity_type = Column(String)
        attributes = Column(Text)
        confidence = Column(Float)

    class GoalModel(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "goals"

        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        agent = Column(String)
        goal = Column(Text)
        status = Column(String, default="pending")
        priority = Column(Integer, default=5)

    class FindingModel(Base):  # type: ignore[misc, valid-type]
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

    class LateralTargetModel(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "lateral_targets"

        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String, index=True)
        discovered_by = Column(String)
        target = Column(String)
        source_evidence = Column(Text)
        approved = Column(Boolean, default=False)

    class LessonMemoryModel(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "lesson_memory"

        id = Column(Integer, primary_key=True, autoincrement=True)
        session_id = Column(String)
        situation = Column(Text)
        action = Column(Text)
        outcome = Column(Text)
        success_rate = Column(Float)
        usage_count = Column(Integer, default=1)
        embedding = Column(Text)  # JSON-encoded vector

    class SQLAlchemyDatabaseManager:
        """SQLAlchemy-based database manager."""

        def __init__(self, db_url: str = "sqlite:///ultron_v6.db"):
            self.engine = create_engine(db_url, echo=False)
            Base.metadata.create_all(self.engine)
            self.SessionFactory = sessionmaker(bind=self.engine)
            self._local = threading.local()

        def get_session(self) -> Session:
            if not hasattr(self._local, "session"):
                self._local.session = self.SessionFactory()
            return self._local.session

        def close(self) -> None:
            if hasattr(self._local, "session"):
                self._local.session.close()


class SQLiteDatabaseManager:
    """Fallback: Raw SQLite database manager (always available, stdlib only)."""

    _SCHEMA = """
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
    """

    TABLES = (
        "episodes",
        "target_state",
        "goals",
        "findings",
        "lateral_targets",
        "lesson_memory",
    )

    def __init__(self, db_path: str = "ultron_v6.db"):
        self.path = db_path
        self.lock = threading.Lock()
        self._local = threading.local()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(
                self.path, check_same_thread=False
            )
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(self._SCHEMA)
        conn.commit()

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> Any:
        with self.lock:
            return self._get_conn().execute(sql, params)

    def commit(self) -> None:
        with self.lock:
            self._get_conn().commit()

    def close(self) -> None:
        if hasattr(self._local, "conn"):
            self._local.conn.close()


if HAS_SQLALCHEMY:
    DatabaseManager = SQLAlchemyDatabaseManager
else:
    DatabaseManager = SQLiteDatabaseManager


__all__ = [
    "Base",
    "DatabaseManager",
    "EpisodeModel",
    "FindingModel",
    "GoalModel",
    "HAS_SQLALCHEMY",
    "LateralTargetModel",
    "LessonMemoryModel",
    "SQLAlchemyDatabaseManager",
    "SQLiteDatabaseManager",
    "TargetStateModel",
]
