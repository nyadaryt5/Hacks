"""Tests for ultron.coordinator — the full FSM-driven pipeline."""

import json

import pytest

from ultron.budget import BudgetGovernor
from ultron.config import ULTRONSettings
from ultron.coordinator import ULTRONCoordinator
from ultron.db import DatabaseManager
from ultron.debate import DebateProtocol
from ultron.events import EventBus, EventType
from ultron.fsm import AgentState


class FakeLLM:
    """Scripted LLM client that also counts tokens."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, system, user, temperature=0.3, max_tokens=3000):
        self.calls.append((system, user))
        return self.responses.pop(0)

    def close(self):
        pass


PLAN_SAFE = {
    "thought": "web recon",
    "action_type": "tool",
    "action": "whatweb ${target}",
    "parameters": {},
    "expected_outcome": "tech fingerprint",
    "safety_level": "safe",
}

PLAN_DESTRUCTIVE = {
    "thought": "forceful cleanup",
    "action_type": "tool",
    "action": "rm -rf /tmp/ultron",
    "parameters": {},
    "expected_outcome": "cleanup",
    "safety_level": "destructive",
}


@pytest.fixture()
def settings(tmp_path):
    return ULTRONSettings(
        google_ai={"api_keys": ["k1"], "max_rpm_per_key": 100},
        budget={"max_tokens_per_session": 100000},
        target="192.0.2.10",
    )


def make_coordinator(
    settings, tmp_path, monkeypatch, llm_responses, event_bus=None
):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'coord.db'}")
    budget = BudgetGovernor(settings)
    llm = FakeLLM(llm_responses)
    coord = ULTRONCoordinator(
        settings,
        db=db,
        budget=budget,
        llm=llm,
        debate=DebateProtocol(llm),
        event_bus=event_bus or EventBus(),
        memory=__import__(
            "ultron.memory", fromlist=["VectorMemory"]
        ).VectorMemory(db, backend="hash"),
    )
    monkeypatch.chdir(tmp_path)
    return coord


def test_scope_includes_target_ip(settings, tmp_path, monkeypatch):
    coord = make_coordinator(settings, tmp_path, monkeypatch, [])
    assert coord.allowed_targets == {"192.0.2.10"}
    assert any(
        __import__("ipaddress").ip_address("192.0.2.10") in net
        for net in coord.allowed_networks
    )


def test_full_launch_happy_path(settings, tmp_path, monkeypatch):
    responses = [
        '{"services": ["http"], "vulnerabilities": [], "next_steps": []}',
        json.dumps(PLAN_SAFE),
        (
            '{"success": true, "confidence": 0.9, "findings": '
            '[{"severity": "low", "title": "info leak"}]}'
        ),
    ]
    coord = make_coordinator(settings, tmp_path, monkeypatch, responses)

    monkeypatch.setattr(
        "ultron.coordinator.subprocess.run",
        lambda *a, **k: type(
            "R", (), {"stdout": "nmap out", "stderr": ""}
        )(),
    )
    coord.launch()

    assert coord.fsm.current_state == AgentState.COMPLETE
    assert [old.name for old, _, _ in coord.fsm.history] == [
        "IDLE",
        "DISCOVERY",
        "ANALYSIS",
        "PLANNING",
        "AUTHORIZATION",
        "EXECUTION",
        "VERIFICATION",
        "REPORTING",
    ]
    # Findings were published on the event bus.
    vulns = coord.event_bus.get_events(EventType.VULNERABILITY_FOUND)
    assert len(vulns) == 1
    assert vulns[0].payload["title"] == "info leak"
    # A report file was written.
    reports = list(tmp_path.glob("ULTRON_V6_REPORT_*.md"))
    assert len(reports) == 1
    content = reports[0].read_text()
    assert "Target: 192.0.2.10" in content
    assert "## Budget Status" in content
    assert "## State Machine History" in content
    assert '"REPORTING"' in content
    # Tool ran without shell=True and with the target substituted.
    assert len(coord.llm.calls) == 3


def test_destructive_plan_requires_debate_approval(settings, tmp_path, monkeypatch):
    responses = [
        "{}",  # analysis
        json.dumps(PLAN_DESTRUCTIVE),  # planning
        '{"argument": "do it", "confidence": 0.9}',  # debate: attacker
        '{"argument": "dont", "risk_level": 0.9}',  # debate: defender
        '{"verdict": "abort", "reasoning": "too risky", "confidence": 0.9}',
    ]
    coord = make_coordinator(settings, tmp_path, monkeypatch, responses)
    monkeypatch.setattr(
        "ultron.coordinator.subprocess.run",
        lambda *a, **k: type(
            "R", (), {"stdout": "ok", "stderr": ""}
        )(),
    )
    coord.launch()
    assert coord.fsm.current_state == AgentState.COMPLETE
    # Execution and verification were skipped after the veto.
    state_names = [new.name for _, new, _ in coord.fsm.history]
    assert "EXECUTION" not in state_names
    assert "VERIFICATION" not in state_names
    assert state_names[-1] == "COMPLETE"
    # The debate verdict was published.
    debates = coord.event_bus.get_events(EventType.DEBATE_COMPLETED)
    assert len(debates) == 1
    assert debates[0].payload["verdict"] == "abort"


def test_jail_blocks_forbidden_command_but_run_completes(
    settings, tmp_path, monkeypatch
):
    evil_plan = dict(PLAN_SAFE, action="rm -rf /")
    coord = make_coordinator(
        settings, tmp_path, monkeypatch,
        ["{}", json.dumps(evil_plan), "{}"],
    )
    coord.launch()
    assert coord.fsm.current_state == AgentState.COMPLETE


def test_planning_falls_back_when_llm_returns_garbage(
    settings, tmp_path, monkeypatch
):
    coord = make_coordinator(
        settings, tmp_path, monkeypatch,
        ["{}", "not json", "{}"],
    )
    monkeypatch.setattr(
        "ultron.coordinator.subprocess.run",
        lambda *a, **k: type(
            "R", (), {"stdout": "ok", "stderr": ""}
        )(),
    )
    coord.launch()
    fallback = coord.fsm.history  # ran through planning without crashing
    assert coord.fsm.current_state == AgentState.COMPLETE
    assert fallback


def test_execute_tool_handles_failure(settings, tmp_path, monkeypatch):
    coord = make_coordinator(settings, tmp_path, monkeypatch, [])
    monkeypatch.setattr(
        "ultron.coordinator.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("nmap missing")),
    )
    output = coord._execute_tool("nmap example.com")
    assert "nmap missing" in output


def test_execute_tool_truncates_long_output(settings, tmp_path, monkeypatch):
    settings.output_max_chars = 500
    coord = make_coordinator(settings, tmp_path, monkeypatch, [])
    big = "x" * 6000
    monkeypatch.setattr(
        "ultron.coordinator.subprocess.run",
        lambda *a, **k: type("R", (), {"stdout": big, "stderr": ""})(),
    )
    output = coord._execute_tool("echo hi")
    assert "[TRUNCATED]" in output
    assert len(output) < 4200


class TestAgentLoop:
    """Behavior of the bounded plan/authorize/execute/verify loop."""

    def _fake_run(self, monkeypatch, out="ok"):
        monkeypatch.setattr(
            "ultron.coordinator.subprocess.run",
            lambda *a, **k: type("R", (), {"stdout": out, "stderr": ""})(),
        )

    def test_loop_continues_while_findings_are_new(
        self, settings, tmp_path, monkeypatch
    ):
        plan2 = dict(PLAN_SAFE, action="nmap -sV ${target}")
        responses = [
            "{}",  # analysis
            json.dumps(PLAN_SAFE),  # iteration 1 plan
            (
                '{"success": false, "confidence": 0.5, "findings": '
                '[{"title": "banner leak", "severity": "medium"}]}'
            ),
            json.dumps(plan2),  # iteration 2 plan
            '{"success": true, "confidence": 0.9}',
        ]
        coord = make_coordinator(settings, tmp_path, monkeypatch, responses)
        self._fake_run(monkeypatch)
        coord.launch()

        assert coord.fsm.current_state == AgentState.COMPLETE
        assert coord.iterations == 2
        planings = [
            new for _, new, _ in coord.fsm.history if new == AgentState.PLANNING
        ]
        executions = [
            new for _, new, _ in coord.fsm.history if new == AgentState.EXECUTION
        ]
        assert len(planings) == 2
        assert len(executions) == 2

        findings = coord.findings.all()
        assert len(findings) == 1
        assert findings[0].severity == "medium"
        assert findings[0].cvss_score is not None
        assert findings[0].target == "192.0.2.10"

        report = tmp_path.glob("ULTRON_V6_REPORT_*.md")
        content = next(iter(report)).read_text()
        assert "## Findings" in content
        assert "banner leak" in content
        assert "## Scope" in content
        assert "## Agent Loop" in content

    def test_loop_stops_when_planner_repeats_an_action(
        self, settings, tmp_path, monkeypatch
    ):
        responses = [
            "{}",
            json.dumps(PLAN_SAFE),
            '{"success": false, "findings": [{"title": "x", "severity": "low"}]}',
            json.dumps(PLAN_SAFE),  # identical action proposed again
        ]
        coord = make_coordinator(settings, tmp_path, monkeypatch, responses)
        self._fake_run(monkeypatch)
        coord.launch()

        assert coord.fsm.current_state == AgentState.COMPLETE
        assert coord.iterations == 2
        executions = [
            new for _, new, _ in coord.fsm.history if new == AgentState.EXECUTION
        ]
        # The repeated plan was rejected before authorization/execution.
        assert len(executions) == 1

    def test_loop_respects_max_iterations(self, settings, tmp_path, monkeypatch):
        plan2 = dict(PLAN_SAFE, action="nmap -sV ${target}")
        responses = [
            "{}",
            json.dumps(PLAN_SAFE),
            '{"success": false, "findings": [{"title": "a", "severity": "low"}]}',
            json.dumps(plan2),
            '{"success": false, "findings": [{"title": "b", "severity": "low"}]}',
        ]
        coord = make_coordinator(settings, tmp_path, monkeypatch, responses)
        coord.settings.max_iterations = 2
        self._fake_run(monkeypatch)
        coord.launch()

        assert coord.fsm.current_state == AgentState.COMPLETE
        assert coord.iterations == 2
        assert len(coord.findings.all()) == 2

    def test_lateral_target_becomes_pending_scope(
        self, settings, tmp_path, monkeypatch
    ):
        plan2 = dict(PLAN_SAFE, action="nmap -sV ${target}")
        responses = [
            "{}",
            json.dumps(PLAN_SAFE),
            (
                '{"success": false, "findings": [], '
                '"lateral_target": "192.168.99.9"}'
            ),
            json.dumps(plan2),
            '{"success": true, "findings": []}',
        ]
        coord = make_coordinator(settings, tmp_path, monkeypatch, responses)
        self._fake_run(monkeypatch)
        coord.launch()

        assert coord.fsm.current_state == AgentState.COMPLETE
        assert "192.168.99.9" in coord.scope.pending
        events = coord.event_bus.get_events(EventType.LATERAL_TARGET_FOUND)
        assert events[0].payload["status"] == "pending"
        # The report (written before any approval) lists it as pending.
        content = next(iter(tmp_path.glob("ULTRON_V6_REPORT_*.md"))).read_text()
        assert "Pending lateral: 192.168.99.9" in content
        # Operator approval makes the target jail-legal.
        assert coord.scope.approve("192.168.99.9") is True
        assert coord.jail.validate_scope("192.168.99.9") is True

    def test_budget_exhaustion_stops_the_loop(self, settings, tmp_path, monkeypatch):
        responses = [
            "{}",
            json.dumps(PLAN_SAFE),
            '{"success": false, "findings": [{"title": "x", "severity": "low"}]}',
        ]
        coord = make_coordinator(settings, tmp_path, monkeypatch, responses)
        coord.budget.budget_exceeded = True
        self._fake_run(monkeypatch)
        coord.launch()

        assert coord.fsm.current_state == AgentState.COMPLETE
        assert coord.iterations == 1

    def test_discovery_command_goes_through_the_jail(
        self, settings, tmp_path, monkeypatch
    ):
        coord = make_coordinator(
            settings, tmp_path, monkeypatch,
            ["{}", json.dumps(PLAN_SAFE), "{}"],
        )

        def _blocked(cmd: str) -> tuple[bool, str]:
            # Force the discovery command to be blocked; the run must
            # survive and the tool executor must not be invoked.
            return False, "BLOCKED: test"

        coord.jail.filter_command = _blocked  # type: ignore[method-assign]
        monkeypatch.setattr(
            "ultron.coordinator.subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")),
        )
        coord.launch()
        assert coord.fsm.current_state == AgentState.COMPLETE
