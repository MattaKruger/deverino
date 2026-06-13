"""TDD tests for A1: _handle_delegate_task.

Micro-cycle (per Plan 2):
    1. Tests that assert failure modes → watch them FAIL (stub/absent impl)
    2. Complete the implementation → watch them PASS
    3. Edge-case tests → watch them PASS
    4. Commit: test + implementation together

These tests use in-memory spies (no database, no real spawner) so they
run in milliseconds and are safe for CI.
"""

from __future__ import annotations

import pytest

from harness_poc.core.events.events import DelegateTaskCompleted
from harness_poc.v2.contracts import (
    DELEGATED_OUTPUT_BLOCKED,
    DELEGATED_OUTPUT_COMPLETED,
    DELEGATED_OUTPUT_FAILED,
    DELEGATED_STATUS_FAILED,
    DELEGATED_STATUS_SUCCESS,
    GOAL_STATUS_BLOCKED,
    DelegatedTaskOutput,
    DelegatedTaskResult,
)
from harness_poc.v2.handlers.delegate_task_handler import (
    MalformedArgumentsError,
    SpawnerFailureError,
    _handle_delegate_task,
)

# ---------------------------------------------------------------------------
# Test doubles (spies)
# ---------------------------------------------------------------------------


class SpawnerSpy:
    """Controllable SubAgentSpawner double.

    Set ``next_result`` before calling code under test; read ``calls``
    after to assert what was passed.
    """

    def __init__(self, next_result: DelegatedTaskResult | Exception) -> None:
        self._next_result = next_result
        self.calls: list[dict] = []

    def spawn(self, task_spec: dict) -> DelegatedTaskResult:
        self.calls.append(task_spec)
        if isinstance(self._next_result, Exception):
            raise self._next_result
        return self._next_result


class EventBusSpy:
    """Records published events for assertion."""

    def __init__(self) -> None:
        self.events: list[DelegateTaskCompleted] = []

    def publish(self, event: DelegateTaskCompleted) -> None:
        self.events.append(event)


class BlackboardSpy:
    """Records writes for assertion."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, DelegatedTaskOutput]] = []

    def write(self, task_id: str, output: DelegatedTaskOutput, session_id: str) -> None:
        self.writes.append((task_id, output))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_arguments(**overrides) -> dict:
    """Return a minimal valid arguments dict."""
    base = {
        "persona": "code-reviewer",
        "objective": "Review the diff for security issues.",
    }
    base.update(overrides)
    return base


def make_delegated_result(status: str, **overrides) -> DelegatedTaskResult:
    """Return a DelegatedTaskResult with defaults filled in."""
    return DelegatedTaskResult(
        task_id=overrides.pop("task_id", "task-001"),
        status=status,
        raw_output=overrides.pop("raw_output", {"findings": 3}),
        error=overrides.pop("error", None),
        **overrides,
    )


# ---------------------------------------------------------------------------
# Tests: failure mode (TDD step 1 — watch it FAIL, then make it PASS)
# ---------------------------------------------------------------------------


class TestFailureModeSpawnerReturnsFailed:
    """When the spawner returns a 'failed' DelegatedTaskResult the handler
    must still write to blackboard and emit an event — just with a
    'failed' label.
    """

    def test_blackboard_receives_failed_output(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_FAILED, error="timeout"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-1",
            arguments=make_arguments(),
        )

        assert len(blackboard.writes) == 1
        _, output = blackboard.writes[0]
        assert output.output_label == DELEGATED_OUTPUT_FAILED
        assert "timeout" in output.summary

    def test_event_emitted_on_failure(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_FAILED, error="tool crash"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-2",
            arguments=make_arguments(),
        )

        assert len(event_bus.events) == 1
        event = event_bus.events[0]
        assert isinstance(event, DelegateTaskCompleted)
        assert event.output_label == DELEGATED_OUTPUT_FAILED
        assert event.session_id == "sess-2"


# ---------------------------------------------------------------------------
# Tests: edge cases — malformed input (TDD step 3 variant)
# ---------------------------------------------------------------------------


class TestEdgeCaseMalformedArgs:
    """Missing required keys must raise MalformedArgumentsError."""

    def test_missing_persona_raises(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="persona"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-3",
                arguments={"objective": "do stuff"},  # no persona
            )

    def test_missing_objective_raises(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="objective"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-4",
                arguments={"persona": "reviewer"},  # no objective
            )

    def test_empty_persona_raises(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="persona"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-5",
                arguments={"persona": "", "objective": "do stuff"},
            )


# ---------------------------------------------------------------------------
# Tests: success path — full roundtrip
# ---------------------------------------------------------------------------


class TestSuccessPathFullRoundtrip:
    """Happy path: spawner succeeds, all side effects fire."""

    def test_output_label_is_completed(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, raw_output="all good"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        result = _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-6",
            arguments=make_arguments(),
        )

        assert result.output.output_label == DELEGATED_OUTPUT_COMPLETED
        assert "all good" in result.output.summary

    def test_blackboard_written(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-7",
            arguments=make_arguments(task_id="custom-42"),
        )

        assert len(blackboard.writes) == 1
        task_id, output = blackboard.writes[0]
        # The spawner is the authority on task_id — the blackboard
        # receives whatever task_id the spawner returned.
        assert task_id == "spawner-77"
        assert output.output_label == DELEGATED_OUTPUT_COMPLETED

    def test_event_payload_contains_task_id(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="t-99"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-8",
            arguments=make_arguments(),
        )

        event = event_bus.events[0]
        assert event.task_id == "t-99"

    def test_spawner_receives_task_spec(self) -> None:
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-9",
            arguments=make_arguments(persona="auditor", objective="audit logs"),
        )

        assert len(spawner.calls) == 1
        spec = spawner.calls[0]
        assert spec["persona"] == "auditor"
        assert spec["objective"] == "audit logs"


# ---------------------------------------------------------------------------
# Tests: status mapping edge case — blocked goal
# ---------------------------------------------------------------------------


class TestStatusMappingBlockedGoal:
    """When original_goal_status='blocked' and the spawner fails, the
    output label must be 'blocked', not the generic 'failed'.
    """

    def test_blocked_becomes_blocked(self) -> None:
        spawner = SpawnerSpy(
            make_delegated_result(DELEGATED_STATUS_FAILED, error="dependency missing")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        result = _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-10",
            arguments=make_arguments(),
            original_goal_status=GOAL_STATUS_BLOCKED,
        )

        assert result.output.output_label == DELEGATED_OUTPUT_BLOCKED

    def test_completed_stays_completed_even_with_blocked_goal(self) -> None:
        """If the spawner succeeds, the label is 'completed' regardless of
        original goal status.
        """
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        result = _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-11",
            arguments=make_arguments(),
            original_goal_status=GOAL_STATUS_BLOCKED,
        )

        assert result.output.output_label == DELEGATED_OUTPUT_COMPLETED


# ---------------------------------------------------------------------------
# Tests: spawner raises unexpected exception
# ---------------------------------------------------------------------------


class TestSpawnerExplodes:
    """If spawner.spawn() raises an exception (not returns a failed result),
    the handler must wrap it in SpawnerFailureError.
    """

    def test_spawner_raises_runtime_error(self) -> None:
        spawner = SpawnerSpy(RuntimeError("connection refused"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        with pytest.raises(SpawnerFailureError, match="RuntimeError"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-12",
                arguments=make_arguments(),
            )

        # Nothing should be written to blackboard or event bus on crash
        assert len(blackboard.writes) == 0
        assert len(event_bus.events) == 0


class TestCorpusKeyPassthrough:
    """corpus_key in arguments flows through to the task_spec."""

    def test_corpus_key_forwarded_to_spawner(self) -> None:
        """_build_task_spec includes corpus_key when provided."""
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-cm",
            arguments=make_arguments(corpus_key="deverino:docs"),
        )

        assert len(spawner.calls) == 1
        task_spec = spawner.calls[0]
        assert task_spec["corpus_key"] == "deverino:docs"

    def test_corpus_key_absent_when_not_provided(self) -> None:
        """corpus_key is None in task_spec when not in arguments."""
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-no-cm",
            arguments=make_arguments(),
        )

        assert len(spawner.calls) == 1
        task_spec = spawner.calls[0]
        assert task_spec.get("corpus_key") is None
