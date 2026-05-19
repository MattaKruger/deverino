from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import TextPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model
    from pydantic_ai.usage import RunUsage

    from harness_poc.core.config import HarnessConfig, LLMConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.llm_client import Message, Usage
    from harness_poc.core.skill_runner import SkillRunner

from harness_poc.core.config import APISettings

HUMAN_ACTION_REQUIRED_STATUS = "needs_orchestrator_action"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentDeps:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    stream_text: Callable[[str], None] | None = None
    on_tool_event: Callable[[str], None] | None = None


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
        on_tool_event: Callable[[str], None] | None = None,
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
                on_tool_event=on_tool_event,
            ),
        )

    async def _stream_text_async(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None,
        on_text: Callable[[str], None] | None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        # Use agent.iter() instead of run_stream() because run_stream()
        # stops at the first text output matching the output type.
        # With tools, the model may produce text BEFORE tool calls — with
        # run_stream() that pre-tool text becomes the "final output" and
        # post-tool text is lost.  agent.iter() runs the full agent graph
        # to completion, giving us all model responses including those
        # after tool calls.
        max_tool_rounds = 5

        deps = replace(self.deps, stream_text=on_text, on_tool_event=on_tool_event)
        all_output_parts: list[str] = []
        seen_text: str = ""
        usage: Usage | None = None
        tool_rounds = 0
        capped = False

        async with self.agent.iter(
            prompt,
            deps=deps,
            message_history=message_history,
            conversation_id="new",
        ) as agent_run:
            async for node in agent_run:
                mr = getattr(node, "model_response", None)
                if mr is None:
                    continue
                # Count tool-call rounds (each CallToolsNode is one round)
                tool_rounds += 1
                if tool_rounds > max_tool_rounds:
                    capped = True
                    logger.warning(
                        "Tool call limit (%d) reached, stopping agent loop",
                        max_tool_rounds,
                        extra={"session_id": self.deps.session_id},
                    )
                    break
                # Collect text parts from this model response
                new_text = "".join(
                    part.content
                    for part in mr.parts
                    if isinstance(part, TextPart)
                )
                # Stream only the NEW portion (diff against seen)
                if new_text and on_text is not None:
                    if new_text.startswith(seen_text):
                        delta = new_text[len(seen_text) :]
                        if delta:
                            on_text(delta)
                    else:
                        # Text changed completely (rare — model revision)
                        on_text(new_text)
                seen_text = new_text
                all_output_parts.append(new_text)

            if capped and on_text is not None:
                on_text(
                    "\n\n[Tool call limit reached — stopping. "
                    "Refine your query for better results.]"
                )

            result_output = agent_run.result.output if agent_run.result else None
            output = str(result_output) if result_output is not None else "".join(all_output_parts)

            if not capped and agent_run.result is not None:
                usage = _usage_to_dict(agent_run.result.usage)
                # Only trust new_messages() when the graph completed
                # cleanly.  Capped runs produce incomplete tool messages
                # that corrupt the next turn's context.
                all_new_messages = agent_run.result.new_messages()
            else:
                # Capped or no result — return empty messages so the
                # REPL uses _append_pydantic_chat_exchange (clean
                # user/assistant pair, no tool pollution).
                all_new_messages = []

        return AgentRunResult(
            content=str(output),
            usage=usage,
            messages=all_new_messages,
        )


def build_model(  # noqa: PLR0911
    config: LLMConfig | None = None,
    *,
    fallback_model: Model | None = None,
) -> Model:
    if config is None:
        return fallback_model or TestModel(call_tools=[])

    api_settings = APISettings.load()

    if config.provider == "anthropic":
        api_key = api_settings.anthropic_api_key
        if not api_key:
            logger.info(
                "No Anthropic API key configured; using fallback PydanticAI model"
            )
            return fallback_model or TestModel(call_tools=[])
        logger.debug(
            "Building Anthropic-backed PydanticAI model",
            extra={"model": config.model},
        )
        return AnthropicModel(
            cast("Any", config.model),
            provider=AnthropicProvider(api_key=api_key),
        )

    if config.provider == "deepseek":
        api_key = api_settings.deepseek_api_key
        if not api_key:
            logger.info(
                "No DeepSeek API key configured; using fallback PydanticAI model"
            )
            return fallback_model or TestModel(call_tools=[])
        logger.debug(
            "Building DeepSeek-backed PydanticAI model",
            extra={"model": config.model},
        )
        return OpenAIChatModel(
            cast("Any", config.model),
            provider=DeepSeekProvider(api_key=api_key),
        )

    # "openai" or any openai-compatible provider
    if config.provider == "openai":
        api_key = api_settings.openai_api_key
        if not api_key:
            logger.info(
                "No OpenAI API key configured; using fallback PydanticAI model"
            )
            return fallback_model or TestModel(call_tools=[])
        provider_kwargs: dict[str, Any] = {"api_key": api_key}
        if config.base_url:
            provider_kwargs["base_url"] = config.base_url
        logger.debug(
            "Building OpenAI-compatible PydanticAI model",
            extra={
                "model": config.model,
                "base_url": config.base_url or "default",
            },
        )
        return OpenAIChatModel(
            cast("Any", config.model),
            provider=OpenAIProvider(**provider_kwargs),
        )

    msg = f"Unknown LLM provider: {config.provider!r}"
    raise ValueError(msg)


def build_primary_agent(
    *,
    system_prompt: str,
    skill_runner: SkillRunner,
    llm: LLMConfig | None = None,
    model: Model | None = None,
    enable_tools: bool = True,
) -> Agent[AgentDeps, str]:
    return Agent(
        model or build_model(llm),
        deps_type=AgentDeps,
        tools=build_skill_tools(skill_runner) if enable_tools else [],
        system_prompt=_with_tool_policy(system_prompt),
        end_strategy="early",
    )


def build_runtime(  # noqa: PLR0913
    *,
    session_id: str,
    database: BlackboardDatabase,
    config: HarnessConfig,
    skill_runner: SkillRunner,
    system_prompt: str,
    llm: LLMConfig | None = None,
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
            llm=llm,
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

    if result.status == HUMAN_ACTION_REQUIRED_STATUS:
        return json.dumps(
            {
                "status": result.status,
                "content": result.content,
                "orchestrator_action_required": True,
                "orchestrator_instruction": (
                    "Stop and surface content to the user unchanged. "
                    "Do not summarize."
                ),
            },
            sort_keys=True,
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
        # Return raw content — the agent reads it directly.
        # No JSON wrapper so the model sees search results / tool
        # output without extra parsing overhead.
        return result.content

    # Non-success (failed, error, etc.)
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
    return f"[{result.status}] {result.content}"


def _with_tool_policy(system_prompt: str) -> str:
    return (
        f"{system_prompt}\n\n"
        "## Tool Result Policy\n"
        "- Successful tool calls return the result content directly as plain text.\n"
        "- Failed tool calls are prefixed with `[failed]`.\n"
        "- If a tool returns JSON with `orchestrator_action_required: true`, "
        "stop and surface the content to the user unchanged.\n"
        "  Do not summarize or rephrase human-in-loop prompts.\n"
        "- **Do not retry failed tools.** If a tool returns status `failed`, "
        "report the error to the user. Do not call the same tool again with "
        "different arguments — the tool is indicating it cannot complete the "
        "request.\n"
        "- **semble_search / web_search**: if the first 2 search calls do not "
        "return the specific information the user asked for (including empty "
        "results or failures), stop searching. Tell the user what you found "
        "(or that the information is unavailable). Do not refine the query "
        "further.\n"
        "- Do not make the same tool call with the same arguments more than once."
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
    handler = ctx.deps.on_tool_event
    if handler is not None:
        handler(message)


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


def chat_text(
    messages: list[Message],
    *,
    model: Model,
) -> str:
    """Run a simple chat without tools and return text content only."""
    system_parts: list[str] = []
    user_parts: list[str] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        elif msg["role"] == "user":
            user_parts.append(msg["content"])

    system_prompt = "\n\n".join(system_parts)
    prompt = "\n\n".join(
        msg["content"] for msg in messages if msg["role"] != "system"
    )

    agent = Agent(model, system_prompt=system_prompt)
    result = agent.run_sync(prompt)
    return str(result.output)


def is_live_model(model: Model) -> bool:
    """Return True if the model is not a TestModel fallback."""
    return not isinstance(model, TestModel)
