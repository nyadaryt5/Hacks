"""Tests for ultron.memory — hash-backend vector memory."""

import pytest

from ultron.db import DatabaseManager
from ultron.memory import VectorMemory


@pytest.fixture()
def memory(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'mem.db'}")
    mem = VectorMemory(db, backend="hash")
    yield mem
    db.close()


def test_unknown_backend_is_rejected(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'x.db'}")
    with pytest.raises(ValueError, match="Unknown backend"):
        VectorMemory(db, backend="nope")
    db.close()


def test_embedding_is_128d_and_normalized(memory):
    vec = memory._generate_embedding("hello world")
    assert len(vec) == 128
    magnitude = sum(x * x for x in vec) ** 0.5
    assert magnitude == pytest.approx(1.0, abs=1e-6)


def test_empty_text_has_zero_embedding(memory):
    assert memory._generate_embedding("") == [0.0] * 128


def test_cosine_similarity_basics(memory):
    assert memory._cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert memory._cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert memory._cosine_similarity([0, 0], [1, 1]) == 0.0


def test_store_and_query_roundtrip(memory):
    memory.store_lesson(
        situation="recon of web server",
        action="nmap -sV",
        outcome="port 443 open",
        success=True,
        session_id="s1",
    )
    assert len(memory.embeddings) == 1

    # Related query returns the stored lesson with a positive similarity.
    results = memory.query_similar("web server recon", top_k=5)
    assert len(results) == 1
    assert 0.0 < results[0]["similarity"] <= 1.0
    assert results[0]["action"] == "nmap -sV"
    assert results[0]["success"] is True


def test_exact_text_matches_itself(memory):
    memory.store_lesson(
        situation="recon", action="nmap", outcome="ports", success=True,
        session_id="s1",
    )
    results = memory.query_similar("recon nmap ports", top_k=1)
    assert results[0]["similarity"] == pytest.approx(1.0)


def test_query_ranks_most_similar_first(memory):
    memory.store_lesson(
        situation="recon", action="nmap", outcome="ports", success=True,
        session_id="s1",
    )
    memory.store_lesson(
        situation="sql injection", action="sqlmap", outcome="dump",
        success=False, session_id="s2",
    )
    results = memory.query_similar("sql injection attack", top_k=2)
    assert results[0]["action"] == "sqlmap"
    assert results[0]["similarity"] >= results[1]["similarity"]


def test_get_relevant_lessons_limits_results(memory):
    for i in range(5):
        memory.store_lesson(
            situation=f"target {i}", action=f"tool {i}", outcome="ok",
            success=True, session_id="s",
        )
    lessons = memory.get_relevant_lessons({"target": "target 0"}, limit=3)
    assert len(lessons) == 3


def test_lessons_are_persisted_to_db(memory):
    memory.store_lesson(
        situation="s", action="a", outcome="o", success=True,
        session_id="sess-1",
    )
    from ultron.db import HAS_SQLALCHEMY, LessonMemoryModel

    if HAS_SQLALCHEMY:
        session = memory.db.get_session()
        stored = session.query(LessonMemoryModel).filter_by(
            session_id="sess-1"
        ).all()
        assert len(stored) == 1
        assert stored[0].action == "a"
    else:
        cursor = memory.db.execute(
            "SELECT action FROM lesson_memory WHERE session_id=?", ("sess-1",)
        )
        assert cursor.fetchone()[0] == "a"


def test_query_empty_memory_returns_no_results(memory):
    assert memory.query_similar("anything") == []
