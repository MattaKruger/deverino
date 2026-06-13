"""Hardening tests for the v2-to-v1 EventBus fusion.

Verifies that:
  - v2 events persist through v1 EventStore and are readable back
  - v2 events dispatch to typed handlers correctly
  - v1 EventBus unsubscribe works (added for fusion)
  - v1 and v2 events coexist in the same event log
  - Handler exceptions don't crash dispatch
  - Session isolation is maintained
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine

from harness_poc.core.events import (
    AgentInputAdded,
    AgentStarted,
    ContextWarmed,
    DelegateTaskCompleted,
    EventBus,
    EventStore,
    ExecutionCompleted,
    GateCompleted,
    GateFailed,
    GatePassed,
    LLMActionEmitted,
    ProbeCompleted,
    ProbeFailed,
    SkillCompleted,
    SpecCommitted,
    WorkflowStarted,
)

# ---------------------------------------------------------------------------
# Persistence: v2 events persist through v1 EventStore
# ---------------------------------------------------------------------------


class TestV2EventPersistence:
    """v2 events published via v1 EventBus persist and are retrievable."""

    def test_workflow_started_persists_and_reads_back(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        event = WorkflowStarted(
            session_id="s1", workflow_id="wf1", goal="test goal", persona_id="coder"
        )
        bus.publish(event)
        events = bus.get_recent_events("s1")
        assert len(events) == 1
        assert isinstance(events[0], WorkflowStarted)
        assert events[0].workflow_id == "wf1"
        assert events[0].goal == "test goal"

    def test_probe_completed_round_trips(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        event = ProbeCompleted(
            session_id="s1",
            workflow_id="wf1",
            probe_id="p1",
            success=True,
            exit_code=0,
            constraints=[{"type": "missing_dep", "detail": "numpy"}],
        )
        bus.publish(event)
        events = bus.get_recent_events("s1")
        assert len(events) == 1
        assert isinstance(events[0], ProbeCompleted)
        assert events[0].constraints == [{"type": "missing_dep", "detail": "numpy"}]

    def test_gate_passed_and_failed_round_trip(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        passed = GatePassed(
            session_id="s1", passed=True, detail="all good", project_id="deverino"
        )
        failed = GatePassed(
            session_id="s1", passed=False, detail="3 tests failed", project_id="deverino"
        )
        bus.publish(passed)
        bus.publish(failed)
        events = bus.get_recent_events("s1")
        assert len(events) == 2
        assert events[0].passed is True
        assert events[1].passed is False

    def test_delegate_task_completed_persists(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        event = DelegateTaskCompleted(
            session_id="s1",
            task_id="task-001",
            output_label="completed",
            summary="Task done",
        )
        bus.publish(event)
        events = bus.get_recent_events("s1")
        assert len(events) == 1
        assert isinstance(events[0], DelegateTaskCompleted)
        assert events[0].output_label == "completed"

    def test_multiple_v2_event_types_coexist(self, db_engine: Engine) -> None:
        """All v2 events round-trip cleanly through EventStore."""
        bus = EventBus(EventStore(db_engine))
        session = "s-multi"

        events_in = [
            WorkflowStarted(session_id=session, workflow_id="wf1"),
            ProbeCompleted(session_id=session),
            ExecutionCompleted(session_id=session),
            GateCompleted(session_id=session),
            ProbeFailed(session_id=session),
            GatePassed(session_id=session),
            SpecCommitted(session_id=session),
            DelegateTaskCompleted(session_id=session),
        ]

        for evt in events_in:
            bus.publish(evt)

        events_out = bus.get_recent_events(session)
        assert len(events_out) == len(events_in)
        for i, cls in enumerate(
            [
                WorkflowStarted,
                ProbeCompleted,
                ExecutionCompleted,
                GateCompleted,
                ProbeFailed,
                GatePassed,
                SpecCommitted,
                DelegateTaskCompleted,
            ]
        ):
            assert isinstance(events_out[i], cls), f"Event {i} should be {cls.__name__}"


# ---------------------------------------------------------------------------
# Cross-mode coexistence: v1 and v2 events share the log
# ---------------------------------------------------------------------------


class TestCrossModeCoexistence:
    """v1 and v2 events coexist in the same event log."""

    def test_v1_and_v2_events_in_same_session(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        session = "s-cross"

        bus.publish(AgentStarted(session_id=session, goal="v1 goal"))
        bus.publish(WorkflowStarted(session_id=session, workflow_id="wf1"))
        bus.publish(SkillCompleted(session_id=session, status="success"))
        bus.publish(GateCompleted(session_id=session, passed=True))

        events = bus.get_recent_events(session)
        assert len(events) == 4
        assert isinstance(events[0], AgentStarted)
        assert isinstance(events[1], WorkflowStarted)
        assert isinstance(events[2], SkillCompleted)
        assert isinstance(events[3], GateCompleted)

    def test_v1_handler_ignores_v2_events(self, db_engine: Engine) -> None:
        """A v1 handler subscribed to AgentStarted doesn't receive v2 events."""
        bus = EventBus(EventStore(db_engine))
        received: list[str] = []

        def handler(event: AgentStarted) -> None:
            received.append(event.goal)

        bus.subscribe(AgentStarted, handler)
        bus.publish(WorkflowStarted(session_id="s1", workflow_id="wf1"))
        bus.publish(ProbeCompleted(session_id="s1"))
        bus.publish(AgentStarted(session_id="s1", goal="only this"))

        assert received == ["only this"]


# ---------------------------------------------------------------------------
# Typed dispatch: v2 events delivered to subscribers
# ---------------------------------------------------------------------------


class TestV2EventDispatch:
    """v2 events dispatch to subscribers with correct typed event objects."""

    def test_workflow_started_dispatches_to_handler(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        handler = MagicMock()
        bus.subscribe(WorkflowStarted, handler)
        event = WorkflowStarted(session_id="s1", workflow_id="wf1", goal="g")
        bus.publish(event)
        handler.assert_called_once_with(event)

    def test_probe_completed_dispatches_to_handler(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        received: list[ProbeCompleted] = []

        def handler(event: ProbeCompleted) -> None:
            received.append(event)

        bus.subscribe(ProbeCompleted, handler)
        bus.publish(ProbeCompleted(session_id="s1", probe_id="p1", success=True))
        assert len(received) == 1
        assert received[0].probe_id == "p1"
        assert received[0].success is True

    def test_gate_completed_receives_correct_fields(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        received: list[dict[str, Any]] = []

        def handler(event: GateCompleted) -> None:
            received.append(
                {
                    "gate_id": event.gate_id,
                    "passed": event.passed,
                    "test_count": event.test_count,
                }
            )

        bus.subscribe(GateCompleted, handler)
        bus.publish(
            GateCompleted(
                session_id="s1", gate_id="g42", passed=True, test_count=15
            )
        )
        assert received == [{"gate_id": "g42", "passed": True, "test_count": 15}]

    def test_spec_committed_dispatches(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        handler = MagicMock()
        bus.subscribe(SpecCommitted, handler)
        event = SpecCommitted(
            session_id="s1",
            execution_id="exec-1",
            task_count=5,
            failure_count=1,
            all_passed=False,
        )
        bus.publish(event)
        handler.assert_called_once()
        assert handler.call_args[0][0].task_count == 5


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


class TestEventBusUnsubscribe:
    """v1 EventBus.unsubscribe removes handlers correctly."""

    def test_unsubscribe_stops_dispatch(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        received: list[str] = []

        def handler(event: WorkflowStarted) -> None:
            received.append(event.workflow_id)

        bus.subscribe(WorkflowStarted, handler)
        bus.unsubscribe(WorkflowStarted, handler)
        bus.publish(WorkflowStarted(session_id="s1", workflow_id="wf1"))
        assert received == []

    def test_unsubscribe_does_not_affect_other_handlers(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        results_a: list[str] = []
        results_b: list[str] = []

        def handler_a(event: WorkflowStarted) -> None:
            results_a.append(event.workflow_id)

        def handler_b(event: WorkflowStarted) -> None:
            results_b.append(event.workflow_id)

        bus.subscribe(WorkflowStarted, handler_a)
        bus.subscribe(WorkflowStarted, handler_b)
        bus.unsubscribe(WorkflowStarted, handler_a)
        bus.publish(WorkflowStarted(session_id="s1", workflow_id="wf1"))

        assert results_a == []
        assert results_b == ["wf1"]

    def test_unsubscribe_nonexistent_is_noop(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))

        def handler(event: WorkflowStarted) -> None:
            pass

        # Should not raise
        bus.unsubscribe(WorkflowStarted, handler)


# ---------------------------------------------------------------------------
# Handler exception resilience
# ---------------------------------------------------------------------------


class TestHandlerExceptionResilience:
    """Exceptions in handlers don't crash publish or affect other handlers."""

    def test_v2_handler_exception_does_not_crash_publish(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        received: list[str] = []

        def crashy(event: WorkflowStarted) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        def safe(event: WorkflowStarted) -> None:
            received.append(event.workflow_id)

        bus.subscribe(WorkflowStarted, crashy)
        bus.subscribe(WorkflowStarted, safe)
        bus.publish(WorkflowStarted(session_id="s1", workflow_id="wf1"))

        assert received == ["wf1"]

    def test_exception_handler_persistence_still_works(self, db_engine: Engine) -> None:
        """Even if a handler crashes, the event is still persisted."""
        bus = EventBus(EventStore(db_engine))

        def crashy(event: ProbeCompleted) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        bus.subscribe(ProbeCompleted, crashy)
        bus.publish(ProbeCompleted(session_id="s1", probe_id="p1"))

        events = bus.get_recent_events("s1")
        assert len(events) == 1
        assert isinstance(events[0], ProbeCompleted)


# ---------------------------------------------------------------------------
# Session isolation (async)
# ---------------------------------------------------------------------------


class TestSessionIsolation:
    """Events for one session don't leak to another session's subscriber."""

    @pytest.mark.asyncio
    async def test_async_subscriber_only_receives_own_session(self, db_engine: Engine) -> None:
        bus = EventBus(EventStore(db_engine))
        session_a = "iso-a"
        session_b = "iso-b"

        received_a: list[type] = []
        received_b: list[type] = []

        async def collector_a() -> None:
            async for event in bus.subscribe(session_a):
                received_a.append(type(event))
                break

        async def collector_b() -> None:
            async for event in bus.subscribe(session_b):
                received_b.append(type(event))
                break

        task_a = asyncio.create_task(collector_a())
        task_b = asyncio.create_task(collector_b())
        await asyncio.sleep(0)

        # Publish to session B only — A should get nothing
        bus.publish(WorkflowStarted(session_id=session_b, workflow_id="wf-b"))

        await asyncio.wait_for(task_b, timeout=2)

        assert received_b == [WorkflowStarted]
        assert received_a == []

    @pytest.mark.asyncio
    async def test_v2_react_events_isolated_per_session(self, db_engine: Engine) -> None:
        """ReAct events for session A don't reach session B's subscriber."""
        bus = EventBus(EventStore(db_engine))
        session_a = "react-a"
        session_b = "react-b"

        received_a: list[str] = []
        received_b: list[str] = []

        async def collector(session_id: str, sink: list[str]) -> None:
            async for event in bus.subscribe(session_id):
                sink.append(event.__class__.__name__)
                if len(sink) >= 2:
                    break

        task_a = asyncio.create_task(collector(session_a, received_a))
        task_b = asyncio.create_task(collector(session_b, received_b))
        await asyncio.sleep(0)

        bus.publish(AgentInputAdded(session_id=session_b, user_content="hello"))
        bus.publish(LLMActionEmitted(session_id=session_b, tokens_used=100, model="test"))

        await asyncio.wait_for(task_b, timeout=2)

        assert "AgentInputAdded" in received_b
        assert "LLMActionEmitted" in received_b
        assert received_a == []


# ---------------------------------------------------------------------------
# Event registry — completeness check
# ---------------------------------------------------------------------------


class TestEventRegistryCompleteness:
    """All v2 event types are registered and constructable."""

    def test_all_v2_events_in_registry(self) -> None:
        from harness_poc.core.events.events import EVENT_REGISTRY

        required = {
            "WorkflowStarted",
            "ProbeCompleted",
            "ExecutionCompleted",
            "GateCompleted",
            "ProbeFailed",
            "ContextWarmed",
            "GatePassed",
            "GateFailed",
            "SpecCommitted",
            "DelegateTaskCompleted",
        }
        missing = required - set(EVENT_REGISTRY.keys())
        assert not missing, f"Missing from EVENT_REGISTRY: {missing}"

    def test_v2_events_constructable(self) -> None:
        """Every v2 event constructs with session_id only (minimal args)."""
        events = [
            WorkflowStarted(session_id="s1", workflow_id="wf1"),
            ProbeCompleted(session_id="s1"),
            ExecutionCompleted(session_id="s1"),
            GateCompleted(session_id="s1"),
            ProbeFailed(session_id="s1"),
            ContextWarmed(session_id="s1"),
            GatePassed(session_id="s1"),
            GateFailed(session_id="s1"),
            SpecCommitted(session_id="s1"),
            DelegateTaskCompleted(session_id="s1"),
        ]
        assert len(events) == 10
        # Verify each has correct type_name
        for evt in events:
            assert evt.event_type == evt.__class__.__name__
            assert evt.session_id == "s1"
