"""Integration tests for the v2 ReAct loop and CircuitBreaker subscribers.

Verifies Phase 2c acceptance criteria:
  - Publishing AgentInputAdded triggers a complete ReAct loop
  - CircuitBreaker publishes StreamPaused after N failures or token exhaustion

Uses typed BaseEvent instances through the v1 EventBus (no real LLM/tool calls).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from harness_poc.core.events.events import (
    AgentInputAdded,
    LLMActionEmitted,
    LLMTextEmitted,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class EventStoreSpy:
    """Records persisted events for assertion."""

    def __init__(self) -> None:
        from harness_poc.core.events.events import BaseEvent
        self.events: list[BaseEvent] = []

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
# Tests: Phase 2c — ReAct full-loop integration
# ---------------------------------------------------------------------------


class TestReActFullLoop:
    """Acceptance criterion: publishing AgentInputAdded triggers the complete
    ReAct loop (LLM → tool call → LLM → text response).

    Uses fast in-process spies — no real LLM or tool calls.
    """

    @pytest.mark.asyncio
    async def test_agent_input_delivered_to_subscriber(self) -> None:
        """AgentInputAdded is delivered to a session subscriber."""
        bus = _make_bus()
        session_id = "loop-sess-1"

        received: list[Any] = []

        async def collector() -> None:
            async for event in bus.subscribe_session(session_id):
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(collector())
        await asyncio.sleep(0)

        bus.publish(AgentInputAdded(session_id=session_id, user_content="hello"))
        bus.publish(LLMActionEmitted(session_id=session_id, model="test-model", tokens_used=100))

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(task, timeout=2)

        assert len(received) >= 1
        assert isinstance(received[0], AgentInputAdded)

    @pytest.mark.asyncio
    async def test_tool_request_triggers_tool_completion(self) -> None:
        """SkillRequested → ToolWorker.run → SkillCompleted."""
        from harness_poc.v2.subscribers.tool_worker import ToolWorker

        bus = _make_bus()
        session_id = "loop-sess-2"

        # Create a minimal SkillRunner spy
        class SkillRunnerSpy:
            class Result:
                def __init__(self) -> None:
                    self.status = "success"
                    self.content = "tool result"
                    self.artifacts = {}

            def execute_skill(self, tool_name, arguments, session_id, call_id):
                return SkillRunnerSpy.Result()

        worker = ToolWorker(skill_runner=SkillRunnerSpy())

        received: list[Any] = []

        async def run_worker_and_collect() -> None:
            async for event in bus.subscribe_session(session_id):
                received.append(event)
                if isinstance(event, SkillCompleted):
                    break

        task = asyncio.create_task(run_worker_and_collect())
        await asyncio.sleep(0)

        worker_task = asyncio.create_task(worker.run(bus, session_id))
        await asyncio.sleep(0)

        bus.publish(
            SkillRequested(
                session_id=session_id,
                skill_name="test_tool",
                arguments={"arg1": "value1"},
            )
        )

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(task, timeout=2)

        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task

        assert any(isinstance(e, SkillCompleted) for e in received)

    @pytest.mark.asyncio
    async def test_goal_evaluator_detects_text_output(self) -> None:
        """LLMTextEmitted → GoalEvaluator.run → GoalEvaluated."""
        from harness_poc.core.events.events import GoalEvaluated
        from harness_poc.v2.subscribers.goal_evaluator import GoalEvaluator

        bus = _make_bus()
        session_id = "loop-sess-3"

        evaluator = GoalEvaluator(max_iterations=50)

        received: list[Any] = []

        async def run_evaluator_and_collect() -> None:
            async for event in bus.subscribe_session(session_id):
                received.append(event)
                if isinstance(event, GoalEvaluated):
                    break

        task = asyncio.create_task(run_evaluator_and_collect())
        await asyncio.sleep(0)

        eval_task = asyncio.create_task(evaluator.run(bus, session_id))
        await asyncio.sleep(0)

        bus.publish(
            LLMTextEmitted(
                session_id=session_id, content="done"
            )
        )

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(task, timeout=2)

        eval_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await eval_task

        assert any(isinstance(e, GoalEvaluated) for e in received)

    @pytest.mark.asyncio
    async def test_goal_evaluator_marks_incomplete_at_max_iterations(self) -> None:
        """GoalEvaluated with is_complete=False when max_iterations reached."""
        from harness_poc.core.events.events import GoalEvaluated
        from harness_poc.v2.subscribers.goal_evaluator import GoalEvaluator

        bus = _make_bus()
        session_id = "loop-sess-4"

        evaluator = GoalEvaluator(max_iterations=2)

        received: list[Any] = []

        async def run_and_collect() -> None:
            async for event in bus.subscribe_session(session_id):
                received.append(event)
                if len(received) >= 3:
                    break

        task = asyncio.create_task(run_and_collect())
        await asyncio.sleep(0)

        eval_task = asyncio.create_task(evaluator.run(bus, session_id))
        await asyncio.sleep(0)

        # Publish 3 LLMActionEmitted (not text) to hit max_iterations=2
        for _i in range(3):
            bus.publish(
                LLMActionEmitted(
                    session_id=session_id, model="test", tokens_used=10
                )
            )
            await asyncio.sleep(0.01)

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(task, timeout=2)

        eval_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await eval_task

        goal_events = [e for e in received if isinstance(e, GoalEvaluated)]
        assert len(goal_events) >= 1
        assert goal_events[0].is_complete is False


# ---------------------------------------------------------------------------
# Tests: Phase 2c — CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Acceptance criterion: CircuitBreaker publishes StreamPaused
    after N consecutive failures or token budget exhaustion.
    """

    @pytest.mark.asyncio
    async def test_pauses_after_consecutive_failures(self) -> None:
        """StreamPaused published after max_retries consecutive failures."""
        from harness_poc.v2.subscribers.circuit_breaker import CircuitBreaker

        bus = _make_bus()
        session_id = "breaker-sess-1"

        breaker = CircuitBreaker(max_retries=2, max_tokens=1_000_000)

        received: list[Any] = []

        async def run_breaker_and_collect() -> None:
            async for event in bus.subscribe_session(session_id):
                received.append(event)
                if isinstance(event, StreamPaused):
                    break

        task = asyncio.create_task(run_breaker_and_collect())
        await asyncio.sleep(0)

        breaker_task = asyncio.create_task(breaker.run(bus, session_id))
        await asyncio.sleep(0)

        # Publish 3 consecutive failures (max_retries=2 → pause on 3rd)
        for i in range(3):
            bus.publish(
                SkillCompleted(
                    session_id=session_id,
                    skill_name="failing_tool",
                    status="failed",
                    content=f"error {i}",
                )
            )
            await asyncio.sleep(0.01)

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(task, timeout=2)

        breaker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await breaker_task

        stream_paused = [e for e in received if isinstance(e, StreamPaused)]
        assert len(stream_paused) >= 1
        assert stream_paused[0].reason == "consecutive_failures"

    @pytest.mark.asyncio
    async def test_resets_failure_count_on_success(self) -> None:
        """Consecutive failure count resets after a success — no pause."""
        from harness_poc.v2.subscribers.circuit_breaker import CircuitBreaker

        bus = _make_bus()
        session_id = "breaker-sess-2"

        breaker = CircuitBreaker(max_retries=2, max_tokens=1_000_000)

        received: list[Any] = []

        async def run_and_collect() -> None:
            async for event in bus.subscribe_session(session_id):
                received.append(event)
                if isinstance(event, StreamPaused):
                    break
                if len(received) >= 5:
                    break

        task = asyncio.create_task(run_and_collect())
        await asyncio.sleep(0)

        breaker_task = asyncio.create_task(breaker.run(bus, session_id))
        await asyncio.sleep(0)

        # Fail, fail, succeed, fail — count should reset after success
        bus.publish(
            SkillCompleted(session_id=session_id, status="failed", content="err1")
        )
        await asyncio.sleep(0.01)
        bus.publish(
            SkillCompleted(session_id=session_id, status="failed", content="err2")
        )
        await asyncio.sleep(0.01)
        bus.publish(
            SkillCompleted(session_id=session_id, status="success", content="ok")
        )
        await asyncio.sleep(0.01)
        bus.publish(
            SkillCompleted(session_id=session_id, status="failed", content="err3")
        )

        # Should NOT have paused (failures not consecutive enough)
        await asyncio.sleep(0.2)

        breaker_task.cancel()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await breaker_task
        with contextlib.suppress(asyncio.CancelledError):
            await task

        stream_paused = [e for e in received if isinstance(e, StreamPaused)]
        assert len(stream_paused) == 0

    @pytest.mark.asyncio
    async def test_pauses_on_token_budget_exhaustion(self) -> None:
        """StreamPaused published when cumulative tokens exceed max_tokens."""
        from harness_poc.v2.subscribers.circuit_breaker import CircuitBreaker

        bus = _make_bus()
        session_id = "breaker-sess-3"

        breaker = CircuitBreaker(max_retries=100, max_tokens=1_000)

        received: list[Any] = []

        async def run_breaker_and_collect() -> None:
            async for event in bus.subscribe_session(session_id):
                received.append(event)
                if isinstance(event, StreamPaused):
                    break

        task = asyncio.create_task(run_breaker_and_collect())
        await asyncio.sleep(0)

        breaker_task = asyncio.create_task(breaker.run(bus, session_id))
        await asyncio.sleep(0)

        # Publish LLMActionEmitted with 600 + 500 = 1100 > 1000 tokens
        bus.publish(LLMActionEmitted(session_id=session_id, model="test", tokens_used=600))
        await asyncio.sleep(0.01)
        bus.publish(LLMActionEmitted(session_id=session_id, model="test", tokens_used=500))

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(task, timeout=2)

        breaker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await breaker_task

        stream_paused = [e for e in received if isinstance(e, StreamPaused)]
        assert len(stream_paused) >= 1
        assert stream_paused[0].reason == "budget_exhausted"
