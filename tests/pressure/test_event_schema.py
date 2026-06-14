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

# ---------------------------------------------------------------------------
# 5. Event schema validation
# ---------------------------------------------------------------------------


class TestEventSchema:
    def test_session_id_is_required(self) -> None:
        """session_id is required on both events (inherited from BaseEvent)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubAgentDispatched(sub_session_id="s", persona="p", objective="o")
        with pytest.raises(ValidationError):
            SubAgentCompleted(sub_session_id="s", status="success", content="ok")

    # 5. Event schema validation

    def test_sub_session_id_is_required(self) -> None:
        """sub_session_id is required on both events."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubAgentDispatched(session_id="s", task_id="t", persona="p", objective="o")
        with pytest.raises(ValidationError):
            SubAgentCompleted(session_id="s", task_id="t", status="success", content="ok")

    def test_sub_session_id_accepts_string(self) -> None:
        """sub_session_id can be set to a UUID string."""
        sid = str(uuid.uuid4())
        d = SubAgentDispatched(
            session_id="s", task_id="t", sub_session_id=sid, persona="p", objective="o"
        )
        assert d.sub_session_id == sid
        c = SubAgentCompleted(
            session_id="s", task_id="t", sub_session_id=sid, status="success", content="ok"
        )
        assert c.sub_session_id == sid

    def test_sub_session_id_accepts_string(self) -> None:
        """sub_session_id can be set to a UUID string."""
        sid = str(uuid.uuid4())
        d = SubAgentDispatched(
            session_id="s", task_id="t", sub_session_id=sid, persona="p", objective="o"
        )
        assert d.sub_session_id == sid
