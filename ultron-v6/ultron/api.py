"""HTTP health and Prometheus metrics endpoints (standard library only).

Exposes ``/healthz`` (liveness), ``/readyz`` (readiness) and ``/metrics``
(Prometheus text format) so deployments can probe and monitor a running
ULTRON instance without extra dependencies.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ultron import __version__
from ultron.tracing import TRACER

_LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - platform dependent
    import resource  # noqa: PLC0415 (unix only)
except ImportError:  # pragma: no cover - platform dependent
    resource = None  # type: ignore[assignment]


class MetricsRegistry:
    """Thread-safe counter/gauge registry with Prometheus rendering."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counters: dict[tuple[str, ...], int] = {}
        self.gauges: dict[str, float] = {}
        self.start_time = time.time()

    def inc(self, name: str, labels: tuple[str, ...] = ()) -> None:
        with self.lock:
            key = (name, labels)
            self.counters[key] = self.counters.get(key, 0) + 1

    def set(self, name: str, value: float) -> None:
        with self.lock:
            self.gauges[name] = value

    def snapshot(self) -> dict[str, float]:
        with self.lock:
            counters = dict(self.counters)
            gauges = dict(self.gauges)
        summary = TRACER.get_trace_summary()
        gauges["ultron_spans_total"] = float(summary["total_spans"])
        gauges["ultron_spans_active"] = float(summary["active"])
        gauges["ultron_tokens_used_total"] = float(summary["total_tokens"])
        gauges["ultron_process_uptime_seconds"] = time.time() - self.start_time
        if resource is not None:
            gauges["ultron_process_rss_kb"] = float(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            )
        return {
            "counters": counters,
            "gauges": gauges,
        }

    def render(self) -> str:
        """Render the registry in Prometheus text format."""
        snap = self.snapshot()
        uptime = snap["gauges"]["ultron_process_uptime_seconds"]
        lines = [
            "# HELP ultron_process_uptime_seconds Seconds since process start.",
            "# TYPE ultron_process_uptime_seconds gauge",
            f"ultron_process_uptime_seconds {uptime:.3f}",
            "# TYPE ultron_http_requests_total counter",
        ]
        for (name, labels), value in sorted(snap["counters"].items()):
            label_str = ",".join(
                f'{key}="{val}"'
                for key, val in zip(
                    labels[0::2], labels[1::2], strict=True
                )
            )
            lines.append(f"{name}{{{label_str}}} {value}")
        for name, value in sorted(snap["gauges"].items()):
            if name == "ultron_process_uptime_seconds":
                continue
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value:g}")
        return "\n".join(lines) + "\n"


METRICS = MetricsRegistry()

_ENDPOINTS = {
    "/": "service info",
    "/healthz": "liveness probe",
    "/readyz": "readiness probe",
    "/metrics": "Prometheus metrics",
}


class UltronHTTPHandler(BaseHTTPRequestHandler):
    """Serves health, readiness and metrics endpoints."""

    server_version = f"UltronHTTPServer/{__version__}"

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self.server.metrics.inc(  # type: ignore[attr-defined]
            "ultron_http_requests_total", ("path", self.path)
        )
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "ultron-v6",
                    "version": __version__,
                },
            )
        elif path == "/readyz":
            ready, reason = self._readiness()
            self._send_json(
                200 if ready else 503,
                {"status": "ready" if ready else "not_ready", "reason": reason},
            )
        elif path == "/metrics":
            body = self.server.metrics.render().encode(  # type: ignore[attr-defined]
                "utf-8"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/":
            self._send_json(
                200,
                {
                    "service": "ultron-v6",
                    "version": __version__,
                    "endpoints": _ENDPOINTS,
                },
            )
        else:
            self._send_json(404, {"error": "not found"})

    def _readiness(self) -> tuple[bool, str]:
        ready_check: Callable[[], tuple[bool, str]] | None = getattr(
            self.server, "ready_check", None
        )
        if ready_check is None:
            return True, "ok"
        try:
            return ready_check()
        except Exception as exc:  # noqa: BLE001 (probe must not raise)
            _LOGGER.warning("readiness check failed: %s", exc)
            return False, str(exc)

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        _LOGGER.debug(
            "%s - %s", self.address_string(), format % args
        )


def start_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    ready_check: Callable[[], tuple[bool, str]] | None = None,
    metrics: MetricsRegistry | None = None,
) -> ThreadingHTTPServer:
    """Create and bind (but do not serve) the monitoring HTTP server."""
    server = ThreadingHTTPServer((host, port), UltronHTTPHandler)
    server.ready_check = ready_check  # type: ignore[attr-defined]
    server.metrics = metrics or METRICS  # type: ignore[attr-defined]
    _LOGGER.info(
        "metrics server listening on %s:%s", host, server.server_address[1]
    )
    return server


def serve_forever(
    host: str = "0.0.0.0",
    port: int = 8080,
    ready_check: Callable[[], tuple[bool, str]] | None = None,
) -> None:
    """Run the monitoring server until interrupted."""
    server = start_server(host=host, port=port, ready_check=ready_check)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _LOGGER.info("metrics server stopped by operator")
    finally:
        server.server_close()


__all__ = [
    "METRICS",
    "MetricsRegistry",
    "UltronHTTPHandler",
    "serve_forever",
    "start_server",
]
