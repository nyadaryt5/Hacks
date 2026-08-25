"""Tests for ultron.scope — lateral-movement approval flow."""

import ipaddress
import sqlite3

import pytest
from ultron.db import HAS_SQLALCHEMY, SQLiteDatabaseManager
from ultron.events import EventBus, EventType
from ultron.safety import SafetyJail
from ultron.scope import LateralRequest, ScopeManager


@pytest.fixture()
def jail():
    return SafetyJail(
        allowed_targets={"192.168.1.10"},
        allowed_networks=[ipaddress.ip_network("10.0.0.0/8")],
    )


@pytest.fixture()
def bus():
    return EventBus()


def make_scope(jail, bus, *, db=None, depth=2, session_id="sess"):
    return ScopeManager(
        jail,
        bus,
        db=db,
        session_id=session_id,
        max_lateral_depth=depth,
    )


class TestScopeDecisions:
    def test_already_in_scope_is_authorized(self, jail, bus):
        scope = make_scope(jail, bus)
        assert scope.request("10.1.2.3")["status"] == "authorized"
        assert scope.request("192.168.1.10")["status"] == "authorized"
        assert bus.get_events(EventType.LATERAL_TARGET_FOUND) == []

    def test_out_of_scope_becomes_pending_and_publishes(self, jail, bus):
        scope = make_scope(jail, bus)
        decision = scope.request("192.168.50.5", evidence="found in /etc/hosts")
        assert decision == {
            "status": "pending",
            "target": "192.168.50.5",
            "depth": 1,
        }
        events = bus.get_events(EventType.LATERAL_TARGET_FOUND)
        assert len(events) == 1
        payload = events[0].payload
        assert payload["target"] == "192.168.50.5"
        assert payload["status"] == "pending"
        assert payload["evidence"] == "found in /etc/hosts"
        assert scope.is_authorized("192.168.50.5") is False

    def test_duplicate_request_is_flagged_without_new_event(self, jail, bus):
        scope = make_scope(jail, bus)
        scope.request("192.168.50.5")
        decision = scope.request("192.168.50.5")
        assert decision["status"] == "pending"
        assert decision["duplicate"] is True
        assert len(bus.get_events(EventType.LATERAL_TARGET_FOUND)) == 1

    def test_depth_beyond_limit_is_denied(self, jail, bus):
        scope = make_scope(jail, bus, depth=1)
        decision = scope.request("192.168.50.5", depth=2)
        assert decision["status"] == "denied"
        assert "exceeds limit" in decision["reason"]
        assert scope.pending == {}

    def test_disabled_lateral_movement_denies_everything(self, jail, bus):
        scope = make_scope(jail, bus, depth=0)
        assert scope.request("192.168.50.5")["status"] == "denied"
        assert scope.summary()["pending"] == []

    def test_empty_target_is_invalid(self, jail, bus):
        scope = make_scope(jail, bus)
        assert scope.request("   ")["status"] == "invalid"

    def test_normalization_is_case_and_whitespace_insensitive(self, jail, bus):
        scope = make_scope(jail, bus)
        scope.request("  192.168.50.5 ")
        assert list(scope.pending) == ["192.168.50.5"]
        assert scope.approve("192.168.50.5") is True


class TestApproveReject:
    def test_approve_makes_target_jail_legal(self, jail, bus):
        scope = make_scope(jail, bus)
        scope.request("192.168.50.5")
        assert scope.approve("192.168.50.5") is True
        assert scope.is_authorized("192.168.50.5") is True
        # A new request now short-circuits as authorized.
        assert scope.request("192.168.50.5")["status"] == "authorized"
        events = bus.get_events(EventType.LATERAL_TARGET_FOUND)
        assert events[-1].payload["status"] == "approved"

    def test_approve_unknown_target_fails(self, jail, bus):
        scope = make_scope(jail, bus)
        assert scope.approve("192.168.50.5") is False

    def test_reject_blocks_re_requests(self, jail, bus):
        scope = make_scope(jail, bus)
        scope.request("192.168.50.5")
        assert scope.reject("192.168.50.5") is True
        assert scope.reject("192.168.50.5") is False
        decision = scope.request("192.168.50.5")
        assert decision["status"] == "denied"
        assert "previously rejected" in decision["reason"]
        assert scope.is_authorized("192.168.50.5") is False

    def test_summary_tracks_state(self, jail, bus):
        scope = make_scope(jail, bus)
        scope.request("192.168.50.5")
        scope.request("192.168.50.6")
        scope.reject("192.168.50.6")
        summary = scope.summary()
        assert summary["authorized"] == ["192.168.1.10"]
        assert summary["pending"] == ["192.168.50.5"]
        assert summary["rejected"] == ["192.168.50.6"]
        assert summary["max_lateral_depth"] == 2  # noqa: PLR2004 (default used)


class TestLateralRequestPayload:
    def test_to_payload_contains_all_fields(self):
        request = LateralRequest(
            target="10.9.9.9", depth=2, evidence="banner", source="verification"
        )
        payload = request.to_payload()
        assert payload["target"] == "10.9.9.9"
        assert payload["depth"] == 2  # noqa: PLR2004 (depth passed above)
        assert payload["evidence"] == "banner"
        assert payload["source"] == "verification"
        assert payload["request_id"]


class TestScopePersistence:
    def test_sqlalchemy_backend_persists_and_updates(self, jail, bus, tmp_path):
        if not HAS_SQLALCHEMY:
            pytest.skip("SQLAlchemy not installed")
        from ultron.db import (  # noqa: PLC0415 (needs SQLAlchemy)
            LateralTargetModel,
            SQLAlchemyDatabaseManager,
        )

        db = SQLAlchemyDatabaseManager(f"sqlite:///{tmp_path / 'scope.db'}")
        try:
            scope = make_scope(jail, bus, db=db, session_id="sess-x")
            scope.request("192.168.50.5", evidence="adjacent host")
            scope.approve("192.168.50.5")
            session = db.get_session()
            row = session.query(LateralTargetModel).one()
            assert row.target == "192.168.50.5"
            assert row.source_evidence == "adjacent host"
            assert row.approved is True
        finally:
            db.close()

    def test_sqlite_fallback_persists(self, jail, bus, tmp_path):
        db = SQLiteDatabaseManager(str(tmp_path / "scope.db"))
        try:
            scope = make_scope(jail, bus, db=db, session_id="sess-y")
            scope.request("192.168.50.5")
            conn = sqlite3.connect(str(tmp_path / "scope.db"))
            row = conn.execute(
                "SELECT target, approved FROM lateral_targets"
            ).fetchone()
            conn.close()
            assert row == ("192.168.50.5", 0)
            scope.approve("192.168.50.5")
            conn = sqlite3.connect(str(tmp_path / "scope.db"))
            row = conn.execute(
                "SELECT approved FROM lateral_targets"
            ).fetchone()
            conn.close()
            assert row == (1,)
        finally:
            db.close()

    def test_persistence_failure_does_not_block_decision(self, jail, bus):
        class BrokenDB:
            def execute(self, *a, **k):
                raise RuntimeError("no disk")

            def commit(self):
                raise RuntimeError("no disk")

        scope = make_scope(jail, bus, db=BrokenDB())
        assert scope.request("192.168.50.5")["status"] == "pending"
        assert scope.approve("192.168.50.5") is True
