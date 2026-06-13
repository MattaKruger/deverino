"""GoalEvaluator — v2 ReAct subscriber for goal completion detection.

New subscriber (no v1 equivalent). Listens for ``LLM_TEXT_EMITTED`` events
and evaluates whether the goal has been satisfied. Publishes ``GOAL_EVALUATED``
with a completion flag and reasoning.

In its simplest form, this is a heuristic evaluator that considers the goal
complete when the LLM emits final text (not a tool request). A future version
could use a separate LLM call to evaluate goal completion.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GoalEvaluator:
    """ReAct goal evaluator — detects when the goal has been satisfied.

    Currently uses a simple heuristic: the goal is considered complete when
    the LLM emits ``LLM_TEXT_EMITTED`` (as opposed to ``TOOL_REQUESTED``),
    indicating it has produced a final answer rather than requesting another
    tool call.
    """

    def __init__(self, *, max_iterations: int = 50) -> None:
        self._max_iterations = max_iterations
        self._iteration_count = 0

    async def run(self, bus: Any, session_id: str) -> None:
        """Run the goal evaluator loop for a session."""
        async for envelope in bus.subscribe_session(session_id):
            event_type: str = envelope["event_type"]

            if event_type == "STREAM_PAUSED":
                break

            if event_type == "LLM_ACTION_EMITTED":
                self._iteration_count += 1

            if event_type == "LLM_TEXT_EMITTED":
                # LLM produced final text — consider the goal complete
                bus.publish(
                    "GOAL_EVALUATED",
                    {
                        "session_id": session_id,
                        "team_member": "goal_evaluator",
                        "is_complete": True,
                        "reasoning": "LLM produced final text output",
                    },
                )

            if self._iteration_count >= self._max_iterations:
                bus.publish(
                    "GOAL_EVALUATED",
                    {
                        "session_id": session_id,
                        "team_member": "goal_evaluator",
                        "is_complete": False,
                        "reasoning": (
                            f"Reached max iterations ({self._max_iterations}) "
                            "without final text output"
                        ),
                    },
                )
                break
