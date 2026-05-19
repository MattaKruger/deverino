from __future__ import annotations

import hashlib
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
from harness_poc.core.pydantic_runtime import build_model

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import Model

    from harness_poc.app_factory import AppState
    from harness_poc.core.llm_client import Message

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
) -> None:
    if on_text is not None and content:
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
            "content": (
                f"[evaluate_goal: is_complete={event.is_complete}] {event.reasoning}"
            ),
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
        marker in normalized
        for marker in ("generate", "write", "draft", "create", "produce")
    )


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
        description=(
            "Optional plain text thought or response when no tool should be called."
        ),
    )


@dataclass
class GoalRunner:
    max_iterations: int = 50
    max_seconds: float | None = None
    max_tokens: int | None = None
    context_window: int = 20
    stuck_threshold: int = 3
    decision_model: Model | None = None

    _stuck_hashes: deque[str] = field(default_factory=lambda: deque(maxlen=3))

    def run(  # noqa: PLR0915
        self,
        goal: str,
        app_state: AppState,
        on_text: Callable[[str], None] | None = None,
    ) -> GoalRunResult:
        """Execute the autonomous ReAct loop for the given goal."""
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
        self._stuck_hashes.clear()
        total_tokens = 0
        events: list[dict[str, Any]] = []

        app_state.event_bus.publish(
            AgentStarted(session_id=app_state.session_id, goal=goal)
        )

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

            # --- Budget: tokens ---
            if self.max_tokens is not None:
                token_count = count_tokens(messages)
                if total_tokens + token_count >= self.max_tokens:
                    logger.warning(
                        "Goal run exhausted token budget",
                        extra={
                            "session_id": app_state.session_id,
                            "goal": goal,
                            "iterations": iteration - 1,
                            "total_tokens": total_tokens,
                            "next_context_tokens": token_count,
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

            # --- PydanticAI structured decision ---
            action, response_tokens = self._decide_next_action(
                goal=goal,
                app_state=app_state,
                recent_events=recent_events,
            )
            if self.max_tokens is not None:
                total_tokens += token_count + response_tokens

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
                f"\n[goal] iteration {iteration}: {tool_name}\n",
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

            # --- Stuck detection ---
            action_hash = self._hash_action(tool_name, arguments)
            if self._is_stuck(action_hash):
                error_msg = (
                    "STUCK DETECTION: You have attempted the same action "
                    f"({tool_name}) with identical arguments "
                    f"{self.stuck_threshold}+ times. The action was blocked. "
                    "Step back and try a different approach."
                )
                logger.warning(
                    "Goal action blocked by stuck detection",
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
                        "content": "Stuck detection triggered.",
                    }
                )
                continue

            self._stuck_hashes.append(action_hash)

            # --- Intercept evaluate_goal ---
            if tool_name == "evaluate_goal":
                is_complete: bool = arguments.get("is_complete", False)
                reasoning: str = arguments.get("reasoning", "")
                final_answer = str(arguments.get("final_answer") or "").strip()
                if reasoning:
                    _emit_goal_progress(
                        on_text, f"[goal] reasoning: {reasoning}\n"
                    )

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

            # --- Execute normal skill ---
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
                result = app_state.skill_runner.execute_skill(
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
        result = agent.run_sync(
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
        parts = [
            "Choose the next concrete action as structured output.",
            "",
            "## Available Tools",
            json.dumps(tools, indent=2, sort_keys=True),
            "",
            "## Recent Events",
        ]

        if recent_events:
            parts.extend(
                f"- {event.event_type}: {event.model_dump_json()}"
                for event in recent_events
            )
        else:
            parts.append("No prior events.")

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
            "- Do not repeat the same action with identical arguments — the system "
            "will block repeated patterns.\n"
            "- Be concise. Focus on actions, not conversation.\n"
        )

    @staticmethod
    def _hash_action(tool_name: str, arguments: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"tool": tool_name, "args": arguments}, sort_keys=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _is_stuck(self, action_hash: str) -> bool:
        if len(self._stuck_hashes) < self.stuck_threshold:
            return False
        return all(h == action_hash for h in self._stuck_hashes)
