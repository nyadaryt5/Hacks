"""Tests for ultron.fsm — transition validation, history and helpers."""

import pytest

from ultron.fsm import (
    VALID_TRANSITIONS,
    AgentState,
    FiniteStateMachine,
    InvalidTransitionError,
)


@pytest.fixture()
def fsm():
    return FiniteStateMachine("agent-1")


def test_initial_state_is_idle(fsm):
    assert fsm.current_state == AgentState.IDLE
    assert fsm.history == []


def test_valid_transition(fsm):
    assert fsm.transition(AgentState.DISCOVERY) is True
    assert fsm.current_state == AgentState.DISCOVERY
    old, new, timestamp = fsm.history[0]
    assert old == AgentState.IDLE
    assert new == AgentState.DISCOVERY
    assert timestamp > 0


def test_invalid_transition_raises(fsm):
    with pytest.raises(InvalidTransitionError) as excinfo:
        fsm.transition(AgentState.COMPLETE)
    assert "Invalid transition: IDLE -> COMPLETE" in str(excinfo.value)


def test_invalid_transition_does_not_change_state(fsm):
    with pytest.raises(InvalidTransitionError):
        fsm.transition(AgentState.EXECUTION)
    assert fsm.current_state == AgentState.IDLE
    assert fsm.history == []


def test_can_transition(fsm):
    assert fsm.can_transition(AgentState.DISCOVERY) is True
    assert fsm.can_transition(AgentState.COMPLETE) is False


def test_get_valid_transitions(fsm):
    assert fsm.get_valid_transitions() == [AgentState.DISCOVERY]


def test_full_happy_path_lifecycle(fsm):
    path = [
        AgentState.DISCOVERY,
        AgentState.ANALYSIS,
        AgentState.PLANNING,
        AgentState.AUTHORIZATION,
        AgentState.EXECUTION,
        AgentState.VERIFICATION,
        AgentState.REPORTING,
        AgentState.COMPLETE,
    ]
    for state in path:
        assert fsm.transition(state) is True
    assert fsm.current_state == AgentState.COMPLETE
    assert len(fsm.history) == len(path)
    # COMPLETE is terminal: no outgoing transitions.
    assert fsm.get_valid_transitions() == []


def test_error_and_terminated_are_terminal_for_complete():
    assert VALID_TRANSITIONS[AgentState.COMPLETE] == set()
    assert VALID_TRANSITIONS[AgentState.TERMINATED] == set()


def test_every_referenced_state_exists():
    names = {state.name for state in AgentState}
    for state, targets in VALID_TRANSITIONS.items():
        assert state.name in names
        for target in targets:
            assert target.name in names
