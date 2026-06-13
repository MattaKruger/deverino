from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import (
    Agent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    Tool,
    ToolCallPartDelta,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import (
        RunContext,
    )
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model
    from pydantic_ai.usage import RunUsage

    from harness_poc.core.config import HarnessConfig, LLMConfig
    from harness_poc.core.runtime.llm_client import Message, Usage
    from harness_poc.core.skills import SkillRunner
    from harness_poc.core.storage import BlackboardDatabase
    from harness_poc.core.tools import ToolRunner

from harness_poc.core.config import APISettings

HUMAN_ACTION_REQUIRED_STATUS = "needs_orchestrator_action"
SEMBLE_SEARCH_TOOL_NAME = "semble_search"
MAX_SEMBLE_SEARCH_CALLS_PER_RUN = 3
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentDeps:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    tool_runner: ToolRunner | None = None
    stream_text: Callable[[str], None] | None = None
    on_tool_event: Callable[[str], None] | None = None
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    max_consecutive_tool_rounds: int | None = 50


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    content: str
    usage: Usage | None = None
    messages: list[ModelMessage] = field(default_factory=list)
    stop_reason: str = "completed"  # "completed" | "tool_limit"


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
        deps = replace(self.deps, tool_call_counts={})
        result = self.agent.run_sync(
            prompt,
            deps=deps,
            message_history=message_history,
        )

        return AgentRunResult(
            content=str(result.output),
            usage=_usage_to_dict(result.usage),
            messages=result.new_messages(),
        )

    def inject_synthetic_tool_return(
        self,
        messages: list[ModelMessage],
        call_id: str,
        tool_name: str,
        content: str,
    ) -> list[ModelMessage]:
        from pydantic_ai.messages import ModelRequest, ToolReturnPart  # noqa: PLC0415

        return [
            *messages,
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name=tool_name,
                        content=content,
                        tool_call_id=call_id,
                    )
                ]
            ),
        ]

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

    async def _stream_text_async(  # noqa: PLR0912
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None,
        on_text: Callable[[str], None] | None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        max_consecutive_tool_rounds = self.deps.max_consecutive_tool_rounds

        deps = replace(
            self.deps,
            stream_text=on_text,
            on_tool_event=on_tool_event,
            tool_call_counts={},
        )
        all_output_parts: list[str] = []
        usage: Usage | None = None
        consecutive_tool_rounds = 0
        capped = False

        async with self.agent.iter(
            prompt,
            deps=deps,
            message_history=message_history,
            conversation_id="new",
        ) as agent_run:
            async for node in agent_run:
                if Agent.is_model_request_node(node):
                    turn_chunks: list[str] = []
                    had_tool_call = False

                    # Emit separator between model turns (after tool calls),
                    # but only when the previous turn actually produced visible text.
                    if all_output_parts and on_text is not None:
                        on_text("\n\n")

                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            if isinstance(event, PartStartEvent):
                                if isinstance(event.part, TextPart) and event.part.content:
                                    if on_text is not None:
                                        on_text(event.part.content)
                                    turn_chunks.append(event.part.content)
                            elif isinstance(event, PartDeltaEvent):
                                if isinstance(event.delta, TextPartDelta):
                                    delta = event.delta.content_delta
                                    if delta:
                                        if on_text is not None:
                                            on_text(delta)
                                        turn_chunks.append(delta)
                                elif isinstance(event.delta, ToolCallPartDelta):
                                    had_tool_call = True

                    if not had_tool_call:
                        consecutive_tool_rounds = 0
                    if turn_chunks:
                        all_output_parts.append("".join(turn_chunks))

                elif Agent.is_call_tools_node(node):
                    consecutive_tool_rounds += 1
                    if (
                        max_consecutive_tool_rounds is not None
                        and consecutive_tool_rounds > max_consecutive_tool_rounds
                    ):
                        capped = True
                        logger.warning(
                            "Consecutive tool call limit (%d) reached, stopping agent loop",
                            max_consecutive_tool_rounds,
                            extra={"session_id": self.deps.session_id},
                        )
                        break

            if capped and on_text is not None:
                on_text(
                    f"\n\n[Consecutive tool call limit ({max_consecutive_tool_rounds}) "
                    "reached — agent stopped mid-loop. "
                    "Reply to continue, or set max_consecutive_tool_rounds higher.]"
                )

            result_output = agent_run.result.output if agent_run.result else None
            output = str(result_output) if result_output is not None else "".join(all_output_parts)

            if not capped and agent_run.result is not None:
                usage = _usage_to_dict(agent_run.result.usage)
                all_new_messages = agent_run.result.new_messages()
            else:
                all_new_messages = []

        return AgentRunResult(
            content=str(output),
            usage=usage,
            messages=all_new_messages,
            stop_reason="tool_limit" if capped else "completed",
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
            logger.info("No Anthropic API key configured; using fallback PydanticAI model")
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
            logger.info("No DeepSeek API key configured; using fallback PydanticAI model")
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
            logger.info("No OpenAI API key configured; using fallback PydanticAI model")
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


def build_primary_agent(  # noqa: PLR0913
    *,
    system_prompt: str,
    skill_runner: SkillRunner,
    tool_runner: ToolRunner | None = None,
    llm: LLMConfig | None = None,
    model: Model | None = None,
    enable_tools: bool = True,
    blocked_skills: frozenset[str] | None = None,
) -> Agent[AgentDeps, str]:
    tools: list[Tool[AgentDeps]] = []
    if enable_tools:
        builtin = build_builtin_tools(tool_runner) if tool_runner else []
        tools.extend(builtin)
        # Collect built-in tool names for dedup against skill runner
        builtin_names: set[str] = set()
        if tool_runner is not None:
            for t in tool_runner.discover_tools():
                fn = t.get("function", {})
                if isinstance(fn, dict):
                    name = fn.get("name")
                    if isinstance(name, str):
                        builtin_names.add(name)
        tools.extend(
            build_skill_tools(
                skill_runner,
                blocked_skills=blocked_skills,
                skip_names=builtin_names,
            )
        )
    return Agent(
        model or build_model(llm),
        deps_type=AgentDeps,
        tools=tools,
        system_prompt=_with_tool_policy(system_prompt),
        end_strategy="early",
    )


def build_runtime(  # noqa: PLR0913
    *,
    session_id: str,
    database: BlackboardDatabase,
    config: HarnessConfig,
    skill_runner: SkillRunner,
    tool_runner: ToolRunner | None = None,
    system_prompt: str,
    llm: LLMConfig | None = None,
    model: Model | None = None,
    enable_tools: bool = True,
    blocked_skills: frozenset[str] | None = None,
    skill_catalog: str = "",
) -> PydanticAgentRuntime:
    deps = AgentDeps(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        tool_runner=tool_runner,
    )

    # Augment system prompt with skill catalog if available
    full_prompt = system_prompt
    if skill_catalog:
        full_prompt = f"{system_prompt}\n\n{skill_catalog}"

    return PydanticAgentRuntime(
        agent=build_primary_agent(
            system_prompt=full_prompt,
            skill_runner=skill_runner,
            tool_runner=tool_runner,
            llm=llm,
            model=model,
            enable_tools=enable_tools,
            blocked_skills=blocked_skills,
        ),
        deps=deps,
    )


def build_skill_tools(
    skill_runner: SkillRunner,
    *,
    blocked_skills: frozenset[str] | None = None,
    skip_names: set[str] | None = None,
) -> list[Tool[AgentDeps]]:
    tools: list[Tool[AgentDeps]] = []
    blocked = blocked_skills or frozenset()
    skip = skip_names or set()
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
        if name in blocked:
            logger.debug(
                "Skipping blocked skill",
                extra={"skill_name": name},
            )
            continue
        if name in skip:
            logger.debug(
                "Skipping skill already handled by built-in tools",
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


def build_builtin_tools(
    tool_runner: ToolRunner | None,
) -> list[Tool[AgentDeps]]:
    """Build PydanticAI Tool objects from the built-in tool registry."""
    if tool_runner is None:
        return []
    tools: list[Tool[AgentDeps]] = []
    for discovered_tool in tool_runner.discover_tools():
        function = discovered_tool.get("function", {})
        if not isinstance(function, dict):
            continue

        name = function.get("name")
        description = function.get("description")
        parameters = function.get("parameters")

        if not isinstance(name, str) or not isinstance(description, str):
            continue
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}

        tools.append(
            Tool.from_schema(
                function=_make_builtin_tool(name),
                name=name,
                description=description,
                json_schema=parameters,
                takes_ctx=True,
            ),
        )

    return tools


def _make_builtin_tool(
    tool_name: str,
) -> Callable[..., str]:
    def execute_builtin_tool(
        ctx: RunContext[AgentDeps],
        **arguments: object,
    ) -> str:
        return _execute_builtin_tool(ctx, tool_name, cast("dict[str, Any]", arguments))

    execute_builtin_tool.__name__ = f"execute_{tool_name}_builtin"
    return execute_builtin_tool


def _execute_builtin_tool(
    ctx: RunContext[AgentDeps],
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Route a built-in tool call through the ToolRunner."""
    if ctx.deps.tool_runner is None:
        return json.dumps({"error": f"Tool runner not available for {tool_name}"})

    _emit_tool_progress(ctx, f"  {tool_name}: {_summarise_args(arguments)} ...")
    try:
        result = ctx.deps.tool_runner.execute_tool(
            tool_name,
            arguments,
            session_id=ctx.deps.session_id,
            call_id=_tool_call_id(ctx),
        )
    except Exception:
        _emit_tool_progress(ctx, f"  {tool_name}: FAILED")
        logger.exception("Built-in tool execution raised: %s", tool_name)
        return json.dumps({"error": f"Tool {tool_name} raised an unexpected error."})

    _emit_tool_progress(ctx, f"  {tool_name}: done")
    return result


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
    if skill_name == SEMBLE_SEARCH_TOOL_NAME and _tool_budget_exhausted(
        ctx,
        skill_name,
        MAX_SEMBLE_SEARCH_CALLS_PER_RUN,
    ):
        _emit_tool_progress(
            ctx,
            (
                "  semble_search: blocked - per-run budget reached "
                f"({MAX_SEMBLE_SEARCH_CALLS_PER_RUN})"
            ),
        )
        return (
            "[blocked] semble_search call budget reached for this agent run "
            f"({MAX_SEMBLE_SEARCH_CALLS_PER_RUN} calls). Use the search results already "
            "available in this run to answer the user instead of searching again."
        )

    # Stream progress so the user sees tool activity during execution.
    _emit_tool_progress(ctx, f"  {skill_name}: {_summarise_args(arguments)} ...")
    try:
        call_id = _tool_call_id(ctx)
        call_kwargs: dict[str, Any] = {}
        if call_id is not None:
            call_kwargs["call_id"] = call_id
        result = ctx.deps.skill_runner.execute_skill(
            tool_name=skill_name,
            arguments=arguments,
            session_id=ctx.deps.session_id,
            on_text=ctx.deps.stream_text,
            on_tool_event=ctx.deps.on_tool_event,
            **call_kwargs,
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
                    "Stop and surface content to the user unchanged. Do not summarize."
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


def _tool_call_id(ctx: RunContext[AgentDeps]) -> str | None:
    call_id = getattr(ctx, "tool_call_id", None)
    return call_id if isinstance(call_id, str) else None


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
        "total_tokens": int((usage.input_tokens or 0) + (usage.output_tokens or 0)),
    }


def _emit_tool_progress(ctx: RunContext[AgentDeps], message: str) -> None:
    handler = ctx.deps.on_tool_event
    if handler is not None:
        handler(message)


def _tool_budget_exhausted(
    ctx: RunContext[AgentDeps],
    skill_name: str,
    max_calls: int,
) -> bool:
    current = ctx.deps.tool_call_counts.get(skill_name, 0)
    if current >= max_calls:
        return True
    ctx.deps.tool_call_counts[skill_name] = current + 1
    return False


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
    prompt = "\n\n".join(msg["content"] for msg in messages if msg["role"] != "system")

    agent = Agent(model, system_prompt=system_prompt)
    result = agent.run_sync(prompt)
    return str(result.output)


def extract_observations_from_turn(
    turn_content: str,
    *,
    model: Model,
    skill_runner: SkillRunner,
    session_id: str,
) -> None:
    """Run a classifier LLM call to extract observations from a turn.

    Builds a compact prompt, calls chat_text(), parses the returned
    AutoObserveBatch, and feeds each entry to the observe skill.

    Errors are logged but never raised — this is a best-effort
    background operation.
    """
    from pydantic import BaseModel, ConfigDict, Field  # noqa: PLC0415

    class AutoObserveEntry(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)

        key: str = Field(..., description="Stable slug identifier")
        observation_type: str = Field(
            ...,
            description=(
                "One of: entity, schema, insight, dispute, boundary, constant, "
                "result, architecture"
            ),
        )
        summary: str = Field(
            ..., description="One-line summary of the observation, be specific"
        )
        detail: str = Field(
            ...,
            description=(
                "2-3 sentences explaining why this observation matters — "
                "what would the agent do differently knowing this, or "
                "what would go wrong without it"
            ),
        )

    class AutoObserveBatch(BaseModel):
        model_config = ConfigDict(extra="forbid")

        entries: list[AutoObserveEntry]

    if not is_live_model(model):
        logger.debug("Skipping observation extraction: model is not live")
        return

    messages: list[Message] = [
        {
            "role": "system",
            "content": (
                "You are a post-turn observation extractor. Scan the conversation "
                "turn below and extract structural observations worth adding to "
                "the project context map.\n\n"
                "Return ONLY a JSON object matching this schema:\n"
                '{"entries": [{"key": "stable-slug", '
                '"observation_type": "entity|schema|insight|dispute|boundary|constant|result", '
                '"summary": "one-line summary", '
                '"detail": "2-3 sentences explaining why this matters — '
                'what would the agent do differently knowing this, '
                'or what would go wrong without it"}]}\n\n'
                "Rules:\n"
                "- Only extract NEW discoveries about the codebase\n"
                "- Be specific: include file paths, class names, function names\n"
                "- Skip trivial things — every file read does NOT need an observation\n"
                '- Return {"entries": []} if nothing worth recording was found\n'
                "- observation_type must be one of: entity, schema, insight, "
                "dispute, boundary, constant, result, architecture\n"
                "- entity: key class, function, module, or concept\n"
                "- schema: data format, config shape, or API contract\n"
                "- insight: non-obvious relationship between components\n"
                "- dispute: stale or incorrect existing knowledge\n"
                "- boundary: something definitively NOT in the codebase\n"
                "- constant: stable domain constant (config value, magic number)\n"
                "- result: reusable computation or analysis result\n"
                "- architecture: cross-cutting structural invariant about "
                "system organization\n"
                "- summary must be a one-line factual statement\n"
                "- detail must explain impact: why does this matter? "
                "what changes because of it?\n"
            ),
        },
        {"role": "user", "content": turn_content},
    ]

    try:
        raw = chat_text(messages, model=model)
    except Exception:
        logger.exception("Observation classifier LLM call failed")
        return

    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:] if lines else []
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        batch = AutoObserveBatch.model_validate_json(raw)
    except Exception:
        logger.exception("Failed to parse observation classifier output")
        return

    if not batch.entries:
        logger.debug("Observation classifier returned no entries")
        return

    for entry in batch.entries:
        try:
            skill_runner.execute_skill(
                tool_name="observe",
                arguments={
                    "observation_type": entry.observation_type,
                    "summary": entry.summary[:200],
                    "detail": entry.detail,
                },
                session_id=session_id,
            )
        except Exception:
            logger.exception(
                "Failed to record observation: %s",
                entry.key,
            )

    logger.debug(
        "Observation extraction completed",
        extra={
            "session_id": session_id,
            "entries_found": len(batch.entries),
        },
    )


def is_live_model(model: Model) -> bool:
    """Return True if the model is not a TestModel fallback."""
    return not isinstance(model, TestModel)
