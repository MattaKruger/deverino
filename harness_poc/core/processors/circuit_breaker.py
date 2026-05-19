from __future__ import annotations

from typing import TYPE_CHECKING

from harness_poc.core.events import (
    LLMActionEmitted,
    SkillCompleted,
    StreamPaused,
)

if TYPE_CHECKING:
    from harness_poc.core.event_bus import EventBus


async def run_circuit_breaker(
    bus: EventBus,
    session_id: str,
    max_retries: int,
    max_tokens: int,
) -> None:
    consecutive_skill_failures = 0
    total_tokens = 0

    async for event in bus.subscribe_session(session_id):
        if isinstance(event, StreamPaused):
            break

        pause_event: StreamPaused | None = None
        if isinstance(event, SkillCompleted):
            if event.status == "failed":
                consecutive_skill_failures += 1
            elif event.status == "success":
                consecutive_skill_failures = 0

            if consecutive_skill_failures > max_retries:
                pause_event = StreamPaused(
                    session_id=session_id,
                    reason="consecutive_failures",
                    threshold_breached=str(max_retries),
                )

        if isinstance(event, LLMActionEmitted):
            total_tokens += event.tokens_used
            if total_tokens > max_tokens:
                pause_event = StreamPaused(
                    session_id=session_id,
                    reason="budget_exhausted",
                    threshold_breached=str(max_tokens),
                )

        if pause_event is not None:
            await bus.publish_async(pause_event)
            break
