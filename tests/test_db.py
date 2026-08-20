"""Tests for ultron.db — both persistence backends."""

import sqlite3

import pytest

from ultron.db import (
    HAS_SQLALCHEMY,
    DatabaseManager,
    SQLAlchemyDatabaseManager,
    SQLiteDatabaseManager,
)


def test_factory_selects_backend_based_on_availability():
    if HAS_SQLALCHEMY:
        assert DatabaseManager is SQLAlchemyDatabaseManager
    else:
        assert DatabaseManager is SQLiteDatabaseManager


def test_sqlite_manager_creates_full_schema(tmp_path):
    db = SQLiteDatabaseManager(str(tmp_path / "test.db"))
    try:
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {row[0] for row in rows}
        assert SQLiteDatabaseManager.TABLES == (
            "episodes",
            "target_state",
            "goals",
            "findings",
            "lateral_targets",
            "lesson_memory",
        )
        assert tables >= set(SQLiteDatabaseManager.TABLES)
    finally:
        db.close()


def test_sqlite_manager_insert_and_query(tmp_path):
    db = SQLiteDatabaseManager(str(tmp_path / "test.db"))
    try:
        db.execute(
            "INSERT INTO lesson_memory(session_id, situation, action, "
            "outcome, success_rate) VALUES (?,?,?,?,?)",
            ("s1", "situation", "action", "outcome", 0.9),
        )
        db.commit()
        cursor = db.execute("SELECT situation, success_rate FROM lesson_memory")
        row = cursor.fetchone()
        assert row == ("situation", 0.9)
    finally:
        db.close()


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="SQLAlchemy not installed")
def test_sqlalchemy_manager_roundtrip(tmp_path):
    db = SQLAlchemyDatabaseManager(f"sqlite:///{tmp_path / 'orm.db'}")
    try:
        from ultron.db import LessonMemoryModel

        session = db.get_session()
        lesson = LessonMemoryModel(
            session_id="s1",
            situation="recon",
            action="nmap",
            outcome="open ports",
            success_rate=1.0,
            embedding="[0.1, 0.2]",
        )
        session.add(lesson)
        session.commit()

        stored = session.query(LessonMemoryModel).first()
        assert stored.situation == "recon"
        assert stored.embedding == "[0.1, 0.2]"
    finally:
        db.close()


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="SQLAlchemy not installed")
def test_sqlalchemy_manager_creates_all_tables(tmp_path):
    from sqlalchemy import inspect

    db = SQLAlchemyDatabaseManager(f"sqlite:///{tmp_path / 'orm.db'}")
    try:
        names = set(inspect(db.engine).get_table_names())
        assert names >= {
            "episodes",
            "target_state",
            "goals",
            "findings",
            "lateral_targets",
            "lesson_memory",
        }
    finally:
        db.close()


def test_sqlite_fallback_without_sqlalchemy():
    """Without SQLAlchemy, DatabaseManager must be the stdlib backend."""
    import subprocess
    import sys

    script = """
import sys
sys.path.insert(0, "ultron-v6")
sys.modules["sqlalchemy"] = None

import ultron_v6

assert ultron_v6.HAS_SQLALCHEMY is False
assert ultron_v6.DatabaseManager is ultron_v6.SQLiteDatabaseManager
db = ultron_v6.DatabaseManager(":memory:")
db.execute("INSERT INTO findings(session_id, title) VALUES (?,?)", ("s", "t"))
db.commit()
print("SQLITE-FALLBACK-OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "SQLITE-FALLBACK-OK" in result.stdout
