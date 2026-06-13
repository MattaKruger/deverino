"""Sub-Agent Spawner — Contract 4 of 4.

Manages the lifecycle of delegated sub-agents: spawn, monitor, collect
results. This is the boundary between ExecutionEngine and the outside
world (other LLM sessions, tool calls, etc.).

Phase 1 implementation: harness_poc/v1/sub_agent_spawner.py (SubAgentSpawnerV1)

Status mapping (see event_runtime.py for the canonical mapping):

    DelegatedTaskResult uses binary "success" / "failed".
    DelegatedTaskOutput uses ternary "completed" / "failed" / "blocked"
    for user-facing display.

The mapping from DelegatedTaskResult → DelegatedTaskOutput is:
    "success" → DELEGATED_OUTPUT_COMPLETED
    "failed"  → DELEGATED_OUTPUT_FAILED   (then caller can refine to BLOCKED
                                            if original goal was "blocked")
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

DELEGATED_STATUS_SUCCESS = "success"
DELEGATED_STATUS_FAILED = "failed"

DELEGATED_OUTPUT_COMPLETED = "completed"
DELEGATED_OUTPUT_FAILED = "failed"
DELEGATED_OUTPUT_BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DelegatedTaskResult:
    """Binary result returned by the spawner infrastructure.

    This is the raw result from the delegation mechanism (API call,
    subprocess, tool invocation). It uses binary success/failed because
    the spawner only knows whether the call succeeded — not the semantic
    nuance of the goal's outcome.
    """

    task_id: str
    status: str  # "success" or "failed"
    raw_output: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in (DELEGATED_STATUS_SUCCESS, DELEGATED_STATUS_FAILED):
            msg = (
                f"DelegatedTaskResult.status must be "
                f"'{DELEGATED_STATUS_SUCCESS}' or '{DELEGATED_STATUS_FAILED}', "
                f"got '{self.status}'"
            )
            raise ValueError(
                msg
            )


@dataclass
class DelegatedTaskOutput:
    """Enriched output for the ExecutionEngine's user-facing report.

    Created by converting a DelegatedTaskResult through the status
    mapping, optionally recovering original goal status nuance.
    """

    task_id: str
    output_label: str  # DELEGATED_OUTPUT_COMPLETED / FAILED / BLOCKED
    summary: str
    raw_output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid = {
            DELEGATED_OUTPUT_COMPLETED,
            DELEGATED_OUTPUT_FAILED,
            DELEGATED_OUTPUT_BLOCKED,
        }
        if self.output_label not in valid:
            msg = (
                f"DelegatedTaskOutput.output_label must be one of "
                f"{sorted(valid)}, got '{self.output_label}'"
            )
            raise ValueError(
                msg
            )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class SubAgentSpawner(Protocol):
    """Spawns and manages delegated sub-agents.

    The spawner abstracts over the delegation mechanism (tool call,
    subprocess, API call to another LLM session). It returns a binary
    DelegatedTaskResult; the ExecutionEngine is responsible for mapping
    that to a user-facing DelegatedTaskOutput using the canonical status
    mapping in event_runtime.py.
    """

    def spawn(self, task_spec: dict[str, Any]) -> DelegatedTaskResult:
        """Spawn a sub-agent and block until completion.

        Args:
            task_spec: A dict describing the task (goal, context, tools).

        Returns:
            DelegatedTaskResult with binary success/failed status.
        """
        ...

    async def spawn_async(self, task_spec: dict[str, Any]) -> DelegatedTaskResult:
        """Spawn a sub-agent asynchronously."""
        ...

    async def spawn_streaming(
        self,
        task_spec: dict[str, Any],
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> DelegatedTaskResult:
        """Spawn a sub-agent asynchronously with streaming output.

        The ``on_text`` callback receives incremental output as the
        sub-agent executes, enabling real-time streaming to the user.
        Lifecycle events (started, completed, failed) are emitted by
        the caller (e.g. delegate_task_streaming handler), not by the
        spawner itself.

        Args:
            task_spec: A dict describing the task (goal, context, tools).
            on_text: Optional callback for incremental output. If None,
                the spawner may skip streaming and return the full result.

        Returns:
            DelegatedTaskResult with binary success/failed status.
        """
        ...

    def status(self, task_id: str) -> DelegatedTaskResult | None:
        """Poll the status of a previously spawned task.

        Returns None if the task_id is unknown.
        """
        ...
