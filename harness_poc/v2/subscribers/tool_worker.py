"""ToolWorker — v2 ReAct subscriber for skill/tool execution.

Ports ``harness_poc.core.processors.tool_worker.run_skill_worker`` to the v2
event bus. Listens for ``TOOL_REQUESTED`` events via async session subscription,
executes the skill, and publishes ``TOOL_COMPLETED``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.skills import SkillRunner

logger = logging.getLogger(__name__)


class ToolWorker:
    """ReAct tool worker — executes skills in response to tool-request events.

    Uses the v2 event bus's async session subscription to receive
    ``TOOL_REQUESTED`` events and publishes ``TOOL_COMPLETED`` results.
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
        async for envelope in bus.subscribe_session(session_id):
            event_type: str = envelope["event_type"]
            payload: dict[str, Any] = envelope["payload"]

            if event_type == "STREAM_PAUSED":
                break
            if event_type != "TOOL_REQUESTED":
                continue

            skill_name = payload.get("skill_name", "")
            arguments = payload.get("arguments", {})

            if self._on_call_started is not None:
                self._on_call_started("", skill_name)

            try:
                try:
                    result = await asyncio.to_thread(
                        self._skill_runner.execute_skill,
                        tool_name=skill_name,
                        arguments=arguments,
                        session_id=session_id,
                        call_id=payload.get("call_id", ""),
                    )
                except Exception as exc:
                    bus.publish(
                        "TOOL_COMPLETED",
                        {
                            "session_id": session_id,
                            "team_member": "tool_worker",
                            "tool_name": skill_name,
                            "skill_name": skill_name,
                            "status": "failed",
                            "content": str(exc),
                            "result": str(exc),
                        },
                    )
                else:
                    bus.publish(
                        "TOOL_COMPLETED",
                        {
                            "session_id": session_id,
                            "team_member": "tool_worker",
                            "tool_name": skill_name,
                            "skill_name": skill_name,
                            "status": result.status,
                            "content": result.content,
                            "result": result.content,
                            "artifacts": result.artifacts,
                        },
                    )
            finally:
                if self._on_call_ended is not None:
                    self._on_call_ended("")
