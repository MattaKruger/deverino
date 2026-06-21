"""TraceContext — correlation IDs propagated through the call stack.

Uses ``contextvars.ContextVar`` which is safe across both threads and asyncio
tasks.  A new ``TraceContext`` is created at the start of each REPL input
handler and automatically flows into every logger call, skill execution,
LLM request, and database write triggered by that input.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(slots=True)
class TraceContext:
    """Correlation context for a single user interaction.

    Attributes:
        trace_id: Stable UUID for the entire user turn (REPL input → response).
        session_id: The harness session identifier.
        span_id: Rotating UUID — callers can bump this to delineate sub-operations
            (LLM call, skill execution, DB write) within the same trace.
    """

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def new_span(self) -> str:
        """Return a fresh span_id and update this context in-place."""
        self.span_id = str(uuid.uuid4())
        return self.span_id

    def as_extra(self) -> dict[str, str]:
        """Return a dict suitable for ``logger.debug(..., extra=ctx.as_extra())``."""
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "span_id": self.span_id,
        }


_current: ContextVar[TraceContext | None] = ContextVar("trace_ctx", default=None)


def current_trace() -> TraceContext | None:
    """Return the TraceContext for the current call stack, or None."""
    return _current.get()


def new_trace(session_id: str) -> TraceContext:
    """Create and set a new TraceContext for the current context.

    Args:
        session_id: The harness session identifier to include in all log lines.
    """
    ctx = TraceContext(session_id=session_id)
    _current.set(ctx)
    return ctx
