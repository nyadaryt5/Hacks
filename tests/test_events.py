"""Tests for ultron.events — pub/sub delivery, filtering, fault isolation."""

import time

from ultron.events import EVENT_BUS, Event, EventBus, EventType


def test_publish_returns_event_with_id():
    bus = EventBus()
    event = bus.publish(
        EventType.STATE_CHANGED, {"from": "IDLE"}, source="fsm"
    )
    assert isinstance(event, Event)
    assert event.event_id
    assert event.event_type == EventType.STATE_CHANGED
    assert event.source == "fsm"
    assert event.payload == {"from": "IDLE"}
    assert event.timestamp > 0


def test_subscriber_receives_published_event():
    bus = EventBus()
    received = []

    def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.VULNERABILITY_FOUND, handler)
    bus.publish(
        EventType.VULNERABILITY_FOUND, {"severity": "high"}, source="scan"
    )
    assert len(received) == 1
    assert received[0].payload["severity"] == "high"


def test_multiple_subscribers_all_receive_event():
    bus = EventBus()
    seen = []
    bus.subscribe(EventType.FLAG_CAPTURED, lambda e: seen.append(("a", e)))
    bus.subscribe(EventType.FLAG_CAPTURED, lambda e: seen.append(("b", e)))
    bus.publish(EventType.FLAG_CAPTURED, {}, source="agent")
    assert [tag for tag, _ in seen] == ["a", "b"]


def test_unrelated_subscribers_are_not_notified():
    bus = EventBus()
    seen = []
    bus.subscribe(EventType.FLAG_CAPTURED, lambda e: seen.append(e))
    bus.publish(EventType.EXPLOIT_FAILED, {}, source="agent")
    assert seen == []


def test_handler_exceptions_are_isolated(caplog):
    import logging

    bus = EventBus()
    called = []

    def bad_handler(event: Event) -> None:
        raise RuntimeError("boom")

    def good_handler(event: Event) -> None:
        called.append(event)

    bus.subscribe(EventType.ERROR_OCCURRED, bad_handler)
    bus.subscribe(EventType.ERROR_OCCURRED, good_handler)

    with caplog.at_level(logging.INFO, logger="ultron.tracing"):
        bus.publish(EventType.ERROR_OCCURRED, {}, source="test")

    assert len(called) == 1  # good handler still ran
    assert any(
        "EVENT_HANDLER_ERROR" in r.message for r in caplog.records
    )


def test_get_events_filters_by_type():
    bus = EventBus()
    bus.publish(EventType.STATE_CHANGED, {}, source="a")
    bus.publish(EventType.FLAG_CAPTURED, {}, source="b")
    bus.publish(EventType.STATE_CHANGED, {}, source="c")

    state_events = bus.get_events(EventType.STATE_CHANGED)
    assert len(state_events) == 2
    assert all(e.event_type == EventType.STATE_CHANGED for e in state_events)


def test_get_events_filters_by_since():
    bus = EventBus()
    bus.publish(EventType.AGENT_STARTED, {}, source="a")
    time.sleep(0.01)
    cutoff = time.time()
    time.sleep(0.01)
    bus.publish(EventType.AGENT_STARTED, {}, source="b")

    recent = bus.get_events(EventType.AGENT_STARTED, since=cutoff)
    assert len(recent) == 1
    assert recent[0].source == "b"


def test_service_discovered_value_spelled_correctly():
    assert EventType.SERVICE_DISCOVERED.value == "service_discovered"


def test_module_level_bus_exists():
    assert isinstance(EVENT_BUS, EventBus)
