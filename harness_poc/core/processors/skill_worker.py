from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from harness_poc.core.events import (
    SkillCalled,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)

if TYPE_CHECKING:
    from harness_poc.core.event_bus import EventBus
    from harness_poc.core.skill_runner import SkillRunner


async def run_skill_worker(
    bus: EventBus,
    session_id: str,
    skill_runner: SkillRunner,
) -> None:
    async for event in bus.subscribe_session(session_id):
        if isinstance(event, StreamPaused):
            break
        if not isinstance(event, (SkillCalled, SkillRequested)):
            continue

        skill_name, arguments = _skill_request_parts(event)
        try:
            result = await asyncio.to_thread(
                skill_runner.execute_skill,
                tool_name=skill_name,
                arguments=arguments,
                session_id=session_id,
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


def _skill_request_parts(event: SkillCalled | SkillRequested) -> tuple[str, dict[str, Any]]:
    if isinstance(event, SkillRequested):
        return event.skill_name, event.arguments
    return event.tool_name, event.arguments
