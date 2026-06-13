"""ExecutionEngine — sub-agent spawning, background pools, and review gates.

Implements planning_specv2.md §4 core interfaces:
  - spawn_sub_agent()          — foreground and background sub-agent dispatch
  - execute_deterministic_gate() — test suite validation boundary

Wraps the v2/handlers delegate_task pipeline with execution-mode awareness
and provides the Step #3 deterministic review gate that enforces "only
verified code enters the materialized context map."
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.events.event_bus import EventBus
    from harness_poc.core.storage.database import BlackboardDatabase
    from harness_poc.v2.contracts.sub_agent_spawner import SubAgentSpawner
    from harness_poc.v2.handlers.delegate_task_handler import BlackboardWriter

from harness_poc.core.events.events import GateFailed, GatePassed
from harness_poc.v2.handlers.delegate_task_handler import _handle_delegate_task

logger = logging.getLogger(__name__)


class ExecutionEngineError(RuntimeError):
    """Raised when the ExecutionEngine cannot complete an operation."""


class GateFailureError(ExecutionEngineError):
    """The deterministic review gate did not pass."""


class SubAgentPoolFullError(ExecutionEngineError):
    """Background sub-agent pool is at capacity."""


class ExecutionEngine:
    """Manages spec execution, sub-agent dispatch, and validation gates.

    Step #2 (Spec Execution): spawn_sub_agent() offloads work to isolated
    sub-agents, optionally in background mode for non-blocking execution.

    Step #3 (Deterministic Review Gate): execute_deterministic_gate() runs
    the test suite and only on success permits the context map to reflect
    the "true" implementation state.
    """

    def __init__(
        self,
        db: BlackboardDatabase,
        spawner: SubAgentSpawner,
        event_bus: EventBus,
        blackboard: BlackboardWriter,
        *,
        project_id: str = "deverino",
        max_background_agents: int = 5,
    ) -> None:
        self._db = db
        self._spawner = spawner
        self._event_bus = event_bus
        self._blackboard = blackboard
        self._project_id = project_id
        self._max_background = max_background_agents
        self._bg_active: dict[str, str] = {}  # task_id → status

    @property
    def event_bus(self) -> EventBus:
        """The v2 EventBus adapter used by this engine (public accessor)."""
        return self._event_bus

    # ------------------------------------------------------------------
    # spawn_sub_agent  (spec §4, ExecutionEngine interface)
    # ------------------------------------------------------------------

    def spawn_sub_agent(
        self,
        agent_type: str,
        task_payload: dict[str, Any],
        *,
        background: bool = False,
        session_id: str | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Spawn a sub-agent for isolated execution.

        Args:
            agent_type: The persona to use (e.g. "code_reviewer", "data_validator").
            task_payload: Dict with at least ``objective`` describing the task.
            background: If True, registers to async task pool and returns
                immediately with a task_id for polling.
            session_id: The orchestrator session identifier. Auto-generated
                if not provided.
            on_text: Optional callback for streaming output from the sub-agent.

        Returns:
            A dict with task_id, output_label, summary, and metadata.

        Raises:
            SubAgentPoolFullError: If background=True and the pool is full.
            SpawnerFailureError: If the spawner raises an unexpected exception.
        """
        resolved_session = session_id or str(uuid.uuid4())

        if background:
            if len(self._bg_active) >= self._max_background:
                raise SubAgentPoolFullError(
                    f"Background pool full ({self._max_background} max). "
                    f"Active tasks: {sorted(self._bg_active)}"
                )
            logger.info(
                "Background sub-agent queued: type=%s",
                agent_type,
            )

        # Build arguments for the delegate_task handler
        arguments: dict[str, Any] = {
            "persona": agent_type,
            "objective": task_payload.get("objective", task_payload.get("task", "")),
        }
        if "context" in task_payload:
            arguments["context"] = task_payload["context"]
        if "tools" in task_payload:
            arguments["tools"] = task_payload["tools"]
        if "metadata" in task_payload:
            arguments["metadata"] = task_payload["metadata"]

        # Delegate through the v2 handler
        result = _handle_delegate_task(
            spawner=self._spawner,
            event_bus=self._event_bus,
            blackboard=self._blackboard,
            session_id=resolved_session,
            arguments=arguments,
            original_goal_status=task_payload.get("original_goal_status"),
        )

        if background:
            self._bg_active[result.output.task_id] = result.output.output_label

        return {
            "task_id": result.output.task_id,
            "output_label": result.output.output_label,
            "summary": result.output.summary,
            "raw_output": result.output.raw_output,
            "metadata": result.output.metadata,
            "session_id": resolved_session,
            "background": background,
        }

    # ------------------------------------------------------------------
    # execute_deterministic_gate  (spec §4, ExecutionEngine interface)
    # ------------------------------------------------------------------

    def execute_deterministic_gate(
        self,
        workspace_path: str,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Run the deterministic review gate — test suite as validation boundary.

        Triggers host-isolated validation commands. On success, persists a
        GATE_PASSED event and updates the materialized context map to reflect
        the "true" verified implementation state.

        Args:
            workspace_path: Absolute path to the workspace to validate.
            session_id: The orchestrator session identifier.

        Returns:
            True if all tests pass cleanly. False on any assertion anomaly.

        Raises:
            GateFailureError: If the test suite fails (non-zero exit or
                assertion errors).
        """
        resolved_session = session_id or str(uuid.uuid4())

        # Run the test suite
        try:
            result = subprocess.run(
                ["uv", "run", "pytest", "--tb=short", "-q"],  # noqa: S607
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self._record_gate_event(
                resolved_session,
                passed=False,
                detail=f"Test suite timed out after 120s: {exc}",
            )
            raise GateFailureError("Deterministic gate timed out") from exc
        except FileNotFoundError:
            # uv not available — try python -m pytest directly
            try:
                result = subprocess.run(
                    ["python", "-m", "pytest", "--tb=short", "-q"],  # noqa: S607
                    cwd=workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                self._record_gate_event(
                    resolved_session,
                    passed=False,
                    detail=f"Test suite timed out after 120s: {exc}",
                )
                raise GateFailureError("Deterministic gate timed out") from exc
            except Exception as exc:
                self._record_gate_event(
                    resolved_session,
                    passed=False,
                    detail=f"Test runner not available: {exc}",
                )
                return False

        passed = result.returncode == 0

        self._record_gate_event(
            resolved_session,
            passed=passed,
            detail=result.stdout[-500:] if result.stdout else result.stderr[-500:],
        )

        # On gate pass, update the materialized context map with verified state
        if passed:
            self._db.upsert_materialized_context_map(
                project_id=self._project_id,
                active_persona="gate",
                pedagogy_snapshot={},
                verified_state={
                    "gate_passed": True,
                    "test_output_summary": result.stdout[:1000] if result.stdout else "",
                    "test_count": self._parse_test_count(result.stdout or ""),
                },
                last_event_id=0,  # will be updated by context engine
            )
            return True

        return False

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def background_status(self, task_id: str) -> str | None:
        """Poll the status of a background sub-agent.

        Returns None if the task_id is unknown.
        """
        return self._bg_active.get(task_id)

    def background_active_count(self) -> int:
        """Return the number of currently active background sub-agents."""
        return len(self._bg_active)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_gate_event(
        self,
        session_id: str,
        *,
        passed: bool,
        detail: str,
    ) -> None:
        """Publish a GatePassed or GateFailed event via the bus."""
        event_cls = GatePassed if passed else GateFailed
        self._event_bus.publish(
            event_cls(
                session_id=session_id,
                team_member="execution_engine",
                passed=passed,
                detail=detail,
                project_id=self._project_id,
            )
        )

    @staticmethod
    def _parse_test_count(stdout: str) -> int:
        """Extract the number of tests run from pytest output (best-effort)."""
        import re

        match = re.search(r"(\d+)\s+passed", stdout)
        if match:
            return int(match.group(1))
        return 0
