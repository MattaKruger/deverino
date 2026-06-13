"""Tool Result Handler — A2: _process_tool_result.

Processes raw tool results from delegated tasks. Handles three error branches:
  - Malformed input (missing fields, wrong types)
  - Timeout (task exceeded deadline)
  - Retryable failures (transient errors the caller can retry)

Also accepts already-constructed DelegatedTaskResult objects directly.
"""

from __future__ import annotations

from typing import Any

from harness_poc.v2.contracts import (
    DELEGATED_OUTPUT_COMPLETED,
    DELEGATED_OUTPUT_FAILED,
    DELEGATED_STATUS_FAILED,
    DELEGATED_STATUS_SUCCESS,
    DelegatedTaskOutput,
    DelegatedTaskResult,
    map_delegated_to_external,
)

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class ToolResultError(Exception):
    """Base exception for tool result processing failures."""


class MalformedToolResultError(ToolResultError):
    """The raw result does not conform to the expected shape."""

    def __init__(self, reason: str, raw: Any = None):
        self.reason = reason
        self.raw = raw
        super().__init__(f"Malformed tool result: {reason}")


class ToolTimeoutError(ToolResultError):
    """The tool call timed out."""

    def __init__(self, task_id: str, detail: str | None = None):
        self.task_id = task_id
        self.detail = detail
        msg = f"Tool '{task_id}' timed out"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class RetryableToolError(ToolResultError):
    """The tool call failed with a transient error that may succeed on retry."""

    def __init__(self, task_id: str, original_error: str):
        self.task_id = task_id
        self.original_error = original_error
        super().__init__(
            f"Tool '{task_id}' failed with retryable error: {original_error}"
        )


# ---------------------------------------------------------------------------
# Retryable error patterns
# ---------------------------------------------------------------------------

_RETRYABLE_PATTERNS: tuple[str, ...] = (
    "429",
    "503",
    "service unavailable",
    "rate limit",
    "too many requests",
    "connectionerror",
    "connection reset",
    "connection refused",
    "timeout",
    "temporary",
    "transient",
)


def _is_retryable(error_msg: str) -> bool:
    """Check whether an error message indicates a retryable failure."""
    if not error_msg:
        return False
    lowered = error_msg.lower()
    return any(pattern in lowered for pattern in _RETRYABLE_PATTERNS)


# ---------------------------------------------------------------------------
# Valid statuses accepted in raw results
# ---------------------------------------------------------------------------

_VALID_RAW_STATUSES: frozenset[str] = frozenset({
    DELEGATED_STATUS_SUCCESS,
    DELEGATED_STATUS_FAILED,
    "timeout",
})


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def _process_tool_result(
    raw_result: Any,
    *,
    original_goal_status: str | None = None,
) -> DelegatedTaskOutput:
    """Process a raw tool result into a DelegatedTaskOutput.

    Handles three error branches:
      - **Malformed**: raises MalformedToolResultError
      - **Timeout**: produces failed output with timed_out=True metadata
      - **Retryable**: raises RetryableToolError (caller should retry)
    """
    # Branch 0: already a DelegatedTaskResult
    if isinstance(raw_result, DelegatedTaskResult):
        return _from_delegated_task_result(raw_result, original_goal_status)

    # Branch 1: malformed (not dict-like)
    if not isinstance(raw_result, dict):
        raise MalformedToolResultError(
            f"Expected dict or DelegatedTaskResult, got {type(raw_result).__name__}",
            raw=raw_result,
        )

    # Branch 2: malformed (missing fields)
    task_id = raw_result.get("task_id")
    if task_id is None or not isinstance(task_id, str):
        raise MalformedToolResultError(
            "Missing or invalid 'task_id' field (must be a non-empty string)",
            raw=raw_result,
        )

    status = raw_result.get("status")
    if status is None or not isinstance(status, str):
        raise MalformedToolResultError(
            f"Missing or invalid 'status' field (must be a string, got {type(status).__name__})",
            raw=raw_result,
        )
    if status not in _VALID_RAW_STATUSES:
        raise MalformedToolResultError(
            f"Invalid status '{status}'. Expected one of {sorted(_VALID_RAW_STATUSES)}",
            raw=raw_result,
        )

    error_msg = raw_result.get("error")
    raw_output = raw_result.get("raw_output")

    # Branch 3: timeout
    if status == "timeout":
        return DelegatedTaskOutput(
            task_id=task_id,
            output_label=DELEGATED_OUTPUT_FAILED,
            summary=f"Task timed out: {error_msg or 'no detail provided'}",
            raw_output=raw_output,
            metadata={
                "raw_status": "timeout",
                "timed_out": True,
                "original_error": error_msg,
            },
        )

    # Branch 4: retryable failure
    if status == DELEGATED_STATUS_FAILED and error_msg and _is_retryable(error_msg):
        raise RetryableToolError(task_id, error_msg)

    # Branch 5: normal success/failure
    output_label = map_delegated_to_external(status, original_goal_status)

    return DelegatedTaskOutput(
        task_id=task_id,
        output_label=output_label,
        summary=_build_summary(status, output_label, error_msg),
        raw_output=raw_output,
        metadata={
            "raw_status": status,
            "original_error": error_msg,
            "original_goal_status": original_goal_status,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _from_delegated_task_result(
    dtr: DelegatedTaskResult,
    original_goal_status: str | None,
) -> DelegatedTaskOutput:
    """Convert an already-constructed DelegatedTaskResult to DelegatedTaskOutput."""
    output_label = map_delegated_to_external(dtr.status, original_goal_status)

    return DelegatedTaskOutput(
        task_id=dtr.task_id,
        output_label=output_label,
        summary=_build_summary(dtr.status, output_label, dtr.error),
        raw_output=dtr.raw_output,
        metadata={
            "raw_status": dtr.status,
            "original_error": dtr.error,
            "original_goal_status": original_goal_status,
        },
    )


def _build_summary(
    raw_status: str,
    output_label: str,
    error_msg: str | None,
) -> str:
    """Build a human-readable summary from the result components."""
    if output_label == DELEGATED_OUTPUT_COMPLETED:
        return "Task completed successfully."

    parts = [f"Task {output_label}"]
    if error_msg:
        parts.append(f"({error_msg})")
    return " ".join(parts)
