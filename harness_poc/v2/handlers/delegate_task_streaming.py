"""A3 — _handle_delegate_task_streaming.

Async streaming handler that mirrors A1's pipeline but uses
spawn_streaming for real-time output via on_text callback.

This is the implementation of Gap 10a from the spec-to-code gap analysis.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from harness_poc.v2.contracts import (
    DELEGATED_STATUS_SUCCESS,
    DelegatedTaskOutput,
    DelegatedTaskResult,
    EventBus,
    SubAgentSpawner,
    map_delegated_to_external,
)
from harness_poc.v2.handlers.delegate_task_handler import (
    REQUIRED_ARGS,
    BlackboardWriter,
    DelegateTaskResult,
    SpawnerFailureError,
    _build_task_spec,
    _validate_args,
)

# ---------------------------------------------------------------------------
# Core handler
# ---------------------------------------------------------------------------

async def _handle_delegate_task_streaming(
    *,
    spawner: SubAgentSpawner,
    event_bus: EventBus,
    blackboard: BlackboardWriter,
    session_id: str,
    arguments: dict[str, Any],
    original_goal_status: str | None = None,
    on_text: Callable[[str], None] | None = None,
) -> DelegateTaskResult:
    """Execute a delegated task with streaming output.

    Pipeline:
        1. Validate required arguments
        2. Build the task_spec dict
        3. Fire on_text("started")
        4. Await spawner.spawn_streaming(task_spec, on_text=on_text)
        5. Map DelegatedTaskResult → DelegatedTaskOutput
        6. Write to BlackboardDB
        7. Emit event on EventBus
        8. Fire on_text("completed"/"failed")
        9. Return DelegateTaskResult

    Args:
        spawner: Satisfies SubAgentSpawner protocol (must have spawn_streaming).
        event_bus: Satisfies EventBus protocol.
        blackboard: Satisfies BlackboardWriter protocol (test seam).
        session_id: The current agent session identifier.
        arguments: Dict with at least ``persona`` and ``objective``.
        original_goal_status: If the delegate_task originated from a
            GoalRunner goal, pass the original goal status here so
            "blocked" nuance is preserved in the output label.
        on_text: Optional callback for streaming output. Receives
            lifecycle events (started, completed, failed) and any
            incremental output from the spawner.

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

    # ---- Step 3: lifecycle — started ---------------------------------
    if on_text:
        on_text(
            f"[{task_spec['task_id']}] Started: "
            f"{task_spec['persona']} — {task_spec['objective']}"
        )

    # ---- Step 4: spawn streaming -------------------------------------
    try:
        raw: DelegatedTaskResult = await spawner.spawn_streaming(
            task_spec, on_text=on_text,
        )
    except Exception as exc:
        if on_text:
            on_text(f"[{task_spec['task_id']}] Error: {exc}")
        raise SpawnerFailureError(
            f"SubAgentSpawner.spawn_streaming() raised "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # ---- Step 5: map status → output label ---------------------------
    output_label = map_delegated_to_external(
        delegated_status=raw.status,
        original_goal_status=original_goal_status,
    )

    # ---- Step 6: build DelegatedTaskOutput ---------------------------
    output = DelegatedTaskOutput(
        task_id=raw.task_id,
        output_label=output_label,
        summary=_build_streaming_summary(raw),
        raw_output=raw.raw_output,
        metadata={
            "original_goal_status": original_goal_status,
            "delegated_status": raw.status,
        },
    )

    # ---- Step 7: write to blackboard ---------------------------------
    blackboard.write(task_id=raw.task_id, output=output)

    # ---- Step 8: emit event ------------------------------------------
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

    # ---- Step 9: lifecycle — completed/failed ------------------------
    if on_text:
        if raw.status == DELEGATED_STATUS_SUCCESS:
            on_text(f"[{raw.task_id}] Completed.")
        else:
            on_text(
                f"[{raw.task_id}] Failed: {raw.error or 'unknown error'}"
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

def _build_streaming_summary(raw: DelegatedTaskResult) -> str:
    """Build a human-readable one-line summary from the raw result."""
    if raw.status == DELEGATED_STATUS_SUCCESS:
        return f"Task {raw.task_id} completed successfully."
    err = raw.error or "unknown error"
    return f"Task {raw.task_id} failed: {err}"
