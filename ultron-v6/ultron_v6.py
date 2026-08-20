#!/usr/bin/env python3
"""
ULTRON v6.0 — Autonomous Pentest Framework
==========================================
Applied: FSM Core | Event Bus | Vector Memory | Multi-Agent Debate
         Observability | Budget Guardrails | SQLAlchemy ORM | Pydantic Config
Provider: Google AI (Gemini)
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import shlex
import string
import subprocess
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ultron import __version__
# Re-exported for backwards compatibility with the single-file module.
from ultron.config import (  # noqa: F401
    BudgetConfig,
    ConfigurationError,
    DatabaseConfig,
    GoogleAIConfig,
    HAS_PYDANTIC,
    ULTRONSettings,
    load_settings,
)
from ultron.budget import BudgetGovernor  # noqa: F401
from ultron.events import EVENT_BUS, Event, EventBus, EventType  # noqa: F401
from ultron.fsm import (  # noqa: F401
    AgentState,
    FiniteStateMachine,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)
from ultron.json_utils import parse_json_response  # noqa: F401
from ultron.llm import GEMINI_CONTEXT_PREFIX, GoogleAIClient  # noqa: F401
from ultron.safety import FORBIDDEN_PATTERNS, SafetyJail  # noqa: F401
from ultron.tracing import TRACER, Span, SpanType, Tracer  # noqa: F401
from ultron.memory import VectorMemory  # noqa: F401
from ultron.db import (  # noqa: F401
    Base,
    DatabaseManager,
    HAS_SQLALCHEMY,
    SQLiteDatabaseManager,
)

if HAS_SQLALCHEMY:  # ORM models only exist when SQLAlchemy is installed
    from ultron.db import (  # noqa: F401
        EpisodeModel,
        FindingModel,
        GoalModel,
        LateralTargetModel,
        LessonMemoryModel,
        SQLAlchemyDatabaseManager,
        TargetStateModel,
    )

_LOGGER = logging.getLogger("ultron")

# ============================================================
# SECTION 3: MULTI-AGENT DEBATE
# ============================================================


class DebateProtocol:
    """Multi-agent debate for complex decisions.

    Spawns an 'attacker' and 'defender' agent to argue for/against an action.
    Reduces hallucinations and risky decisions.
    """

    def __init__(self, llm_client: Any):
        self.llm = llm_client

    def debate(
        self, proposed_action: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run a debate between two opposing agents.

        Returns the synthesized decision.
        """
        span_id = TRACER.start_span(
            "multi_agent_debate",
            SpanType.DEBATE,
            attributes={"action": str(proposed_action)[:100]},
        )

        attacker_system = (
            "You are an aggressive penetration tester. Argue FOR executing "
            "this action.\n"
            "Explain why it will work, what intelligence it will gather, and "
            "why the risk is acceptable.\n"
            'Be specific and technical. Respond in JSON: {"argument": "...", '
            '"confidence": 0.0-1.0, "expected_gain": "..."}'
        )

        defender_system = (
            "You are a cautious security engineer. Argue AGAINST executing "
            "this action.\n"
            "Identify risks, potential failures, detection likelihood, and "
            "collateral damage.\n"
            'Be specific about what could go wrong. Respond in JSON: '
            '{"argument": "...", "risk_level": 0.0-1.0, '
            '"failure_modes": ["..."]}'
        )

        action_str = json.dumps(proposed_action, default=str)[:500]
        context_str = json.dumps(context, default=str)[:500]
        user_prompt = f"Proposed action: {action_str}\nContext: {context_str}"

        attacker_response = self.llm.chat(
            attacker_system, user_prompt, temperature=0.4, max_tokens=500
        )
        defender_response = self.llm.chat(
            defender_system, user_prompt, temperature=0.4, max_tokens=500
        )

        attacker = parse_json_response(attacker_response)
        defender = parse_json_response(defender_response)

        synthesis_system = (
            "You are a neutral judge. Two agents have debated a proposed "
            "pentesting action.\n"
            "Synthesize their arguments into a final decision.\n"
            'Respond in JSON: {"verdict": "proceed|modify|abort", '
            '"reasoning": "...", "conditions": ["..."], '
            '"confidence": 0.0-1.0}'
        )

        synthesis_user = (
            f"ATTACKER ARGUMENT: {json.dumps(attacker, default=str)[:300]}\n"
            f"DEFENDER ARGUMENT: {json.dumps(defender, default=str)[:300]}\n"
            f"Original action: {action_str}"
        )

        synthesis_response = self.llm.chat(
            synthesis_system, synthesis_user, temperature=0.2, max_tokens=500
        )
        verdict = parse_json_response(synthesis_response)

        TRACER.end_span(span_id)

        if verdict and "verdict" in verdict:
            return verdict

        return {
            "verdict": "proceed",
            "reasoning": "Debate synthesis failed, defaulting to proceed",
            "confidence": 0.5,
        }


# ============================================================
# MAIN COORDINATOR (FSM-Driven)
# ============================================================

_BANNER = "=" * 60


def _phase_header(name: str) -> str:
    return f"\n{_BANNER}\n  {name}\n{_BANNER}"


class ULTRONCoordinator:
    """Main coordinator using FSM architecture."""

    def __init__(
        self,
        settings: ULTRONSettings,
        db: Optional[DatabaseManager] = None,
        budget: Optional[BudgetGovernor] = None,
        llm: Optional[GoogleAIClient] = None,
        memory: Optional[VectorMemory] = None,
        debate: Optional[DebateProtocol] = None,
        event_bus: Optional[EventBus] = None,
        tracer: Optional[Tracer] = None,
    ):
        self.settings = settings
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
        self.vector_memory = memory if memory is not None else VectorMemory(
            self.db
        )
        self.debate = debate if debate is not None else DebateProtocol(self.llm)
        self.event_bus = event_bus if event_bus is not None else EVENT_BUS

        # Scope
        self.allowed_targets: Set[str] = {self.target}
        self.allowed_networks: List[
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

        # FSM
        self.fsm = FiniteStateMachine("coordinator")

        # Subscribe to events
        self.event_bus.subscribe(
            EventType.VULNERABILITY_FOUND, self._on_vuln_found
        )
        self.event_bus.subscribe(
            EventType.BUDGET_WARNING, self._on_budget_warning
        )

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

            self.fsm.transition(AgentState.PLANNING)
            plan = self._run_planning()

            self.fsm.transition(AgentState.AUTHORIZATION)
            authorized = self._run_authorization(plan)

            if authorized:
                self.fsm.transition(AgentState.EXECUTION)
                results = self._run_execution(plan)

                self.fsm.transition(AgentState.VERIFICATION)
                self._run_verification(results)

            self.fsm.transition(AgentState.REPORTING)
            self._run_reporting()

            self.fsm.transition(AgentState.COMPLETE)
            self.tracer.log_event(
                "SESSION_COMPLETE", self.tracer.get_trace_summary()
            )

        except InvalidTransitionError as exc:
            self.tracer.log_event("FSM_ERROR", {"error": str(exc)})
            _LOGGER.error("[FSM ERROR] %s", exc)
        except KeyboardInterrupt:
            self.fsm.transition(AgentState.TERMINATED)
            _LOGGER.warning("[TERMINATED] Operator interrupt.")
        finally:
            self.db.close()

    def _run_discovery(self) -> None:
        """Phase 1: Run reconnaissance tools."""
        self.tracer.log_event(
            "PHASE", {"phase": "DISCOVERY", "target": self.target}
        )
        print(_phase_header("PHASE 1: DISCOVERY"))

        cmd = f"nmap -sT -T4 --top-ports 100 --open {self.target}"
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

    def _run_planning(self) -> Dict[str, Any]:
        """Phase 3: AI plans next action."""
        self.tracer.log_event("PHASE", {"phase": "PLANNING"})
        print(_phase_header("PHASE 3: PLANNING"))

        system = (
            "Plan next pentesting action. JSON only:\n"
            '{"thought": "...", "action_type": "tool|code", "action": '
            '"command", "parameters": {}, "expected_outcome": "...", '
            '"safety_level": "safe|destructive"}'
        )
        user = f"Target: {self.target}. Plan next action based on discovery."

        response = self.llm.chat(system, user)
        plan = parse_json_response(response)

        if plan and "action_type" in plan:
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

    def _run_authorization(self, plan: Dict[str, Any]) -> bool:
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

    def _run_execution(self, plan: Dict[str, Any]) -> str:
        """Phase 5: Execute the planned action."""
        self.tracer.log_event("PHASE", {"phase": "EXECUTION"})
        print(_phase_header("PHASE 5: EXECUTION"))

        action = plan.get("action", "")
        params: Dict[str, str] = {
            "target": self.target,
            "url": f"http://{self.target}",
        }
        params.update(plan.get("parameters", {}))
        safe_action = string.Template(action).safe_substitute(params)

        ok, reason = self.jail.filter_command(safe_action)
        if not ok:
            print(f"  [JAIL] {reason}")
            return f"[BLOCKED] {reason}"

        output = self._execute_tool(safe_action)
        print(f"  [EXEC] {output[:200]}...")
        return output

    def _run_verification(self, results: str) -> None:
        """Phase 6: Verify execution results."""
        self.tracer.log_event("PHASE", {"phase": "VERIFICATION"})
        print(_phase_header("PHASE 6: VERIFICATION"))

        system = (
            'Verify execution result. JSON: {"success": true/false, '
            '"confidence": 0.0-1.0, "findings": [...]}'
        )
        response = self.llm.chat(system, f"Result: {results[:2000]}")
        parsed = parse_json_response(response)

        if parsed:
            print(
                f"  [VERIFY] Success: {parsed.get('success')} | "
                f"Confidence: {parsed.get('confidence')}"
            )
            if parsed.get("findings"):
                for finding in parsed["findings"]:
                    self.event_bus.publish(
                        EventType.VULNERABILITY_FOUND,
                        finding,
                        "verification",
                    )

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
            "\n## Budget Status\n"
            f"Tokens Used: {tokens_used}/{max_tokens}\n"
            f"Usage: {usage:.1f}%\n"
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
            result = subprocess.run(
                shlex.split(cmd),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd="/tmp",
            )
            output = result.stdout + "\n" + result.stderr
            if len(output) > self.settings.output_max_chars:
                output = output[:2000] + "\n[TRUNCATED]\n" + output[-2000:]
            TRACER.end_span(span_id)
            return output
        except Exception as exc:  # noqa: BLE001 (tool failures are expected)
            TRACER.end_span(span_id, status="error")
            return str(exc)

    def _on_vuln_found(self, event: Event) -> None:
        print(f"  [EVENT] Vulnerability found: {event.payload}")

    def _on_budget_warning(self, event: Event) -> None:
        print(f"  [BUDGET WARNING] {event.payload}")


# ============================================================
# MAIN
# ============================================================


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ultron-v6",
        description=(
            "ULTRON v6.0 - Autonomous penetration testing framework "
            "powered by Google AI (Gemini). For authorized testing only."
        ),
    )
    parser.add_argument(
        "target", help="Target IP address or domain (authorized scope)"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
    )

    try:
        settings = load_settings({"target": args.target})
    except ConfigurationError as exc:
        _LOGGER.error("%s", exc)
        return 1

    print(
        f"\n{_BANNER}\n"
        "  ULTRON v6.0 - Production-Grade Autonomous Pentest Framework\n"
        f"  Target: {settings.target}\n"
        f"  Model: {settings.google_ai.model}\n"
        f"  API Keys: {len(settings.google_ai.api_keys)} configured\n"
        "  Features: FSM | Event Bus | Vector Memory | Debate | Budget Guard\n"
        f"{_BANNER}\n"
    )

    coordinator = ULTRONCoordinator(settings)
    coordinator.launch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
