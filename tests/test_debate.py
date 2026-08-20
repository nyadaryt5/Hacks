"""Tests for ultron.debate — debate flow and fallback behavior."""

from ultron.debate import DebateProtocol


class FakeLLM:
    """Scripted LLM client for debate tests."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def chat(self, system, user, temperature=0.3, max_tokens=3000):
        self.calls.append((system, user, temperature, max_tokens))
        return self.responses.pop(0) if self.responses else "{}"


def test_debate_synthesizes_verdict():
    llm = FakeLLM(
        responses=[
            '{"argument": "do it", "confidence": 0.9}',
            '{"argument": "dont", "risk_level": 0.8}',
            '{"verdict": "abort", "reasoning": "too risky", "confidence": 0.9}',
        ]
    )
    verdict = DebateProtocol(llm).debate(
        {"action": "rm -rf /tmp/x"}, {"target": "example.com"}
    )
    assert verdict == {
        "verdict": "abort",
        "reasoning": "too risky",
        "confidence": 0.9,
    }
    assert len(llm.calls) == 3  # attacker, defender, judge


def test_debate_makes_three_llm_calls():
    llm = FakeLLM()
    DebateProtocol(llm).debate({"action": "x"}, {"target": "t"})
    assert len(llm.calls) == 3
    # attacker and defender run at higher temperature than the judge
    assert llm.calls[0][2] == 0.4
    assert llm.calls[1][2] == 0.4
    assert llm.calls[2][2] == 0.2


def test_debate_falls_back_when_synthesis_is_garbage():
    llm = FakeLLM(responses=["not json", "also not json", "still not json"])
    verdict = DebateProtocol(llm).debate({"action": "x"}, {"target": "t"})
    assert verdict["verdict"] == "proceed"
    assert "defaulting" in verdict["reasoning"]


def test_debate_falls_back_when_synthesis_missing_verdict():
    llm = FakeLLM(responses=["{}", "{}", '{"reasoning": "no verdict here"}'])
    verdict = DebateProtocol(llm).debate({"action": "x"}, {"target": "t"})
    assert verdict["verdict"] == "proceed"
