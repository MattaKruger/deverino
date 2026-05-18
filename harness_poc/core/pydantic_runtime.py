from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

from harness_poc.core.llm_client import DeepSeekSettings, Usage

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model
    from pydantic_ai.usage import RunUsage

    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.skill_runner import SkillRunner


HUMAN_ACTION_REQUIRED_STATUS = "needs_orchestrator_action"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentDeps:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    stream_text: Callable[[str], None] | None = None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    content: str
    usage: Usage | None = None
    messages: list[ModelMessage] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PydanticAgentRuntime:
    agent: Agent[AgentDeps, str]
    deps: AgentDeps

    def run_text(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
    ) -> AgentRunResult:
        logger.debug(
            "Running PydanticAI text request",
            extra={
                "session_id": self.deps.session_id,
                "history_length": len(message_history or []),
            },
        )
        result = self.agent.run_sync(
            prompt,
            deps=self.deps,
            message_history=message_history,
        )

        return AgentRunResult(
            content=str(result.output),
            usage=_usage_to_dict(result.usage),
            messages=result.new_messages(),
        )

    def stream_text(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        logger.debug(
            "Streaming PydanticAI text request",
            extra={
                "session_id": self.deps.session_id,
                "history_length": len(message_history or []),
            },
        )
        return asyncio.run(
            self._stream_text_async(
                prompt,
                message_history=message_history,
                on_text=on_text,
            ),
        )

    async def _stream_text_async(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None,
        on_text: Callable[[str], None] | None,
    ) -> AgentRunResult:
        deps = replace(self.deps, stream_text=on_text)
        async with self.agent.run_stream(
            prompt,
            deps=deps,
            message_history=message_history,
        ) as result:
            async for chunk in result.stream_text(delta=True):
                if on_text is not None:
                    on_text(chunk)
            output = await result.get_output()

            return AgentRunResult(
                content=str(output),
                usage=_usage_to_dict(result.usage),
                messages=result.new_messages(),
            )


def build_model(
    settings: DeepSeekSettings | None = None,
    *,
    fallback_model: Model | None = None,
) -> Model:
    resolved_settings = settings or DeepSeekSettings.load()
    if resolved_settings.api_key is None:
        logger.info(
            "No provider API key configured; using fallback PydanticAI model"
        )
        return fallback_model or TestModel(call_tools=[])

    if resolved_settings.base_url == "https://api.deepseek.com":
        logger.debug(
            "Building DeepSeek-backed PydanticAI model",
            extra={"model": resolved_settings.model},
        )
        return OpenAIChatModel(
            cast("Any", resolved_settings.model),
            provider=DeepSeekProvider(api_key=resolved_settings.api_key),
        )

    logger.debug(
        "Building OpenAI-compatible PydanticAI model",
        extra={
            "model": resolved_settings.model,
            "base_url": resolved_settings.base_url,
        },
    )
    return OpenAIChatModel(
        cast("Any", resolved_settings.model),
        provider=OpenAIProvider(
            base_url=resolved_settings.base_url,
            api_key=resolved_settings.api_key,
        ),
    )


def build_primary_agent(
    *,
    system_prompt: str,
    skill_runner: SkillRunner,
    model: Model | None = None,
    enable_tools: bool = True,
) -> Agent[AgentDeps, str]:
    return Agent(
        model or build_model(),
        deps_type=AgentDeps,
        tools=build_skill_tools(skill_runner) if enable_tools else [],
        system_prompt=_with_tool_policy(system_prompt),
        end_strategy="exhaustive",
    )


def build_runtime(  # noqa: PLR0913
    *,
    session_id: str,
    database: BlackboardDatabase,
    config: HarnessConfig,
    skill_runner: SkillRunner,
    system_prompt: str,
    model: Model | None = None,
    enable_tools: bool = True,
) -> PydanticAgentRuntime:
    deps = AgentDeps(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
    )

    return PydanticAgentRuntime(
        agent=build_primary_agent(
            system_prompt=system_prompt,
            skill_runner=skill_runner,
            model=model,
            enable_tools=enable_tools,
        ),
        deps=deps,
    )


def build_skill_tools(skill_runner: SkillRunner) -> list[Tool[AgentDeps]]:
    tools: list[Tool[AgentDeps]] = []
    for discovered_skill in skill_runner.discover_skills():
        function = discovered_skill.get("function", {})

        if not isinstance(function, dict):
            continue

        name = function.get("name")
        description = function.get("description")
        parameters = function.get("parameters")
        auto_invokable = function.get("auto_invokable", False)

        if not isinstance(name, str) or not isinstance(description, str):
            continue
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        if not auto_invokable:
            logger.debug(
                "Skipping non-auto-invokable skill",
                extra={"skill_name": name},
            )
            continue

        tools.append(
            Tool.from_schema(
                function=_make_skill_tool(name),
                name=name,
                description=description,
                json_schema=parameters,
                takes_ctx=True,
            ),
        )

    return tools


def _make_skill_tool(
    skill_name: str,
) -> Callable[..., str]:
    def execute_skill_tool(
        ctx: RunContext[AgentDeps],
        **arguments: object,
    ) -> str:
        return execute_skill_as_tool(
            ctx,
            skill_name,
            cast("dict[str, Any]", arguments),
        )

    execute_skill_tool.__name__ = f"execute_{skill_name}_tool"

    return execute_skill_tool


def execute_skill_as_tool(
    ctx: RunContext[AgentDeps],
    skill_name: str,
    arguments: dict[str, Any],
) -> str:
    logger.debug(
        "Executing skill through PydanticAI tool adapter",
        extra={
            "session_id": ctx.deps.session_id,
            "skill_name": skill_name,
            "arguments": arguments,
        },
    )
    # Stream progress so the user sees tool activity during execution.
    _emit_tool_progress(
        ctx, f"  {skill_name}: {_summarise_args(arguments)} ..."
    )
    try:
        result = ctx.deps.skill_runner.execute_skill(
            tool_name=skill_name,
            arguments=arguments,
            session_id=ctx.deps.session_id,
            on_text=ctx.deps.stream_text,
        )
    except Exception:
        _emit_tool_progress(ctx, f"  {skill_name}: FAILED")
        logger.exception(
            "PydanticAI tool adapter skill execution raised",
            extra={
                "session_id": ctx.deps.session_id,
                "skill_name": skill_name,
            },
        )
        raise

    if result.status == "success":
        _emit_tool_progress(ctx, f"  {skill_name}: done")
    else:
        _emit_tool_progress(ctx, f"  {skill_name}: {result.status}")

    payload: dict[str, Any] = {
        "status": result.status,
        "content": result.content,
        "artifacts": result.artifacts,
        "requested_actions": [
            {
                "requested_skill": request.requested_skill,
                "arguments": request.arguments,
                "reason": request.reason,
            }
            for request in result.requested_actions
        ],
    }
    if result.status == HUMAN_ACTION_REQUIRED_STATUS:
        payload["orchestrator_action_required"] = True
        payload["orchestrator_instruction"] = (
            "Stop and surface content to the user unchanged. Do not summarize."
        )

    if result.status == "success":
        logger.debug(
            "PydanticAI tool adapter skill execution completed",
            extra={
                "session_id": ctx.deps.session_id,
                "skill_name": skill_name,
                "status": result.status,
            },
        )
    else:
        logger.error(
            "PydanticAI tool adapter skill returned non-success status",
            extra={
                "session_id": ctx.deps.session_id,
                "skill_name": skill_name,
                "status": result.status,
                "content": result.content,
                "artifacts": result.artifacts,
            },
        )

    return json.dumps(payload, sort_keys=True)


def _with_tool_policy(system_prompt: str) -> str:
    return (
        f"{system_prompt}\n\n"
        "## Tool Result Policy\n"
        "- Tools return JSON with status, content, artifacts, and requested_actions.\n"
        "- If a tool returns status `needs_orchestrator_action`, stop and surface "
        "the tool content to the user unchanged.\n"
        "- Do not summarize human-in-loop prompts."
    )


def _usage_to_dict(usage: RunUsage) -> Usage:
    return {
        "prompt_tokens": int(usage.input_tokens or 0),
        "completion_tokens": int(usage.output_tokens or 0),
        "total_tokens": int(
            (usage.input_tokens or 0) + (usage.output_tokens or 0)
        ),
    }


def _emit_tool_progress(ctx: RunContext[AgentDeps], message: str) -> None:
    """Stream a progress line through the agent's text callback if available."""
    stream = ctx.deps.stream_text
    if stream is not None:
        stream(f"\n  {message}\n")


ARG_SUMMARY_MAX_LEN = 60


def _summarise_args(arguments: dict[str, Any]) -> str:
    """Return a compact summary of skill arguments for progress display."""
    parts: list[str] = []
    for key, value in arguments.items():
        if key in {"query", "objective", "description"}:
            val = str(value)
            truncated = val[:ARG_SUMMARY_MAX_LEN]
            suffix = "..." if len(val) > ARG_SUMMARY_MAX_LEN else ""
            parts.append(f"{truncated}{suffix}")
        elif key in {"action", "mode", "status"}:
            parts.append(str(value))
    if not parts:
        parts.append("...")
    return ", ".join(parts)
