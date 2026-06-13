"""GoalEvaluator — v2 ReAct subscriber for goal completion detection.

Listens for LLMTextEmitted and LLMActionEmitted events and evaluates whether
the goal has been satisfied. Publishes GoalEvaluated with a completion flag
and reasoning.
"""

from __future__ import annotations

import logging
from typing import Any

from harness_poc.core.events.events import (
    GoalEvaluated,
    LLMActionEmitted,
    LLMTextEmitted,
    StreamPaused,
)

logger = logging.getLogger(__name__)


class GoalEvaluator:
    """ReAct goal evaluator — detects when the goal has been satisfied.

    Currently uses a simple heuristic: the goal is considered complete when
    the LLM emits LLMTextEmitted (as opposed to a tool request),
    indicating it has produced a final answer rather than requesting another
    tool call.
    """

    def __init__(self, *, max_iterations: int = 50) -> None:
        self._max_iterations = max_iterations
        self._iteration_count = 0

    async def run(self, bus: Any, session_id: str) -> None:
        """Run the goal evaluator loop for a session."""
        async for event in bus.subscribe_session(session_id):
            if isinstance(event, StreamPaused):
                break

            if isinstance(event, LLMActionEmitted):
                self._iteration_count += 1

            if isinstance(event, LLMTextEmitted):
                # LLM produced final text — consider the goal complete
                bus.publish(
                    GoalEvaluated(
                        session_id=session_id,
                        is_complete=True,
                        reasoning="LLM produced final text output",
                    )
                )

            if self._iteration_count >= self._max_iterations:
                bus.publish(
                    GoalEvaluated(
                        session_id=session_id,
                        is_complete=False,
                        reasoning=(
                            f"Reached max iterations ({self._max_iterations}) "
                            "without final text output"
                        ),
                    )
                )
                break
