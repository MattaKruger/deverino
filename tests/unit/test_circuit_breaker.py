"""Unit tests for the circuit breaker processor.

The circuit breaker monitors SkillCompleted events for consecutive
failures and LLMActionEmitted events for token budget — emitting
StreamPaused when thresholds are breached.
"""

# ruff: noqa: ANN201, FBT003

import asyncio

import pytest
from sqlalchemy import Engine

from harness_poc.core.event_bus import EventBus
from harness_poc.core.event_store import EventStore
from harness_poc.core.events import LLMActionEmitted, SkillCompleted, StreamPaused
from harness_poc.core.processors.circuit_breaker import run_circuit_breaker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus(in_memory_engine: Engine) -> EventBus:
    """EventBus backed by in-memory SQLite — no Postgres needed."""
    return EventBus(EventStore(in_memory_engine))


# ---------------------------------------------------------------------------
# Consecutive failure detection
# ---------------------------------------------------------------------------


async def test_pauses_after_consecutive_failures(event_bus: EventBus) -> None:
    """StreamPaused is emitted when skill failures exceed max_retries."""
    session_id = "s1"
    paused = asyncio.Event()
    pause_event: StreamPaused | None = None

    def on_paused(event: StreamPaused) -> None:
        nonlocal pause_event
        pause_event = event
        paused.set()

    event_bus.subscribe(StreamPaused, on_paused)
    task = asyncio.create_task(
        run_circuit_breaker(event_bus, session_id, max_retries=2, max_tokens=10_000)
    )
    await asyncio.sleep(0)

    # 3 consecutive failures — exceeds max_retries=2
    for i in range(3):
        await event_bus.publish_async(
            SkillCompleted(
                session_id=session_id,
                tool_name=f"skill_{i}",
                status="failed",
                content="error",
            )
        )

    await asyncio.wait_for(paused.wait(), timeout=2)
    await asyncio.wait_for(task, timeout=2)

    assert pause_event is not None
    assert pause_event.reason == "consecutive_failures"
    assert pause_event.threshold_breached == "2"


async def test_success_resets_failure_count(event_bus: EventBus) -> None:
    """A successful skill resets the consecutive failure counter."""
    session_id = "s1"
    seen: list[StreamPaused] = []

    def on_paused(event: StreamPaused) -> None:
        seen.append(event)

    event_bus.subscribe(StreamPaused, on_paused)
    task = asyncio.create_task(
        run_circuit_breaker(event_bus, session_id, max_retries=2, max_tokens=10_000)
    )
    await asyncio.sleep(0)

    # 2 failures (at threshold)
    await event_bus.publish_async(
        SkillCompleted(session_id=session_id, tool_name="s1", status="failed", content="err")
    )
    await event_bus.publish_async(
        SkillCompleted(session_id=session_id, tool_name="s2", status="failed", content="err")
    )
    # Success resets counter
    await event_bus.publish_async(
        SkillCompleted(session_id=session_id, tool_name="s3", status="success", content="ok")
    )
    # 2 more failures — should NOT trigger because counter was reset
    await event_bus.publish_async(
        SkillCompleted(session_id=session_id, tool_name="s4", status="failed", content="err")
    )
    await event_bus.publish_async(
        SkillCompleted(session_id=session_id, tool_name="s5", status="failed", content="err")
    )
    await asyncio.sleep(0.1)

    # Pause to stop the worker
    await event_bus.publish_async(
        StreamPaused(session_id=session_id, reason="done", threshold_breached="")
    )
    await asyncio.wait_for(task, timeout=2)

    # Only the manual pause event, no circuit-breaker pause
    assert len(seen) == 1
    assert seen[0].reason == "done"


async def test_no_pause_when_under_threshold(event_bus: EventBus) -> None:
    """No StreamPaused is emitted when failures stay under max_retries."""
    session_id = "s1"
    seen: list[StreamPaused] = []

    def on_paused(event: StreamPaused) -> None:
        seen.append(event)

    event_bus.subscribe(StreamPaused, on_paused)
    task = asyncio.create_task(
        run_circuit_breaker(event_bus, session_id, max_retries=3, max_tokens=10_000)
    )
    await asyncio.sleep(0)

    # 2 failures — under max_retries=3
    await event_bus.publish_async(
        SkillCompleted(session_id=session_id, tool_name="s1", status="failed", content="err")
    )
    await event_bus.publish_async(
        SkillCompleted(session_id=session_id, tool_name="s2", status="failed", content="err")
    )
    await asyncio.sleep(0.1)

    await event_bus.publish_async(
        StreamPaused(session_id=session_id, reason="done", threshold_breached="")
    )
    await asyncio.wait_for(task, timeout=2)

    assert len(seen) == 1
    assert seen[0].reason == "done"


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------


async def test_pauses_on_token_budget_exhausted(event_bus: EventBus) -> None:
    """StreamPaused is emitted when total tokens exceed max_tokens."""
    session_id = "s1"
    paused = asyncio.Event()
    pause_event: StreamPaused | None = None

    def on_paused(event: StreamPaused) -> None:
        nonlocal pause_event
        pause_event = event
        paused.set()

    event_bus.subscribe(StreamPaused, on_paused)
    task = asyncio.create_task(
        run_circuit_breaker(event_bus, session_id, max_retries=10, max_tokens=500)
    )
    await asyncio.sleep(0)

    # 3 LLM calls totalling 600 tokens > max_tokens=500
    await event_bus.publish_async(
        LLMActionEmitted(session_id=session_id, tokens_used=200, model="test")
    )
    await event_bus.publish_async(
        LLMActionEmitted(session_id=session_id, tokens_used=200, model="test")
    )
    await event_bus.publish_async(
        LLMActionEmitted(session_id=session_id, tokens_used=200, model="test")
    )

    await asyncio.wait_for(paused.wait(), timeout=2)
    await asyncio.wait_for(task, timeout=2)

    assert pause_event is not None
    assert pause_event.reason == "budget_exhausted"
    assert pause_event.threshold_breached == "500"


async def test_no_pause_when_token_budget_not_exhausted(event_bus: EventBus) -> None:
    """No StreamPaused is emitted when total tokens stay under max_tokens."""
    session_id = "s1"
    seen: list[StreamPaused] = []

    def on_paused(event: StreamPaused) -> None:
        seen.append(event)

    event_bus.subscribe(StreamPaused, on_paused)
    task = asyncio.create_task(
        run_circuit_breaker(event_bus, session_id, max_retries=10, max_tokens=1000)
    )
    await asyncio.sleep(0)

    await event_bus.publish_async(
        LLMActionEmitted(session_id=session_id, tokens_used=300, model="test")
    )
    await event_bus.publish_async(
        LLMActionEmitted(session_id=session_id, tokens_used=300, model="test")
    )
    await asyncio.sleep(0.1)

    await event_bus.publish_async(
        StreamPaused(session_id=session_id, reason="done", threshold_breached="")
    )
    await asyncio.wait_for(task, timeout=2)

    assert len(seen) == 1
    assert seen[0].reason == "done"


# ---------------------------------------------------------------------------
# StreamPaused from external source stops the breaker
# ---------------------------------------------------------------------------


async def test_external_stream_paused_stops_breaker(event_bus: EventBus) -> None:
    """An externally emitted StreamPaused causes the breaker to exit cleanly."""
    session_id = "s1"
    task = asyncio.create_task(
        run_circuit_breaker(event_bus, session_id, max_retries=5, max_tokens=10_000)
    )
    await asyncio.sleep(0)

    await event_bus.publish_async(
        StreamPaused(session_id=session_id, reason="user_stop", threshold_breached="")
    )
    await asyncio.wait_for(task, timeout=2)
    # No exception means the breaker exited cleanly


# ---------------------------------------------------------------------------
# Events from other sessions are ignored
# ---------------------------------------------------------------------------


async def test_ignores_events_from_other_sessions(event_bus: EventBus) -> None:
    """Only events matching the monitored session_id trigger thresholds."""
    session_id = "s1"
    seen: list[StreamPaused] = []

    def on_paused(event: StreamPaused) -> None:
        seen.append(event)

    event_bus.subscribe(StreamPaused, on_paused)
    task = asyncio.create_task(
        run_circuit_breaker(event_bus, session_id, max_retries=1, max_tokens=10_000)
    )
    await asyncio.sleep(0)

    # Failures in a different session should not count
    for _ in range(3):
        await event_bus.publish_async(
            SkillCompleted(
                session_id="other_session",
                tool_name="s",
                status="failed",
                content="err",
            )
        )
    await asyncio.sleep(0.1)

    await event_bus.publish_async(
        StreamPaused(session_id=session_id, reason="done", threshold_breached="")
    )
    await asyncio.wait_for(task, timeout=2)

    assert len(seen) == 1
    assert seen[0].reason == "done"
