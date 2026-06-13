"""WorkflowOrchestrator — Two-Mode Workflow: Exploration → Execution → Review.

Implements planning_specv2.md §3 lifecycle:
  Step #1: Fail-Fast Probe  — sandbox execution → failure → warm context map
  Step #2: Spec Execution   — spawn sub-agents (foreground + background)
  Step #3: Review Gate      — deterministic test suite → context refresh

The orchestrator wires ContextEngine and ExecutionEngine into a single
state-machine pipeline. On gate pass, the materialized context map is
refreshed to reflect only the "true" verified implementation state.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.v2.context_engine import ContextEngine
    from harness_poc.v2.execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class WorkflowError(RuntimeError):
    """Raised when the workflow orchestrator cannot complete an operation."""


class ProbeError(WorkflowError):
    """The fail-fast probe encountered an unrecoverable error."""


class SpecExecutionError(WorkflowError):
    """Spec execution failed — one or more sub-agents returned failure."""


class GateRejectedError(WorkflowError):
    """The deterministic review gate did not pass."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    """Result of Step #1: Fail-Fast Probe."""

    probe_id: str
    success: bool  # True = code ran clean (no constraints found)
    exit_code: int
    stdout: str
    stderr: str
    context_delta: dict[str, Any] = field(default_factory=dict)
    # Constraints discovered from the failure (if any)
    discovered_constraints: list[dict[str, str]] = field(default_factory=list)


@dataclass
class SubAgentResult:
    """Result of a single sub-agent spawned in Step #2."""

    task_id: str
    agent_type: str
    output_label: str  # completed | failed | blocked
    summary: str
    session_id: str
    background: bool = False


@dataclass
class ExecutionResult:
    """Aggregate result of Step #2: Spec Execution."""

    execution_id: str
    sub_agents: list[SubAgentResult] = field(default_factory=list)
    all_passed: bool = True
    failure_count: int = 0


@dataclass
class GateResult:
    """Result of Step #3: Deterministic Review Gate."""

    gate_id: str
    passed: bool
    test_count: int = 0
    output_summary: str = ""


@dataclass
class WorkflowResult:
    """Complete result of the two-mode workflow pipeline."""

    workflow_id: str
    probe: ProbeResult | None = None
    execution: ExecutionResult | None = None
    gate: GateResult | None = None
    # Which steps completed successfully
    steps_completed: list[str] = field(default_factory=list)
    # The final context map state (only populated after gate pass)
    context_map_refreshed: bool = False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class WorkflowOrchestrator:
    """Orchestrates the Exploration → Execution → Review lifecycle.

    Wires ContextEngine (context materialization) and ExecutionEngine
    (sub-agent dispatch + validation gate) into the three-step pipeline
    defined in planning_specv2.md §3.
    """

    def __init__(
        self,
        context_engine: ContextEngine,
        execution_engine: ExecutionEngine,
        *,
        sandbox_timeout_seconds: int = 30,
        project_id: str = "deverino",
    ) -> None:
        self._context = context_engine
        self._execution = execution_engine
        self._sandbox_timeout = sandbox_timeout_seconds
        self._project_id = project_id

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def execute_workflow(
        self,
        *,
        spec: dict[str, Any],
        persona_id: str,
        probe_code: str | None = None,
        workspace_path: str | None = None,
    ) -> WorkflowResult:
        """Run the complete two-mode workflow.

        Args:
            spec: The specification dict with keys:
                - probe: Optional code string for Step #1 sandbox probe
                - tasks: List of task dicts for Step #2 sub-agent dispatch
                - workspace: Optional workspace path for Step #3 gate
            persona_id: The persona to use for context materialization.
            probe_code: Code to execute in the sandbox probe (Step #1).
                If None, Step #1 is skipped.
            workspace_path: Path for the review gate (Step #3).
                If None, Step #3 is skipped.

        Returns:
            WorkflowResult with the outcome of all executed steps.
        """
        workflow_id = str(uuid.uuid4())
        result = WorkflowResult(workflow_id=workflow_id)
        session_id = str(uuid.uuid4())

        # ---- Step #1: Fail-Fast Probe (Exploration Mode) ----
        if probe_code is not None:
            probe = self.run_exploration_probe(
                code=probe_code,
                session_id=session_id,
            )
            result.probe = probe
            result.steps_completed.append("probe")

            if not probe.success:
                logger.info(
                    "Probe discovered %d constraints — context map warmed",
                    len(probe.discovered_constraints),
                )
            else:
                logger.info("Probe passed cleanly — no constraints discovered")

        # ---- Step #2: Spec Execution (Execution Mode) ----
        tasks = spec.get("tasks", [])
        if tasks:
            execution = self.run_spec_execution(
                tasks=tasks,
                session_id=session_id,
            )
            result.execution = execution
            result.steps_completed.append("execution")

            if not execution.all_passed:
                logger.warning(
                    "Spec execution: %d/%d sub-agents failed",
                    execution.failure_count,
                    len(execution.sub_agents),
                )

        # ---- Step #3: Deterministic Review Gate ----
        if workspace_path is not None:
            gate = self.run_review_gate(
                workspace_path=workspace_path,
                session_id=session_id,
            )
            result.gate = gate
            result.steps_completed.append("gate")

            if gate.passed:
                # Refresh context map to reflect verified state
                self._refresh_context_map(persona_id=persona_id)
                result.context_map_refreshed = True
                logger.info("Gate passed — context map refreshed to verified state")
            else:
                logger.warning("Gate rejected — context map NOT refreshed")

        return result

    def run_pipeline_via_bus(
        self,
        *,
        spec: dict[str, Any],
        persona_id: str,
        probe_code: str | None = None,
        workspace_path: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Run the pipeline via event bus subscriptions (event-driven mode).

        Constructs a ``PipelineStepRunner``, subscribes it to step boundary
        events, and publishes ``WORKFLOW_STARTED``. The pipeline then runs
        itself via event callbacks — zero further calls to the orchestrator.

        This is the Phase 2b event-driven equivalent of ``execute_workflow``.
        """
        from harness_poc.v2.subscribers.pipeline_runner import (  # noqa: PLC0415
            PipelineStepRunner,
        )

        workflow_id = str(uuid.uuid4())
        resolved_session = session_id or str(uuid.uuid4())
        tasks = spec.get("tasks", [])
        bus = self._execution._event_bus

        runner = PipelineStepRunner(self)

        # Register the runner on the bus for each step boundary event
        bus.subscribe("WORKFLOW_STARTED", runner.handle_workflow_started)
        bus.subscribe("PROBE_COMPLETED", runner.handle_probe_completed)
        bus.subscribe("EXECUTION_COMPLETED", runner.handle_execution_completed)

        # Kick off the pipeline
        bus.publish(
            "WORKFLOW_STARTED",
            {
                "session_id": resolved_session,
                "team_member": "orchestrator",
                "workflow_id": workflow_id,
                "goal": spec.get("goal", ""),
                "persona_id": persona_id,
                "probe_code": probe_code,
                "tasks": tasks,
                "workspace_path": workspace_path,
            },
        )

    # ------------------------------------------------------------------
    # Step #1: Fail-Fast Probe
    # ------------------------------------------------------------------

    def run_exploration_probe(
        self,
        code: str,
        *,
        session_id: str,
    ) -> ProbeResult:
        """Execute code in an isolated sandbox and capture failures.

        Deliberately allows the agent to fail, then extracts raw error
        details to warm up the context map with discovered constraints.

        Args:
            code: The Python code to execute in the sandbox.
            session_id: The orchestrator session identifier.

        Returns:
            ProbeResult with exit code, stdout, stderr, and any
            constraints discovered from the failure.
        """
        probe_id = str(uuid.uuid4())

        # Execute in an isolated temporary directory
        with tempfile.TemporaryDirectory(prefix="deverino-probe-") as sandbox_dir:
            script_path = Path(sandbox_dir) / "probe.py"
            script_path.write_text(code)

            try:
                proc = subprocess.run(
                    ["python", str(script_path)],
                    cwd=sandbox_dir,
                    capture_output=True,
                    text=True,
                    timeout=self._sandbox_timeout,
                )
                exit_code = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
            except subprocess.TimeoutExpired as exc:
                exit_code = -1
                stdout = exc.stdout or "" if exc.stdout else ""
                stderr = f"Probe timed out after {self._sandbox_timeout}s\n{exc.stderr or ''}"

        success = exit_code == 0

        if success:
            return ProbeResult(
                probe_id=probe_id,
                success=True,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )

        # Failure: extract constraints via ContextEngine
        execution_error = {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "traceback": _extract_traceback_lines(stderr),
        }

        context_delta = self._context.warm_up_context_from_failure(
            session_id=session_id,
            execution_error=execution_error,
        )

        return ProbeResult(
            probe_id=probe_id,
            success=False,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            context_delta=context_delta,
            discovered_constraints=context_delta.get("discovered_constraints", []),
        )

    # ------------------------------------------------------------------
    # Step #2: Spec Execution
    # ------------------------------------------------------------------

    def run_spec_execution(
        self,
        tasks: list[dict[str, Any]],
        *,
        session_id: str,
    ) -> ExecutionResult:
        """Spawn sub-agents for each task in the specification.

        Each task dict must have:
          - agent_type: The persona to use (e.g. "code_reviewer")
          - objective: What the sub-agent should accomplish
          - background (optional): If True, dispatch to background pool

        Args:
            tasks: List of task specifications.
            session_id: The orchestrator session identifier.

        Returns:
            ExecutionResult aggregating all sub-agent outcomes.
        """
        execution_id = str(uuid.uuid4())
        sub_results: list[SubAgentResult] = []
        failure_count = 0

        for task in tasks:
            agent_type = task.get("agent_type", "coder")
            background = task.get("background", False)

            try:
                raw = self._execution.spawn_sub_agent(
                    agent_type=agent_type,
                    task_payload=task,
                    background=background,
                    session_id=session_id,
                )
            except Exception as exc:
                logger.exception(
                    "Sub-agent spawn failed for type=%s: %s", agent_type, exc
                )
                sub_results.append(
                    SubAgentResult(
                        task_id="error",
                        agent_type=agent_type,
                        output_label="failed",
                        summary=f"Spawn error: {exc}",
                        session_id=session_id,
                        background=background,
                    )
                )
                failure_count += 1
                continue

            sub = SubAgentResult(
                task_id=raw["task_id"],
                agent_type=agent_type,
                output_label=raw["output_label"],
                summary=raw["summary"],
                session_id=raw["session_id"],
                background=background,
            )
            sub_results.append(sub)

            if raw["output_label"] != "completed":
                failure_count += 1

        # Publish SPEC_COMMITTED event via the execution engine's event bus
        self._execution._event_bus.publish(
            "SPEC_COMMITTED",
            {
                "session_id": session_id,
                "team_member": "orchestrator",
                "execution_id": execution_id,
                "task_count": len(tasks),
                "failure_count": failure_count,
                "all_passed": (failure_count == 0),
            },
        )

        return ExecutionResult(
            execution_id=execution_id,
            sub_agents=sub_results,
            all_passed=(failure_count == 0),
            failure_count=failure_count,
        )

    # ------------------------------------------------------------------
    # Step #3: Deterministic Review Gate
    # ------------------------------------------------------------------

    def run_review_gate(
        self,
        workspace_path: str,
        *,
        session_id: str,
    ) -> GateResult:
        """Execute the deterministic review gate.

        Runs the test suite against the workspace. On success, triggers
        a context map refresh so the materialized state reflects only
        the "true" verified implementation.

        Args:
            workspace_path: Absolute path to the workspace to validate.
            session_id: The orchestrator session identifier.

        Returns:
            GateResult with pass/fail status and test metadata.
        """
        gate_id = str(uuid.uuid4())

        try:
            passed = self._execution.execute_deterministic_gate(
                workspace_path=workspace_path,
                session_id=session_id,
            )
        except Exception as exc:
            logger.exception("Review gate raised: %s", exc)
            return GateResult(
                gate_id=gate_id,
                passed=False,
                output_summary=str(exc),
            )

        # Extract test count from the materialized map
        test_count = 0
        snapshot = self._execution._db.get_materialized_context_map(self._project_id)
        if snapshot:
            verified = snapshot.get("verified_state", {})
            test_count = verified.get("test_count", 0)

        return GateResult(
            gate_id=gate_id,
            passed=passed,
            test_count=test_count,
            output_summary="Gate passed" if passed else "Gate failed",
        )

    # ------------------------------------------------------------------
    # Context map refresh (post-gate loopback)
    # ------------------------------------------------------------------

    def _refresh_context_map(self, *, persona_id: str) -> None:
        """Refresh the materialized context map after a gate pass.

        This is the spec's "context refresh loop" — after verification
        success, the context map is re-materialized to reflect only the
        "true" implementation state.
        """
        try:
            self._context.materialize_context_map(
                working_context={"gate_passed": True, "phase": "verified"},
                persona_id=persona_id,
            )
        except Exception:
            logger.exception("Context map refresh failed after gate pass")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_traceback_lines(stderr: str) -> list[str]:
    """Extract traceback-relevant lines from stderr output.

    Returns the last 20 lines that look like traceback entries.
    """
    if not stderr:
        return []
    lines = stderr.strip().split("\n")
    # Keep lines that look like traceback entries or error messages
    tb_lines = [
        line
        for line in lines
        if any(
            marker in line
            for marker in (
                "Traceback",
                'File "',
                "Error",
                "Error:",
                "  ",
            )
        )
    ]
    return tb_lines[-20:]  # last 20 relevant lines
