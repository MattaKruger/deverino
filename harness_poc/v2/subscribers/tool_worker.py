"""ToolWorker — v2 ReAct subscriber for skill/tool execution.

Listens for SkillRequested events via the v1 EventBus's async session subscription,
executes the skill, and publishes SkillCompleted.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.skills import SkillRunner

from harness_poc.core.events.events import (
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)

logger = logging.getLogger(__name__)


class ToolWorker:
    """ReAct tool worker — executes skills in response to tool-request events.

    Uses the v1 EventBus's async session subscription to receive
    SkillRequested events and publishes SkillCompleted results.
    """

    def __init__(
        self,
        skill_runner: SkillRunner,
        *,
        on_call_started: Callable[[str, str], None] | None = None,
        on_call_ended: Callable[[str], None] | None = None,
    ) -> None:
        self._skill_runner = skill_runner
        self._on_call_started = on_call_started
        self._on_call_ended = on_call_ended

    async def run(self, bus: Any, session_id: str) -> None:
        """Run the tool worker loop for a session."""
        async for event in bus.subscribe_session(session_id):
            if isinstance(event, StreamPaused):
                break
            if not isinstance(event, SkillRequested):
                continue

            skill_name = event.skill_name
            arguments = event.arguments

            if self._on_call_started is not None:
                self._on_call_started("", skill_name)

            try:
                try:
                    result = await asyncio.to_thread(
                        self._skill_runner.execute_skill,
                        tool_name=skill_name,
                        arguments=arguments,
                        session_id=session_id,
                        call_id=getattr(event, "call_id", ""),
                    )
                except Exception as exc:
                    bus.publish(
                        SkillCompleted(
                            session_id=session_id,
                            skill_name=skill_name,
                            tool_name=skill_name,
                            status="failed",
                            content=str(exc),
                            result=str(exc),
                        )
                    )
                else:
                    bus.publish(
                        SkillCompleted(
                            session_id=session_id,
                            skill_name=skill_name,
                            tool_name=skill_name,
                            status=result.status,
                            content=result.content,
                            result=result.content,
                            artifacts=result.artifacts,
                        )
                    )
            finally:
                if self._on_call_ended is not None:
                    self._on_call_ended("")
