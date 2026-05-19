from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from harness_poc.core.events import (
    AgentInputAdded,
    LLMActionEmitted,
    LLMTextEmitted,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)
from harness_poc.core.pydantic_runtime import build_runtime
from harness_poc.core.reducers import derive_session_state

if TYPE_CHECKING:
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.event_bus import EventBus
    from harness_poc.core.pydantic_runtime import PydanticAgentRuntime
    from harness_poc.core.skill_runner import SkillRunner


async def run_llm_worker(  # noqa: PLR0913
    bus: EventBus,
    session_id: str,
    database: BlackboardDatabase,
    config: HarnessConfig,
    skill_runner: SkillRunner,
    system_prompt: str | None = None,
    runtime: PydanticAgentRuntime | None = None,
) -> None:
    llm_runtime = runtime or build_runtime(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        system_prompt=system_prompt or config.paths.soul.read_text(encoding="utf-8"),
        llm=config.llm,
        enable_tools=False,
    )

    async for event in bus.subscribe_session(session_id):
        if isinstance(event, StreamPaused):
            break
        if not isinstance(event, (AgentInputAdded, SkillCompleted)):
            continue

        state = await derive_session_state(database, session_id)
        if state.get("stream_paused"):
            break

        prompt = _prompt_from_event(event)
        result = await asyncio.to_thread(llm_runtime.run_text, prompt)
        if result.usage is not None:
            await bus.publish_async(
                LLMActionEmitted(
                    session_id=session_id,
                    model=config.llm.model,
                    tokens_used=int(result.usage.get("total_tokens", 0)),
                ),
            )

        requested_skill = _parse_skill_request(result.content)
        if requested_skill is not None:
            await bus.publish_async(SkillRequested(session_id=session_id, **requested_skill))
        elif result.content:
            await bus.publish_async(
                LLMTextEmitted(session_id=session_id, content=result.content),
            )


def _prompt_from_event(event: AgentInputAdded | SkillCompleted) -> str:
    if isinstance(event, AgentInputAdded):
        return event.user_content
    return "\n".join(
        [
            f"Skill {event.tool_name or event.skill_name} completed with {event.status}.",
            event.content or event.result,
        ],
    )


def _parse_skill_request(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    skill_name = parsed.get("skill_name") or parsed.get("tool_name")
    arguments = parsed.get("arguments", {})
    if not isinstance(skill_name, str) or not isinstance(arguments, dict):
        return None
    return {"skill_name": skill_name, "arguments": arguments}
