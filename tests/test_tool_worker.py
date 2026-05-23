from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from sqlalchemy import Engine

from harness_poc.core.events import (
    EventBus,
    EventStore,
    SkillCalled,
    SkillCancelled,
    SkillCompleted,
    StreamPaused,
)
from harness_poc.core.processors.tool_worker import run_skill_worker
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillRunner


class _FakeSkillRunner:
    def execute_skill(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        session_id: str,
        call_id: str | None = None,
    ) -> SkillResult:
        del tool_name, arguments, session_id, call_id
        return SkillResult(status="success", content="ok")


class _CancelledSkillRunner:
    def execute_skill(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        session_id: str,
        call_id: str | None = None,
    ) -> SkillResult:
        del tool_name, arguments, session_id, call_id
        return SkillResult(status="cancelled", content="cancelled: reload")


async def test_run_skill_worker_reports_call_lifecycle(db_engine: Engine) -> None:
    session_id = "s1"
    bus = EventBus(EventStore(db_engine))
    completed = asyncio.Event()
    started: list[tuple[str, str]] = []
    ended: list[str] = []

    def on_completed(_event: SkillCompleted) -> None:
        completed.set()

    bus.subscribe(SkillCompleted, on_completed)
    task = asyncio.create_task(
        run_skill_worker(
            bus,
            session_id,
            cast("SkillRunner", _FakeSkillRunner()),
            on_call_started=lambda call_id, skill_name: started.append((call_id, skill_name)),
            on_call_ended=ended.append,
        )
    )
    await asyncio.sleep(0)

    request = SkillCalled(session_id=session_id, tool_name="sample", arguments={})
    await bus.publish_async(request)
    await asyncio.wait_for(completed.wait(), timeout=1)
    await bus.publish_async(
        StreamPaused(session_id=session_id, reason="done", threshold_breached="")
    )
    await asyncio.wait_for(task, timeout=1)

    assert started == [(request.event_id, "sample")]
    assert ended == [request.event_id]


async def test_run_skill_worker_emits_cancelled_event(db_engine: Engine) -> None:
    session_id = "s1"
    bus = EventBus(EventStore(db_engine))
    cancelled = asyncio.Event()
    seen: list[SkillCancelled] = []

    def on_cancelled(event: SkillCancelled) -> None:
        seen.append(event)
        cancelled.set()

    bus.subscribe(SkillCancelled, on_cancelled)
    task = asyncio.create_task(
        run_skill_worker(
            bus,
            session_id,
            cast("SkillRunner", _CancelledSkillRunner()),
        )
    )
    await asyncio.sleep(0)

    request = SkillCalled(session_id=session_id, tool_name="sample", arguments={})
    await bus.publish_async(request)
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    await bus.publish_async(
        StreamPaused(session_id=session_id, reason="done", threshold_breached="")
    )
    await asyncio.wait_for(task, timeout=1)

    assert seen[0].call_id == request.event_id
    assert seen[0].skill_name == "sample"
    assert seen[0].reason == "reload"
