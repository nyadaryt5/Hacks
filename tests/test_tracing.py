"""Tests for ultron.tracing — span lifecycle and trace summaries."""

import logging
import time

from ultron.tracing import Span, SpanType, TRACER, Tracer


def test_span_finish_records_status_and_duration():
    span = Span(
        span_id="s1",
        trace_id="t1",
        name="test",
        span_type=SpanType.LLM_CALL,
        start_time=time.time(),
    )
    assert span.status == "active"
    assert span.end_time is None
    span.finish(status="error")
    assert span.status == "error"
    assert span.end_time is not None
    assert span.duration_ms >= 0.0


def test_span_duration_of_open_span_is_zero():
    span = Span(
        span_id="s2",
        trace_id="t2",
        name="open",
        span_type=SpanType.TOOL_EXECUTION,
        start_time=time.time(),
    )
    assert span.duration_ms == 0.0


def test_tracer_start_and_end_span():
    tracer = Tracer("test-service")
    span_id = tracer.start_span("op", SpanType.LLM_CALL, attributes={"x": 1})
    assert len(tracer.active_spans) == 1
    assert len(tracer.traces) == 1
    assert tracer.traces[0].span_id == span_id
    assert tracer.traces[0].attributes == {"x": 1}

    tracer.end_span(span_id, tokens_used=42, cost_usd=0.01)
    assert tracer.active_spans == {}
    span = tracer.traces[0]
    assert span.end_time is not None
    assert span.tokens_used == 42
    assert span.cost_usd == 0.01


def test_tracer_end_unknown_span_is_noop():
    tracer = Tracer("test-service")
    tracer.end_span("does-not-exist")
    assert tracer.traces == []
    assert tracer.active_spans == {}


def test_tracer_links_parent_and_child():
    tracer = Tracer("test-service")
    parent_id = tracer.start_span("parent", SpanType.VECTOR_QUERY)
    child_id = tracer.start_span(
        "child", SpanType.VECTOR_QUERY, parent_span_id=parent_id
    )
    assert tracer.traces[0].children == [child_id]
    assert tracer.traces[1].parent_span_id == parent_id
    tracer.end_span(child_id)
    tracer.end_span(parent_id)
    assert tracer.active_spans == {}


def test_trace_summary_counts_completed_spans():
    tracer = Tracer("test-service")
    a = tracer.start_span("a", SpanType.LLM_CALL)
    b = tracer.start_span("b", SpanType.DEBATE)
    tracer.end_span(a, tokens_used=10)
    tracer.end_span(b, tokens_used=5)

    summary = tracer.get_trace_summary()
    assert summary["total_spans"] == 2
    assert summary["completed"] == 2
    assert summary["active"] == 0
    assert summary["total_tokens"] == 15
    assert summary["total_duration_ms"] >= 0
    assert summary["by_type"][SpanType.LLM_CALL.name] == 1
    assert summary["by_type"][SpanType.DEBATE.name] == 1
    assert summary["by_type"][SpanType.VECTOR_QUERY.name] == 0


def test_tracer_logs_event_to_logger(caplog):
    tracer = Tracer("test-service")
    with caplog.at_level(logging.INFO, logger="ultron.tracing"):
        tracer.log_event("SESSION_START", {"target": "example.com"})
    assert any("SESSION_START" in record.message for record in caplog.records)
    assert any("example.com" in record.message for record in caplog.records)


def test_module_level_tracer_exists():
    assert isinstance(TRACER, Tracer)
