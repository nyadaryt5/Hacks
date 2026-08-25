"""Scope management: authorized targets and lateral-movement approval.

:class:`ScopeManager` sits on top of the safety jail's authorized set and
gives the agent a controlled way to expand scope: verification results that
mention an adjacent asset produce a *lateral request*, which is depth-checked
against ``max_lateral_depth``, persisted to the ``lateral_targets`` table and
published as a ``LATERAL_TARGET_FOUND`` event. Nothing is actually added to
the authorized scope until the operator (or policy) calls
:meth:`ScopeManager.approve`, at which point the target becomes jail-legal.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ultron.events import EventBus, EventType
from ultron.safety import SafetyJail
from ultron.tracing import TRACER

_LOGGER = logging.getLogger(__name__)


@dataclass
class LateralRequest:
    """A proposed lateral-movement target awaiting operator approval."""

    target: str
    depth: int
    evidence: str = ""
    source: str = "verification"
    requested_at: float = field(default_factory=time.time)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_payload(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "depth": self.depth,
            "evidence": self.evidence,
            "source": self.source,
            "requested_at": self.requested_at,
            "request_id": self.request_id,
        }


class ScopeManager:
    """Gate for scope expansion via approved lateral-movement targets."""

    def __init__(
        self,
        jail: SafetyJail,
        event_bus: EventBus,
        *,
        db: Any = None,
        session_id: str = "",
        max_lateral_depth: int = 2,
    ):
        self.jail = jail
        self.event_bus = event_bus
        self.db = db
        self.session_id = session_id
        self.max_lateral_depth = max(0, int(max_lateral_depth))
        self.pending: dict[str, LateralRequest] = {}
        self._depths: dict[str, int] = {}
        self._rejected: set[str] = set()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _log_decision(target: str, decision: str) -> None:
        TRACER.log_event(
            "SCOPE_DECISION", {"target": target, "decision": decision}
        )

    # -- queries -----------------------------------------------------------

    @staticmethod
    def _normalize(target: str) -> str:
        return str(target).strip().lower().rstrip(".")

    def is_authorized(self, target: str) -> bool:
        """True when the jail currently allows ``target``."""
        return self.jail.validate_scope(self._normalize(target))

    def summary(self) -> dict[str, Any]:
        """Snapshot of the authorization state for reports and probes."""
        return {
            "authorized": sorted(self.jail.allowed_targets),
            "pending": [r.target for r in self.pending.values()],
            "rejected": sorted(self._rejected),
            "max_lateral_depth": self.max_lateral_depth,
        }

    # -- lifecycle ----------------------------------------------------------

    def request(  # noqa: PLR0911 (readable decision ladder)
        self,
        target: str,
        *,
        evidence: str = "",
        source: str = "verification",
        depth: int = 1,
    ) -> dict[str, Any]:
        """Request authorization for a newly discovered target.

        Returns a decision dict with ``status`` in
        ``authorized | pending | denied | invalid``. Already-authorized
        targets short-circuit; depth violations and previously rejected
        targets are denied; everything else becomes *pending* and is
        published as a ``LATERAL_TARGET_FOUND`` event.
        """
        normalized = self._normalize(target)
        if not normalized:
            return {"status": "invalid", "target": "", "reason": "empty target"}

        if self.jail.validate_scope(normalized):
            self._log_decision(normalized, "authorized")
            return {
                "status": "authorized",
                "target": normalized,
                "reason": "already in scope",
            }
        if normalized in self.pending:
            return {
                "status": "pending",
                "target": normalized,
                "depth": self.pending[normalized].depth,
                "duplicate": True,
            }
        if normalized in self._depths:
            self._log_decision(normalized, "authorized")
            return {
                "status": "authorized",
                "target": normalized,
                "reason": "previously approved",
            }
        if normalized in self._rejected:
            self._log_decision(normalized, "denied")
            return {
                "status": "denied",
                "target": normalized,
                "reason": "previously rejected by operator",
            }
        if self.max_lateral_depth <= 0:
            self._log_decision(normalized, "denied")
            return {
                "status": "denied",
                "target": normalized,
                "reason": "lateral movement is disabled (max_lateral_depth=0)",
            }
        if depth > self.max_lateral_depth:
            self._log_decision(normalized, "denied")
            return {
                "status": "denied",
                "target": normalized,
                "reason": (
                    f"lateral depth {depth} exceeds limit "
                    f"{self.max_lateral_depth}"
                ),
            }

        request = LateralRequest(
            target=normalized,
            depth=depth,
            evidence=str(evidence)[:500],
            source=source,
        )
        self.pending[normalized] = request
        self._persist_pending(request)
        self.event_bus.publish(
            EventType.LATERAL_TARGET_FOUND,
            {**request.to_payload(), "status": "pending"},
            "scope_manager",
        )
        self._log_decision(normalized, "pending")
        return {"status": "pending", "target": normalized, "depth": depth}

    def approve(self, target: str) -> bool:
        """Approve a pending lateral target; it becomes jail-legal."""
        normalized = self._normalize(target)
        request = self.pending.pop(normalized, None)
        if request is None:
            return False
        self.jail.allowed_targets.add(normalized)
        self._depths[normalized] = request.depth
        self._persist_approved(normalized)
        self.event_bus.publish(
            EventType.LATERAL_TARGET_FOUND,
            {**request.to_payload(), "status": "approved"},
            "scope_manager",
        )
        self._log_decision(normalized, "approved")
        _LOGGER.info(
            "Lateral target approved: %s (depth %d)", normalized, request.depth
        )
        return True

    def reject(self, target: str) -> bool:
        """Reject a pending lateral target; re-requests stay denied."""
        normalized = self._normalize(target)
        if self.pending.pop(normalized, None) is None:
            return False
        self._depths.pop(normalized, None)
        self._rejected.add(normalized)
        self._log_decision(normalized, "rejected")
        _LOGGER.info("Lateral target rejected: %s", normalized)
        return True

    # -- persistence ---------------------------------------------------------

    def _persist_pending(self, request: LateralRequest) -> None:
        if self.db is None:
            return
        try:
            if hasattr(self.db, "get_session"):  # SQLAlchemy backend
                self._persist_pending_orm(request)
            else:  # stdlib SQLite backend
                self.db.execute(
                    "INSERT INTO lateral_targets(session_id, discovered_by, "
                    "target, source_evidence, approved) VALUES (?,?,?,?,0)",
                    (
                        self.session_id,
                        request.source,
                        request.target,
                        request.evidence,
                    ),
                )
                self.db.commit()
        except Exception as exc:  # noqa: BLE001 (persistence is best effort)
            _LOGGER.warning(
                "Failed to persist lateral request %s: %s", request.target, exc
            )

    def _persist_pending_orm(self, request: LateralRequest) -> None:
        from ultron.db import LateralTargetModel  # noqa: PLC0415 (needs SQLAlchemy)

        session = self.db.get_session()
        session.add(
            LateralTargetModel(
                session_id=self.session_id,
                discovered_by=request.source,
                target=request.target,
                source_evidence=request.evidence,
                approved=False,
            )
        )
        session.commit()

    def _persist_approved(self, target: str) -> None:
        if self.db is None:
            return
        try:
            if hasattr(self.db, "get_session"):  # SQLAlchemy backend
                from ultron.db import (  # noqa: PLC0415 (needs SQLAlchemy)
                    LateralTargetModel,
                )

                session = self.db.get_session()
                session.query(LateralTargetModel).filter_by(
                    session_id=self.session_id, target=target
                ).update({LateralTargetModel.approved: True})
                session.commit()
            else:  # stdlib SQLite backend
                self.db.execute(
                    "UPDATE lateral_targets SET approved=1 "
                    "WHERE session_id=? AND target=?",
                    (self.session_id, target),
                )
                self.db.commit()
        except Exception as exc:  # noqa: BLE001 (persistence is best effort)
            _LOGGER.warning("Failed to persist approval for %s: %s", target, exc)


__all__ = ["LateralRequest", "ScopeManager"]
