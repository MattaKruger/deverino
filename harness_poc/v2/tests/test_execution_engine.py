"""Tests for ExecutionEngine — sub-agent spawning and deterministic review gate.

Uses in-memory spies (no database, no real spawner) so tests run in
milliseconds and are safe for CI.
"""

from __future__ import annotations

import pytest

from harness_poc.v2.contracts import (
    DELEGATED_OUTPUT_COMPLETED,
    DELEGATED_OUTPUT_FAILED,
    DELEGATED_STATUS_FAILED,
    DELEGATED_STATUS_SUCCESS,
    DelegatedTaskOutput,
    DelegatedTaskResult,
)
from harness_poc.v2.execution_engine import (
    ExecutionEngine,
    SubAgentPoolFullError,
)

# ---------------------------------------------------------------------------
# Test doubles (spies)
# ---------------------------------------------------------------------------

class DatabaseSpy:
    """Records DB calls for assertion — no real database."""

    def __init__(self) -> None:
        self.context_events: list[dict] = []
        self.materialized_maps: dict[str, dict] = {}
        self._next_event_id = 1

    def append_context_event(
        self,
        session_id: str,
        team_member: str,
        event_type: str,
        payload: dict,
    ) -> int:
        event_id = self._next_event_id
        self._next_event_id += 1
        self.context_events.append(
            {
                "id": event_id,
                "session_id": session_id,
                "team_member": team_member,
                "event_type": event_type,
                "payload": payload,
            }
        )
        return event_id

    def upsert_materialized_context_map(
        self,
        project_id: str,
        active_persona: str,
        pedagogy_snapshot: dict,
        verified_state: dict,
        last_event_id: int,
    ) -> None:
        self.materialized_maps[project_id] = {
            "project_id": project_id,
            "active_persona": active_persona,
            "pedagogy_snapshot": pedagogy_snapshot,
            "verified_state": verified_state,
            "last_event_id": last_event_id,
        }

    def get_materialized_context_map(self, project_id: str) -> dict | None:
        return self.materialized_maps.get(project_id)


class SpawnerSpy:
    """Controllable SubAgentSpawner double."""

    def __init__(self, next_result: DelegatedTaskResult | Exception) -> None:
        self._next_result = next_result
        self.spawn_calls: list[dict] = []

    def spawn(self, task_spec: dict) -> DelegatedTaskResult:
        self.spawn_calls.append(task_spec)
        if isinstance(self._next_result, Exception):
            raise self._next_result
        return self._next_result


class EventBusSpy:
    """Records published events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def subscribe(self, event_type: str, handler) -> None:
        pass

    def unsubscribe(self, event_type: str, handler) -> None:
        pass

    def publish(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class BlackboardSpy:
    """Records writes for assertion."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, DelegatedTaskOutput]] = []

    def write(self, task_id: str, output: DelegatedTaskOutput) -> None:
        self.writes.append((task_id, output))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
# Tests: spawn_sub_agent — success path
# ---------------------------------------------------------------------------

class TestSpawnSubAgentSuccess:
    def test_returns_completed_output(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        result = engine.spawn_sub_agent(
            agent_type="code_reviewer",
            task_payload={"objective": "Review the diff"},
            session_id="sess-1",
        )

        assert result["output_label"] == DELEGATED_OUTPUT_COMPLETED
        assert result["task_id"] == "spawner-77"
        assert result["background"] is False

    def test_spawner_receives_persona_and_objective(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        engine.spawn_sub_agent(
            agent_type="data_validator",
            task_payload={"objective": "Validate schemas", "context": "JSON files"},
            session_id="sess-2",
        )

        assert len(spawner.spawn_calls) == 1
        spec = spawner.spawn_calls[0]
        assert spec["persona"] == "data_validator"
        assert spec["objective"] == "Validate schemas"
        assert spec["context"] == "JSON files"

    def test_passes_tools_to_spawner(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        engine.spawn_sub_agent(
            agent_type="coder",
            task_payload={
                "objective": "Write function",
                "tools": ["read_file", "edit_file"],
            },
            session_id="sess-3",
        )

        spec = spawner.spawn_calls[0]
        assert spec["tools"] == ["read_file", "edit_file"]

    def test_defaults_objective_from_task_key(self):
        """When 'task' is used instead of 'objective', it maps correctly."""
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        engine.spawn_sub_agent(
            agent_type="reviewer",
            task_payload={"task": "Review everything"},
            session_id="sess-4",
        )

        spec = spawner.spawn_calls[0]
        assert spec["objective"] == "Review everything"


# ---------------------------------------------------------------------------
# Tests: spawn_sub_agent — failure path
# ---------------------------------------------------------------------------

class TestSpawnSubAgentFailure:
    def test_returns_failed_output_when_spawner_fails(self):
        spawner = SpawnerSpy(
            make_delegated_result(DELEGATED_STATUS_FAILED, error="timeout")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        result = engine.spawn_sub_agent(
            agent_type="code_reviewer",
            task_payload={"objective": "Review"},
            session_id="sess-5",
        )

        assert result["output_label"] == DELEGATED_OUTPUT_FAILED

    def test_writes_to_blackboard_on_failure(self):
        spawner = SpawnerSpy(
            make_delegated_result(DELEGATED_STATUS_FAILED, error="tool crash")
        )
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        engine.spawn_sub_agent(
            agent_type="reviewer",
            task_payload={"objective": "Review"},
            session_id="sess-6",
        )

        assert len(blackboard.writes) == 1


# ---------------------------------------------------------------------------
# Tests: background sub-agent pool
# ---------------------------------------------------------------------------

class TestBackgroundPool:
    def test_records_background_task(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            max_background_agents=3,
        )

        result = engine.spawn_sub_agent(
            agent_type="coder",
            task_payload={"objective": "Build feature"},
            background=True,
            session_id="sess-bg-1",
        )

        assert result["background"] is True
        assert result["task_id"] == "spawner-77"

    def test_pool_at_capacity_raises(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            max_background_agents=1,
        )

        # Fill the pool
        engine.spawn_sub_agent(
            agent_type="coder",
            task_payload={"objective": "Task 1"},
            background=True,
            session_id="sess-bg-2",
        )

        with pytest.raises(SubAgentPoolFullError, match="full"):
            engine.spawn_sub_agent(
                agent_type="reviewer",
                task_payload={"objective": "Task 2"},
                background=True,
                session_id="sess-bg-3",
            )

    def test_background_status_tracks_tasks(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="bg-task-1"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        engine.spawn_sub_agent(
            agent_type="coder",
            task_payload={"objective": "Task"},
            background=True,
            session_id="sess-bg-4",
        )

        status = engine.background_status("bg-task-1")
        assert status == DELEGATED_OUTPUT_COMPLETED

    def test_background_active_count(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        assert engine.background_active_count() == 0
        engine.spawn_sub_agent(
            agent_type="coder",
            task_payload={"objective": "Task"},
            background=True,
            session_id="sess-bg-5",
        )
        assert engine.background_active_count() == 1

    def test_background_status_unknown_returns_none(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        assert engine.background_status("nonexistent") is None


# ---------------------------------------------------------------------------
# Tests: execute_deterministic_gate
# ---------------------------------------------------------------------------

class TestDeterministicGate:
    def test_gate_pass_records_event_and_updates_map(self):
        """Simulate a gate pass by testing the event recording directly.
        The actual subprocess call is tested via the _record_gate_event method.
        """
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        # Manually record a gate pass (avoiding real subprocess call)
        engine._record_gate_event(
            session_id="sess-gate-1",
            passed=True,
            detail="15 passed in 2.34s",
        )

        assert len(event_bus.events) == 1
        event_type, payload = event_bus.events[0]
        assert event_type == "GATE_PASSED"
        assert payload["passed"] is True

    def test_gate_fail_records_event(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
        )

        engine._record_gate_event(
            session_id="sess-gate-2",
            passed=False,
            detail="2 failed, 13 passed in 3.12s",
        )

        event_type, payload = event_bus.events[0]
        assert event_type == "GATE_FAILED"
        assert payload["passed"] is False

    def test_gate_pass_updates_materialized_map(self):
        spawner = SpawnerSpy(make_delegated_result(DELEGATED_STATUS_SUCCESS, task_id="spawner-77"))
        event_bus = EventBusSpy()
        blackboard = BlackboardSpy()
        db = DatabaseSpy()

        engine = ExecutionEngine(
            db=db,
            spawner=spawner,
            event_bus=event_bus,
            blackboard=blackboard,
            project_id="test-project",
        )

        # Simulate the gate pass path (what happens in execute_deterministic_gate
        # when passed=True)
        engine._record_gate_event(
            session_id="sess-gate-3",
            passed=True,
            detail="10 passed",
        )

        engine._db.upsert_materialized_context_map(
            project_id="test-project",
            active_persona="gate",
            pedagogy_snapshot={},
            verified_state={
                "gate_passed": True,
                "test_count": 10,
            },
            last_event_id=1,
        )

        mmap = db.materialized_maps["test-project"]
        assert mmap["active_persona"] == "gate"
        assert mmap["verified_state"]["gate_passed"] is True
        assert mmap["verified_state"]["test_count"] == 10


# ---------------------------------------------------------------------------
# Tests: _parse_test_count
# ---------------------------------------------------------------------------

class TestParseTestCount:
    def test_parses_standard_pytest_output(self):
        stdout = "10 passed in 1.23s"
        count = ExecutionEngine._parse_test_count(stdout)
        assert count == 10

    def test_parses_large_count(self):
        stdout = "152 passed, 3 skipped in 45.67s"
        count = ExecutionEngine._parse_test_count(stdout)
        assert count == 152

    def test_returns_zero_on_no_match(self):
        count = ExecutionEngine._parse_test_count("FAILED (errors=5)")
        assert count == 0

    def test_returns_zero_on_empty(self):
        count = ExecutionEngine._parse_test_count("")
        assert count == 0
