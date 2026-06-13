"""Event Runtime — status constants and mapping.

Single source of truth for the three-layer status mapping between
GoalRunner, DelegatedTaskResult, and external labels.

Status mapping summary:

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

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_FAILED = "failed"
GOAL_STATUS_BLOCKED = "blocked"
GOAL_STATUS_TIMEOUT = "timeout"

GOAL_STATUSES = frozenset(
    {
        GOAL_STATUS_COMPLETED,
        GOAL_STATUS_FAILED,
        GOAL_STATUS_BLOCKED,
        GOAL_STATUS_TIMEOUT,
    }
)

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
    "failed": "failed",  # Callers recover nuance via original_goal_status
}

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
        raise ValueError(msg)
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
        raise ValueError(msg)

    if delegated_status == "success":
        return "completed"

    # On failure, preserve the original nuance if available
    if original_goal_status is not None and original_goal_status in GOAL_TO_EXTERNAL_STATUS:
        return GOAL_TO_EXTERNAL_STATUS[original_goal_status]

    return "failed"
