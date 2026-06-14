"""Pressure-test the sub-agent system end-to-end.

Exercises EventBus + EventStore + ExecutionEngine + delegate_task handler
in a single integrated test, covering:

1. Event ordering (SubAgentDispatched always before SubAgentCompleted)
2. try/finally guarantee (SubAgentCompleted emitted on spawner crash)
3. Background pool edge cases (full, cancel, result, status)
4. Session isolation (sub_session_id on lifecycle events)
5. Error paths (SpawnerFailureError, SubAgentPoolFullError, TaskNotFoundError)
6. Event schema (task_id present, sub_session_id optional)
"""

from __future__ import annotations

import pytest

from harness_poc.v2.execution_engine import (
    ExecutionEngine,
    SubAgentPoolFullError,
    TaskNotFoundError,
)
from harness_poc.v2.handlers.delegate_task_handler import (
    _handle_delegate_task,
)

from .conftest import BlackboardSpy, EventBusSpy, SpawnerSpy

# ---------------------------------------------------------------------------
# 6. Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_missing_persona_raises(self) -> None:
        """Missing persona raises MalformedArgumentsError."""
        from harness_poc.v2.handlers.delegate_task_handler import MalformedArgumentsError

        spawner = SpawnerSpy()
        bus = EventBusSpy()
        bb = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="persona"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=bus,
                blackboard=bb,
                session_id="sess-bad",
                arguments={"objective": "test"},
            )

    def test_missing_objective_raises(self) -> None:
        """Missing objective raises MalformedArgumentsError."""
        from harness_poc.v2.handlers.delegate_task_handler import MalformedArgumentsError

        spawner = SpawnerSpy()
        bus = EventBusSpy()
        bb = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="objective"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=bus,
                blackboard=bb,
                session_id="sess-bad",
                arguments={"persona": "test"},
            )

    def test_empty_persona_raises(self) -> None:
        """Empty persona string raises MalformedArgumentsError."""
        from harness_poc.v2.handlers.delegate_task_handler import MalformedArgumentsError

        spawner = SpawnerSpy()
        bus = EventBusSpy()
        bb = BlackboardSpy()

        with pytest.raises(MalformedArgumentsError, match="persona"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=bus,
                blackboard=bb,
                session_id="sess-bad",
                arguments={"persona": "", "objective": "test"},
            )

    def test_pool_full_before_dispatch_no_events(self) -> None:
        """Pool-full raises before SubAgentDispatched is emitted."""
        engine = ExecutionEngine(
            db=None,  # type: ignore[arg-type]
            spawner=SpawnerSpy(),
            event_bus=EventBusSpy(),  # type: ignore[arg-type]
            blackboard=BlackboardSpy(),  # type: ignore[arg-type]
            max_background_agents=0,
        )
        bus = EventBusSpy()
        engine._event_bus = bus  # type: ignore[assignment]

        with pytest.raises(SubAgentPoolFullError):
            engine.spawn_sub_agent(
                agent_type="test",
                task_payload={"objective": "test"},
                mode="background",
                session_id="sess-full",
            )
        # No events emitted — validation failed before dispatch
        assert len(bus.events) == 0

    def test_unknown_status_returns_unknown(self, engine: ExecutionEngine) -> None:
        """status() returns 'unknown' for unrecognized task_id."""
        assert engine.status("garbage-id") == "unknown"

    def test_unknown_cancel_raises(self, engine: ExecutionEngine) -> None:
        """cancel() on unknown task raises TaskNotFoundError."""
        with pytest.raises(TaskNotFoundError):
            engine.cancel("garbage-id")
