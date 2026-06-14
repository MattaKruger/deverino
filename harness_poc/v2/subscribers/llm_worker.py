"""LlmWorker — v2 ReAct subscriber for LLM inference.

Listens for AgentInputAdded and SkillCompleted events via the v1 EventBus's
async session subscription. On each input, runs the LLM and publishes
LLMActionEmitted, SkillRequested, or LLMTextEmitted.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.runtime import PydanticAgentRuntime
    from harness_poc.core.skills import SkillRunner
    from harness_poc.core.storage import BlackboardDatabase

from harness_poc.core.events.events import (
    AgentInputAdded,
    LLMActionEmitted,
    LLMTextEmitted,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
)

logger = logging.getLogger(__name__)


class LlmWorker:
    """ReAct LLM worker — runs the model in response to input/tool-completion events.

    Uses the v1 EventBus's async session subscription to receive events
    and publishes LLM results back through the same bus.
    """

    def __init__(
        self,
        database: BlackboardDatabase,
        config: HarnessConfig,
        skill_runner: SkillRunner,
        *,
        system_prompt: str | None = None,
        runtime: PydanticAgentRuntime | None = None,
    ) -> None:
        self._database = database
        self._config = config
        self._skill_runner = skill_runner
        self._system_prompt = system_prompt
        self._runtime = runtime

    async def run(self, bus: Any, session_id: str) -> None:  # noqa: ANN401
        """Run the LLM worker loop for a session.

        Listens via async session subscription and reacts to
        AgentInputAdded and SkillCompleted events.
        """
        from harness_poc.core.runtime import (
            account_for_model_run,
            build_runtime,
            derive_session_state,
        )

        llm_runtime = self._runtime or build_runtime(
            session_id=session_id,
            database=self._database,
            config=self._config,
            skill_runner=self._skill_runner,
            system_prompt=self._system_prompt
            or self._config.paths.soul.read_text(encoding="utf-8"),
            llm=self._config.llm,
            enable_tools=False,
        )

        async for event in bus.subscribe_session(session_id):
            if isinstance(event, StreamPaused):
                break
            if not isinstance(event, (AgentInputAdded, SkillCompleted)):
                continue

            state = await derive_session_state(self._database, session_id)
            if state.get("stream_paused"):
                break

            prompt = self._prompt_from_event(event)
            result = await asyncio.to_thread(llm_runtime.run_text, prompt)

            if result.usage is not None:
                accounting = account_for_model_run(result.usage, new_messages=result.messages)
                bus.publish(
                    LLMActionEmitted(
                        session_id=session_id,
                        model=self._config.llm.model,
                        tokens_used=accounting.new_tokens,
                        input_tokens=accounting.input_tokens,
                        output_tokens=accounting.output_tokens,
                        billable_tokens=accounting.billable_tokens,
                        new_tokens=accounting.new_tokens,
                    )
                )

            requested_skill = self._parse_skill_request(result.content)
            if requested_skill is not None:
                bus.publish(
                    SkillRequested(
                        session_id=session_id,
                        skill_name=requested_skill["skill_name"],
                        arguments=requested_skill["arguments"],
                    )
                )
            elif result.content:
                bus.publish(
                    LLMTextEmitted(
                        session_id=session_id,
                        content=result.content,
                    )
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt_from_event(event: AgentInputAdded | SkillCompleted) -> str:
        if isinstance(event, AgentInputAdded):
            return event.user_content
        # SkillCompleted
        tool_name = event.skill_name or event.tool_name or "unknown"
        status = event.status
        content = event.content or event.result
        return f"Skill {tool_name} completed with {status}.\n{content}"

    @staticmethod
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
