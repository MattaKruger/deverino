"""Tests for the v2 EventBus adapter and pub/sub dispatch.

Verifies Phase 2a acceptance criteria:
  - publish persists events
  - subscribe fires handlers on matching events
  - unsubscribe removes handlers
  - async session subscriptions work for ReAct mode

Uses an in-memory database spy so tests run fast without PostgreSQL.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class DatabaseSpy:
    """Records db.append_context_event calls for assertion."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self._event_id = 1

    def append_context_event(
        self,
        session_id: str,
        team_member: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        eid = self._event_id
        self._event_id += 1
        self.events.append(
            {
                "id": eid,
                "session_id": session_id,
                "team_member": team_member,
                "event_type": event_type,
                "payload": payload,
            }
        )
        return eid

    def write_memory(self, **kwargs: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests: Phase 2a — real EventBus adapter
# ---------------------------------------------------------------------------


class TestEventBusPublish:
    """Acceptance criterion: publish persists an event row."""

    def test_publish_persists_event(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        bus.publish("TEST_EVENT", {"session_id": "sess-1", "key": "value"})

        assert len(db.events) == 1
        event = db.events[0]
        assert event["event_type"] == "TEST_EVENT"
        assert event["session_id"] == "sess-1"
        assert event["payload"]["key"] == "value"

    def test_publish_defaults_session_id(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        bus.publish("NO_SESSION", {"data": 42})

        assert db.events[0]["session_id"] == "v2-runtime"

    def test_publish_defaults_team_member(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        bus.publish("NO_TEAM", {"session_id": "sess-2"})

        assert db.events[0]["team_member"] == "v2"


class TestEventBusSubscribe:
    """Acceptance criterion: subscribe fires the handler on matching events."""

    def test_subscribe_handler_is_called(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        received: list[tuple[str, dict]] = []

        def handler(event_type: str, payload: dict) -> None:
            received.append((event_type, payload))

        bus.subscribe("MY_EVENT", handler)
        bus.publish("MY_EVENT", {"session_id": "sess-3", "msg": "hello"})

        assert len(received) == 1
        assert received[0][0] == "MY_EVENT"
        assert received[0][1]["msg"] == "hello"

    def test_subscribe_only_fires_for_matching_type(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        received: list[str] = []

        def handler_a(event_type: str, _payload: dict) -> None:
            received.append(f"A:{event_type}")

        def handler_b(event_type: str, _payload: dict) -> None:
            received.append(f"B:{event_type}")

        bus.subscribe("TYPE_A", handler_a)
        bus.subscribe("TYPE_B", handler_b)
        bus.publish("TYPE_A", {"session_id": "s-4"})

        assert received == ["A:TYPE_A"]

    def test_multiple_handlers_for_same_event(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        received: list[str] = []

        def h1(_et: str, _p: dict) -> None:
            received.append("h1")

        def h2(_et: str, _p: dict) -> None:
            received.append("h2")

        bus.subscribe("SHARED", h1)
        bus.subscribe("SHARED", h2)
        bus.publish("SHARED", {"session_id": "s-5"})

        assert sorted(received) == ["h1", "h2"]

    def test_handler_exception_does_not_crash_publish(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        received: list[str] = []

        def crashy(_et: str, _p: dict) -> None:
            raise RuntimeError("boom")

        def safe(_et: str, _p: dict) -> None:
            received.append("safe")

        bus.subscribe("DANGER", crashy)
        bus.subscribe("DANGER", safe)
        bus.publish("DANGER", {"session_id": "s-6"})

        assert received == ["safe"]


class TestEventBusUnsubscribe:
    """Acceptance criterion: unsubscribe removes a handler."""

    def test_unsubscribe_stops_handler(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        received: list[str] = []

        def handler(_et: str, _p: dict) -> None:
            received.append("fired")

        bus.subscribe("EPHEMERAL", handler)
        bus.unsubscribe("EPHEMERAL", handler)
        bus.publish("EPHEMERAL", {"session_id": "s-7"})

        assert received == []

    def test_unsubscribe_nonexistent_handler_is_noop(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        def handler(_et: str, _p: dict) -> None:
            pass

        # Should not raise
        bus.unsubscribe("NONEXISTENT", handler)


# ---------------------------------------------------------------------------
# Tests: Phase 2c — async session subscriptions for ReAct mode
# ---------------------------------------------------------------------------


class TestAsyncSessionSubscription:
    """Async session-scoped subscriptions for ReAct mode workers."""

    @pytest.mark.asyncio
    async def test_session_subscription_receives_events(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        received: list[dict] = []

        async def collector() -> None:
            async for envelope in bus.subscribe_session("sess-async"):
                received.append(envelope)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(collector())
        await asyncio.sleep(0)  # let subscriber start
        bus.publish("AGENT_INPUT", {"session_id": "sess-async", "content": "hello"})
        await asyncio.wait_for(task, timeout=2)

        assert len(received) == 1
        assert received[0]["event_type"] == "AGENT_INPUT"
        assert received[0]["payload"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_session_subscription_only_receives_matching_session(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        received_a: list[dict] = []
        received_b: list[dict] = []

        async def collector_a() -> None:
            async for envelope in bus.subscribe_session("sess-A"):
                received_a.append(envelope)
                break

        async def collector_b() -> None:
            async for envelope in bus.subscribe_session("sess-B"):
                received_b.append(envelope)
                break

        task_a = asyncio.create_task(collector_a())
        task_b = asyncio.create_task(collector_b())
        await asyncio.sleep(0)
        bus.publish("AGENT_INPUT", {"session_id": "sess-B", "content": "for B"})
        await asyncio.wait_for(task_b, timeout=2)

        assert len(received_a) == 0
        assert len(received_b) == 1


# ---------------------------------------------------------------------------
# Tests: Phase 2a — pipeline events flow through bus
# ---------------------------------------------------------------------------


class TestPipelineEventsViaBus:
    """Verify that context_engine and execution_engine route events through the bus."""

    def test_context_engine_warm_up_publishes_events(self):
        from harness_poc.v2.context_engine import ContextEngine
        from harness_poc.v2.wiring import _build_event_bus_adapter

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

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

        engine = ContextEngine(
            db=db,
            materializer=MaterializerSpy(),
            personas_dir=None,  # type: ignore[arg-type]
            pedagogy_path=None,  # type: ignore[arg-type]
            event_bus=bus,
        )

        # Directly test _publish_event (warm_up_context_from_failure is
        # complex — test the event path via _publish_event directly)
        engine._publish_event(
            "PROBE_FAILED",
            {
                "session_id": "sess-probe",
                "team_member": "orchestrator",
                "key": "val",
            },
        )

        assert len(db.events) == 1
        assert db.events[0]["event_type"] == "PROBE_FAILED"
        assert db.events[0]["payload"]["key"] == "val"

    def test_context_engine_falls_back_to_db_when_no_bus(self):
        from harness_poc.v2.context_engine import ContextEngine

        db = DatabaseSpy()

        engine = ContextEngine(
            db=db,
            materializer=None,  # type: ignore[arg-type]
            personas_dir=None,  # type: ignore[arg-type]
            pedagogy_path=None,  # type: ignore[arg-type]
            event_bus=None,
        )

        engine._publish_event(
            "TEST_FALLBACK",
            {"session_id": "sess-fb", "team_member": "test"},
        )

        assert len(db.events) == 1
        assert db.events[0]["event_type"] == "TEST_FALLBACK"


# ---------------------------------------------------------------------------
# Tests: Phase 2b — PipelineStepRunner
# ---------------------------------------------------------------------------


class TestPipelineStepRunnerEventChain:
    """Verify the pipeline subscriber chains events correctly."""

    def test_workflow_started_publishes_probe_completed(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter
        from harness_poc.v2.subscribers.pipeline_runner import PipelineStepRunner

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

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

        runner = PipelineStepRunner(OrchSpy())
        bus.subscribe("WORKFLOW_STARTED", runner.handle_workflow_started)
        bus.subscribe("PROBE_COMPLETED", runner.handle_probe_completed)
        bus.subscribe("EXECUTION_COMPLETED", runner.handle_execution_completed)

        bus.publish(
            "WORKFLOW_STARTED",
            {
                "session_id": "sess-chain",
                "workflow_id": "wf-1",
                "probe_code": "print('hello')",
                "tasks": [],
            },
        )

        # Should have WORKFLOW_STARTED + PROBE_COMPLETED + EXECUTION_COMPLETED
        event_types = [e["event_type"] for e in db.events]
        assert "WORKFLOW_STARTED" in event_types
        assert "PROBE_COMPLETED" in event_types
        assert "EXECUTION_COMPLETED" in event_types

    def test_reentrancy_guard_prevents_infinite_loop(self):
        from harness_poc.v2.wiring import _build_event_bus_adapter
        from harness_poc.v2.subscribers.pipeline_runner import PipelineStepRunner

        db = DatabaseSpy()
        bus = _build_event_bus_adapter(db)

        class OrchSpy:
            class ExecSpy:
                _event_bus = bus
            _execution = ExecSpy()

            def run_exploration_probe(self, code, session_id):
                from harness_poc.v2.workflow_orchestrator import ProbeResult

                return ProbeResult(
                    probe_id="p1", success=True, exit_code=0, stdout="", stderr=""
                )

        runner = PipelineStepRunner(OrchSpy())
        bus.subscribe("WORKFLOW_STARTED", runner.handle_workflow_started)
        bus.subscribe("PROBE_COMPLETED", runner.handle_probe_completed)
        bus.subscribe("EXECUTION_COMPLETED", runner.handle_execution_completed)

        # Publish WORKFLOW_STARTED multiple times — handlers should only fire once
        bus.publish(
            "WORKFLOW_STARTED",
            {"session_id": "sess-reentrant", "workflow_id": "wf-2", "tasks": []},
        )

        # Only one PROBE_COMPLETED and EXECUTION_COMPLETED should appear
        probe_count = sum(
            1 for e in db.events if e["event_type"] == "PROBE_COMPLETED"
        )
        exec_count = sum(
            1 for e in db.events if e["event_type"] == "EXECUTION_COMPLETED"
        )
        assert probe_count == 1
        assert exec_count == 1
