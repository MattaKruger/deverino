from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import tiktoken
from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput

from harness_poc.core.pydantic_runtime import build_model

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import Model

    from harness_poc.app_factory import AppState
    from harness_poc.core.database import StateEvent
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


def _completion_content(
    *,
    goal: str,
    reasoning: str,
    final_answer: str,
    recent_events: list[StateEvent],
) -> str:
    if final_answer:
        return final_answer

    generated_result = _latest_generated_result(recent_events)
    if generated_result and _looks_like_meta_completion(reasoning):
        return generated_result

    if reasoning:
        return reasoning
    if generated_result and _looks_like_generation_goal(goal):
        return generated_result
    return "Goal completed."


def _latest_generated_result(recent_events: list[StateEvent]) -> str:
    for event in reversed(recent_events):
        payload = event.payload
        if not isinstance(payload, dict):
            continue
        if event.event_type != "tool_observation":
            continue
        if payload.get("status") != "success":
            continue
        content = str(payload.get("content") or "").strip()
        extracted = _extract_generated_result(content)
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
    content: str  # final summary for the user
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
    stuck_threshold: int = 3  # block on 4th identical consecutive action
    decision_model: Model | None = None

    # Internal state (per run)
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
            recent_events = app_state.database.get_recent_events(
                app_state.session_id, limit=self.context_window
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

            if action.tool_name == "_llm_text":
                # Structured fallback for a model text response with no concrete action.
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="_llm_text",
                    status="success",
                    content=action.content,
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": "_llm_text",
                        "content": action.content[:200],
                    }
                )
                continue

            # --- Tool call path ---
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

            # --- Record llm_action ---
            app_state.database.record_llm_action(
                session_id=app_state.session_id,
                tool_name=tool_name,
                arguments=arguments,
            )
            events.append(
                {
                    "type": "llm_action",
                    "tool": tool_name,
                    "arguments": arguments,
                }
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
                        "arguments": arguments,
                    },
                )
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    status="blocked",
                    content=error_msg,
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
                    _emit_goal_progress(on_text, f"[goal] reasoning: {reasoning}\n")

                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="evaluate_goal",
                    status="success",
                    content=(
                        f"is_complete={is_complete}, reasoning={reasoning}, "
                        f"final_answer={final_answer}"
                    ),
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

                # Not complete — inject reasoning as observation, continue
                feedback = (
                    f"Goal not yet complete. Your reasoning: {reasoning}\n\n"
                    "Continue working. Try a different approach if stuck."
                )
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="_evaluate_goal_feedback",
                    status="success",
                    content=feedback,
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
            try:
                result = app_state.skill_runner.execute_skill(
                    tool_name=tool_name,
                    arguments=arguments,
                    session_id=app_state.session_id,
                    on_text=on_text,
                )
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    status=result.status,
                    content=result.content,
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
                        "arguments": arguments,
                    },
                )
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    status="error",
                    content=error_msg,
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
                f"Iteration budget ({self.max_iterations}) exhausted. "
                "Goal may be incomplete."
            ),
            iterations=self.max_iterations,
            total_tokens=total_tokens,
            events=events,
        )

    # ------------------------------------------------------------------
    # Context window building
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        goal: str,
        recent_events: list[StateEvent],
    ) -> list[Message]:
        """Build message list: system prompt + formatted event history + continue prompt."""
        system_prompt = self._goal_system_prompt(goal)

        messages: list[Message] = [
            {"role": "system", "content": system_prompt},
        ]

        for event in recent_events:
            payload = event.payload
            if not isinstance(payload, dict):
                continue

            if event.event_type == "llm_action":
                tool_name = str(payload.get("tool_name", "unknown"))
                args = payload.get("arguments", {})
                messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            f"[Action] Called {tool_name}"
                            f"({json.dumps(args, sort_keys=True)})"
                        ),
                    }
                )
            elif event.event_type == "tool_observation":
                tool_name = str(payload.get("tool_name", "unknown"))
                content = str(payload.get("content", ""))
                status = str(payload.get("status", ""))
                prefix = f"[Observation from {tool_name}"
                if status:
                    prefix += f" — {status}"
                prefix += "]"
                messages.append(
                    {
                        "role": "user",
                        "content": f"{prefix}\n{content}",
                    }
                )

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
        recent_events: list[StateEvent],
    ) -> tuple[GoalAction, int]:
        model = (
            self.decision_model
            or app_state.goal_decision_model
            or build_model()
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
        recent_events: list[StateEvent],
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
            parts.extend(_format_event_for_prompt(event) for event in recent_events)
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
            "`is_complete: true` and explain what was accomplished. If the goal "
            "asked you to generate, draft, write, or produce text, include that "
            "generated text verbatim in `final_answer`; do not only describe where "
            "it was produced.\n"
            "- If you are stuck or cannot proceed, call `evaluate_goal` with "
            "`is_complete: false` and explain what is blocking you.\n"
            "- Do not repeat the same action with identical arguments — the system "
            "will block repeated patterns.\n"
            "- Be concise. Focus on actions, not conversation.\n"
        )

    # ------------------------------------------------------------------
    # Stuck detection
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_action(tool_name: str, arguments: dict[str, Any]) -> str:
        """Deterministic hash of a (tool_name, arguments) pair."""
        canonical = json.dumps(
            {"tool": tool_name, "args": arguments}, sort_keys=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _is_stuck(self, action_hash: str) -> bool:
        """Return True if this action_hash matches all last stuck_threshold hashes."""
        if len(self._stuck_hashes) < self.stuck_threshold:
            return False
        return all(h == action_hash for h in self._stuck_hashes)


def _format_event_for_prompt(event: StateEvent) -> str:
    payload = event.payload
    if not isinstance(payload, dict):
        return f"- {event.event_type}: {payload}"

    return f"- {event.event_type}: {json.dumps(payload, sort_keys=True)}"
