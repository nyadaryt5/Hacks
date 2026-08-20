"""Span-based observability for ULTRON.

OpenTelemetry-style tracing implemented on the standard library: spans are
created with :meth:`Tracer.start_span`, finished with :meth:`Tracer.end_span`,
and aggregated via :meth:`Tracer.get_trace_summary`. A module-level
:data:`TRACER` singleton is shared by all components.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


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

    def finish(self, status: str = "completed") -> None:
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
        self.logger = logging.getLogger("ultron.tracing")

    def start_span(
        self,
        name: str,
        span_type: SpanType,
        attributes: Optional[Dict[str, Any]] = None,
        parent_span_id: Optional[str] = None,
    ) -> str:
        """Start a new trace span and return its span id."""
        span_id = uuid.uuid4().hex[:12]
        trace_id = uuid.uuid4().hex[:16]

        span = Span(
            span_id=span_id,
            trace_id=trace_id,
            name=name,
            span_type=span_type,
            start_time=time.time(),
            attributes=attributes or {},
            parent_span_id=parent_span_id,
        )

        with self.lock:
            self.traces.append(span)
            self.active_spans[span_id] = span
            if parent_span_id and parent_span_id in self.active_spans:
                self.active_spans[parent_span_id].children.append(span_id)

        self.logger.info("[SPAN START] %s | %s | id=%s", span_type.name, name, span_id)
        return span_id

    def end_span(
        self,
        span_id: str,
        status: str = "completed",
        tokens_used: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """End a trace span."""
        with self.lock:
            if span_id in self.active_spans:
                span = self.active_spans[span_id]
                span.finish(status)
                span.tokens_used = tokens_used
                span.cost_usd = cost_usd
                del self.active_spans[span_id]
                self.logger.info(
                    "[SPAN END] %s | %s | %.0fms | tokens=%s",
                    span.name,
                    status,
                    span.duration_ms,
                    tokens_used,
                )

    def log_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Log a structured event."""
        self.logger.info(
            "[EVENT] %s | %s", event_type, json.dumps(data or {}, default=str)[:200]
        )

    def get_trace_summary(self) -> Dict[str, Any]:
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
                },
            }


# Global tracer instance shared by every component.
TRACER = Tracer()

__all__ = ["Span", "SpanType", "TRACER", "Tracer"]
