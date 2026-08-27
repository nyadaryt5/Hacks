"""FSM-driven orchestration of the pentest phases.

:class:`ULTRONCoordinator` wires the FSM, event bus, vector memory, budget
governor, LLM client, debate protocol, safety jail, scope manager and
finding store together, and drives the pentest phases to a final markdown
report. The core of the run is a *bounded agent loop* (plan → authorize →
execute → verify) that keeps iterating while the verifier reports new
progress and stops on success, veto, jail block, budget exhaustion or a
repeated action. Every dependency is injectable so the whole pipeline can
be exercised without network access.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import shlex
import string

# Command execution is an intentional framework boundary. Every command is
# scope/denylist checked before this module invokes it with shell=False.
import subprocess  # nosec B404
import tempfile
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ultron.budget import BudgetGovernor
from ultron.db import DatabaseManager
from ultron.debate import DebateProtocol
from ultron.errors import capture_exception, init_error_tracking
from ultron.events import EVENT_BUS, Event, EventBus, EventType
from ultron.fsm import (
    AgentState,
    FiniteStateMachine,
    InvalidTransitionError,
)
from ultron.json_utils import parse_json_response
from ultron.llm import GoogleAIClient
from ultron.memory import VectorMemory
from ultron.safety import SafetyJail
from ultron.scope import ScopeManager
from ultron.tracing import TRACER, SpanType, Tracer
from ultron.vulns import FindingStore

if TYPE_CHECKING:  # pragma: no cover
    from ultron.config import ULTRONSettings

_LOGGER = logging.getLogger(__name__)

_BANNER = "=" * 60

# Child tools are untrusted relative to the coordinator process. Do not leak
# model, cloud, Vault, or telemetry credentials through inherited env vars.
_SENSITIVE_TOOL_ENV = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "ULTRON_SENTRY_DSN",
    "ULTRON_VAULT_TOKEN",
    "VAULT_TOKEN",
}


def _tool_environment() -> dict[str, str]:
    """Return a subprocess environment with coordinator secrets removed."""
    return {
        name: value
        for name, value in os.environ.items()
        if name not in _SENSITIVE_TOOL_ENV
        and name != "GOOGLE_API_KEY"
        and not name.startswith("GOOGLE_API_KEY_")
    }


def _phase_header(name: str) -> str:
    return f"\n{_BANNER}\n  {name}\n{_BANNER}"


class ULTRONCoordinator:
    """Main coordinator using FSM architecture."""

    def __init__(  # noqa: PLR0913 (dependency-injection container)
        self,
        settings: ULTRONSettings,
        *,
        db: Any | None = None,
        budget: BudgetGovernor | None = None,
        llm: GoogleAIClient | None = None,
        memory: VectorMemory | None = None,
        debate: DebateProtocol | None = None,
        event_bus: EventBus | None = None,
        tracer: Tracer | None = None,
        findings: FindingStore | None = None,
        scope: ScopeManager | None = None,
    ):
        self.settings = settings
        init_error_tracking()
        self.target = settings.target
        self.session_id = (
            f"ULTRON_{uuid.uuid4().hex[:8]}_{self.target.replace('.', '_')}"
        )
        self.tracer = tracer if tracer is not None else TRACER

        # Initialize components
        self.db = db if db is not None else DatabaseManager(
            getattr(settings.database, "url", "sqlite:///ultron_v6.db")
        )
        self.budget = budget if budget is not None else BudgetGovernor(settings)
        self.llm = llm if llm is not None else GoogleAIClient(
            settings, self.budget
        )
        self.vector_memory = (
            memory if memory is not None else VectorMemory(self.db)
        )
        self.debate = debate if debate is not None else DebateProtocol(self.llm)
        self.event_bus = event_bus if event_bus is not None else EVENT_BUS

        # Scope
        self.allowed_targets: set[str] = {self.target}
        self.allowed_networks: list[
            ipaddress.IPv4Network | ipaddress.IPv6Network
        ] = []
        try:
            ipaddress.ip_address(self.target)
            self.allowed_networks.append(
                ipaddress.ip_network(f"{self.target}/32", strict=False)
            )
        except ValueError:
            pass
        self.jail = SafetyJail(self.allowed_targets, self.allowed_networks)
        self.scope = (
            scope
            if scope is not None
            else ScopeManager(
                self.jail,
                self.event_bus,
                db=self.db,
                session_id=self.session_id,
                max_lateral_depth=getattr(settings, "max_lateral_depth", 2),
            )
        )
        self.findings = (
            findings
            if findings is not None
            else FindingStore(
                self.db, target=self.target, session_id=self.session_id
            )
        )

        # Agent loop state
        self.iterations = 0
        self._executed_actions: set[str] = set()

        # FSM
        self.fsm = FiniteStateMachine("coordinator")

        # Subscribe to events
        self.event_bus.subscribe(
            EventType.VULNERABILITY_FOUND, self._on_vuln_found
        )
        self.event_bus.subscribe(
            EventType.BUDGET_WARNING, self._on_budget_warning
        )

    def close(self) -> None:
        """Release resources owned by the coordinator."""
        self.db.close()
        close_llm = getattr(self.llm, "close", None)
        if close_llm is not None:
            close_llm()

    def launch(self) -> None:
        """Main execution flow driven by FSM."""
        self.tracer.log_event(
            "SESSION_START",
            {"target": self.target, "session": self.session_id},
        )

        try:
            self.fsm.transition(AgentState.DISCOVERY)
            self._run_discovery()

            self.fsm.transition(AgentState.ANALYSIS)
            self._run_analysis()

            self._run_agent_loop()

            self.fsm.transition(AgentState.REPORTING)
            self._run_reporting()

            self.fsm.transition(AgentState.COMPLETE)
            self.tracer.log_event(
                "SESSION_COMPLETE", self.tracer.get_trace_summary()
            )

        except InvalidTransitionError as exc:
            self.tracer.log_event("FSM_ERROR", {"error": str(exc)})
            capture_exception(exc, session=self.session_id, target=self.target)
            _LOGGER.error("[FSM ERROR] %s", exc)
        except KeyboardInterrupt:
            self.fsm.transition(AgentState.TERMINATED)
            _LOGGER.warning("[TERMINATED] Operator interrupt.")
        finally:
            self.close()

    # -- agent loop ---------------------------------------------------------

    def _run_agent_loop(self) -> None:
        """Bounded plan → authorize → execute → verify loop.

        Stops when the goal is achieved (verification success), the plan is
        vetoed, execution is jail-blocked, the token budget is exhausted,
        the planner repeats a previously executed action, no new progress
        is made, or ``max_iterations`` is reached.
        """
        max_iterations = max(1, int(getattr(self.settings, "max_iterations", 30)))

        for _ in range(max_iterations):
            self.iterations += 1
            self.fsm.transition(AgentState.PLANNING)
            plan = self._run_planning(self.iterations)
            action_key = self._action_key(plan)
            if action_key in self._executed_actions:
                _LOGGER.info(
                    "Planner repeated action %r; ending agent loop.",
                    action_key,
                )
                break

            self.fsm.transition(AgentState.AUTHORIZATION)
            if not self._run_authorization(plan):
                _LOGGER.info("Plan vetoed at authorization; ending agent loop.")
                break

            self.fsm.transition(AgentState.EXECUTION)
            results, blocked = self._run_execution(plan)
            self._executed_actions.add(action_key)

            self.fsm.transition(AgentState.VERIFICATION)
            progress, success = self._run_verification(results)

            if success:
                _LOGGER.info("Verification reports success; goal achieved.")
                break
            if blocked:
                _LOGGER.info("Execution blocked by safety jail; ending loop.")
                break
            if not progress:
                _LOGGER.info("No new progress from verification; ending loop.")
                break
            if self.budget.budget_exceeded:
                _LOGGER.warning("Token budget exceeded; ending agent loop.")
                break
            # Otherwise continue: VERIFICATION -> PLANNING is a legal
            # FSM transition, so the next cycle plans from fresh context.

    @staticmethod
    def _action_key(plan: dict[str, Any]) -> str:
        """Canonical form of a plan's action, used for repeat detection."""
        action = plan.get("action", "") if isinstance(plan, dict) else str(plan)
        return str(action).strip().lower()

    # -- phases -------------------------------------------------------------

    def _run_discovery(self) -> None:
        """Phase 1: Run reconnaissance tools."""
        self.tracer.log_event(
            "PHASE", {"phase": "DISCOVERY", "target": self.target}
        )
        print(_phase_header("PHASE 1: DISCOVERY"))

        cmd = f"nmap -sT -T4 --top-ports 100 --open {self.target}"
        ok, reason = self.jail.filter_command(cmd)
        if not ok:
            _LOGGER.warning("Discovery command blocked by jail: %s", reason)
            output = f"[BLOCKED] {reason}"
        else:
            output = self._execute_tool(cmd)
        print(f"  [DISCOVERY] {output[:200]}...")

        self.vector_memory.store_lesson(
            situation=f"Initial recon of {self.target}",
            action=cmd,
            outcome=output[:200],
            success=True,
            session_id=self.session_id,
        )

    def _run_analysis(self) -> None:
        """Phase 2: Analyze discovery results with AI."""
        self.tracer.log_event("PHASE", {"phase": "ANALYSIS"})
        print(_phase_header("PHASE 2: ANALYSIS"))

        lessons = self.vector_memory.get_relevant_lessons(
            {"target": self.target}, limit=3
        )
        if lessons:
            print(f"  [MEMORY] Found {len(lessons)} relevant past lessons")

        system = (
            'Analyze scan results. JSON: {"services": [...], '
            '"vulnerabilities": [...], "next_steps": [...]}'
        )
        response = self.llm.chat(
            system, f"Target: {self.target}. Analyze and suggest next steps."
        )
        parsed = parse_json_response(response)
        if parsed:
            print(f"  [ANALYSIS] {json.dumps(parsed, default=str)[:200]}")

    def _run_planning(self, iteration: int) -> dict[str, Any]:
        """Phase 3: AI plans next action."""
        self.tracer.log_event("PHASE", {"phase": "PLANNING", "iteration": iteration})
        print(_phase_header(f"PHASE 3: PLANNING (iteration {iteration})"))

        system = (
            "Plan next pentesting action. JSON only:\n"
            '{"thought": "...", "action_type": "tool|code", "action": '
            '"command", "parameters": {}, "expected_outcome": "...", '
            '"safety_level": "safe|destructive"}'
        )
        executed = sorted(self._executed_actions)
        user = (
            f"Target: {self.target}. Plan next action based on discovery.\n"
            f"Iteration: {iteration}.\n"
            f"Already executed: {executed if executed else 'none'}\n"
            f"Findings so far: {len(self.findings.all())}"
        )

        response = self.llm.chat(system, user)
        plan = parse_json_response(response)

        if isinstance(plan, dict) and "action_type" in plan:
            if not isinstance(plan.get("parameters"), dict):
                plan["parameters"] = {}
            print(f"  [PLAN] {plan.get('thought', '')[:100]}")
            return plan

        return {
            "thought": "Fallback",
            "action_type": "tool",
            "action": f"whatweb {self.target}",
            "parameters": {},
            "expected_outcome": "Web tech ID",
            "safety_level": "safe",
        }

    def _run_authorization(self, plan: dict[str, Any]) -> bool:
        """Phase 4: Multi-agent debate for authorization."""
        self.tracer.log_event("PHASE", {"phase": "AUTHORIZATION"})
        print(_phase_header("PHASE 4: AUTHORIZATION (Multi-Agent Debate)"))

        if plan.get("safety_level") == "destructive":
            print("  [DEBATE] Destructive action detected. Initiating debate...")
            verdict = self.debate.debate(plan, {"target": self.target})
            print(
                f"  [VERDICT] {verdict.get('verdict', 'proceed')} - "
                f"{verdict.get('reasoning', '')[:100]}"
            )
            self.event_bus.publish(
                EventType.DEBATE_COMPLETED, verdict, "debate_protocol"
            )
            return verdict.get("verdict") == "proceed"

        print("  [AUTH] Safe action, proceeding.")
        return True

    def _run_execution(self, plan: dict[str, Any]) -> tuple[str, bool]:
        """Phase 5: Execute the planned action. Returns (output, blocked)."""
        self.tracer.log_event("PHASE", {"phase": "EXECUTION"})
        print(_phase_header("PHASE 5: EXECUTION"))

        action = plan.get("action", "")
        params: dict[str, str] = {
            "target": self.target,
            "url": f"http://{self.target}",
        }
        params.update(plan.get("parameters", {}))
        safe_action = string.Template(action).safe_substitute(params)

        ok, reason = self.jail.filter_command(safe_action)
        if not ok:
            print(f"  [JAIL] {reason}")
            self.event_bus.publish(
                EventType.ERROR_OCCURRED,
                {"phase": "execution", "reason": reason, "command": safe_action[:200]},
                "safety_jail",
            )
            return f"[BLOCKED] {reason}", True

        output = self._execute_tool(safe_action)
        print(f"  [EXEC] {output[:200]}...")
        return output, False

    def _run_verification(self, results: str) -> tuple[bool, bool]:
        """Phase 6: Verify execution results. Returns (progress, success)."""
        self.tracer.log_event("PHASE", {"phase": "VERIFICATION"})
        print(_phase_header("PHASE 6: VERIFICATION"))

        system = (
            'Verify execution result. JSON: {"success": true/false, '
            '"confidence": 0.0-1.0, "findings": [...], '
            '"lateral_target": "..."}'
        )
        response = self.llm.chat(system, f"Result: {results[:2000]}")
        parsed = parse_json_response(response)

        progress = False
        success = False
        if isinstance(parsed, dict):
            success = bool(parsed.get("success"))
            findings = parsed.get("findings") or []
            if isinstance(findings, (str, int, float)):
                findings = [findings]
            for item in findings:
                finding, is_new = self.findings.record(item, phase="VERIFICATION")
                if is_new:
                    progress = True
                    self.event_bus.publish(
                        EventType.VULNERABILITY_FOUND,
                        finding.to_payload(),
                        "verification",
                    )
            lateral = parsed.get("lateral_target")
            if lateral:
                decision = self.scope.request(
                    str(lateral),
                    evidence=str(parsed.get("lateral_evidence", ""))[:200],
                    source="verification",
                )
                print(f"  [SCOPE] {decision['status']}: {decision['target']}")
                if decision["status"] == "pending":
                    progress = True
            print(
                f"  [VERIFY] Success: {success} | "
                f"Confidence: {parsed.get('confidence')}"
            )
        return progress, success

    def _run_reporting(self) -> None:
        """Phase 7: Generate final report."""
        self.tracer.log_event("PHASE", {"phase": "REPORTING"})
        print(_phase_header("PHASE 7: REPORTING"))

        budget_status = self.budget.get_status()
        trace_summary = self.tracer.get_trace_summary()
        tokens_used = budget_status["tokens_used_session"]
        max_tokens = budget_status["max_tokens_session"]
        usage = budget_status["usage_percent"]
        total_spans = trace_summary["total_spans"]
        total_tokens = trace_summary["total_tokens"]
        total_duration = trace_summary["total_duration_ms"]
        history = json.dumps(
            [(old.name, new.name) for old, new, _ in self.fsm.history],
            indent=2,
        )

        report = (
            "# ULTRON v6.0 Pentest Report\n"
            f"Target: {self.target}\n"
            f"Session: {self.session_id}\n"
            f"Date: {datetime.now().isoformat()}\n"
            "\n## Agent Loop\n"
            f"Iterations: {self.iterations}\n"
            f"Actions executed: {len(self._executed_actions)}\n"
            "\n## Budget Status\n"
            f"Tokens Used: {tokens_used}/{max_tokens}\n"
            f"Usage: {usage:.1f}%\n"
            "\n## Findings\n"
        )
        findings = self.findings.all()
        if findings:
            report += f"{len(findings)} recorded:\n\n"
            report += "| # | Severity | CVSS | Title |\n"
            report += "|---|----------|------|-------|\n"
            for row in self.findings.report_rows():
                report += f"| {' | '.join(row)} |\n"
        else:
            report += "None recorded.\n"

        scope_summary = self.scope.summary()
        report += (
            "\n## Scope\n"
            f"Authorized: {', '.join(scope_summary['authorized'])}\n"
            f"Pending lateral: "
            f"{', '.join(scope_summary['pending']) or 'none'}\n"
            "\n## Trace Summary\n"
            f"Total Spans: {total_spans}\n"
            f"Total Tokens: {total_tokens}\n"
            f"Total Duration: {total_duration:.0f}ms\n"
            "\n## State Machine History\n"
            f"{history}\n"
        )

        report_file = f"ULTRON_V6_REPORT_{self.session_id}.md"
        with open(report_file, "w", encoding="utf-8") as handle:
            handle.write(report)
        print(f"  [REPORT] Saved: {report_file}")

    def _execute_tool(self, cmd: str, timeout: int = 120) -> str:
        span_id = TRACER.start_span(
            "tool_execution",
            SpanType.TOOL_EXECUTION,
            attributes={"command": cmd[:100]},
        )
        try:
            # SafetyJail filtered this command at the caller; shell expansion
            # remains disabled here. B603 is therefore explicitly accepted.
            result = subprocess.run(  # nosec B603
                shlex.split(cmd),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tempfile.gettempdir(),
                env=_tool_environment(),
                check=False,
                shell=False,
            )
            output = result.stdout + "\n" + result.stderr
            if len(output) > self.settings.output_max_chars:
                output = output[:2000] + "\n[TRUNCATED]\n" + output[-2000:]
            TRACER.end_span(span_id)
            return output
        except Exception as exc:  # noqa: BLE001 (tool failures are expected)
            TRACER.end_span(span_id, status="error")
            capture_exception(exc, command=cmd[:100])
            return str(exc)

    def _on_vuln_found(self, event: Event) -> None:
        print(f"  [EVENT] Vulnerability found: {event.payload}")

    def _on_budget_warning(self, event: Event) -> None:
        print(f"  [BUDGET WARNING] {event.payload}")


__all__ = ["ULTRONCoordinator"]
