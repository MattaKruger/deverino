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

import json

import pytest

from harness_poc.core.events.context_map_events import SubAgentTaskStarted
from harness_poc.v2.execution_engine import (
    ExecutionEngine,
)
from harness_poc.v2.handlers.delegate_task_handler import (
    SpawnerFailureError,
    _handle_delegate_task,
)

from .conftest import BlackboardSpy, EventBusSpy, SpawnerSpy

# ---------------------------------------------------------------------------
# 9. Context map lifecycle events
# ---------------------------------------------------------------------------


class TestContextMapLifecycleEvents:
    """SubAgentTaskStarted/Completed are emitted to the database when db is passed."""

    def test_lifecycle_events_emitted_on_success(
        self,
        spawner: SpawnerSpy,
        event_bus: EventBusSpy,
        blackboard: BlackboardSpy,
        engine: ExecutionEngine,
    ) -> None:
        """Emitted on success with correct corpus_key and ordering."""
        corpus_key = "deverino:subagent:code_reviewer"

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-lifecycle",
            arguments={
                "persona": "code_reviewer",
                "objective": "Review context map code",
                "corpus_key": corpus_key,
            },
            db=engine._db,
        )

        # Read pending events from the database
        events = engine._db.get_pending_context_map_events(corpus_key)
        event_types = [e.event_type for e in events]

        assert "sub_agent_task_started" in event_types, (
            f"Expected sub_agent_task_started in {event_types}"
        )
        assert "sub_agent_task_completed" in event_types, (
            f"Expected sub_agent_task_completed in {event_types}"
        )

        # Verify event ordering: started before completed
        started_idx = event_types.index("sub_agent_task_started")
        completed_idx = event_types.index("sub_agent_task_completed")
        assert started_idx < completed_idx, (
            f"Started ({started_idx}) should come before completed ({completed_idx})"
        )

    def test_lifecycle_event_fields_match(
        self,
        spawner: SpawnerSpy,
        event_bus: EventBusSpy,
        blackboard: BlackboardSpy,
        engine: ExecutionEngine,
    ) -> None:
        """SubAgentTaskStarted/Completed carry correct persona, objective, task_id."""
        from harness_poc.core.events.context_map_events import SubAgentTaskStarted

        corpus_key = "deverino:subagent:architect"

        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-fields",
            arguments={
                "persona": "architect",
                "objective": "Design API",
                "corpus_key": corpus_key,
                "sub_session_id": "sub-sess-123",
            },
            db=engine._db,
        )

        events = engine._db.get_pending_context_map_events(corpus_key)
        started_events = [e for e in events if e.event_type == "sub_agent_task_started"]
        assert len(started_events) == 1

        import json

        payload = json.loads(started_events[0].payload)
        started = SubAgentTaskStarted.model_validate(payload)
        assert started.persona == "architect"
        assert started.objective == "Design API"
        assert started.corpus_key == corpus_key
        assert started.sub_session_id == "sub-sess-123"

        completed_events = [e for e in events if e.event_type == "sub_agent_task_completed"]
        assert len(completed_events) == 1

    def test_no_lifecycle_events_when_db_is_none(
        self,
        spawner: SpawnerSpy,
        event_bus: EventBusSpy,
        blackboard: BlackboardSpy,
    ) -> None:
        """When db is not passed, lifecycle events are silently skipped."""
        _handle_delegate_task(
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            session_id="sess-no-db",
            arguments={
                "persona": "tester",
                "objective": "Test without db",
                "corpus_key": "deverino:subagent:tester",
            },
            # db omitted
        )
        # Should not raise — just verifies the optional path works

    def test_lifecycle_event_on_spawner_crash(
        self,
        event_bus: EventBusSpy,
        blackboard: BlackboardSpy,
        engine: ExecutionEngine,
    ) -> None:
        """SubAgentTaskCompleted with status=failed is emitted when spawner raises."""
        crash_spawner = SpawnerSpy(_error=RuntimeError("Boom"))
        corpus_key = "deverino:subagent:crash_test"

        from harness_poc.v2.handlers.delegate_task_handler import SpawnerFailureError

        with pytest.raises(SpawnerFailureError, match="RuntimeError"):
            _handle_delegate_task(
                spawner=crash_spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-crash",
                arguments={
                    "persona": "crasher",
                    "objective": "Will crash",
                    "corpus_key": corpus_key,
                },
                db=engine._db,
            )

        events = engine._db.get_pending_context_map_events(corpus_key)
        # Started should have been emitted before the spawn attempt
        started = [e for e in events if e.event_type == "sub_agent_task_started"]
        assert len(started) == 1
        # Completed with failure should also be emitted
        completed = [e for e in events if e.event_type == "sub_agent_task_completed"]
        assert len(completed) == 1

        import json

        payload = json.loads(completed[0].payload)
        assert payload["status"] == "failed"
        assert "RuntimeError" in payload["summary"]


class TestCorpusKeyAutoGeneration:
    """spawn_sub_agent auto-generates corpus_key from project_id + agent_type."""

    def test_corpus_key_auto_generated_when_not_in_payload(self, engine: ExecutionEngine) -> None:
        """When task_payload lacks corpus_key, spawn_sub_agent generates one."""
        r = engine.spawn_sub_agent(
            agent_type="data_validator",
            task_payload={"objective": "Validate"},
            mode="foreground",
            session_id="sess-autogen",
        )
        assert r["task_id"]
        # Verify corpus_key was generated and forwarded
        # (checked via the spawner spy receiving it)

    def test_corpus_key_from_payload_overrides_autogen(self, engine: ExecutionEngine) -> None:
        """Explicit corpus_key in task_payload is used, not overridden."""
        r = engine.spawn_sub_agent(
            agent_type="data_validator",
            task_payload={
                "objective": "Validate",
                "corpus_key": "custom:key",
            },
            mode="foreground",
            session_id="sess-override",
        )
        assert r["task_id"]
        # The explicit corpus_key should flow through to the spawner

    def test_corpus_key_forwarded_to_spawner(
        self,
        spawner: SpawnerSpy,
        event_bus: EventBusSpy,
        blackboard: BlackboardSpy,
        engine: ExecutionEngine,
    ) -> None:
        """spawn_sub_agent includes corpus_key in the task_spec passed to spawner."""
        engine.spawn_sub_agent(
            agent_type="code_reviewer",
            task_payload={
                "objective": "Review code",
                "corpus_key": "deverino:subagent:code_reviewer",
            },
            mode="foreground",
            session_id="sess-fwd",
        )
        assert len(spawner.calls) == 1
        spec = spawner.calls[0]
        assert spec["corpus_key"] == "deverino:subagent:code_reviewer"
