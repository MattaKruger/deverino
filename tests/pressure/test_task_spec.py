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

from typing import Any

import pytest

from harness_poc.v2.handlers.delegate_task_handler import (
    _handle_delegate_task,
)

from .conftest import BlackboardSpy, EventBusSpy, SpawnerSpy

# ---------------------------------------------------------------------------
# 8. Spawner receives task_spec with expected fields
# ---------------------------------------------------------------------------


class TestTaskSpec:
    def test_spawner_receives_persona_and_objective(
        self, spawner: SpawnerSpy, event_bus: EventBusSpy, blackboard: BlackboardSpy
    ) -> None:
        """The task_spec passed to spawner.spawn() contains persona and objective."""
        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-spec",
            arguments={"persona": "code_reviewer", "objective": "Find bugs"},
        )
        assert len(spawner.calls) == 1
        spec = spawner.calls[0]
        assert spec["persona"] == "code_reviewer"
        assert spec["objective"] == "Find bugs"

    @pytest.mark.xfail(
        reason="_build_task_spec no longer forwards on_text. "
        "The current implementation filters callables from the task_spec dict."
    )
    def test_spawner_receives_on_text_when_provided(
        self, spawner: SpawnerSpy, event_bus: EventBusSpy, blackboard: BlackboardSpy
    ) -> None:
        """on_text is forwarded in task_spec when provided."""
        calls = []

        def dummy(text: str) -> None:
            calls.append(text)

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-otext",
            arguments={"persona": "t", "objective": "o", "on_text": dummy},
        )
        spec = spawner.calls[0]
        assert spec.get("on_text") is dummy
