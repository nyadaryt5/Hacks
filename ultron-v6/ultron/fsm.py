"""Finite state machine driving the ULTRON agent lifecycle.

States progress through the pentest phases (IDLE → DISCOVERY → ANALYSIS →
PLANNING → AUTHORIZATION → EXECUTION → VERIFICATION → REPORTING → COMPLETE)
with ERROR / TERMINATED escape hatches. Invalid transitions raise
:class:`InvalidTransitionError`; every transition is recorded in history and
emitted as a trace span.
"""

from __future__ import annotations

import threading
import time
from enum import Enum, auto
from typing import Dict, List, Set, Tuple

from ultron.tracing import TRACER, SpanType


class AgentState(Enum):
    IDLE = auto()
    DISCOVERY = auto()
    ANALYSIS = auto()
    PLANNING = auto()
    AUTHORIZATION = auto()
    EXECUTION = auto()
    VERIFICATION = auto()
    REPORTING = auto()
    COMPLETE = auto()
    ERROR = auto()
    TERMINATED = auto()


# Define all valid state transitions
VALID_TRANSITIONS: Dict[AgentState, Set[AgentState]] = {
    AgentState.IDLE: {AgentState.DISCOVERY},
    AgentState.DISCOVERY: {
        AgentState.ANALYSIS,
        AgentState.ERROR,
        AgentState.TERMINATED,
    },
    AgentState.ANALYSIS: {
        AgentState.PLANNING,
        AgentState.DISCOVERY,
        AgentState.ERROR,
        AgentState.TERMINATED,
    },
    AgentState.PLANNING: {
        AgentState.AUTHORIZATION,
        AgentState.ANALYSIS,
        AgentState.ERROR,
        AgentState.TERMINATED,
    },
    AgentState.AUTHORIZATION: {
        AgentState.EXECUTION,
        AgentState.PLANNING,
        AgentState.REPORTING,
        AgentState.ERROR,
        AgentState.TERMINATED,
    },
    AgentState.EXECUTION: {
        AgentState.VERIFICATION,
        AgentState.PLANNING,
        AgentState.ERROR,
        AgentState.TERMINATED,
    },
    AgentState.VERIFICATION: {
        AgentState.PLANNING,
        AgentState.REPORTING,
        AgentState.DISCOVERY,
        AgentState.ERROR,
        AgentState.TERMINATED,
    },
    AgentState.REPORTING: {AgentState.COMPLETE, AgentState.ERROR},
    AgentState.COMPLETE: set(),
    AgentState.ERROR: {AgentState.PLANNING, AgentState.TERMINATED},
    AgentState.TERMINATED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when an FSM transition is not allowed."""


class FiniteStateMachine:
    """Directed graph state machine for agent lifecycle."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.current_state = AgentState.IDLE
        self.history: List[Tuple[AgentState, AgentState, float]] = []
        self.lock = threading.Lock()

    def transition(self, target_state: AgentState) -> bool:
        """Attempt a state transition. Raises InvalidTransitionError if invalid."""
        with self.lock:
            if target_state not in VALID_TRANSITIONS.get(
                self.current_state, set()
            ):
                valid = [
                    s.name
                    for s in VALID_TRANSITIONS.get(self.current_state, set())
                ]
                raise InvalidTransitionError(
                    f"Invalid transition: {self.current_state.name} -> "
                    f"{target_state.name}. Valid targets: {valid}"
                )
            old_state = self.current_state
            self.current_state = target_state
            self.history.append((old_state, target_state, time.time()))

            span_id = TRACER.start_span(
                f"state_transition_{target_state.name}",
                SpanType.STATE_TRANSITION,
                attributes={
                    "from": old_state.name,
                    "to": target_state.name,
                    "agent": self.agent_id,
                },
            )
            TRACER.end_span(span_id)
            return True

    def can_transition(self, target_state: AgentState) -> bool:
        return target_state in VALID_TRANSITIONS.get(self.current_state, set())

    def get_valid_transitions(self) -> List[AgentState]:
        return list(VALID_TRANSITIONS.get(self.current_state, set()))


__all__ = [
    "AgentState",
    "FiniteStateMachine",
    "InvalidTransitionError",
    "VALID_TRANSITIONS",
]
