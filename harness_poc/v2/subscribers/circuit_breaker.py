"""CircuitBreaker — v2 ReAct subscriber for budget enforcement.

Tracks consecutive skill failures and cumulative token usage via the v1 EventBus;
publishes StreamPaused when thresholds are breached.
"""

from __future__ import annotations

import logging
from typing import Any

from harness_poc.core.events.events import (
    LLMActionEmitted,
    SkillCompleted,
    StreamPaused,
)

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """ReAct circuit breaker — enforces failure and token budgets.

    Listens via async session subscription for SkillCompleted and
    LLMActionEmitted events. Publishes StreamPaused when:
    - Consecutive skill failures exceed ``max_retries``
    - Cumulative token usage exceeds ``max_tokens``
    """

    def __init__(self, *, max_retries: int = 3, max_tokens: int = 100_000) -> None:
        self._max_retries = max_retries
        self._max_tokens = max_tokens

    async def run(self, bus: Any, session_id: str) -> None:
        """Run the circuit breaker loop for a session."""
        consecutive_failures = 0
        total_tokens = 0

        async for event in bus.subscribe_session(session_id):
            if isinstance(event, StreamPaused):
                break

            pause_reason: str | None = None
            pause_threshold: str = ""

            if isinstance(event, SkillCompleted):
                if event.status == "failed":
                    consecutive_failures += 1
                elif event.status == "success":
                    consecutive_failures = 0

                if consecutive_failures > self._max_retries:
                    pause_reason = "consecutive_failures"
                    pause_threshold = str(self._max_retries)

            if isinstance(event, LLMActionEmitted):
                total_tokens += event.tokens_used
                if total_tokens > self._max_tokens:
                    pause_reason = "budget_exhausted"
                    pause_threshold = str(self._max_tokens)

            if pause_reason is not None:
                bus.publish(
                    StreamPaused(
                        session_id=session_id,
                        reason=pause_reason,
                        threshold_breached=pause_threshold,
                    )
                )
                break
