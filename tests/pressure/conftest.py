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
)
from harness_poc.v2.contracts.sub_agent_spawner import (
    DELEGATED_STATUS_SUCCESS,
    DelegatedTaskResult,
)
from harness_poc.v2.execution_engine import (
    ExecutionEngine,
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
def engine(
    spawner: SpawnerSpy, event_bus: EventBusSpy, blackboard: BlackboardSpy
) -> ExecutionEngine:
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
