"""Tests for the v1 EventBus pub/sub dispatch used by v2 engines.

Verifies:
  - publish persists events via EventStore
  - subscribe fires handlers on matching event types
  - unsubscribe removes handlers
  - async session subscriptions work for ReAct mode

Uses typed BaseEvent instances through the v1 EventBus.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from harness_poc.core.events.events import (
    AgentInputAdded,
    ExecutionCompleted,
    ProbeCompleted,
    ProbeFailed,
    WorkflowStarted,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class EventStoreSpy:
    """Records persisted events for assertion."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def persist(self, event: Any) -> None:
        self.events.append(event)

    async def persist_async(self, event: Any) -> None:
        self.events.append(event)

    def get_recent_events(
        self, *, session_id, limit=20, event_types=None
    ):
        return [e for e in self.events if e.session_id == session_id][-limit:]


def _make_bus(store=None):
    """Create a v1 EventBus with a spy store."""
    from harness_poc.core.events.event_bus import EventBus

    if store is None:
        store = EventStoreSpy()
    return EventBus(store)


# ---------------------------------------------------------------------------
# Tests: publish
# ---------------------------------------------------------------------------


class TestEventBusPublish:
    """Acceptance criterion: publish persists an event row."""

    def test_publish_persists_event(self):
        store = EventStoreSpy()
        bus = _make_bus(store)

        bus.publish(
            AgentInputAdded(session_id="sess-1", user_content="value")
        )

        assert len(store.events) == 1
        event = store.events[0]
        assert isinstance(event, AgentInputAdded)
        assert event.session_id == "sess-1"
        assert event.user_content == "value"

    def test_publish_defaults_session_id(self):
        store = EventStoreSpy()
        bus = _make_bus(store)

        bus.publish(
            AgentInputAdded(session_id="sess-default", user_content="data")
        )

        assert store.events[0].session_id == "sess-default"

    def test_publish_with_different_event_type(self):
        store = EventStoreSpy()
        bus = _make_bus(store)

        bus.publish(
            ProbeFailed(session_id="sess-2", execution_error={"key": "val"})
        )

        assert isinstance(store.events[0], ProbeFailed)
        assert store.events[0].session_id == "sess-2"


class TestEventBusSubscribe:
    """Acceptance criterion: subscribe fires the handler on matching events."""

    def test_subscribe_handler_is_called(self):
        store = EventStoreSpy()
        bus = _make_bus(store)

        received: list[Any] = []

        def handler(event: AgentInputAdded) -> None:
            received.append(event)

        bus.subscribe(AgentInputAdded, handler)
        bus.publish(AgentInputAdded(session_id="sess-3", user_content="hello"))

        assert len(received) == 1
        assert isinstance(received[0], AgentInputAdded)
        assert received[0].user_content == "hello"

    def test_subscribe_only_fires_for_matching_type(self):
        store = EventStoreSpy()
        bus = _make_bus(store)

        received: list[str] = []

        def handler_a(event: AgentInputAdded) -> None:
            received.append(f"A:{event.event_type}")

        def handler_b(event: ProbeFailed) -> None:
            received.append(f"B:{event.event_type}")

        bus.subscribe(AgentInputAdded, handler_a)
        bus.subscribe(ProbeFailed, handler_b)
        bus.publish(AgentInputAdded(session_id="s-4", user_content="x"))

        assert received == ["A:AgentInputAdded"]

    def test_multiple_handlers_for_same_event(self):
        store = EventStoreSpy()
        bus = _make_bus(store)

        received: list[str] = []

        def h1(event: AgentInputAdded) -> None:
            received.append("h1")

        def h2(event: AgentInputAdded) -> None:
            received.append("h2")

        bus.subscribe(AgentInputAdded, h1)
        bus.subscribe(AgentInputAdded, h2)
        bus.publish(AgentInputAdded(session_id="s-5", user_content="x"))

        assert sorted(received) == ["h1", "h2"]

    def test_handler_exception_does_not_crash_publish(self):
        store = EventStoreSpy()
        bus = _make_bus(store)

        received: list[str] = []

        def crashy(event: AgentInputAdded) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        def safe(event: AgentInputAdded) -> None:
            received.append("safe")

        bus.subscribe(AgentInputAdded, crashy)
        bus.subscribe(AgentInputAdded, safe)
        bus.publish(AgentInputAdded(session_id="s-6", user_content="x"))

        assert received == ["safe"]


class TestEventBusUnsubscribe:
    """Acceptance criterion: unsubscribe removes a handler."""

    def test_unsubscribe_stops_handler(self):
        bus = _make_bus()

        received: list[str] = []

        def handler(event: AgentInputAdded) -> None:
            received.append("fired")

        bus.subscribe(AgentInputAdded, handler)
        bus.unsubscribe(AgentInputAdded, handler)
        bus.publish(AgentInputAdded(session_id="s-7", user_content="x"))

        assert received == []

    def test_unsubscribe_nonexistent_handler_is_noop(self):
        bus = _make_bus()

        def handler(event: AgentInputAdded) -> None:
            pass

        # Should not raise
        bus.unsubscribe(AgentInputAdded, handler)


# ---------------------------------------------------------------------------
# Tests: async session subscriptions for ReAct mode
# ---------------------------------------------------------------------------


class TestAsyncSessionSubscription:
    """Async session-scoped subscriptions for ReAct mode workers."""

    @pytest.mark.asyncio
    async def test_session_subscription_receives_events(self):
        bus = _make_bus()

        received: list[Any] = []

        async def collector() -> None:
            async for event in bus.subscribe_session("sess-async"):
                received.append(event)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(collector())
        await asyncio.sleep(0)  # let subscriber start
        bus.publish(
            AgentInputAdded(session_id="sess-async", user_content="hello")
        )
        await asyncio.wait_for(task, timeout=2)

        assert len(received) == 1
        assert isinstance(received[0], AgentInputAdded)
        assert received[0].user_content == "hello"

    @pytest.mark.asyncio
    async def test_session_subscription_only_receives_matching_session(self):
        bus = _make_bus()

        received_a: list[Any] = []
        received_b: list[Any] = []

        async def collector_a() -> None:
            async for event in bus.subscribe_session("sess-A"):
                received_a.append(event)
                break

        async def collector_b() -> None:
            async for event in bus.subscribe_session("sess-B"):
                received_b.append(event)
                break

        task_a = asyncio.create_task(collector_a())
        task_b = asyncio.create_task(collector_b())
        await asyncio.sleep(0)
        bus.publish(
            AgentInputAdded(session_id="sess-B", user_content="for B")
        )
        await asyncio.wait_for(task_b, timeout=2)

        assert len(received_a) == 0
        assert len(received_b) == 1


# ---------------------------------------------------------------------------
# Tests: pipeline events flow through bus
# ---------------------------------------------------------------------------


class TestPipelineEventsViaBus:
    """Verify that context_engine and execution_engine route events through the bus."""

    def test_context_engine_warm_up_publishes_events(self):
        from harness_poc.v2.context_engine import ContextEngine

        store = EventStoreSpy()
        bus = _make_bus(store)

        class MaterializerSpy:
            def materialize(self, _corpus_path: str):
                from harness_poc.v2.contracts.context_map_pipeline import (
                    DbContextMap,
                )

                return DbContextMap(
                    map_id="test",
                    rendered="rendered",
                    render_mode="full",
                    source_paths=["docs/"],
                    token_count=100,
                    stages_run=["test"],
                )

        class DatabaseSpy:
            def __init__(self) -> None:
                pass
            def append_context_event(self, **kw: Any) -> int:
                return 1

        engine = ContextEngine(
            db=DatabaseSpy(),
            materializer=MaterializerSpy(),
            personas_dir=None,  # type: ignore[arg-type]
            pedagogy_path=None,  # type: ignore[arg-type]
            event_bus=bus,
        )

        engine._publish_event(
            ProbeFailed(
                session_id="sess-probe",
                team_member="orchestrator",
                execution_error={"key": "val"},
            )
        )

        # Event persisted through the EventBus store
        assert len(store.events) == 1
        assert isinstance(store.events[0], ProbeFailed)
        assert store.events[0].execution_error["key"] == "val"

    def test_context_engine_falls_back_to_db_when_no_bus(self):
        from harness_poc.v2.context_engine import ContextEngine

        class DatabaseSpy:
            def __init__(self) -> None:
                self.events: list[dict] = []
            def append_context_event(self, session_id, team_member, event_type, payload) -> int:
                self.events.append(
                    {"session_id": session_id, "team_member": team_member,
                     "event_type": event_type, "payload": payload}
                )
                return 1

        db = DatabaseSpy()

        engine = ContextEngine(
            db=db,
            materializer=None,  # type: ignore[arg-type]
            personas_dir=None,  # type: ignore[arg-type]
            pedagogy_path=None,  # type: ignore[arg-type]
            event_bus=None,
        )

        engine._publish_event(
            ProbeFailed(
                session_id="sess-fb",
                team_member="test",
            )
        )

        assert len(db.events) == 1
        assert db.events[0]["event_type"] == "ProbeFailed"


# ---------------------------------------------------------------------------
# Tests: PipelineStepRunner
# ---------------------------------------------------------------------------


class TestPipelineStepRunnerEventChain:
    """Verify the pipeline subscriber chains events correctly."""

    def test_workflow_started_publishes_probe_completed(self):
        from harness_poc.v2.subscribers.pipeline_runner import PipelineStepRunner

        store = EventStoreSpy()
        bus = _make_bus(store)

        # Minimal spy orchestrator
        class OrchSpy:
            class ExecSpy:
                _event_bus = bus
            _execution = ExecSpy()

            def run_exploration_probe(self, code, session_id):
                from harness_poc.v2.workflow_orchestrator import ProbeResult

                return ProbeResult(
                    probe_id="p1",
                    success=True,
                    exit_code=0,
                    stdout="ok",
                    stderr="",
                )

        runner = PipelineStepRunner(OrchSpy(), bus)
        bus.subscribe(WorkflowStarted, runner.handle_workflow_started)
        bus.subscribe(ProbeCompleted, runner.handle_probe_completed)
        bus.subscribe(ExecutionCompleted, runner.handle_execution_completed)

        bus.publish(
            WorkflowStarted(
                session_id="sess-chain",
                workflow_id="wf-1",
                probe_code="print('hello')",
                tasks=[],
            )
        )

        # Should have WorkflowStarted + ProbeCompleted + ExecutionCompleted
        event_names = [e.event_type for e in store.events]
        assert "WorkflowStarted" in event_names
        assert "ProbeCompleted" in event_names
        assert "ExecutionCompleted" in event_names

    def test_reentrancy_guard_prevents_infinite_loop(self):
        from harness_poc.v2.subscribers.pipeline_runner import PipelineStepRunner

        store = EventStoreSpy()
        bus = _make_bus(store)

        class OrchSpy:
            class ExecSpy:
                _event_bus = bus
            _execution = ExecSpy()

            def run_exploration_probe(self, code, session_id):
                from harness_poc.v2.workflow_orchestrator import ProbeResult

                return ProbeResult(
                    probe_id="p1", success=True, exit_code=0, stdout="", stderr=""
                )

        runner = PipelineStepRunner(OrchSpy(), bus)
        bus.subscribe(WorkflowStarted, runner.handle_workflow_started)
        bus.subscribe(ProbeCompleted, runner.handle_probe_completed)
        bus.subscribe(ExecutionCompleted, runner.handle_execution_completed)

        # Publish WorkflowStarted multiple times — handlers should only fire once
        bus.publish(
            WorkflowStarted(
                session_id="sess-reentrant",
                workflow_id="wf-2",
                tasks=[],
            )
        )

        # Only one ProbeCompleted and ExecutionCompleted should appear
        probe_count = sum(
            1 for e in store.events if isinstance(e, ProbeCompleted)
        )
        exec_count = sum(
            1 for e in store.events if isinstance(e, ExecutionCompleted)
        )
        assert probe_count == 1
        assert exec_count == 1
