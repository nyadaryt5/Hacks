"""In-process event bus for decoupled component communication.

The bus supports typed subscribe/publish with an append-only event log and
query helpers. Handler exceptions are isolated so one faulty subscriber can
never break publication. Extensible to Redis/RabbitMQ for distributed setups.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ultron.tracing import TRACER, SpanType


class EventType(Enum):
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    VULNERABILITY_FOUND = "vulnerability_found"
    SERVICE_DISCOVERED = "service_discovered"
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
    payload: dict[str, Any]
    correlation_id: str = field(default="")


class EventBus:
    """In-process event bus for decoupled agent communication."""

    def __init__(self) -> None:
        self.subscribers: dict[EventType, list[Callable[[Event], None]]] = (
            defaultdict(list)
        )
        self.event_log: list[Event] = []
        self.lock = threading.Lock()

    def subscribe(
        self, event_type: EventType, handler: Callable[[Event], None]
    ) -> None:
        """Subscribe a handler to an event type."""
        with self.lock:
            self.subscribers[event_type].append(handler)

    def publish(
        self, event_type: EventType, payload: dict[str, Any], source: str
    ) -> Event:
        """Publish an event to all subscribers."""
        event = Event(
            event_id=uuid.uuid4().hex[:12],
            event_type=event_type,
            timestamp=time.time(),
            source=source,
            payload=payload,
        )

        with self.lock:
            self.event_log.append(event)

        span_id = TRACER.start_span(
            f"event_{event_type.value}",
            SpanType.EVENT_PUBLISHED,
            attributes={"event_type": event_type.value, "source": source},
        )

        for handler in list(self.subscribers.get(event_type, [])):
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 (isolate handler failures)
                TRACER.log_event(
                    "EVENT_HANDLER_ERROR",
                    {"error": str(exc), "event": event.event_id},
                )

        TRACER.end_span(span_id)
        return event

    def get_events(
        self,
        event_type: EventType | None = None,
        since: float | None = None,
    ) -> list[Event]:
        """Query event log."""
        with self.lock:
            events = self.event_log
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            if since:
                events = [e for e in events if e.timestamp >= since]
            return list(events)


# Global event bus shared by all components.
EVENT_BUS = EventBus()

__all__ = ["EVENT_BUS", "Event", "EventBus", "EventType"]
