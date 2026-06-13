"""CircuitBreaker — v2 ReAct subscriber for budget enforcement.

Ports ``harness_poc.core.processors.circuit_breaker.run_circuit_breaker`` to
the v2 event bus. Tracks consecutive skill failures and cumulative token usage;
publishes ``STREAM_PAUSED`` when thresholds are breached.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """ReAct circuit breaker — enforces failure and token budgets.

    Listens via async session subscription for ``TOOL_COMPLETED`` and
    ``LLM_ACTION_EMITTED`` events. Publishes ``STREAM_PAUSED`` when:
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

        async for envelope in bus.subscribe_session(session_id):
            event_type: str = envelope["event_type"]
            payload: dict[str, Any] = envelope["payload"]

            if event_type == "STREAM_PAUSED":
                break

            pause_reason: str | None = None
            pause_threshold: str = ""

            if event_type == "TOOL_COMPLETED":
                status = payload.get("status", "unknown")
                if status == "failed":
                    consecutive_failures += 1
                elif status == "success":
                    consecutive_failures = 0

                if consecutive_failures > self._max_retries:
                    pause_reason = "consecutive_failures"
                    pause_threshold = str(self._max_retries)

            if event_type == "LLM_ACTION_EMITTED":
                total_tokens += payload.get("tokens_used", 0)
                if total_tokens > self._max_tokens:
                    pause_reason = "budget_exhausted"
                    pause_threshold = str(self._max_tokens)

            if pause_reason is not None:
                bus.publish(
                    "STREAM_PAUSED",
                    {
                        "session_id": session_id,
                        "team_member": "circuit_breaker",
                        "reason": pause_reason,
                        "threshold_breached": pause_threshold,
                    },
                )
                break
