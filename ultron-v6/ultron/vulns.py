"""Vulnerability registry: CVSS 3.1 scoring and a persistent finding store.

:func:`base_score` implements the CVSS v3.1 base-score formula (FIRST,
"Common Vulnerability Scoring System v3.1 Specification") for the eight
base metrics, so findings can be scored and prioritized without external
services. :class:`FindingStore` normalizes raw verification output into
:class:`Finding` records, deduplicates them, attaches a CVSS vector and
score, and persists them to the relational backend (findings table).
"""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

#: Base metrics required for a complete CVSS 3.x vector.
REQUIRED_METRICS = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")

_ATTACK_VECTOR = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
_ATTACK_COMPLEXITY = {"L": 0.77, "H": 0.44}
_PRIVILEGES_SCOPE_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PRIVILEGES_SCOPE_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.50}
_USER_INTERACTION = {"N": 0.85, "R": 0.62}
_REQUIREMENT = {"H": 0.56, "L": 0.22, "N": 0.0}

#: Multiplier applied to (Impact + Exploitability) when Scope is Changed.
_SCOPE_CHANGED_MULTIPLIER = 1.08

#: CVSS qualitative rating band boundaries (base score).
_SEVERITY_LOW_MAX = 3.9
_SEVERITY_MEDIUM_MAX = 6.9
_SEVERITY_HIGH_MAX = 8.9

#: Canonical vectors used to score findings that report severity only.
SUGGESTED_VECTORS: dict[str, str] = {
    "critical": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
    "high": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
    "medium": "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:N/A:N",
    "low": "CVSS:3.1/AV:L/AC:L/PR:L/UI:R/S:U/C:L/I:N/A:N",
    "info": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N",
}

_SEVERITY_ALIASES = {
    "critical": "critical",
    "crit": "critical",
    "high": "high",
    "medium": "medium",
    "moderate": "medium",
    "med": "medium",
    "low": "low",
    "info": "info",
    "informational": "info",
    "none": "info",
}


class InvalidVectorError(ValueError):
    """Raised when a CVSS vector string is malformed or unsupported."""


def _roundup(value: float) -> float:
    """Smallest multiple of 0.1 that is >= ``value`` (CVSS Roundup)."""
    return math.ceil(value * 10) / 10


def parse_vector(vector: str) -> dict[str, str]:
    """Parse a CVSS v3.0/v3.1 vector string into a metrics dict.

    Accepts the ``CVSS:3.1/...`` prefix or a bare ``AV:N/...`` body. Raises
    :class:`InvalidVectorError` for unknown prefixes, missing metrics,
    duplicate metrics or empty input.
    """
    text = (vector or "").strip()
    if not text:
        raise InvalidVectorError("empty vector")
    if text.startswith("CVSS:"):
        prefix, _, body = text.partition("/")
        if prefix not in ("CVSS:3.0", "CVSS:3.1"):
            raise InvalidVectorError(f"unsupported CVSS version: {prefix}")
        if not body:
            raise InvalidVectorError("vector has no metrics")
    else:
        body = text

    _VALID_VALUES = {
        "AV": {"N", "A", "L", "P"},
        "AC": {"L", "H"},
        "PR": {"N", "L", "H"},
        "UI": {"N", "R"},
        "S": {"U", "C"},
        "C": {"H", "L", "N"},
        "I": {"H", "L", "N"},
        "A": {"H", "L", "N"},
    }

    metrics: dict[str, str] = {}
    for token in body.split("/"):
        if not token:
            continue
        key, _, value = token.partition(":")
        key, value = key.strip().upper(), value.strip().upper()
        if not key or not value:
            raise InvalidVectorError(f"malformed metric token: {token!r}")
        if key in metrics and metrics[key] != value:
            raise InvalidVectorError(f"duplicate metric: {key}")
        metrics[key] = value

    missing = [name for name in REQUIRED_METRICS if name not in metrics]
    if missing:
        raise InvalidVectorError(f"missing metrics: {', '.join(missing)}")

    for name in REQUIRED_METRICS:
        if metrics[name] not in _VALID_VALUES[name]:
            raise InvalidVectorError(f"invalid value for {name}: {metrics[name]}")
    return {name: metrics[name] for name in REQUIRED_METRICS}


def base_score(vector: str) -> float:
    """Compute the CVSS 3.x base score (0.0-10.0) for a vector string.

    Implements the official CVSS v3.1 base-score equations (identical in
    v3.0; v3.1 refined the metric-selection guidance):

    * ``ISS = 1 - [(1-C)(1-I)(1-A)]``
    * Impact (S:U) ``6.42*ISS``; Impact (S:C)
      ``7.52*(ISS-0.029) - 3.25*(ISS-0.02)^15``
    * ``Exploitability = 8.22*AV*AC*PR*UI`` (PR weighted by scope)
    * BaseScore: 0 if Impact <= 0, else
      ``Roundup(MIN(Impact + Exploitability, 10))`` for S:U and
      ``Roundup(MIN(1.08 * (Impact + Exploitability), 10))`` for S:C.
    """
    metrics = parse_vector(vector)

    privileges = (
        _PRIVILEGES_SCOPE_UNCHANGED
        if metrics.get("S") == "U"
        else _PRIVILEGES_SCOPE_CHANGED
    )
    for name, table in (
        ("AV", _ATTACK_VECTOR),
        ("AC", _ATTACK_COMPLEXITY),
        ("PR", privileges),
        ("UI", _USER_INTERACTION),
        ("C", _REQUIREMENT),
        ("I", _REQUIREMENT),
        ("A", _REQUIREMENT),
    ):
        if metrics[name] not in table:
            raise InvalidVectorError(f"invalid value for {name}: {metrics[name]}")
    if metrics["S"] not in ("U", "C"):
        raise InvalidVectorError(f"invalid value for S: {metrics['S']}")

    iss = 1.0 - (
        (1.0 - _REQUIREMENT[metrics["C"]])
        * (1.0 - _REQUIREMENT[metrics["I"]])
        * (1.0 - _REQUIREMENT[metrics["A"]])
    )

    if metrics["S"] == "U":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15

    exploitability = (
        8.22
        * _ATTACK_VECTOR[metrics["AV"]]
        * _ATTACK_COMPLEXITY[metrics["AC"]]
        * privileges[metrics["PR"]]
        * _USER_INTERACTION[metrics["UI"]]
    )

    if impact <= 0.0:
        return 0.0
    total = impact + exploitability
    if metrics["S"] == "C":
        total = _SCOPE_CHANGED_MULTIPLIER * total
    return _roundup(min(total, 10.0))


def score_of_vector(vector: str) -> float | None:
    """Like :func:`base_score` but returns ``None`` for invalid vectors."""
    try:
        return base_score(vector)
    except InvalidVectorError:
        return None


def severity_for_score(score: float) -> str:
    """Map a numeric base score to the CVSS qualitative rating."""
    if score <= 0.0:
        return "none"
    if score <= _SEVERITY_LOW_MAX:
        return "low"
    if score <= _SEVERITY_MEDIUM_MAX:
        return "medium"
    if score <= _SEVERITY_HIGH_MAX:
        return "high"
    return "critical"


def normalize_severity(raw: Any) -> str:
    """Normalize a free-form severity label to critical/high/medium/low/info."""
    if isinstance(raw, str):
        return _SEVERITY_ALIASES.get(raw.strip().lower(), "info")
    if isinstance(raw, (int, float)):
        return severity_for_score(float(raw))
    return "info"


def suggested_vector(severity: str) -> str:
    """Return the canonical CVSS 3.1 vector for a qualitative severity."""
    return SUGGESTED_VECTORS[normalize_severity(severity)]


@dataclass
class Finding:
    """A single vulnerability observation with CVSS metadata."""

    title: str
    severity: str = "info"
    target: str = ""
    phase: str = ""
    description: str = ""
    evidence: str = ""
    cvss_vector: str = ""
    cvss_score: float | None = None
    remediation: str = ""
    finding_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def dedup_key(self) -> str:
        """Stable identity used to deduplicate repeated observations."""
        material = f"{self.target.lower()}|{self.title.lower()}"
        return hashlib.sha1(  # noqa: S324 (dedup fingerprint, not security)
            material.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:16]

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe payload for event publication and reports."""
        return {
            "id": self.finding_id,
            "title": self.title,
            "severity": self.severity,
            "target": self.target,
            "phase": self.phase,
            "cvss_vector": self.cvss_vector,
            "cvss_score": self.cvss_score,
            "created_at": self.created_at,
        }


class FindingStore:
    """Collects, deduplicates, scores and persists findings for a session.

    The ``db`` argument accepts either backend from :mod:`ultron.db`
    (SQLAlchemy or the stdlib SQLite manager); both are duck-typed here.
    """

    def __init__(
        self,
        db: Any = None,
        *,
        target: str = "",
        session_id: str = "",
    ):
        self.db = db
        self.target = target
        self.session_id = session_id
        self._findings: list[Finding] = []
        self._dedup: dict[str, Finding] = {}

    # -- collection ------------------------------------------------------

    def record(
        self, payload: dict[str, Any] | str, phase: str = ""
    ) -> tuple[Finding, bool]:
        """Normalize ``payload`` into a :class:`Finding` and store it.

        Returns ``(finding, is_new)``. Repeated observations (same target +
        title) return the original finding with ``is_new=False`` so callers
        do not re-publish duplicate events.
        """
        data = self._normalize(payload)
        title = str(data.get("title") or "(untitled finding)").strip()[:200]
        severity = normalize_severity(data.get("severity"))
        finding_target = str(data.get("target") or self.target)

        vector = ""
        score: float | None = None
        raw_vector = data.get("cvss_vector")
        if isinstance(raw_vector, str) and raw_vector.strip():
            vector = raw_vector.strip()
            score = score_of_vector(vector)
            if score is None:
                _LOGGER.warning(
                    "Invalid CVSS vector %r on finding %r", raw_vector, title
                )
        elif isinstance(data.get("cvss_score"), (int, float)):
            score = max(0.0, min(10.0, float(data["cvss_score"])))
        else:
            vector = suggested_vector(severity)
            score = base_score(vector)

        finding = Finding(
            title=title,
            severity=severity,
            target=finding_target,
            phase=str(data.get("phase") or phase),
            description=str(data.get("description") or "")[:1000],
            evidence=str(data.get("evidence") or "")[:1000],
            cvss_vector=vector,
            cvss_score=score,
            remediation=str(data.get("remediation") or "")[:1000],
        )

        existing = self._dedup.get(finding.dedup_key)
        if existing is not None:
            return existing, False

        self._findings.append(finding)
        self._dedup[finding.dedup_key] = finding
        self._persist(finding)
        return finding, True

    @staticmethod
    def _normalize(
        payload: dict[str, Any] | str,
    ) -> dict[str, Any]:
        if isinstance(payload, str):
            return {"title": payload}
        if isinstance(payload, dict):
            return dict(payload)
        return {"title": str(payload)}

    # -- queries ----------------------------------------------------------

    def all(self) -> list[Finding]:
        """All recorded findings, in insertion order."""
        return list(self._findings)

    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self._findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    def summary(self) -> dict[str, Any]:
        """Aggregate statistics used by the report and metrics."""
        scores = [f.cvss_score for f in self._findings if f.cvss_score is not None]
        return {
            "total": len(self._findings),
            "by_severity": self.by_severity(),
            "max_cvss": max(scores) if scores else None,
        }

    def report_rows(self) -> list[list[str]]:
        """Markdown table rows for the findings section of a report."""
        rows: list[list[str]] = []
        for index, finding in enumerate(self._findings, start=1):
            score = (
                f"{finding.cvss_score:.1f}"
                if finding.cvss_score is not None
                else "-"
            )
            rows.append(
                [str(index), finding.severity.upper(), score, finding.title]
            )
        return rows

    # -- persistence ------------------------------------------------------

    def _persist(self, finding: Finding) -> None:
        """Write the finding to the relational backend (best effort)."""
        if self.db is None:
            return
        try:
            if hasattr(self.db, "get_session"):  # SQLAlchemy backend
                self._persist_orm(finding)
            else:  # stdlib SQLite backend
                self._persist_sqlite(finding)
        except Exception as exc:  # noqa: BLE001 (persistence is best effort)
            _LOGGER.warning("Failed to persist finding %s: %s", finding.title, exc)

    def _persist_orm(self, finding: Finding) -> None:
        from ultron.db import FindingModel  # noqa: PLC0415 (needs SQLAlchemy)

        session = self.db.get_session()
        session.add(
            FindingModel(
                session_id=self.session_id,
                agent="coordinator",
                phase=finding.phase,
                finding_type=finding.title[:80],
                severity=finding.severity,
                title=finding.title,
                evidence=finding.evidence,
                target=finding.target,
                cvss_score=finding.cvss_score,
                cvss_vector=finding.cvss_vector,
                remediation=finding.remediation,
            )
        )
        session.commit()

    def _persist_sqlite(self, finding: Finding) -> None:
        self.db.execute(
            "INSERT INTO findings(session_id, agent, phase, finding_type, "
            "severity, title, evidence, target, cvss_score, cvss_vector, "
            "remediation, validated) VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                self.session_id,
                "coordinator",
                finding.phase,
                finding.title[:80],
                finding.severity,
                finding.title,
                finding.evidence,
                finding.target,
                finding.cvss_score,
                finding.cvss_vector,
                finding.remediation,
            ),
        )
        self.db.commit()


__all__ = [
    "Finding",
    "FindingStore",
    "InvalidVectorError",
    "REQUIRED_METRICS",
    "SUGGESTED_VECTORS",
    "base_score",
    "normalize_severity",
    "parse_vector",
    "score_of_vector",
    "severity_for_score",
    "suggested_vector",
]
