"""ExecutionEngine -- sub-agent spawning, background pools, and review gates.

Implements v2 architecture core interfaces:
  - spawn_sub_agent()          -- foreground and background sub-agent dispatch
  - execute_deterministic_gate() -- test suite validation boundary.

Wraps the v2/handlers delegate_task pipeline with execution-mode awareness
and provides the Step #3 deterministic review gate that enforces "only
verified code enters the materialized context map."
"""

from __future__ import annotations

import logging
import subprocess
import threading
import uuid
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from harness_poc.core.events.event_bus import EventBus
    from harness_poc.core.storage.database import BlackboardDatabase
    from harness_poc.v2.contracts.sub_agent_spawner import SubAgentSpawner
    from harness_poc.v2.handlers.delegate_task_handler import BlackboardWriter

from harness_poc.core.events.events import GateFailed, GatePassed
from harness_poc.v2.handlers.delegate_task_handler import _handle_delegate_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class ExecutionEngineError(RuntimeError):
    """Raised when the ExecutionEngine cannot complete an operation."""


class GateFailureError(ExecutionEngineError):
    """The deterministic review gate did not pass."""


class SubAgentPoolFullError(ExecutionEngineError):
    """Background sub-agent pool is at capacity."""


class TaskNotCompleteError(ExecutionEngineError):
    """Result requested for a task that is still running."""


class TaskCancelledError(ExecutionEngineError):
    """Result requested for a task that was cancelled."""


class TaskNotFoundError(ExecutionEngineError):
    """No task found with the given task_id."""


# ---------------------------------------------------------------------------
# ExecutionEngine
# ---------------------------------------------------------------------------


class ExecutionEngine:
    """Manages spec execution, sub-agent dispatch, and validation gates.

    Step #2 (Spec Execution): spawn_sub_agent() offloads work to isolated
    sub-agents, optionally in background mode for non-blocking execution.

    Step #3 (Deterministic Review Gate): execute_deterministic_gate() runs
    the test suite and only on success permits the context map to reflect
    the "true" implementation state.
    """

    def __init__(  # noqa: PLR0913
        self,
        db: BlackboardDatabase,
        spawner: SubAgentSpawner,
        event_bus: EventBus,
        blackboard: BlackboardWriter,
        *,
        project_id: str = "deverino",
        max_background_agents: int = 8,
    ) -> None:
        self._db = db
        self._spawner = spawner
        self._event_bus = event_bus
        self._blackboard = blackboard
        self._project_id = project_id
        self._max_background = max_background_agents
        self._active_tasks: dict[str, threading.Thread] = {}  # task_id -> worker thread
        self._results_cache: dict[str, dict[str, Any]] = {}  # task_id -> completed result
        self._cancelled: set[str] = set()

    @property
    def event_bus(self) -> EventBus:
        """The v2 EventBus adapter used by this engine (public accessor)."""
        return self._event_bus

    # ------------------------------------------------------------------
    # spawn_sub_agent
    # ------------------------------------------------------------------

    def spawn_sub_agent(  # noqa: PLR0913
        self,
        agent_type: str,
        task_payload: dict[str, Any],
        *,
        mode: Literal["foreground", "background"] = "foreground",
        session_id: str | None = None,
        on_text: Callable[[str], None] | None = None,
        isolate_session: bool = False,
    ) -> dict[str, Any]:
        """Spawn a sub-agent for isolated execution.

        Args:
            agent_type: The persona to use (e.g. "code_reviewer", "data_validator").
            task_payload: Dict with at least ``objective`` describing the task.
            mode: "foreground" blocks until completion. "background" runs via
                a daemon thread and returns immediately with a task_id.
            session_id: The orchestrator session identifier. Auto-generated
                if not provided.
            on_text: Optional callback for streaming output from the sub-agent.
            isolate_session: If True, generate a sub_session_id for event isolation.

        Returns:
            A dict with task_id, output_label, summary, and metadata.

        Raises:
            SubAgentPoolFullError: If mode="background" and the pool is full.
        """
        resolved_session = session_id or str(uuid.uuid4())

        # Build arguments for the delegate_task handler (shared by both modes)
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
        # Auto-generate corpus_key for per-sub-agent context map isolation
        arguments["corpus_key"] = task_payload.get("corpus_key") or f"{self._project_id}:subagent:{agent_type}"
        if isolate_session:
            arguments["sub_session_id"] = str(uuid.uuid4())
        if on_text is not None:
            arguments["on_text"] = on_text
        if mode == "foreground":
            # Foreground: call handler synchronously, block until complete.
            result = _handle_delegate_task(
                spawner=self._spawner,
                event_bus=self._event_bus,
                blackboard=self._blackboard,
                session_id=resolved_session,
                arguments=arguments,
                original_goal_status=task_payload.get("original_goal_status"),
                db=self._db,
            )
            return {
                "task_id": result.output.task_id,
                "output_label": result.output.output_label,
                "summary": result.output.summary,
                "raw_output": result.output.raw_output,
                "metadata": result.output.metadata,
                "session_id": resolved_session,
                "background": False,
            }

        # Background mode: validate capacity, spawn daemon thread, return immediately.
        active_count = len(self._active_tasks) + len(self._results_cache)
        if active_count >= self._max_background:
            msg = (
                f"Background pool full ({self._max_background} max). "
                f"Active tasks: {sorted(set(self._active_tasks) | set(self._results_cache))}"
            )
            raise SubAgentPoolFullError(msg)

        task_id = arguments.get("task_id", str(uuid.uuid4()))
        arguments["task_id"] = task_id

        logger.info(
            "Background sub-agent queued: type=%s task_id=%s active=%d/%d",
            agent_type,
            task_id,
            active_count + 1,
            self._max_background,
        )

        thread = threading.Thread(
            target=self._run_background_task,
            args=(task_id, resolved_session, arguments, task_payload),
            daemon=True,
        )
        self._active_tasks[task_id] = thread
        thread.start()

        return {
            "task_id": task_id,
            "output_label": "running",
            "summary": f"Background task queued: {agent_type}",
            "raw_output": "",
            "metadata": {"agent_type": agent_type},
            "session_id": resolved_session,
            "background": True,
        }

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def status(self, task_id: str) -> str:
        """Return the status of a sub-agent task.

        Returns:
            "running" | "done" | "cancelled" | "unknown"
        """
        if task_id in self._cancelled:
            return "cancelled"
        if task_id in self._results_cache:
            return "done"
        if task_id in self._active_tasks and self._active_tasks[task_id].is_alive():
            return "running"
        return "unknown"

    def result(self, task_id: str) -> dict[str, Any]:
        """Retrieve the result of a completed sub-agent task.

        Removes the task from the results cache and active tracking on success.

        Raises:
            TaskNotCompleteError: If the task is still running.
            TaskCancelledError: If the task was cancelled.
            TaskNotFoundError: If the task_id is unknown.
        """
        current_status = self.status(task_id)
        if current_status == "unknown":
            msg = f"No task found with id '{task_id}'"
            raise TaskNotFoundError(msg)
        if current_status == "running":
            msg = f"Task '{task_id}' is still running"
            raise TaskNotCompleteError(msg)
        if current_status == "cancelled":
            msg = f"Task '{task_id}' was cancelled"
            raise TaskCancelledError(msg)

        result_dict = self._results_cache.pop(task_id)
        self._active_tasks.pop(task_id, None)
        return result_dict

    def cancel(self, task_id: str) -> bool:
        """Cancel a running background sub-agent.

        Marks the task as cancelled. The background thread continues to run
        but its result will be discarded. Use status() to check state.

        Returns:
            True if the task was cancelled, False if it was already completed.

        Raises:
            TaskNotFoundError: If the task_id is unknown.
        """
        current_status = self.status(task_id)
        if current_status == "unknown":
            msg = f"No task found with id '{task_id}'"
            raise TaskNotFoundError(msg)
        if current_status in ("done", "cancelled"):
            return False

        # Mark as cancelled, remove from active tracking
        self._cancelled.add(task_id)
        self._active_tasks.pop(task_id, None)
        self._results_cache.pop(task_id, None)
        return True

    def list_tasks(self) -> dict[str, dict[str, str]]:
        """Return all known background tasks with their status and summary.

        Returns:
            Dict mapping task_id to {"status": str, "persona": str, "summary": str}.
        """
        result: dict[str, dict[str, str]] = {}

        for task_id in self._cancelled:
            result[task_id] = {"status": "cancelled", "persona": "unknown", "summary": ""}

        for task_id, thread in self._active_tasks.items():
            status = "running" if thread.is_alive() else "done"
            result[task_id] = {"status": status, "persona": "unknown", "summary": ""}

        for task_id, cached in self._results_cache.items():
            result[task_id] = {
                "status": "done",
                "persona": cached.get("metadata", {}).get("agent_type", "unknown"),
                "summary": cached.get("summary", ""),
            }

        return result

    def _run_background_task(
        self,
        task_id: str,
        resolved_session: str,
        arguments: dict[str, Any],
        task_payload: dict[str, Any],
    ) -> None:
        """Execute a background sub-agent in a daemon thread.

        On completion, stores the result in ``_results_cache`` and removes
        the entry from ``_active_tasks``. If the task was cancelled mid-run,
        the result is discarded.
        """
        try:
            result = _handle_delegate_task(
                spawner=self._spawner,
                event_bus=self._event_bus,
                blackboard=self._blackboard,
                session_id=resolved_session,
                arguments=arguments,
                original_goal_status=task_payload.get("original_goal_status"),
                db=self._db,
            )
            output_dict = {
                "task_id": result.output.task_id,
                "output_label": result.output.output_label,
                "summary": result.output.summary,
                "raw_output": result.output.raw_output,
                "metadata": result.output.metadata,
                "session_id": resolved_session,
                "background": True,
            }
        except Exception:
            logger.exception("Background sub-agent %s failed", task_id)
            output_dict = {
                "task_id": task_id,
                "output_label": "failed",
                "summary": f"Background task {task_id} raised an exception",
                "raw_output": "",
                "metadata": {"agent_type": arguments.get("persona", "unknown")},
                "session_id": resolved_session,
                "background": True,
            }
        finally:
            if task_id in self._cancelled:
                # Task was cancelled mid-run -- discard result
                self._active_tasks.pop(task_id, None)
                logger.info(
                    "Background task %s completed but was cancelled -- result discarded",
                    task_id,
                )
            else:
                self._results_cache[task_id] = output_dict
                self._active_tasks.pop(task_id, None)
                logger.info(
                    "Background task %s completed with status=%s",
                    task_id,
                    output_dict["output_label"],
                )

    # ------------------------------------------------------------------
    # Legacy pool methods (backward compatibility)
    # ------------------------------------------------------------------

    def background_status(self, task_id: str) -> str | None:
        """Legacy: poll the status of a background sub-agent.

        Returns the output_label string, or None if unknown.
        """
        if task_id in self._cancelled:
            return "cancelled"
        if task_id in self._active_tasks:
            return "running"
        cached = self._results_cache.get(task_id)
        if cached is not None:
            return cached["output_label"]
        return None

    def background_active_count(self) -> int:
        """Return the number of currently active background sub-agents."""
        return len(self._active_tasks) + len(self._results_cache)

    # ------------------------------------------------------------------
    # execute_deterministic_gate
    # ------------------------------------------------------------------

    def execute_deterministic_gate(
        self,
        workspace_path: str,
        *,
        session_id: str | None = None,
    ) -> bool:
        """Run the deterministic review gate -- test suite as validation boundary.

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
            msg = "Deterministic gate timed out"
            raise GateFailureError(msg) from exc
        except FileNotFoundError:
            # uv not available -- try python -m pytest directly
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
                msg = "Deterministic gate timed out"
                raise GateFailureError(msg) from exc
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
        for line in stdout.splitlines():
            if " passed" in line or " failed" in line:
                try:
                    parts = line.strip().split()
                    for part in parts:
                        if part.isdigit():
                            return int(part)
                except (ValueError, IndexError):
                    pass
        return 0
