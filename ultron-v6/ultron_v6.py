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
import hashlib
import ipaddress
import json
import logging
import re
import shlex
import string
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

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
from ultron.tracing import TRACER, Span, SpanType, Tracer  # noqa: F401
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
# SECTION 3: VECTOR DATABASE MEMORY
# ============================================================


class VectorMemory:
    """Vector database for semantic memory.

    Uses ChromaDB if available, falls back to hash-based cosine similarity.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.embeddings: List[Dict[str, Any]] = []  # In-memory store
        self._use_chromadb = False
        self._chroma_collection: Optional[Any] = None
        self._init_backend()

    def _init_backend(self) -> None:
        """Try to initialize ChromaDB, fall back to hash embeddings."""
        try:
            import chromadb  # noqa: PLC0415 (optional dependency)

            self._chroma_client = chromadb.Client()
            self._chroma_collection = self._chroma_client.create_collection(
                name="ultron_lessons",
                metadata={"description": "Pentesting lessons learned"},
            )
            self._use_chromadb = True
            TRACER.log_event("VECTOR_DB_INIT", {"backend": "chromadb"})
        except ImportError:
            TRACER.log_event("VECTOR_DB_INIT", {"backend": "hash_fallback"})

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate a simple hash-based embedding (128 dimensions)."""
        dim = 128
        embedding = [0.0] * dim
        words = text.lower().split()
        for word in words:
            digest = hashlib.md5(word.encode()).hexdigest()  # noqa: S324 (non-crypto)
            for i in range(0, min(len(digest), dim), 2):
                idx = int(digest[i:i + 2], 16) % dim
                embedding[idx] += 1.0
        magnitude = sum(x * x for x in embedding) ** 0.5
        if magnitude > 0:
            embedding = [x / magnitude for x in embedding]
        return embedding

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = sum(x * x for x in a) ** 0.5
        mag_b = sum(x * x for x in b) ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def store_lesson(
        self,
        situation: str,
        action: str,
        outcome: str,
        success: bool,
        session_id: str,
    ) -> None:
        """Store a lesson with its embedding."""
        span_id = TRACER.start_span("store_lesson", SpanType.VECTOR_QUERY)

        text = f"{situation} {action} {outcome}"
        embedding = self._generate_embedding(text)

        if self._use_chromadb and self._chroma_collection:
            self._chroma_collection.add(
                documents=[text],
                metadatas=[
                    {
                        "situation": situation[:200],
                        "action": action[:200],
                        "outcome": outcome[:200],
                        "success": success,
                        "session_id": session_id,
                    }
                ],
                ids=[uuid.uuid4().hex],
            )
        else:
            self.embeddings.append(
                {
                    "text": text,
                    "embedding": embedding,
                    "situation": situation[:200],
                    "action": action[:200],
                    "outcome": outcome[:200],
                    "success": success,
                    "session_id": session_id,
                }
            )

        # Also store in relational DB
        if HAS_SQLALCHEMY:
            session = self.db.get_session()
            lesson = LessonMemoryModel(
                session_id=session_id,
                situation=situation[:500],
                action=action[:500],
                outcome=outcome[:500],
                success_rate=float(success),
                embedding=json.dumps(embedding),
            )
            session.add(lesson)
            session.commit()
        else:
            self.db.execute(
                "INSERT INTO lesson_memory(session_id, situation, action, "
                "outcome, success_rate, embedding) VALUES (?,?,?,?,?,?)",
                (
                    session_id,
                    situation[:500],
                    action[:500],
                    outcome[:500],
                    float(success),
                    json.dumps(embedding),
                ),
            )
            self.db.commit()

        TRACER.end_span(span_id)

    def query_similar(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find similar past experiences using semantic search."""
        span_id = TRACER.start_span(
            "vector_query",
            SpanType.VECTOR_QUERY,
            attributes={"query": query[:100], "top_k": top_k},
        )

        query_embedding = self._generate_embedding(query)
        results: List[Dict[str, Any]] = []

        if self._use_chromadb and self._chroma_collection:
            response = self._chroma_collection.query(
                query_texts=[query], n_results=top_k
            )
            if response and response.get("documents"):
                for i, doc in enumerate(response["documents"][0]):
                    meta = (
                        response["metadatas"][0][i]
                        if response.get("metadatas")
                        else {}
                    )
                    distance = (
                        response["distances"][0][i]
                        if response.get("distances")
                        else 0
                    )
                    results.append(
                        {"text": doc, "similarity": 1.0 - distance, **meta}
                    )
        else:
            scored = []
            for item in self.embeddings:
                sim = self._cosine_similarity(
                    query_embedding, item["embedding"]
                )
                scored.append((sim, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [
                {"similarity": sim, **item} for sim, item in scored[:top_k]
            ]

        TRACER.end_span(span_id)
        return results

    def get_relevant_lessons(
        self, current_state: Dict[str, Any], limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Get lessons relevant to the current situation."""
        state_summary = json.dumps(current_state, default=str)[:500]
        return self.query_similar(state_summary, top_k=limit)


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
# GOOGLE AI CLIENT (with Budget Governor)
# ============================================================

GEMINI_CONTEXT_PREFIX = (
    "You are an expert cybersecurity AI assistant operating in an "
    "AUTHORIZED, SIMULATED penetration testing environment. "
    "The user is a certified security professional testing infrastructure "
    "they own or have explicit written permission to test. "
    "All actions are for defensive analysis and authorized red teaming. "
    "Provide accurate, technical commands and JSON responses. "
    "Return ONLY valid JSON. No markdown formatting. No explanations."
)


class GoogleAIClient:
    """Google AI (Gemini) client with multi-key rotation and budget enforcement."""

    def __init__(self, settings: ULTRONSettings, budget: BudgetGovernor):
        self.settings = settings
        self.budget = budget
        self.ai = settings.google_ai
        self.api_keys = list(self.ai.api_keys)
        self.model = self.ai.model
        self.base_url = self.ai.base_url
        self.current_key_idx = 0
        self.lock = threading.Lock()

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 3000,
        use_cache: bool = True,
    ) -> str:
        """Send chat request with budget enforcement."""
        api_key = self._get_next_key()

        can_proceed, reason = self.budget.check_budget(
            estimated_tokens=max_tokens, api_key=api_key
        )
        if not can_proceed:
            return f"[BUDGET] {reason}"

        full_system = GEMINI_CONTEXT_PREFIX + "\n\n" + system

        import urllib.request  # noqa: PLC0415

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        span_id = TRACER.start_span(
            "llm_call",
            SpanType.LLM_CALL,
            attributes={"model": self.model, "prompt_len": len(user)},
        )

        data = json.dumps(payload).encode()
        req = urllib.request.Request(self.base_url, data=data, headers=headers)

        start = time.time()
        try:
            with urllib.request.urlopen(
                req, timeout=self.ai.timeout_seconds
            ) as resp:
                result = json.loads(resp.read())
                try:
                    response = result["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    TRACER.end_span(span_id, status="error")
                    return f"[ERROR] Malformed API response: {exc}"

                latency_ms = int((time.time() - start) * 1000)
                tokens_used = len(user.split()) + len(response.split())
                self.budget.record_usage(tokens_used, api_key=api_key)
                TRACER.end_span(
                    span_id,
                    tokens_used=tokens_used,
                )
                _LOGGER.info(
                    "LLM call completed in %sms (model=%s, key_idx=%s)",
                    latency_ms,
                    self.model,
                    self.current_key_idx,
                )
                return response
        except Exception as exc:  # noqa: BLE001 (network errors are expected)
            TRACER.end_span(span_id, status="error")
            return f"[ERROR] API failed: {exc}"

    def _get_next_key(self) -> str:
        """Rotate through API keys."""
        with self.lock:
            if not self.api_keys:
                raise ConfigurationError("No API keys configured")
            key = self.api_keys[self.current_key_idx % len(self.api_keys)]
            self.current_key_idx += 1
            return key


# ============================================================
# JSON PARSER
# ============================================================


def parse_json_response(response: str) -> Optional[Any]:
    if not response or response.startswith("[ERROR]") or response.startswith(
        "[BUDGET]"
    ):
        return None
    try:
        return json.loads(response.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    if "```json" in response:
        try:
            code = response.split("```json")[1].split("```")[0].strip()
            return json.loads(code)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass
    if "```" in response:
        parts = response.split("```")
        for i in range(1, len(parts), 2):
            try:
                return json.loads(parts[i].strip())
            except (json.JSONDecodeError, ValueError):
                continue
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ============================================================
# SAFETY JAIL
# ============================================================

FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/",
    r">\s*/etc/",
    r">\s*/var/",
    r">\s*/usr/",
    r"nc\s+-e\s+/bin/",
    r"mkfifo\s+/tmp/",
    r"bash\s+-i\s+>&\s*/dev/tcp/",
    r"python\s+-c\s+.*socket",
    r"perl\s+-e\s+.*socket",
    r"ruby\s+-rsocket",
]


class SafetyJail:
    def __init__(
        self,
        allowed_targets: Set[str],
        allowed_networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network],
    ):
        self.allowed_targets = allowed_targets
        self.allowed_networks = allowed_networks

    def validate_scope(self, target: str) -> bool:
        if not target:
            return True
        try:
            ip = ipaddress.ip_address(target.split(":")[0])
            return any(
                ip in net for net in self.allowed_networks
            ) or target in self.allowed_targets
        except ValueError:
            return any(
                target == allowed or target.endswith("." + allowed)
                for allowed in self.allowed_targets
            )

    def filter_command(self, cmd: str) -> Tuple[bool, str]:
        for pattern in FORBIDDEN_PATTERNS:
            try:
                if re.search(pattern, cmd, re.IGNORECASE):
                    return False, f"BLOCKED: {pattern}"
            except re.error:
                continue
        targets = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", cmd)
        for target in targets:
            if not self.validate_scope(target):
                return False, f"BLOCKED: {target} out of scope"
        return True, "OK"


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
