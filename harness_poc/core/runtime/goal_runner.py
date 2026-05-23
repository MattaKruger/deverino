from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import tiktoken
from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput

from harness_poc.core.events import (
    AgentStarted,
    BaseEvent,
    GoalEvaluated,
    LLMTextEmitted,
    SkillCalled,
    SkillCompleted,
)
from harness_poc.core.runtime.pydantic_runtime import build_model

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import Model

    from harness_poc.app_factory import AppState
    from harness_poc.core.runtime.llm_client import Message

_encoder_cache: dict[str, tiktoken.Encoding] = {}
logger = logging.getLogger(__name__)


def _get_encoder() -> tiktoken.Encoding:
    if "enc" not in _encoder_cache:
        _encoder_cache["enc"] = tiktoken.get_encoding("cl100k_base")
    return _encoder_cache["enc"]


def count_tokens(messages: Any) -> int:  # noqa: ANN401
    r"""Count tokens in a message list using OpenAI's formula.

    Each message follows <|im_start|>{role}\n{content}<|im_end|>\n
    plus 3 tokens for the assistant priming.

    Accepts any iterable of dict-like objects (list[Message], list[dict[str, str]], etc.).
    """
    encoder = _get_encoder()
    tokens_per_message = 3
    num_tokens = 0
    for message in messages:  # type: ignore[union-attr]
        num_tokens += tokens_per_message
        for value in message.values():  # type: ignore[union-attr]
            num_tokens += len(encoder.encode(str(value)))
    num_tokens += 3  # assistant priming
    return num_tokens


def _emit_goal_progress(
    on_text: Callable[[str], None] | None,
    content: str,
    *,
    on_tool_event: Callable[[str], None] | None = None,
    tool_event: bool = False,
) -> None:
    if tool_event and on_tool_event is not None and content:
        on_tool_event(content)
    elif on_text is not None and content:
        on_text(content)


def _event_to_message(event: BaseEvent) -> Message | None:
    if isinstance(event, SkillCalled):
        return {
            "role": "assistant",
            "content": (
                f"[Action] Called {event.tool_name}({json.dumps(event.arguments, sort_keys=True)})"
            ),
        }
    if isinstance(event, SkillCompleted):
        prefix = f"[Observation from {event.tool_name} — {event.status}]"
        return {"role": "user", "content": f"{prefix}\n{event.content}"}
    if isinstance(event, LLMTextEmitted):
        return {"role": "user", "content": f"[LLM text]\n{event.content}"}
    if isinstance(event, GoalEvaluated):
        return {
            "role": "user",
            "content": (f"[evaluate_goal: is_complete={event.is_complete}] {event.reasoning}"),
        }
    return None


def _completion_content(
    *,
    goal: str,
    reasoning: str,
    final_answer: str,
    recent_events: list[BaseEvent],
) -> str:
    # --- Pick the primary content ---
    if final_answer:
        content = final_answer
    else:
        generated_result = _latest_generated_result(recent_events)
        if generated_result and _looks_like_meta_completion(reasoning):
            content = generated_result
        elif reasoning:
            content = reasoning
        elif generated_result and _looks_like_generation_goal(goal):
            content = generated_result
        else:
            # Safety net: surface the last successful skill's output
            # when the LLM didn't provide any answer at all.
            content = _last_skill_output(recent_events) or "Goal completed."

    # --- Append source file references so they're always clickable ---
    refs = _extract_file_refs(recent_events)
    if refs:
        content += "\n\n**Source files:**\n" + refs

    return content


def _latest_generated_result(recent_events: list[BaseEvent]) -> str:
    for event in reversed(recent_events):
        if not isinstance(event, SkillCompleted):
            continue
        if event.status != "success":
            continue
        extracted = _extract_generated_result(event.content)
        if extracted:
            return extracted
    return ""


def _extract_generated_result(content: str) -> str:
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(decoded, dict):
        return content

    summary = decoded.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    artifacts = decoded.get("artifacts")
    if isinstance(artifacts, dict):
        model_output = artifacts.get("model_output")
        if isinstance(model_output, dict):
            model_summary = model_output.get("summary")
            if isinstance(model_summary, str) and model_summary.strip():
                return model_summary.strip()

    return content


# Semble outputs file references like:
#   ## 1. path/to/file.py:123-456  [score=0.027]
# This regex captures the path and start line.
_FILE_REF_RE = re.compile(
    r"##\s*\d+\.\s+([^\s\[\]]+):(\d+)(?:-\d+)?",
)


def _extract_file_refs(recent_events: list[BaseEvent]) -> str:
    """Extract clickable `file:line` references from SkillCompleted events."""
    seen: set[str] = set()
    lines: list[str] = []
    for event in recent_events:
        if not isinstance(event, SkillCompleted):
            continue
        if event.status != "success":
            continue
        for match in _FILE_REF_RE.finditer(event.content):
            path = match.group(1)
            line_num = match.group(2)
            ref = f"{path}:{line_num}"
            if ref not in seen:
                seen.add(ref)
                lines.append(f"- `{ref}`")
    return "\n".join(lines)


def _last_skill_output(recent_events: list[BaseEvent]) -> str:
    """Return the content of the most recent successful SkillCompleted event."""
    for event in reversed(recent_events):
        if not isinstance(event, SkillCompleted):
            continue
        if event.status != "success":
            continue
        if event.content.strip():
            return event.content.strip()
    return ""


def _looks_like_meta_completion(reasoning: str) -> bool:
    normalized = reasoning.lower()
    meta_markers = (
        "skill returned",
        "delegate_task",
        "read_memory",
        "goal has been achieved",
        "goal has been completed",
        "goal is complete",
        "covers all",
        "summarizing the changes",
    )
    return any(marker in normalized for marker in meta_markers)


def _looks_like_generation_goal(goal: str) -> bool:
    normalized = goal.lower()
    return any(
        marker in normalized for marker in ("generate", "write", "draft", "create", "produce")
    )


def _semantic_key(tool_name: str, arguments: dict[str, Any]) -> str:
    """Build a normalized key for semantic comparison of actions.

    Normalizes string values so that minor phrasing differences
    (whitespace, casing, punctuation) do not produce distinct hashes.
    For example, "BlackboardDatabase schema" and "BlackboardDatabase  schema"
    produce the same key.
    """
    normalized: dict[str, Any] = {}
    for k, v in sorted(arguments.items()):
        if isinstance(v, str):
            normalized[k] = " ".join(v.lower().split())
        elif isinstance(v, (int, float, bool)):
            normalized[k] = v
        elif isinstance(v, list):
            normalized[k] = [
                " ".join(str(x).lower().split()) if isinstance(x, str) else x for x in v
            ]
        elif isinstance(v, dict):
            inner: dict[str, Any] = {}
            for ik, iv in sorted(v.items()):
                if isinstance(iv, str):
                    inner[str(ik)] = " ".join(iv.lower().split())
                elif isinstance(iv, (int, float, bool)):
                    inner[str(ik)] = iv
                else:
                    inner[str(ik)] = str(iv)
            normalized[k] = json.dumps(inner, sort_keys=True)
        else:
            normalized[k] = str(v)
    return f"{tool_name}:{json.dumps(normalized, sort_keys=True)}"


# ---------------------------------------------------------------------------
# Context Window Compression (Phase 2)
# ---------------------------------------------------------------------------

_SKILL_CONTENT_MAX_CHARS = 500
_EVENT_SUMMARY_MAX_TOOLS = 10


def _format_event_compact(event: BaseEvent) -> str:
    """Format a single event compactly for the decision prompt.

    SkillCompleted events get their content compressed; other events
    get a compact one-line representation.
    """
    event_type = event.event_type

    if isinstance(event, SkillCalled):
        return f"- {event_type}: {event.tool_name}({json.dumps(event.arguments, sort_keys=True)})"
    if isinstance(event, SkillCompleted):
        compressed = _compress_skill_content(event.tool_name, event.content)
        return f"- {event_type}({event.tool_name}): [{event.status}] {compressed}"
    if isinstance(event, GoalEvaluated):
        return f"- {event_type}: is_complete={event.is_complete} {event.reasoning[:200]}"
    if isinstance(event, LLMTextEmitted):
        return f"- {event_type}: {event.content[:200]}"

    # Fallback: compact JSON representation
    return f"- {event_type}: {event.model_dump_json(exclude={'timestamp', 'created_at', 'id'})}"[
        :500
    ]


def _compress_skill_content(tool_name: str, content: str) -> str:
    """Compress SkillCompleted content to fit within a character budget.

    For JSON content, extracts key fields. For text content, truncates.
    """
    if not content:
        return "(empty)"

    # For very long content, try JSON extraction first
    if len(content) > _SKILL_CONTENT_MAX_CHARS and content.strip().startswith("{"):
        try:
            decoded = json.loads(content)
            if isinstance(decoded, dict):
                return _extract_skill_json_summary(tool_name, decoded)
        except json.JSONDecodeError:
            pass

    # Truncate plain text
    if len(content) <= _SKILL_CONTENT_MAX_CHARS:
        return content.replace("\n", " ")

    truncated = content[:_SKILL_CONTENT_MAX_CHARS].replace("\n", " ")
    return f"{truncated}... [truncated, {len(content)} total chars]"


def _extract_skill_json_summary(tool_name: str, data: dict[str, Any]) -> str:
    """Extract a compact summary from JSON skill output."""
    parts: list[str] = []

    # Common fields for container/exec outputs
    if "exit_code" in data:
        parts.append(f"exit={data['exit_code']}")
    if "stdout" in data and isinstance(data["stdout"], str):
        stdout = data["stdout"]
        if len(stdout) <= 200:  # noqa: PLR2004
            parts.append(f'stdout="{stdout}"')
        else:
            parts.append(f"stdout={len(stdout)}chars")
    if "stderr" in data and isinstance(data["stderr"], str):
        stderr = data["stderr"]
        if stderr.strip():
            parts.append(f"stderr={len(stderr)}chars")

    # For search results, count results
    if "results" in data and isinstance(data["results"], list):
        parts.append(f"results={len(data['results'])}")
    if "count" in data:
        parts.append(f"count={data['count']}")

    # Fallback: key fields
    if not parts:
        for key in ("summary", "content", "result", "message"):
            if key in data and isinstance(data[key], str):
                val = data[key].replace("\n", " ")
                parts.append(f"{key}={val[:300]}")
                break
        if not parts:
            parts.append(f"keys={sorted(data.keys())}")

    return f"{tool_name}: " + ", ".join(parts)


def _summarize_event_list(events: list[BaseEvent]) -> str:
    """Create a dense summary of older events for context compression.

    Reduces verbose event history to a compact narrative that preserves
    semantic meaning while dropping serialized JSON bloat.
    """
    tool_calls: list[str] = []
    tool_results: list[str] = []
    goal_checks: list[str] = []

    for event in events:
        if isinstance(event, SkillCalled):
            tool_calls.append(f"{event.tool_name}({_summarise_args_compact(event.arguments)})")
        elif isinstance(event, SkillCompleted):
            result = _compress_skill_content(event.tool_name, event.content)
            tool_results.append(f"{event.tool_name} → {event.status}: {result}")
        elif isinstance(event, GoalEvaluated):
            goal_checks.append(
                f"evaluate_goal(is_complete={event.is_complete}, reasoning={event.reasoning[:100]})"
            )
        elif isinstance(event, LLMTextEmitted):
            tool_results.append(f"_llm_text: {event.content[:150]}")

    lines: list[str] = []

    if tool_calls:
        # Deduplicate and show only unique calls
        seen: set[str] = set()
        unique_calls: list[str] = []
        for call in tool_calls:
            if call not in seen:
                seen.add(call)
                unique_calls.append(call)
        if len(unique_calls) > _EVENT_SUMMARY_MAX_TOOLS:
            extra = len(unique_calls) - _EVENT_SUMMARY_MAX_TOOLS
            unique_calls = unique_calls[:_EVENT_SUMMARY_MAX_TOOLS]
            unique_calls.append(f"... and {extra} more tool calls")
        lines.append("**Actions taken:** " + "; ".join(unique_calls))

    if tool_results:
        lines.append("**Results:** " + "; ".join(tool_results[-5:]))

    if goal_checks:
        lines.append("**Progress checks:** " + "; ".join(goal_checks[-3:]))

    if not lines:
        lines.append(f"(No significant events in {len(events)} history items)")

    return "\n".join(lines)


def _summarise_args_compact(arguments: dict[str, Any]) -> str:
    """Ultra-compact argument summary for context compression."""
    for key in ("query", "objective", "description", "code", "command"):
        if key in arguments:
            val = str(arguments[key])
            truncated = val[:80].replace("\n", " ")
            suffix = "..." if len(val) > 80 else ""  # noqa: PLR2004
            return f"{key}={truncated}{suffix}"
    # Show first key with a short value
    for k, v in sorted(arguments.items()):
        s = str(v)
        if len(s) < 40:  # noqa: PLR2004
            return f"{k}={s}"
        return f"{k}={s[:40]}..."
    return ""


@dataclass
class GoalRunResult:
    status: str  # "completed" | "budget_exhausted" | "error"
    content: str
    iterations: int
    total_tokens: int
    events: list[dict[str, Any]] = field(default_factory=list)


class GoalAction(BaseModel):
    tool_name: str = Field(
        description=(
            "Name of the next skill/tool to execute. Use evaluate_goal when "
            "the goal is complete, blocked, or needs an explicit progress check."
        ),
    )
    arguments: dict[str, Any] = Field(default_factory=dict)
    content: str = Field(
        default="",
        description=("Optional plain text thought or response when no tool should be called."),
    )


@dataclass
class GoalRunner:
    max_iterations: int = 50
    max_seconds: float | None = None
    max_tokens: int | None = None
    context_window: int = 20
    stuck_threshold: int = 3
    decision_model: Model | None = None

    _failed_action_keys: deque[str] = field(default_factory=lambda: deque(maxlen=5))

    def run(
        self,
        goal: str,
        app_state: AppState,
        on_text: Callable[[str], None] | None = None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> GoalRunResult:
        """Run synchronously for backward compatibility. Use run_async() for new code."""
        return asyncio.run(self.run_async(goal, app_state, on_text, on_tool_event))

    async def run_async(  # noqa: PLR0915
        self,
        goal: str,
        app_state: AppState,
        on_text: Callable[[str], None] | None = None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> GoalRunResult:
        """Execute the autonomous ReAct loop for the given goal (async)."""
        logger.info(
            "Goal run started",
            extra={
                "session_id": app_state.session_id,
                "goal": goal,
                "max_iterations": self.max_iterations,
                "max_seconds": self.max_seconds,
                "max_tokens": self.max_tokens,
            },
        )
        start_time = time.monotonic()
        self._failed_action_keys.clear()
        total_tokens = 0
        previous_context_tokens = 0
        events: list[dict[str, Any]] = []

        app_state.event_bus.publish(AgentStarted(session_id=app_state.session_id, goal=goal))

        for iteration in range(1, self.max_iterations + 1):
            # --- Budget: time ---
            if self.max_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.max_seconds:
                    logger.warning(
                        "Goal run exhausted time budget",
                        extra={
                            "session_id": app_state.session_id,
                            "goal": goal,
                            "iterations": iteration - 1,
                            "elapsed": elapsed,
                        },
                    )
                    return GoalRunResult(
                        status="budget_exhausted",
                        content=(
                            f"Time budget ({self.max_seconds}s) exhausted "
                            f"after {iteration - 1} iterations."
                        ),
                        iterations=iteration - 1,
                        total_tokens=total_tokens,
                        events=events,
                    )

            # --- Build context window ---
            recent_events = app_state.event_bus.get_recent_events(
                app_state.session_id,
                limit=self.context_window,
                event_types=[
                    SkillCalled,
                    SkillCompleted,
                    GoalEvaluated,
                    LLMTextEmitted,
                ],
            )

            # --- Build messages for LLM ---
            messages = self._build_messages(goal, recent_events)
            token_count = count_tokens(messages)
            context_delta_tokens = max(0, token_count - previous_context_tokens)

            # --- Budget: tokens ---
            if (
                self.max_tokens is not None
                and total_tokens + context_delta_tokens >= self.max_tokens
            ):
                logger.warning(
                    "Goal run exhausted token budget",
                    extra={
                        "session_id": app_state.session_id,
                        "goal": goal,
                        "iterations": iteration - 1,
                        "total_tokens": total_tokens,
                        "next_context_tokens": context_delta_tokens,
                    },
                )
                return GoalRunResult(
                    status="budget_exhausted",
                    content=(
                        f"Token budget ({self.max_tokens}) exhausted "
                        f"after {iteration - 1} iterations."
                    ),
                    iterations=iteration - 1,
                    total_tokens=total_tokens,
                    events=events,
                )

            # --- PydanticAI structured decision (async) ---
            action, response_tokens = await self._decide_next_action_async(
                goal=goal,
                app_state=app_state,
                recent_events=recent_events,
            )
            total_tokens += context_delta_tokens + response_tokens
            previous_context_tokens = token_count

            # --- _llm_text path ---
            if action.tool_name == "_llm_text":
                app_state.event_bus.publish(
                    LLMTextEmitted(
                        session_id=app_state.session_id,
                        content=action.content,
                    )
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": "_llm_text",
                        "content": action.content[:200],
                    }
                )
                continue

            tool_name = action.tool_name
            arguments = action.arguments
            _emit_goal_progress(
                on_text,
                f"iteration {iteration}: {tool_name}",
                on_tool_event=on_tool_event,
                tool_event=True,
            )
            logger.info(
                "Goal action selected",
                extra={
                    "session_id": app_state.session_id,
                    "goal": goal,
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )

            # --- Stuck detection (semantic, only against FAILED actions) ---
            if self._is_semantically_stuck(tool_name, arguments):
                error_msg = (
                    "Action rejected: You have already attempted this specific "
                    f"approach ({tool_name}). It failed previously. You must "
                    "pivot your strategy or use a different tool."
                )
                logger.warning(
                    "Goal action blocked by semantic stuck detection",
                    extra={
                        "session_id": app_state.session_id,
                        "goal": goal,
                        "iteration": iteration,
                        "tool_name": tool_name,
                    },
                )
                app_state.event_bus.publish(
                    SkillCompleted(
                        session_id=app_state.session_id,
                        tool_name=tool_name,
                        status="blocked",
                        content=error_msg,
                    )
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": tool_name,
                        "status": "blocked",
                        "content": "Semantic stuck detection triggered.",
                    }
                )
                continue

            # --- Intercept evaluate_goal ---
            if tool_name == "evaluate_goal":
                is_complete: bool = arguments.get("is_complete", False)
                reasoning: str = arguments.get("reasoning", "")
                final_answer = str(arguments.get("final_answer") or "").strip()
                if reasoning:
                    _emit_goal_progress(on_text, f"[goal] reasoning: {reasoning}\n")

                app_state.event_bus.publish(
                    GoalEvaluated(
                        session_id=app_state.session_id,
                        is_complete=is_complete,
                        reasoning=reasoning,
                        final_answer=final_answer,
                    )
                )

                if is_complete:
                    content = _completion_content(
                        goal=goal,
                        reasoning=reasoning,
                        final_answer=final_answer,
                        recent_events=recent_events,
                    )
                    logger.info(
                        "Goal run completed",
                        extra={
                            "session_id": app_state.session_id,
                            "goal": goal,
                            "iteration": iteration,
                            "total_tokens": total_tokens,
                        },
                    )
                    return GoalRunResult(
                        status="completed",
                        content=content,
                        iterations=iteration,
                        total_tokens=total_tokens,
                        events=events,
                    )

                events.append(
                    {
                        "type": "tool_observation",
                        "tool": "evaluate_goal",
                        "content": f"Not complete: {reasoning[:200]}",
                    }
                )
                continue

            # --- Execute normal skill (via asyncio.to_thread) ---
            app_state.event_bus.publish(
                SkillCalled(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            )
            events.append(
                {
                    "type": "llm_action",
                    "tool": tool_name,
                    "arguments": arguments,
                }
            )
            try:
                result = await asyncio.to_thread(
                    app_state.skill_runner.execute_skill,
                    tool_name=tool_name,
                    arguments=arguments,
                    session_id=app_state.session_id,
                    on_text=on_text,
                )
                app_state.event_bus.publish(
                    SkillCompleted(
                        session_id=app_state.session_id,
                        tool_name=tool_name,
                        status=result.status,
                        content=result.content,
                        artifacts=result.artifacts,
                    )
                )
                # Track failed actions for semantic stuck detection
                if result.status in ("failed", "error", "blocked"):
                    self._failed_action_keys.append(_semantic_key(tool_name, arguments))
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": tool_name,
                        "status": result.status,
                        "content": result.content[:200],
                    }
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                error_msg = f"Skill execution failed: {exc}"
                logger.exception(
                    "Goal skill execution failed",
                    extra={
                        "session_id": app_state.session_id,
                        "goal": goal,
                        "iteration": iteration,
                        "tool_name": tool_name,
                    },
                )
                app_state.event_bus.publish(
                    SkillCompleted(
                        session_id=app_state.session_id,
                        tool_name=tool_name,
                        status="error",
                        content=error_msg,
                    )
                )
                # Track failed actions for semantic stuck detection
                self._failed_action_keys.append(_semantic_key(tool_name, arguments))
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": tool_name,
                        "status": "error",
                        "content": error_msg,
                    }
                )

        # --- Budget exhausted (iterations) ---
        logger.warning(
            "Goal run exhausted iteration budget",
            extra={
                "session_id": app_state.session_id,
                "goal": goal,
                "iterations": self.max_iterations,
                "total_tokens": total_tokens,
            },
        )
        return GoalRunResult(
            status="budget_exhausted",
            content=(
                f"Iteration budget ({self.max_iterations}) exhausted. Goal may be incomplete."
            ),
            iterations=self.max_iterations,
            total_tokens=total_tokens,
            events=events,
        )

    def _build_messages(
        self,
        goal: str,
        recent_events: list[BaseEvent],
    ) -> list[Message]:
        """Build message list: system prompt + formatted event history + continue prompt."""
        system_prompt = self._goal_system_prompt(goal)
        messages: list[Message] = [
            {"role": "system", "content": system_prompt},
        ]

        for event in recent_events:
            msg = _event_to_message(event)
            if msg is not None:
                messages.append(msg)

        messages.append(
            {
                "role": "user",
                "content": (
                    "Continue working toward the goal. Take the next concrete action. "
                    "If the goal is fully achieved, call evaluate_goal with "
                    "is_complete=true and explain what was accomplished. "
                    "If you are stuck or cannot proceed, call evaluate_goal with "
                    "is_complete=false and explain what is blocking you."
                ),
            }
        )
        return messages

    def _decide_next_action(
        self,
        *,
        goal: str,
        app_state: AppState,
        recent_events: list[BaseEvent],
    ) -> tuple[GoalAction, int]:
        """Decide next action synchronously for backward compatibility."""
        return asyncio.run(
            self._decide_next_action_async(
                goal=goal,
                app_state=app_state,
                recent_events=recent_events,
            )
        )

    async def _decide_next_action_async(
        self,
        *,
        goal: str,
        app_state: AppState,
        recent_events: list[BaseEvent],
    ) -> tuple[GoalAction, int]:
        model = (
            self.decision_model
            or app_state.goal_decision_model
            or build_model(app_state.config.llm)
        )
        logger.debug(
            "Requesting goal decision",
            extra={
                "session_id": app_state.session_id,
                "recent_event_count": len(recent_events),
                "tool_count": len(app_state.tools),
            },
        )
        agent = Agent(
            model,
            output_type=PromptedOutput(
                GoalAction,
                name="goal_action",
                description=(
                    "Return the next harness skill to execute as JSON. "
                    "Do not call the skill directly."
                ),
            ),
            system_prompt=self._goal_system_prompt(goal),
            output_retries=2,
        )
        result = await agent.run(
            self._build_decision_prompt(recent_events, app_state.tools),
        )
        usage = result.usage
        response_tokens = int(usage.output_tokens or 0)
        action = cast("GoalAction", result.output)
        logger.debug(
            "Goal decision received",
            extra={
                "session_id": app_state.session_id,
                "tool_name": action.tool_name,
                "response_tokens": response_tokens,
            },
        )
        return action, response_tokens

    @staticmethod
    def _build_decision_prompt(
        recent_events: list[BaseEvent],
        tools: list[dict[str, Any]],
    ) -> str:
        # Character budget for event rendering — prevents context bloat
        _max_event_chars = 8000
        _keep_raw_last = 3  # preserve last N events uncompressed

        parts = [
            "Choose the next concrete action as structured output.",
            "",
            "## Available Tools",
            json.dumps(tools, indent=2, sort_keys=True),
            "",
        ]

        if not recent_events:
            parts.append("## Recent Events\nNo prior events.")
        else:
            # Split into older (summarizable) and recent (keep raw)
            if len(recent_events) <= _keep_raw_last:
                raw_events = recent_events
                older_events: list[BaseEvent] = []
            else:
                raw_events = recent_events[-_keep_raw_last:]
                older_events = recent_events[:-_keep_raw_last]

            # Render older events as a compressed summary
            if older_events:
                summary = _summarize_event_list(older_events)
                parts.append("## Prior Context Summary")
                parts.append(summary)
                parts.append("")

            # Render recent raw events (with compression for large content)
            parts.append("## Recent Events")
            event_chars = 0
            for event in raw_events:
                line = _format_event_compact(event)
                event_chars += len(line)
                if event_chars > _max_event_chars:
                    parts.append(
                        f"[Context window overflow — {len(raw_events)} recent events, "
                        f"total {event_chars} chars. See Prior Context Summary above.]"
                    )
                    break
                parts.append(line)

        parts.extend(
            [
                "",
                "## Required Response",
                "Return a structured object with:",
                "- tool_name: the skill/tool to call next.",
                "- arguments: the JSON arguments for that tool.",
                "- content: optional text only when tool_name is _llm_text.",
                "",
                "Do not call any of these tools directly. Return the selected tool "
                "name and arguments as JSON matching the requested structured output.",
                "",
                "Use evaluate_goal with is_complete=true when the goal is fully achieved. "
                "For generation goals, include the generated artifact verbatim in "
                "arguments.final_answer. The user should not need to inspect memory or "
                "logs to see the generated result. "
                "Use evaluate_goal with is_complete=false when progress is incomplete or blocked.",
            ],
        )
        return "\n".join(parts)

    @staticmethod
    def _goal_system_prompt(goal: str) -> str:
        return (
            "You are an autonomous agent operating in a ReAct (Reason + Act) loop. "
            "Your sole objective is to achieve the following goal.\n\n"
            f"## Goal\n{goal}\n\n"
            "## Instructions\n"
            "- Work step by step. Call tools to take actions.\n"
            "- After each tool result, decide on your next action.\n"
            "- When the goal is fully achieved, call `evaluate_goal` with "
            "`is_complete: true` and explain what was accomplished in `reasoning`. "
            "**Always include the complete, polished answer to the user in "
            "`final_answer`** — this is the only text the user will see. "
            "For research/information goals, synthesize the results into a "
            "coherent answer. For generation goals, include the generated "
            "text verbatim. Never leave `final_answer` empty or just state "
            "that the goal is complete.\n"
            "- If you are stuck or cannot proceed, call `evaluate_goal` with "
            "`is_complete: false` and explain what is blocking you.\n"
            "- Do not repeat a previously failed action — the system "
            "will detect semantically similar attempts and block them.\n"
            "- Be concise. Focus on actions, not conversation.\n"
        )

    def _is_semantically_stuck(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Check if this action is semantically similar to a recent failed action."""
        if len(self._failed_action_keys) < self.stuck_threshold:
            return False
        key = _semantic_key(tool_name, arguments)
        match_count = sum(1 for k in self._failed_action_keys if k == key)
        return match_count >= self.stuck_threshold
