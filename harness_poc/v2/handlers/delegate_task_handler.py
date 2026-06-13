"""A1 — _handle_delegate_task.

Complete handler that receives a parsed delegation request, spawns a
sub-agent via SubAgentSpawner, maps the result through the canonical
status tables, writes to the BlackboardDB, and emits an event.

This is the implementation of Gap 2 from the spec-to-code gap analysis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from harness_poc.v2.contracts import (
    DELEGATED_STATUS_SUCCESS,
    DelegatedTaskOutput,
    DelegatedTaskResult,
    # Event bus
    EventBus,
    # Errors
    SubAgentSpawner,
    map_delegated_to_external,
)

# ---------------------------------------------------------------------------
# Blackboard write protocol (testability seam)
# ---------------------------------------------------------------------------

@runtime_checkable
class BlackboardWriter(Protocol):
    """Minimal write-side interface for the BlackboardDB.

    The real BlackboardDB is a SQLite-backed store; this protocol lets
    tests supply an in-memory spy without any database dependency.
    """

    def write(self, task_id: str, output: DelegatedTaskOutput, session_id: str) -> None:
        """Persist the output of a delegated task."""
        ...


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class DelegateTaskError(Exception):
    """Raised when _handle_delegate_task encounters a problem."""


class MalformedArgumentsError(DelegateTaskError, ValueError):
    """The arguments dict is missing required keys or has invalid values."""


class SpawnerFailureError(DelegateTaskError):
    """The SubAgentSpawner raised an unexpected exception."""


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------

@dataclass
class DelegateTaskResult:
    """Full result of handling a delegate_task call.

    Wraps the DelegatedTaskOutput with the original request context so
    the agent loop can route the result correctly.
    """

    output: DelegatedTaskOutput
    event_id: str
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Required arguments
# ---------------------------------------------------------------------------

REQUIRED_ARGS = frozenset({"persona", "objective"})


# ---------------------------------------------------------------------------
# Core handler
# ---------------------------------------------------------------------------

def _handle_delegate_task(
    *,
    spawner: SubAgentSpawner,
    event_bus: EventBus,
    blackboard: BlackboardWriter,
    session_id: str,
    arguments: dict[str, Any],
    original_goal_status: str | None = None,
) -> DelegateTaskResult:
    """Execute a delegated task end-to-end.

    Pipeline:
        1. Validate required arguments
        2. Build the task_spec dict for SubAgentSpawner.spawn()
        3. Spawn the sub-agent (synchronous path)
        4. Map the binary DelegatedTaskResult → DelegatedTaskOutput
           via the canonical map_delegated_to_external()
        5. Write DelegatedTaskOutput to the BlackboardDB
        6. Emit a "delegate_task_completed" event on the EventBus
        7. Return the composite DelegateTaskResult

    Args:
        spawner: Satisfies SubAgentSpawner protocol.
        event_bus: Satisfies EventBus protocol.
        blackboard: Satisfies BlackboardWriter protocol (test seam).
        session_id: The current agent session identifier.
        arguments: Dict with at least ``persona`` and ``objective``.
        original_goal_status: If the delegate_task originated from a
            GoalRunner goal, pass the original goal status here so
            "blocked" nuance is preserved in the output label.

    Returns:
        DelegateTaskResult wrapping the enriched output and event metadata.

    Raises:
        MalformedArgumentsError: If required arguments are missing.
        SpawnerFailureError: If the spawner raises an unexpected exception.
    """
    # ---- Step 1: validate arguments ----------------------------------
    _validate_args(arguments, REQUIRED_ARGS)

    # ---- Step 2: build task_spec ------------------------------------
    task_id = arguments.get("task_id", str(uuid.uuid4()))
    task_spec = _build_task_spec(task_id=task_id, arguments=arguments)

    # ---- Step 3: spawn ----------------------------------------------
    try:
        raw: DelegatedTaskResult = spawner.spawn(task_spec)
    except Exception as exc:
        raise SpawnerFailureError(
            f"SubAgentSpawner.spawn() raised {type(exc).__name__}: {exc}"
        ) from exc

    # ---- Step 4: map status → output label ---------------------------
    output_label = map_delegated_to_external(
        delegated_status=raw.status,
        original_goal_status=original_goal_status,
    )

    # ---- Step 5: build DelegatedTaskOutput ---------------------------
    output = DelegatedTaskOutput(
        task_id=raw.task_id,
        output_label=output_label,
        summary=_build_summary(raw),
        raw_output=raw.raw_output,
        metadata={
            "original_goal_status": original_goal_status,
            "delegated_status": raw.status,
        },
    )

    # ---- Step 6: write to blackboard ---------------------------------
    blackboard.write(task_id=raw.task_id, output=output, session_id=session_id)

    # ---- Step 7: emit event ------------------------------------------
    event_id = str(uuid.uuid4())
    event_bus.publish(
        "delegate_task_completed",
        {
            "event_id": event_id,
            "session_id": session_id,
            "task_id": raw.task_id,
            "output_label": output_label,
            "summary": output.summary,
        },
    )

    return DelegateTaskResult(
        output=output,
        event_id=event_id,
        session_id=session_id,
        metadata={
            "original_goal_status": original_goal_status,
            "delegated_status": raw.status,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_args(arguments: dict[str, Any], required: frozenset[str]) -> None:
    """Check that every required key is present and non-empty."""
    missing = [k for k in required if k not in arguments or not arguments[k]]
    if missing:
        raise MalformedArgumentsError(
            f"Missing required argument(s): {', '.join(missing)}"
        )


def _build_task_spec(*, task_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Construct the task_spec dict from the user-facing arguments."""
    return {
        "task_id": task_id,
        "persona": arguments["persona"],
        "objective": arguments["objective"],
        "context": arguments.get("context"),
        "tools": arguments.get("tools"),
        "metadata": arguments.get("metadata", {}),
    }


def _build_summary(raw: DelegatedTaskResult) -> str:
    """Build a human-readable one-line summary from the raw result."""
    if raw.status == DELEGATED_STATUS_SUCCESS:
        snippet = _truncate(raw.raw_output, 120)
        return f"Task {raw.task_id} completed. Output: {snippet}"
    err = raw.error or "unknown error"
    return f"Task {raw.task_id} failed: {err}"


def _truncate(value: Any, max_len: int) -> str:
    """Safe string truncation for summary generation."""
    if value is None:
        return "<no output>"
    s = str(value)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
