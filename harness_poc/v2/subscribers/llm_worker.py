"""LlmWorker — v2 ReAct subscriber for LLM inference.

Ports ``harness_poc.core.processors.llm_worker.run_llm_worker`` to the v2
event bus. The core logic is unchanged — only the event type model changes
from typed ``BaseEvent`` subclasses to string-based v2 events.

Listens for ``AGENT_INPUT`` and ``TOOL_COMPLETED`` events via the v2 bus's
async session subscription. On each input, runs the LLM and publishes
``LLM_ACTION_EMITTED``, ``TOOL_REQUESTED``, or ``LLM_TEXT_EMITTED``.
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

logger = logging.getLogger(__name__)


class LlmWorker:
    """ReAct LLM worker — runs the model in response to input/tool-completion events.

    Uses the v2 event bus's async session subscription to receive events
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

    async def run(self, bus: Any, session_id: str) -> None:
        """Run the LLM worker loop for a session.

        Listens via async session subscription and reacts to
        ``AGENT_INPUT`` and ``TOOL_COMPLETED`` events.
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

        async for envelope in bus.subscribe_session(session_id):
            event_type: str = envelope["event_type"]
            payload: dict[str, Any] = envelope["payload"]

            if event_type == "STREAM_PAUSED":
                break
            if event_type not in ("AGENT_INPUT", "TOOL_COMPLETED"):
                continue

            state = await derive_session_state(self._database, session_id)
            if state.get("stream_paused"):
                break

            prompt = self._prompt_from_envelope(event_type, payload)
            result = await asyncio.to_thread(llm_runtime.run_text, prompt)

            if result.usage is not None:
                accounting = account_for_model_run(
                    result.usage, new_messages=result.messages
                )
                bus.publish(
                    "LLM_ACTION_EMITTED",
                    {
                        "session_id": session_id,
                        "team_member": "llm_worker",
                        "model": self._config.llm.model,
                        "tokens_used": accounting.new_tokens,
                        "input_tokens": accounting.input_tokens,
                        "output_tokens": accounting.output_tokens,
                        "billable_tokens": accounting.billable_tokens,
                        "new_tokens": accounting.new_tokens,
                    },
                )

            requested_skill = self._parse_skill_request(result.content)
            if requested_skill is not None:
                bus.publish(
                    "TOOL_REQUESTED",
                    {
                        "session_id": session_id,
                        "team_member": "llm_worker",
                        "skill_name": requested_skill["skill_name"],
                        "arguments": requested_skill["arguments"],
                    },
                )
            elif result.content:
                bus.publish(
                    "LLM_TEXT_EMITTED",
                    {
                        "session_id": session_id,
                        "team_member": "llm_worker",
                        "content": result.content,
                    },
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt_from_envelope(event_type: str, payload: dict[str, Any]) -> str:
        if event_type == "AGENT_INPUT":
            return payload.get("content", "")
        # TOOL_COMPLETED
        tool_name = payload.get("tool_name", payload.get("skill_name", "unknown"))
        status = payload.get("status", "unknown")
        content = payload.get("content", payload.get("result", ""))
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
