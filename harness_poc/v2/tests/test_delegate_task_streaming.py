"""TDD tests for A3: _handle_delegate_task_streaming.

Micro-cycle (per Plan 2):
    1. Tests that assert failure modes → watch them FAIL (no impl yet)
    2. Complete the implementation → watch them PASS
    3. Edge-case tests → watch them PASS
    4. Commit: test + implementation together
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

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
)
from harness_poc.v2.handlers.delegate_task_streaming import (
    _handle_delegate_task_streaming,
)

# ---------------------------------------------------------------------------
# Test doubles (spies)
# ---------------------------------------------------------------------------

class SpawnerStreamingSpy:
    """Controllable SubAgentSpawner double for spawn_streaming."""

    def __init__(self, next_result: DelegatedTaskResult | Exception) -> None:
        self._next_result = next_result
        self.streaming_calls: list[dict] = []

    def spawn(self, task_spec: dict) -> DelegatedTaskResult:
        msg = "sync spawn not used in streaming tests"
        raise NotImplementedError(msg)

    async def spawn_async(self, task_spec: dict) -> DelegatedTaskResult:
        msg = "spawn_async not used in streaming tests"
        raise NotImplementedError(msg)

    async def spawn_streaming(
        self,
        task_spec: dict,
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> DelegatedTaskResult:
        self.streaming_calls.append(
            {"task_spec": task_spec, "on_text": on_text}
        )
        # Simulate streaming output during execution
        if on_text:
            on_text(f"[{task_spec['task_id']}] Processing...")
        if isinstance(self._next_result, Exception):
            raise self._next_result
        return self._next_result

    def status(self, task_id: str) -> DelegatedTaskResult | None:
        return None


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


class OnTextSpy:
    """Captures on_text calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> None:
        self.calls.append(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_arguments(**overrides) -> dict:
    """Return a minimal valid arguments dict."""
    base = {"persona": "code-reviewer", "objective": "Review the diff."}
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


def run_async(coro):
    """Run an async coroutine synchronously for pytest."""
    return asyncio.run(coro)


# ====================================================================
# Tests: failure mode — spawner returns failed
# ====================================================================

class TestStreamingFailureMode:
    """When spawn_streaming returns 'failed', handler still writes to
    blackboard, emits event, and fires on_text lifecycle.
    """

    def test_on_text_receives_started_and_failed(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_FAILED, error="timeout")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        on_text = OnTextSpy()

        run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-1",
            arguments=make_arguments(task_id="t-fail"),
            on_text=on_text,
        ))

        assert any("Started" in c for c in on_text.calls), on_text.calls
        assert any("Failed" in c for c in on_text.calls), on_text.calls
        assert any("Processing" in c for c in on_text.calls), on_text.calls

    def test_blackboard_receives_failed_output(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_FAILED, error="timeout")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-2",
            arguments=make_arguments(),
        ))

        assert len(blackboard.writes) == 1
        _, output = blackboard.writes[0]
        assert output.output_label == DELEGATED_OUTPUT_FAILED

    def test_event_emitted_on_failure(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_FAILED, error="crash")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-3",
            arguments=make_arguments(),
        ))

        assert len(event_bus.events) == 1
        event = event_bus.events[0]
        assert isinstance(event, DelegateTaskCompleted)
        assert event.output_label == DELEGATED_OUTPUT_FAILED


# ====================================================================
# Tests: spawner explodes
# ====================================================================

class TestStreamingSpawnerExplodes:
    """If spawn_streaming raises, handler wraps in SpawnerFailureError
    and fires on_text lifecycle.
    """

    def test_on_text_receives_started_and_error(self):
        spawner = SpawnerStreamingSpy(RuntimeError("connection refused"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        on_text = OnTextSpy()

        with pytest.raises(SpawnerFailureError, match="RuntimeError"):
            run_async(_handle_delegate_task_streaming(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-4",
                arguments=make_arguments(task_id="t-boom"),
                on_text=on_text,
            ))

        assert any("Started" in c for c in on_text.calls), on_text.calls
        assert any("Error" in c for c in on_text.calls), on_text.calls

    def test_no_side_effects_on_crash(self):
        spawner = SpawnerStreamingSpy(RuntimeError("connection refused"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        with pytest.raises(SpawnerFailureError):
            run_async(_handle_delegate_task_streaming(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-13",
                arguments=make_arguments(),
            ))

        assert len(blackboard.writes) == 0
        assert len(event_bus.events) == 0


# ====================================================================
# Tests: success path
# ====================================================================

class TestStreamingSuccessPath:
    """Happy path: spawn_streaming succeeds, all side effects fire."""

    def test_on_text_receives_started_completed_and_processing(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="t-ok")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        on_text = OnTextSpy()

        result = run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-5",
            arguments=make_arguments(),
            on_text=on_text,
        ))

        assert result.output.output_label == DELEGATED_OUTPUT_COMPLETED
        assert any("Started" in c for c in on_text.calls), on_text.calls
        assert any("Completed" in c for c in on_text.calls), on_text.calls
        assert any("Processing" in c for c in on_text.calls), on_text.calls

    def test_spawner_streaming_receives_on_text(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="t-stream")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        on_text = OnTextSpy()

        run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-6",
            arguments=make_arguments(),
            on_text=on_text,
        ))

        assert len(spawner.streaming_calls) == 1
        assert spawner.streaming_calls[0]["on_text"] is on_text

    def test_spawner_receives_correct_task_spec(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS)
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-7",
            arguments=make_arguments(
                persona="auditor", objective="audit logs"
            ),
        ))

        spec = spawner.streaming_calls[0]["task_spec"]
        assert spec["persona"] == "auditor"
        assert spec["objective"] == "audit logs"

    def test_event_payload_contains_task_id(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="t-99")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-8",
            arguments=make_arguments(),
        ))

        event = event_bus.events[0]
        assert event.task_id == "t-99"
        assert event.output_label == DELEGATED_OUTPUT_COMPLETED


# ====================================================================
# Tests: on_text is None
# ====================================================================

class TestOnTextNone:
    """Handler should not crash when on_text is None."""

    def test_success_without_on_text(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="t-silent")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        result = run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-9",
            arguments=make_arguments(),
            on_text=None,
        ))

        assert result.output.output_label == DELEGATED_OUTPUT_COMPLETED

    def test_failure_without_on_text(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_FAILED, error="boom")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        result = run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-10",
            arguments=make_arguments(),
            on_text=None,
        ))

        assert result.output.output_label == DELEGATED_OUTPUT_FAILED


# ====================================================================
# Tests: blocked goal nuance
# ====================================================================

class TestStreamingBlockedGoal:
    """When original_goal_status='blocked' and spawner fails, the
    output label must be 'blocked', not generic 'failed'.
    """

    def test_blocked_becomes_blocked(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(
                DELEGATED_STATUS_FAILED, error="dependency missing"
            )
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        result = run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-11",
            arguments=make_arguments(),
            original_goal_status=GOAL_STATUS_BLOCKED,
        ))

        assert result.output.output_label == DELEGATED_OUTPUT_BLOCKED

    def test_completed_stays_completed(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS)
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        result = run_async(_handle_delegate_task_streaming(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-12",
            arguments=make_arguments(),
            original_goal_status=GOAL_STATUS_BLOCKED,
        ))

        assert result.output.output_label == DELEGATED_OUTPUT_COMPLETED


# ====================================================================
# Tests: malformed arguments
# ====================================================================

class TestStreamingMalformedArgs:
    """Missing required keys must raise MalformedArgumentsError."""

    def test_missing_persona_raises(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS)
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="persona"):
            run_async(_handle_delegate_task_streaming(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-14",
                arguments={"objective": "do stuff"},
            ))

    def test_missing_objective_raises(self):
        spawner = SpawnerStreamingSpy(
            make_delegated_result(DELEGATED_STATUS_SUCCESS)
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="objective"):
            run_async(_handle_delegate_task_streaming(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-15",
                arguments={"persona": "reviewer"},
            ))
