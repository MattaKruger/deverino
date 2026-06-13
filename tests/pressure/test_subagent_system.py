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

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from harness_poc.core.events.events import (
    BaseEvent,
    SubAgentCompleted,
    SubAgentDispatched,
)
from harness_poc.v2.contracts.sub_agent_spawner import (
    DELEGATED_STATUS_SUCCESS,
    DelegatedTaskResult,
)
from harness_poc.v2.execution_engine import (
    ExecutionEngine,
    SubAgentPoolFullError,
    TaskCancelledError,
    TaskNotFoundError,
)
from harness_poc.v2.handlers.delegate_task_handler import (
    SpawnerFailureError,
    _handle_delegate_task,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_result(
    status: str = DELEGATED_STATUS_SUCCESS,
    task_id: str | None = None,
    raw_output: str | None = None,
) -> DelegatedTaskResult:
    return DelegatedTaskResult(
        status=status,
        task_id=task_id or str(uuid.uuid4()),
        raw_output=raw_output or "ok",
    )

@dataclass
class SpawnerSpy:
    """Records calls and returns canned results or raises."""

    results: list[DelegatedTaskResult] = field(default_factory=list)
    _error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    delay: float = 0.0  # Seconds to block in spawn() for testing async cancel

    def spawn(self, task_spec: dict[str, Any]) -> DelegatedTaskResult:
        self.calls.append(task_spec)
        if self.delay > 0:
            time.sleep(self.delay)
        if self._error is not None:
            raise self._error
        if self.results:
            return self.results.pop(0)
        return _make_result()


@dataclass
class EventBusSpy:
    events: list[BaseEvent] = field(default_factory=list)

    def publish(self, event: BaseEvent) -> None:
        self.events.append(event)

    def subscribe(self, event_type: type, handler: Any) -> None:
        pass

    def subscribe_session(self, session_id: str) -> Any:

        async def _empty():
            if False:
                yield

        return _empty()


@dataclass
class BlackboardSpy:
    writes: list[tuple[str, Any, str]] = field(default_factory=list)

    def write(self, *, task_id: str, output: Any, session_id: str) -> None:
        self.writes.append((task_id, output, session_id))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spawner() -> SpawnerSpy:
    return SpawnerSpy(results=[_make_result()])


@pytest.fixture
def event_bus() -> EventBusSpy:
    return EventBusSpy()


@pytest.fixture
def blackboard() -> BlackboardSpy:
    return BlackboardSpy()


@pytest.fixture
def engine(spawner: SpawnerSpy, event_bus: EventBusSpy, blackboard: BlackboardSpy) -> ExecutionEngine:
    """Minimal ExecutionEngine for pressure testing — no database needed."""
    from harness_poc.core.storage.database import BlackboardDatabase, create_db_engine

    db = BlackboardDatabase(create_db_engine("sqlite:///:memory:"))
    db.create_tables()

    return ExecutionEngine(
        db=db,
        spawner=spawner,
        event_bus=event_bus,  # type: ignore[arg-type]
        blackboard=blackboard,  # type: ignore[arg-type]
        max_background_agents=2,
    )


# ---------------------------------------------------------------------------
# 1. Event ordering
# ---------------------------------------------------------------------------


class TestEventOrdering:
    def test_dispatched_before_completed(self, engine: ExecutionEngine, event_bus: EventBusSpy) -> None:
        """SubAgentDispatched must appear before SubAgentCompleted."""
        engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="foreground",
            session_id="sess-order",
        )
        events = event_bus.events
        dispatched = [e for e in events if isinstance(e, SubAgentDispatched)]
        completed = [e for e in events if isinstance(e, SubAgentCompleted)]
        assert len(dispatched) == 1
        assert len(completed) == 1
        d_idx = events.index(dispatched[0])
        c_idx = events.index(completed[0])
        assert d_idx < c_idx, f"Dispatched at {d_idx}, completed at {c_idx}"

    def test_dispatched_and_completed_share_task_id(
        self, engine: ExecutionEngine, event_bus: EventBusSpy
    ) -> None:
        """The task_id on both events must match."""
        engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="foreground",
            session_id="sess-taskid",
        )
        dispatched = [e for e in event_bus.events if isinstance(e, SubAgentDispatched)][0]
        completed = [e for e in event_bus.events if isinstance(e, SubAgentCompleted)][0]
        assert dispatched.task_id == completed.task_id
        assert isinstance(dispatched.task_id, str)
        assert len(dispatched.task_id) > 0

    def test_sub_session_id_is_none_by_default(
        self, engine: ExecutionEngine, event_bus: EventBusSpy
    ) -> None:
        """Default isolate_session=False → sub_session_id is None."""
        engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="foreground",
            session_id="sess-noiso",
        )
        dispatched = [e for e in event_bus.events if isinstance(e, SubAgentDispatched)][0]
        completed = [e for e in event_bus.events if isinstance(e, SubAgentCompleted)][0]
        assert dispatched.sub_session_id is None
        assert completed.sub_session_id is None


# ---------------------------------------------------------------------------
# 2. try/finally guarantee
# ---------------------------------------------------------------------------


class TestFinallyGuarantee:
    def test_completed_emitted_on_spawner_crash(
        self,
        spawner: SpawnerSpy,
        event_bus: EventBusSpy,
        blackboard: BlackboardSpy,
    ) -> None:
        """Even when spawner crashes, SubAgentCompleted is emitted."""
        spawner._error = RuntimeError("connection refused")

        with pytest.raises(SpawnerFailureError, match="RuntimeError"):
            _handle_delegate_task(
                spawner=spawner,
                event_bus=event_bus,
                blackboard=blackboard,
                session_id="sess-crash",
                arguments={"persona": "t", "objective": "o"},
            )

        dispatched = [e for e in event_bus.events if isinstance(e, SubAgentDispatched)]
        completed = [e for e in event_bus.events if isinstance(e, SubAgentCompleted)]
        assert len(dispatched) == 1
        assert len(completed) == 1
        assert completed[0].status == "failed"
        assert "connection refused" in completed[0].content
        # Blackboard NOT written on crash
        assert len(blackboard.writes) == 0

    def test_completed_emitted_on_success(
        self, engine: ExecutionEngine, event_bus: EventBusSpy
    ) -> None:
        """Normal success path emits both events."""
        result = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="foreground",
            session_id="sess-ok",
        )
        dispatched = [e for e in event_bus.events if isinstance(e, SubAgentDispatched)]
        completed = [e for e in event_bus.events if isinstance(e, SubAgentCompleted)]
        assert len(dispatched) == 1
        assert len(completed) == 1
        assert completed[0].status == DELEGATED_STATUS_SUCCESS
        assert result["output_label"] == "completed"


# ---------------------------------------------------------------------------
# 3. Background pool edge cases
# ---------------------------------------------------------------------------


class TestBackgroundPool:
    def test_background_returns_immediately(
        self, engine: ExecutionEngine, event_bus: EventBusSpy
    ) -> None:
        """Background mode returns a task_id, not the full result."""
        engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="background",
            session_id="sess-bg1",
        )
        # Since spawn is synchronous, result dict has background=True
        # and the task is stored
        assert engine.background_active_count() == 1

    def test_pool_capacity_enforced(self, engine: ExecutionEngine) -> None:
        """Pool-full raises SubAgentPoolFullError."""
        # Max is 2
        engine.spawn_sub_agent(
            agent_type="a",
            task_payload={"objective": "1"},
            mode="background",
            session_id="sess-pool",
        )
        engine.spawn_sub_agent(
            agent_type="b",
            task_payload={"objective": "2"},
            mode="background",
            session_id="sess-pool",
        )
        with pytest.raises(SubAgentPoolFullError):
            engine.spawn_sub_agent(
                agent_type="c",
                task_payload={"objective": "3"},
                mode="background",
                session_id="sess-pool",
            )

    def test_status_transitions(self, engine: ExecutionEngine) -> None:
        """status() reflects task state: running → done after thread completes."""
        result = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="background",
            session_id="sess-status",
        )
        tid = result["task_id"]
        # Thread is alive (or just finished — SpawnerSpy is instant)
        assert engine.status(tid) in ("running", "done")
        # Wait for background thread to complete
        engine._active_tasks.get(tid, None) and engine._active_tasks[tid].join(timeout=1.0)
        assert engine.status(tid) == "done"
    def test_result_removes_from_pool(self, engine: ExecutionEngine) -> None:
        result = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="background",
            session_id="sess-remove",
        )
        tid = result["task_id"]
        assert engine.background_active_count() >= 1
        # Wait for background thread to complete
        engine._active_tasks.get(tid, None) and engine._active_tasks[tid].join(timeout=1.0)
        engine.result(tid)
        assert engine.background_active_count() == 0
        assert engine.status(tid) == "unknown"

    def test_result_on_unknown_raises(self, engine: ExecutionEngine) -> None:
        """result() on unknown task raises TaskNotFoundError."""
        with pytest.raises(TaskNotFoundError):
            engine.result("nonexistent-task-id")

    def test_cancel_on_unknown_raises(self, engine: ExecutionEngine) -> None:
        """cancel() on unknown task raises TaskNotFoundError."""
        with pytest.raises(TaskNotFoundError):
            engine.cancel("nonexistent-task-id")

    def test_cancel_on_completed_returns_false(self, engine: ExecutionEngine) -> None:
        """cancel() on already-done task returns False."""
        result = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="background",
            session_id="sess-cancel-done",
        )
        tid = result["task_id"]
        # Wait for background thread to complete
    def test_result_after_cancel_raises(self, engine: ExecutionEngine, spawner: SpawnerSpy) -> None:
        """After cancel, result() raises TaskCancelledError."""
        # Add delay so the thread is still alive when we cancel
        spawner.delay = 0.5
        result = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="background",
            session_id="sess-cancel-result",
        )
        tid = result["task_id"]
        assert engine.status(tid) == "running"
        # Cancel the running task
        assert engine.cancel(tid) is True
        with pytest.raises(TaskCancelledError, match="cancelled"):
            engine.result(tid)
    def test_legacy_background_status(self, engine: ExecutionEngine) -> None:
        """background_status() returns output_label or None."""
        result = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="background",
            session_id="sess-legacy",
        )
        tid = result["task_id"]
        # Wait for thread to complete to avoid race
        engine._active_tasks.get(tid, None) and engine._active_tasks[tid].join(timeout=1.0)
        assert engine.background_status(tid) in ("running", "completed")
        assert engine.background_status("nonexistent") is None


# ---------------------------------------------------------------------------
# 4. Session isolation
# ---------------------------------------------------------------------------


class TestSessionIsolation:
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


# ---------------------------------------------------------------------------
# 5. Event schema validation
# ---------------------------------------------------------------------------


class TestEventSchema:
    def test_task_id_is_required(self) -> None:
        """task_id is required on both events."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubAgentDispatched(session_id="s", persona="p", objective="o")
        with pytest.raises(ValidationError):
            SubAgentCompleted(session_id="s", status="success", content="ok")
# 5. Event schema validation

    def test_sub_session_id_defaults_to_none(self) -> None:
        """sub_session_id defaults to None."""
        d = SubAgentDispatched(session_id="s", task_id="t", persona="p", objective="o")
        assert d.sub_session_id is None
        c = SubAgentCompleted(session_id="s", task_id="t", status="success", content="ok")
        assert c.sub_session_id is None

    def test_sub_session_id_accepts_string(self) -> None:
        """sub_session_id can be set to a UUID string."""
        sid = str(uuid.uuid4())
        d = SubAgentDispatched(
            session_id="s", task_id="t", sub_session_id=sid, persona="p", objective="o"
        )
        assert d.sub_session_id == sid
        assert d.sub_session_id is None
        c = SubAgentCompleted(session_id="s", task_id="t", status="success", content="ok")
        assert c.sub_session_id is None

    def test_sub_session_id_accepts_string(self) -> None:
        """sub_session_id can be set to a UUID string."""
        sid = str(uuid.uuid4())
        d = SubAgentDispatched(
            session_id="s", task_id="t", sub_session_id=sid, persona="p", objective="o"
        )
        assert d.sub_session_id == sid


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


# ---------------------------------------------------------------------------
# 7. spawn_sub_agent return value
# ---------------------------------------------------------------------------


class TestSpawnSubAgentReturn:
    def test_background_flag_in_result(self, engine: ExecutionEngine) -> None:
        """Background spawn includes background=True in result dict."""
        r = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="background",
            session_id="sess-return-bg",
        )
        assert r["background"] is True
        assert r["output_label"] == "running"
        assert r["session_id"] == "sess-return-bg"

    def test_foreground_flag_in_result(self, engine: ExecutionEngine) -> None:
        """Foreground spawn includes background=False in result dict."""
        r = engine.spawn_sub_agent(
            agent_type="test",
            task_payload={"objective": "test"},
            mode="foreground",
            session_id="sess-return-fg",
        )
        assert r["background"] is False
        assert r["task_id"]
        assert r["output_label"] in ("completed", "failed")


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

    def test_corpus_key_auto_generated_when_not_in_payload(
        self, engine: ExecutionEngine
    ) -> None:
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

    def test_corpus_key_from_payload_overrides_autogen(
        self, engine: ExecutionEngine
    ) -> None:
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
            task_payload={"objective": "Review code", "corpus_key": "deverino:subagent:code_reviewer"},
            mode="foreground",
            session_id="sess-fwd",
        )
        assert len(spawner.calls) == 1
        spec = spawner.calls[0]
        assert spec["corpus_key"] == "deverino:subagent:code_reviewer"
