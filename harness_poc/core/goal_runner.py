from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import tiktoken

if TYPE_CHECKING:
    from harness_poc.app_factory import AppState
    from harness_poc.core.database import StateEvent
    from harness_poc.core.llm_client import Message

_encoder_cache: dict[str, tiktoken.Encoding] = {}


def _get_encoder() -> tiktoken.Encoding:
    if "enc" not in _encoder_cache:
        _encoder_cache["enc"] = tiktoken.get_encoding("cl100k_base")
    return _encoder_cache["enc"]


def count_tokens(messages: Any) -> int:
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


@dataclass
class GoalRunResult:
    status: str  # "completed" | "budget_exhausted" | "error"
    content: str  # final summary for the user
    iterations: int
    total_tokens: int
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GoalRunner:
    max_iterations: int = 50
    max_seconds: float | None = None
    max_tokens: int | None = None
    context_window: int = 20
    stuck_threshold: int = 3  # block on 4th identical consecutive action

    # Internal state (per run)
    _stuck_hashes: deque[str] = field(default_factory=lambda: deque(maxlen=3))

    def run(self, goal: str, app_state: AppState) -> GoalRunResult:
        """Execute the autonomous ReAct loop for the given goal."""
        start_time = time.monotonic()
        self._stuck_hashes.clear()
        total_tokens = 0
        events: list[dict[str, Any]] = []

        for iteration in range(1, self.max_iterations + 1):
            # --- Budget: time ---
            if self.max_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.max_seconds:
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

            # --- LLM decision ---
            response = app_state.llm_client.chat(
                messages=messages, tools=app_state.tools
            )
            # Count tokens consumed by this call (input + approximate output)
            if self.max_tokens is not None:
                total_tokens += token_count + count_tokens(
                    [{"role": "assistant", "content": response.content}]
                )

            if response.kind == "text":
                # LLM returned text instead of a tool call — record and continue
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="_llm_text",
                    status="success",
                    content=response.content,
                )
                events.append(
                    {
                        "type": "tool_observation",
                        "tool": "_llm_text",
                        "content": response.content[:200],
                    }
                )
                continue

            # --- Tool call path ---
            assert response.tool_call is not None  # guaranteed by kind == "tool_call"
            tool_name: str = response.tool_call["name"]
            arguments: dict[str, Any] = response.tool_call["arguments"]

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

                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="evaluate_goal",
                    status="success",
                    content=f"is_complete={is_complete}, reasoning={reasoning}",
                )

                if is_complete:
                    return GoalRunResult(
                        status="completed",
                        content=reasoning or "Goal completed.",
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
            "`is_complete: true` and explain what was accomplished.\n"
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
