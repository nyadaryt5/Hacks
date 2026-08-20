"""Multi-agent debate protocol for high-risk decisions.

An attacker agent argues FOR a proposed action, a defender agent argues
AGAINST it, and a neutral judge synthesizes a verdict
(``proceed | modify | abort``). Reduces hallucinations and risky decisions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict

from ultron.json_utils import parse_json_response
from ultron.tracing import TRACER, SpanType

if TYPE_CHECKING:  # pragma: no cover
    from ultron.llm import GoogleAIClient


class DebateProtocol:
    """Multi-agent debate for complex decisions."""

    def __init__(self, llm_client: "GoogleAIClient"):
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


__all__ = ["DebateProtocol"]
