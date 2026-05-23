from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from harness_poc.core.events import (
    SkillCalled,
    SkillCancelled,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.events import EventBus
    from harness_poc.core.skills import SkillRunner


async def run_skill_worker(
    bus: EventBus,
    session_id: str,
    skill_runner: SkillRunner,
    *,
    on_call_started: Callable[[str, str], None] | None = None,
    on_call_ended: Callable[[str], None] | None = None,
) -> None:
    async for event in bus.subscribe_session(session_id):
        if isinstance(event, StreamPaused):
            break
        if not isinstance(event, (SkillCalled, SkillRequested)):
            continue

        skill_name, arguments = _skill_request_parts(event)
        call_id = event.event_id
        if on_call_started is not None:
            on_call_started(call_id, skill_name)
        try:
            try:
                result = await asyncio.to_thread(
                    skill_runner.execute_skill,
                    tool_name=skill_name,
                    arguments=arguments,
                    session_id=session_id,
                    call_id=call_id,
                )
                if result.status == "cancelled":
                    await bus.publish_async(
                        SkillCancelled(
                            session_id=session_id,
                            call_id=call_id,
                            skill_name=skill_name,
                            reason=_cancel_reason(result.content),
                        )
                    )
                completed = SkillCompleted(
                    session_id=session_id,
                    tool_name=skill_name,
                    skill_name=skill_name,
                    status=result.status,
                    content=result.content,
                    result=result.content,
                    artifacts=result.artifacts,
                )
            except Exception as exc:  # noqa: BLE001
                completed = SkillCompleted(
                    session_id=session_id,
                    tool_name=skill_name,
                    skill_name=skill_name,
                    status="failed",
                    content=str(exc),
                    result=str(exc),
                )

            await bus.publish_async(completed)
        finally:
            if on_call_ended is not None:
                on_call_ended(call_id)


def _skill_request_parts(event: SkillCalled | SkillRequested) -> tuple[str, dict[str, Any]]:
    if isinstance(event, SkillRequested):
        return event.skill_name, event.arguments
    return event.tool_name, event.arguments


def _cancel_reason(content: str) -> str:
    prefix = "cancelled:"
    if content.startswith(prefix):
        return content.removeprefix(prefix).strip()
    return content or "cancelled"
