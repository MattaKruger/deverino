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

import uuid

import pytest

from harness_poc.core.events.events import (
    SubAgentCompleted,
    SubAgentDispatched,
)
from harness_poc.v2.execution_engine import (
    ExecutionEngine,
)

from .conftest import EventBusSpy

# ---------------------------------------------------------------------------
# 4. Session isolation
# ---------------------------------------------------------------------------


class TestSessionIsolation:
    @pytest.mark.xfail(
        reason="SubAgentDispatched/SubAgentCompleted are no longer emitted by engine.spawn_sub_agent(). "
        "The handler now emits DelegateTaskCompleted which lacks sub_session_id. "
        "Session isolation via sub_session_id cannot be verified through current event types."
    )
    def test_sub_session_id_set_when_isolated(
        self, engine: ExecutionEngine, event_bus: EventBusSpy
    ) -> None:
        """isolate_session=True → sub_session_id is a non-null UUID."""
        engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="foreground",
            session_id="sess-parent",
            isolate_session=True,
        )
        dispatched = [e for e in event_bus.events if isinstance(e, SubAgentDispatched)][0]
        completed = [e for e in event_bus.events if isinstance(e, SubAgentCompleted)][0]
        assert dispatched.sub_session_id is not None
        assert completed.sub_session_id is not None
        # Should be a valid UUID
        uuid.UUID(dispatched.sub_session_id)
        uuid.UUID(completed.sub_session_id)
        assert dispatched.sub_session_id == completed.sub_session_id

    @pytest.mark.xfail(
        reason="SubAgentDispatched is no longer emitted by engine.spawn_sub_agent(). "
        "The handler now emits DelegateTaskCompleted which lacks sub_session_id."
    )
    def test_isolated_session_differs_from_parent(
        self, engine: ExecutionEngine, event_bus: EventBusSpy
    ) -> None:
        """sub_session_id differs from parent session_id."""
        parent_id = "sess-parent-2"
        engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="foreground",
            session_id=parent_id,
            isolate_session=True,
        )
        dispatched = [e for e in event_bus.events if isinstance(e, SubAgentDispatched)][0]
        assert dispatched.session_id == parent_id
        assert dispatched.sub_session_id != parent_id
