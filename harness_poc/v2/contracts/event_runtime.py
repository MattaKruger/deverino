"""Event Runtime — Contract 3 of 4.

The event runtime is the backbone for goal execution and delegation.
It defines the EventStore (persistence), EventBus (pub/sub), and
GoalRunner (execution) protocols, plus the canonical status enum
mapping between the three layers.

Phase 1 implementation: harness_poc/v1/event_runtime.py (EventRuntimeV1)

Status mapping summary (single source of truth):

    GoalRunner status  →  DelegatedTaskResult status  →  external label
    ─────────────────     ──────────────────────────     ─────────────
    "completed"        →  "success"                   →  "completed"
    "failed"           →  "failed"                    →  "failed"
    "blocked"          →  "failed"                    →  "blocked"
    "timeout"          →  "failed"                    →  "failed"

Rationale: DelegatedTaskResult only has success/failed (binary pass/fail
for the spawner). The external label recovers the original nuance for
the ExecutionEngine's user-facing report.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_FAILED = "failed"
GOAL_STATUS_BLOCKED = "blocked"
GOAL_STATUS_TIMEOUT = "timeout"

GOAL_STATUSES = frozenset({
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_BLOCKED,
    GOAL_STATUS_TIMEOUT,
})

# ---------------------------------------------------------------------------
# Status mapping — single source of truth
# ---------------------------------------------------------------------------

# GoalRunner status → DelegatedTaskResult status
GOAL_TO_DELEGATED_STATUS = {
    GOAL_STATUS_COMPLETED: "success",
    GOAL_STATUS_FAILED: "failed",
    GOAL_STATUS_BLOCKED: "failed",
    GOAL_STATUS_TIMEOUT: "failed",
}

# DelegatedTaskResult status → external label (for ExecutionEngine)
DELEGATED_TO_EXTERNAL_STATUS = {
    "success": "completed",
    "failed": "failed",       # for DelegatedTaskResult("failed"), you can't
}                             # distinguish blocked from failed — see below

# Direct GoalRunner status → external label (for non-delegated goals)
GOAL_TO_EXTERNAL_STATUS = {
    GOAL_STATUS_COMPLETED: "completed",
    GOAL_STATUS_FAILED: "failed",
    GOAL_STATUS_BLOCKED: "blocked",
    GOAL_STATUS_TIMEOUT: "failed",
}


def map_goal_status_to_delegated(goal_status: str) -> str:
    """Translate GoalRunner status to DelegatedTaskResult status.

    Raises ValueError if goal_status is not a known GOAL_STATUS_*.
    """
    if goal_status not in GOAL_STATUSES:
        msg = (
            f"Unknown goal status '{goal_status}'. "
            f"Expected one of {sorted(GOAL_STATUSES)}"
        )
        raise ValueError(
            msg
        )
    return GOAL_TO_DELEGATED_STATUS[goal_status]


def map_delegated_to_external(
    delegated_status: str,
    original_goal_status: str | None = None,
) -> str:
    """Translate DelegatedTaskResult status to external label.

    If original_goal_status is provided and delegated_status is "failed",
    the original nuance is recovered (e.g. "blocked" → "blocked").

    Args:
        delegated_status: "success" or "failed"
        original_goal_status: Optional original GoalRunner status for
                              nuance recovery on failure.

    Returns:
        External label string.

    Raises:
        ValueError if delegated_status is not "success" or "failed".
    """
    if delegated_status not in ("success", "failed"):
        msg = (
            f"Unknown delegated status '{delegated_status}'. "
            f"Expected 'success' or 'failed'."
        )
        raise ValueError(
            msg
        )
    if delegated_status == "success":
        return "completed"
    # On failure, recover original nuance if available
    if original_goal_status in GOAL_STATUSES:
        return GOAL_TO_EXTERNAL_STATUS[original_goal_status]
    return "failed"


# ---------------------------------------------------------------------------
# Event handler type
# ---------------------------------------------------------------------------

EventHandler = Callable[[str, dict[str, Any]], None]
"""An event handler receives (event_type: str, payload: dict)."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EventStoreError(RuntimeError):
    """Raised when the EventStore cannot complete an operation."""


class GoalExecutionError(RuntimeError):
    """Raised when a GoalRunner fails to execute a goal.

    Attributes:
        goal: The Goal that was being executed.
        reason: Human-readable explanation.
    """

    def __init__(self, goal: Goal, reason: str) -> None:
        self.goal = goal
        self.reason = reason
        super().__init__(f"Goal '{goal.goal_id}' failed: {reason}")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Goal:
    """A unit of work to be executed by a GoalRunner."""

    goal_id: str
    description: str
    status: str = GOAL_STATUS_COMPLETED  # current status
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.goal_id:
            msg = "Goal.goal_id must not be empty"
            raise ValueError(msg)


@dataclass
class GoalResult:
    """The result of executing a Goal."""

    goal_id: str
    status: str  # one of GOAL_STATUSES
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in GOAL_STATUSES:
            msg = (
                f"GoalResult.status must be one of {sorted(GOAL_STATUSES)}, "
                f"got '{self.status}'"
            )
            raise ValueError(
                msg
            )


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class EventStore(Protocol):
    """Durable append-only log of events with query support.

    Implementations MUST support the context-manager protocol so that
    callers can guarantee connection cleanup:

        with event_store as store:
            store.append(...)
    """

    def initialize(self, db_path: str) -> None:
        """Open or create the event database at db_path.

        Must be called before append/query. Idempotent — calling
        initialize on an already-initialized store is safe.
        """
        ...

    def close(self) -> None:
        """Release the underlying connection/resources.

        Safe to call multiple times. After close(), the store may be
        re-initialized with a different path.
        """
        ...

    def append(self, event_type: str, payload: dict[str, Any]) -> str:
        """Persist an event and return its event_id."""
        ...

    def query(
        self,
        event_type: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return events matching the filter."""
        ...

    def __enter__(self) -> EventStore:
        """Enter the runtime context."""
        ...

    def __exit__(self, *args: Any) -> None:  # noqa: ANN401
        """Exit the runtime context, calling close()."""
        ...


@runtime_checkable
class EventBus(Protocol):
    """In-process pub/sub for live events."""

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        ...

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler."""
        ...

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Deliver an event to all subscribers synchronously."""
        ...


@runtime_checkable
class GoalRunner(Protocol):
    """Executes a Goal and returns a GoalResult.

    Implementation is expected to be a thin wrapper around the LLM loop:
    it receives a Goal, runs the agent cycle, and reports the outcome.
    """

    def run(self, goal: Goal) -> GoalResult:
        """Execute a goal synchronously."""
        ...

    async def run_async(self, goal: Goal) -> GoalResult:
        """Execute a goal asynchronously."""
        ...
