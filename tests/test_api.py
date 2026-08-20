"""Tests for ultron.api — health, readiness and metrics endpoints."""

import json
import threading
import urllib.request

import pytest

from ultron.api import METRICS, MetricsRegistry, start_server


@pytest.fixture()
def server():
    srv = start_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _get(port, path):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=5
        ) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_healthz_reports_ok(server):
    status, body = _get(server.server_address[1], "/healthz")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["service"] == "ultron-v6"


def test_root_lists_endpoints(server):
    status, body = _get(server.server_address[1], "/")
    assert status == 200
    payload = json.loads(body)
    assert "/healthz" in payload["endpoints"]
    assert "/metrics" in payload["endpoints"]


def test_readyz_default_is_ready(server):
    status, body = _get(server.server_address[1], "/readyz")
    assert status == 200
    assert json.loads(body)["status"] == "ready"


def test_readyz_respects_ready_check():
    def not_ready():
        return False, "database unreachable"

    srv = start_server(
        host="127.0.0.1", port=0, ready_check=not_ready
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(srv.server_address[1], "/readyz")
        assert status == 503
        assert json.loads(body)["reason"] == "database unreachable"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_metrics_endpoint_serves_prometheus_format(server):
    status, body = _get(server.server_address[1], "/metrics")
    assert status == 200
    assert "ultron_process_uptime_seconds" in body
    assert "ultron_http_requests_total" in body


def test_request_counter_increments(server):
    import re

    def healthz_count():
        _, body = _get(server.server_address[1], "/metrics")
        match = re.search(
            r'ultron_http_requests_total\{path="/healthz"\} (\d+)', body
        )
        return int(match.group(1)) if match else 0

    before = healthz_count()
    _get(server.server_address[1], "/healthz")
    _get(server.server_address[1], "/healthz")
    assert healthz_count() == before + 2


def test_unknown_path_is_404(server):
    status, _ = _get(server.server_address[1], "/nope")
    assert status == 404


def test_registry_counters_and_gauges():
    registry = MetricsRegistry()
    registry.inc("hits", ("path", "/x"))
    registry.inc("hits", ("path", "/x"))
    registry.set("temperature", 42.0)
    rendered = registry.render()
    assert 'hits{path="/x"} 2' in rendered
    assert "temperature 42" in rendered


def test_module_level_metrics_registry_exists():
    assert isinstance(METRICS, MetricsRegistry)
