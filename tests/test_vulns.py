"""Tests for ultron.vulns — CVSS 3.1 scoring and the finding store."""

import json
import sqlite3

import pytest
from ultron.db import (
    HAS_SQLALCHEMY,
    SQLAlchemyDatabaseManager,
    SQLiteDatabaseManager,
)
from ultron.vulns import (
    Finding,
    FindingStore,
    InvalidVectorError,
    base_score,
    normalize_severity,
    parse_vector,
    score_of_vector,
    severity_for_score,
    suggested_vector,
)


class TestParseVector:
    def test_parses_prefixed_vector(self):
        metrics = parse_vector("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        assert metrics == {
            "AV": "N", "AC": "L", "PR": "N", "UI": "N",
            "S": "U", "C": "H", "I": "H", "A": "H",
        }

    def test_accepts_bare_body_and_case_insensitive_keys(self):
        metrics = parse_vector("av:n/ac:l/pr:n/ui:n/s:u/c:h/i:h/a:h")
        assert metrics["AV"] == "N"
        assert metrics["S"] == "U"

    def test_accepts_v3_0_prefix(self):
        assert parse_vector("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N")["A"] == "N"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "CVSS:3.1/",
            "CVSS:4.0/AV:N",
            "CVSS:2.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H",  # missing A
            "AV:N/AV:L/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # duplicate metric
            "AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # empty value token
        ],
    )
    def test_rejects_malformed_vectors(self, bad):
        with pytest.raises(InvalidVectorError):
            parse_vector(bad)


class TestBaseScore:
    @pytest.mark.parametrize(
        ("vector", "expected"),
        [
            # Canonical NVD scores.
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),   # unauth RCE
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),  # maximum
            ("CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H", 7.2),   # admin RCE
            ("CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 8.4),   # local RCE
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:H/I:H/A:H", 9.6),   # scope change
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N", 5.3),
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),   # no impact
            ("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N", 0.0),
            # No-impact vectors score zero regardless of exploitability.
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:N/I:N/A:N", 0.0),
        ],
    )
    def test_known_scores(self, vector, expected):
        assert base_score(vector) == pytest.approx(expected)

    def test_pr_high_is_weighted_by_scope(self):
        unchanged = base_score(
            "CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H"
        )
        changed = base_score(
            "CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:C/C:H/I:H/A:H"
        )
        # Scope-changed PR:H weighs 0.50 vs 0.27 unchanged, plus 1.08x.
        assert changed > unchanged

    @pytest.mark.parametrize(
        "vector",
        [
            "CVSS:3.1/AV:Z/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "CVSS:3.1/AV:N/AC:Z/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "CVSS:3.1/AV:N/AC:L/PR:Z/UI:N/S:U/C:H/I:H/A:H",
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:Z/S:U/C:H/I:H/A:H",
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:Z/C:H/I:H/A:H",
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:Z/I:H/A:H",
        ],
    )
    def test_invalid_metric_values_raise(self, vector):
        with pytest.raises(InvalidVectorError):
            base_score(vector)


class TestScoreHelpers:
    def test_score_of_vector_returns_none_when_invalid(self):
        assert score_of_vector("not-a-vector") is None
        assert score_of_vector("CVSS:3.1/AV:N") is None

    @pytest.mark.parametrize(
        ("score", "severity"),
        [
            (0.0, "none"),
            (0.1, "low"),
            (3.9, "low"),
            (4.0, "medium"),
            (6.9, "medium"),
            (7.0, "high"),
            (8.9, "high"),
            (9.0, "critical"),
            (10.0, "critical"),
        ],
    )
    def test_severity_for_score(self, score, severity):
        assert severity_for_score(score) == severity

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("CRITICAL", "critical"),
            ("Crit", "critical"),
            ("high", "high"),
            ("moderate", "medium"),
            ("MED", "medium"),
            ("low", "low"),
            ("informational", "info"),
            ("weird-label", "info"),
            (8.0, "high"),
            (2.5, "low"),
            (None, "info"),
        ],
    )
    def test_normalize_severity(self, raw, expected):
        assert normalize_severity(raw) == expected

    def test_suggested_vectors_stay_in_their_severity_band(self):
        for severity in ("critical", "high", "medium", "low"):
            vector = suggested_vector(severity)
            score = base_score(vector)
            assert severity_for_score(score) == severity
        # "info" maps to a no-impact vector, which scores 0.0 ("none").
        assert base_score(suggested_vector("info")) == 0.0


class TestFinding:
    def test_dedup_key_is_stable_and_target_sensitive(self):
        a = Finding(title="RCE in /api", target="10.0.0.1")
        b = Finding(title="rce in /api", target="10.0.0.1")
        c = Finding(title="RCE in /api", target="10.0.0.2")
        assert a.dedup_key == b.dedup_key
        assert a.dedup_key != c.dedup_key

    def test_to_payload_is_json_safe(self):
        finding = Finding(title="t", cvss_score=9.8)
        json.dumps(finding.to_payload())


class TestFindingStore:
    def test_record_scores_severity_only_findings(self):
        store = FindingStore()
        finding, is_new = store.record(
            {"title": "admin panel exposed", "severity": "high"}
        )
        assert is_new is True
        assert finding.severity == "high"
        assert finding.cvss_vector.startswith("CVSS:3.1/")
        assert finding.cvss_score == base_score(finding.cvss_vector)

    def test_record_keeps_explicit_cvss_vector(self):
        store = FindingStore(target="10.0.0.1")
        finding, _ = store.record(
            {
                "title": "sql injection",
                "severity": "low",
                "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            }
        )
        # Vector wins over the suggested severity vector.
        assert finding.cvss_score == 9.8  # noqa: PLR2004 (known canonical score)

    def test_record_clamps_explicit_score(self):
        store = FindingStore()
        finding, _ = store.record(
            {"title": "x", "severity": "low", "cvss_score": 12.5}
        )
        assert finding.cvss_score == 10.0  # noqa: PLR2004 (scale maximum)

    def test_record_handles_invalid_vector_gracefully(self):
        store = FindingStore()
        finding, _ = store.record(
            {"title": "x", "severity": "low", "cvss_vector": "garbage"}
        )
        assert finding.cvss_vector == "garbage"
        assert finding.cvss_score is None

    def test_record_deduplicates_by_target_and_title(self):
        store = FindingStore(target="10.0.0.1")
        first, is_new = store.record({"title": "open port 22", "severity": "info"})
        second, is_new_again = store.record(
            {"title": "OPEN PORT 22", "severity": "info"}
        )
        assert is_new is True
        assert is_new_again is False
        assert second is first
        assert len(store.all()) == 1

    def test_record_accepts_plain_strings(self):
        store = FindingStore()
        finding, _ = store.record("buffer overflow in service X")
        assert finding.title == "buffer overflow in service X"
        assert finding.severity == "info"

    def test_summary_and_report_rows(self):
        store = FindingStore(target="10.0.0.1")
        store.record({"title": "a", "severity": "critical"})
        store.record({"title": "b", "severity": "low"})
        summary = store.summary()
        assert summary["total"] == 2  # noqa: PLR2004 (two findings recorded)
        assert summary["by_severity"] == {"critical": 1, "low": 1}
        assert summary["max_cvss"] == 9.8  # noqa: PLR2004 (critical band max)

        rows = store.report_rows()
        assert rows[0][1] == "CRITICAL"
        assert rows[0][3] == "a"
        assert rows[1][0] == "2"

    def test_persists_to_sqlalchemy_backend(self, tmp_path):
        if not HAS_SQLALCHEMY:
            pytest.skip("SQLAlchemy not installed")
        from ultron.db import FindingModel  # noqa: PLC0415 (needs SQLAlchemy)

        db = SQLAlchemyDatabaseManager(f"sqlite:///{tmp_path / 'vulns.db'}")
        try:
            store = FindingStore(db, target="10.0.0.1", session_id="sess-1")
            store.record({"title": "persisted finding", "severity": "high"})
            session = db.get_session()
            stored = session.query(FindingModel).all()
            assert len(stored) == 1
            assert stored[0].title == "persisted finding"
            assert stored[0].cvss_score is not None
            assert stored[0].target == "10.0.0.1"
        finally:
            db.close()

    def test_persists_to_sqlite_fallback_backend(self, tmp_path):
        db = SQLiteDatabaseManager(str(tmp_path / "fallback.db"))
        try:
            store = FindingStore(db, target="10.0.0.2", session_id="sess-2")
            store.record({"title": "fallback finding", "severity": "medium"})
            conn = sqlite3.connect(str(tmp_path / "fallback.db"))
            row = conn.execute(
                "SELECT severity, title, target FROM findings"
            ).fetchone()
            conn.close()
            assert row == ("medium", "fallback finding", "10.0.0.2")
        finally:
            db.close()

    def test_persistence_failure_does_not_break_collection(self):
        class BrokenDB:
            def execute(self, *a, **k):
                raise RuntimeError("disk on fire")

            def commit(self):
                raise RuntimeError("disk on fire")

        store = FindingStore(BrokenDB())
        finding, is_new = store.record({"title": "still recorded", "severity": "low"})
        assert is_new is True
        assert store.all()[0] is finding
