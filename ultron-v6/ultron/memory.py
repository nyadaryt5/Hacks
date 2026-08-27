"""Vector memory: semantic search over past lessons.

Uses ChromaDB when installed; otherwise falls back to a dependency-free
128-dimension hash-based embedding with cosine similarity, so memory always
works. Lessons are persisted in both the vector store and the relational
database.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from ultron.db import HAS_SQLALCHEMY

if HAS_SQLALCHEMY:  # pragma: no branch
    from ultron.db import LessonMemoryModel  # noqa: F401
from ultron.tracing import TRACER, SpanType

_LOGGER = logging.getLogger(__name__)


class VectorMemory:
    """Vector database for semantic memory."""

    def __init__(self, db_manager: Any, backend: str = "auto"):
        self.db = db_manager
        self.embeddings: list[dict[str, Any]] = []  # In-memory store
        self._use_chromadb = False
        self._chroma_collection: Any | None = None
        if backend not in ("auto", "chroma", "hash"):
            raise ValueError(
                f"Unknown backend {backend!r}; expected auto, chroma or hash"
            )
        self._backend = backend
        self._init_backend()

    def _init_backend(self) -> None:
        """Try to initialize ChromaDB, fall back to hash embeddings."""
        if self._backend == "hash":
            TRACER.log_event("VECTOR_DB_INIT", {"backend": "hash_fallback"})
            return
        try:
            import chromadb  # noqa: PLC0415 (optional dependency)
            from chromadb.config import Settings  # noqa: PLC0415

            self._chroma_client = chromadb.Client(
                Settings(anonymized_telemetry=False)
            )
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name="ultron_lessons",
                metadata={"description": "Pentesting lessons learned"},
            )
            self._use_chromadb = True
            TRACER.log_event("VECTOR_DB_INIT", {"backend": "chromadb"})
        except Exception as exc:  # noqa: BLE001 (optional native dependency)
            if self._backend == "chroma":
                raise RuntimeError(
                    "Chroma initialization failed "
                    f"({type(exc).__name__}); use backend='hash' or repair the "
                    "constrained Chroma installation"
                ) from None
            _LOGGER.warning(
                "Chroma unavailable (%s); using the local hash backend",
                type(exc).__name__,
            )
            TRACER.log_event("VECTOR_DB_INIT", {"backend": "hash_fallback"})

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate a simple hash-based embedding (128 dimensions)."""
        dim = 128
        embedding = [0.0] * dim
        words = text.lower().split()
        for word in words:
            digest = hashlib.md5(
                word.encode(), usedforsecurity=False
            ).hexdigest()
            for i in range(0, min(len(digest), dim), 2):
                idx = int(digest[i:i + 2], 16) % dim
                embedding[idx] += 1.0
        magnitude = sum(x * x for x in embedding) ** 0.5
        if magnitude > 0:
            embedding = [x / magnitude for x in embedding]
        return embedding

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        mag_a = sum(x * x for x in a) ** 0.5
        mag_b = sum(x * x for x in b) ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return float(dot / (mag_a * mag_b))

    def store_lesson(
        self,
        situation: str,
        action: str,
        outcome: str,
        success: bool,
        session_id: str,
    ) -> None:
        """Store a lesson with its embedding."""
        span_id = TRACER.start_span("store_lesson", SpanType.VECTOR_QUERY)

        text = f"{situation} {action} {outcome}"
        embedding = self._generate_embedding(text)

        if self._use_chromadb and self._chroma_collection:
            # Supply ULTRON's deterministic local embedding explicitly. Letting
            # Chroma apply its default function would download an ONNX model at
            # runtime, violating the offline execution boundary.
            self._chroma_collection.add(
                documents=[text],
                embeddings=[embedding],
                metadatas=[
                    {
                        "situation": situation[:200],
                        "action": action[:200],
                        "outcome": outcome[:200],
                        "success": success,
                        "session_id": session_id,
                    }
                ],
                ids=[uuid.uuid4().hex],
            )
        else:
            self.embeddings.append(
                {
                    "text": text,
                    "embedding": embedding,
                    "situation": situation[:200],
                    "action": action[:200],
                    "outcome": outcome[:200],
                    "success": success,
                    "session_id": session_id,
                }
            )

        # Also store in relational DB
        if HAS_SQLALCHEMY:
            session = self.db.get_session()
            lesson = LessonMemoryModel(
                session_id=session_id,
                situation=situation[:500],
                action=action[:500],
                outcome=outcome[:500],
                success_rate=float(success),
                embedding=json.dumps(embedding),
            )
            session.add(lesson)
            session.commit()
        else:
            self.db.execute(
                "INSERT INTO lesson_memory(session_id, situation, action, "
                "outcome, success_rate, embedding) VALUES (?,?,?,?,?,?)",
                (
                    session_id,
                    situation[:500],
                    action[:500],
                    outcome[:500],
                    float(success),
                    json.dumps(embedding),
                ),
            )
            self.db.commit()

        TRACER.end_span(span_id)

    def query_similar(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Find similar past experiences using semantic search."""
        span_id = TRACER.start_span(
            "vector_query",
            SpanType.VECTOR_QUERY,
            attributes={"query": query[:100], "top_k": top_k},
        )

        query_embedding = self._generate_embedding(query)
        results: list[dict[str, Any]] = []

        if self._use_chromadb and self._chroma_collection:
            response = self._chroma_collection.query(
                query_embeddings=[query_embedding], n_results=top_k
            )
            if response and response.get("documents"):
                for i, doc in enumerate(response["documents"][0]):
                    meta = (
                        response["metadatas"][0][i]
                        if response.get("metadatas")
                        else {}
                    )
                    distance = (
                        response["distances"][0][i]
                        if response.get("distances")
                        else 0
                    )
                    results.append(
                        {"text": doc, "similarity": 1.0 - distance, **meta}
                    )
        else:
            scored = []
            for item in self.embeddings:
                sim = self._cosine_similarity(
                    query_embedding, item["embedding"]
                )
                scored.append((sim, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [
                {"similarity": sim, **item} for sim, item in scored[:top_k]
            ]

        TRACER.end_span(span_id)
        return results

    def get_relevant_lessons(
        self, current_state: dict[str, Any], limit: int = 3
    ) -> list[dict[str, Any]]:
        """Get lessons relevant to the current situation."""
        state_summary = json.dumps(current_state, default=str)[:500]
        return self.query_similar(state_summary, top_k=limit)


__all__ = ["VectorMemory"]
