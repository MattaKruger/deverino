"""Pipeline subscriber — event-driven pipeline execution.

Extracts the 3-step pipeline (Probe → Execute → Gate) from the monolithic
``WorkflowOrchestrator.execute_workflow`` into a ``PipelineStepRunner`` that
reacts to events on the v2 EventBus.

The orchestrator becomes a thin factory: it constructs the runner, registers it
on the bus, and publishes ``WORKFLOW_STARTED``. The pipeline then runs itself
via event callbacks through the orchestrator's existing step methods.

Step counters prevent re-entrancy: each handler fires at most once per event
type, then unsubscribes. This avoids infinite recursion when a subscriber
publishes events it's also subscribed to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.v2.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)


class PipelineStepRunner:
    """Runs the 3-step pipeline via event subscriptions.

    Delegates each step to the ``WorkflowOrchestrator``'s existing methods
    (``run_exploration_probe``, ``run_spec_execution``, ``run_review_gate``).
    The orchestrator is not modified — it still owns the step implementations.

    The runner is registered as a subscriber on the v2 EventBus. Publishing
    ``WORKFLOW_STARTED`` triggers the full chain.
    """

    def __init__(self, orchestrator: WorkflowOrchestrator) -> None:
        self._orch = orchestrator
        # Step counters guard against re-entrancy (max 1 fire per handler)
        self._fired: set[str] = set()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_workflow_started(
        self, _event_type: str, payload: dict[str, Any]
    ) -> None:
        """WORKFLOW_STARTED → run fail-fast probe (Step #1)."""
        if "WORKFLOW_STARTED" in self._fired:
            return
        self._fired.add("WORKFLOW_STARTED")

        session_id = payload.get("session_id", "v2-runtime")
        workflow_id = payload.get("workflow_id", "unknown")
        probe_code = payload.get("probe_code")

        if probe_code is not None:
            probe = self._orch.run_exploration_probe(
                code=probe_code, session_id=session_id
            )
            probe_data = {
                "probe_id": probe.probe_id,
                "success": probe.success,
                "exit_code": probe.exit_code,
                "constraints": probe.discovered_constraints,
            }
        else:
            probe_data = {
                "probe_id": None,
                "success": True,
                "exit_code": 0,
                "constraints": [],
            }

        self._orch._execution._event_bus.publish(
            "PROBE_COMPLETED",
            {
                "session_id": session_id,
                "team_member": "pipeline_runner",
                "workflow_id": workflow_id,
                **probe_data,
                "tasks": payload.get("tasks", []),
                "workspace_path": payload.get("workspace_path"),
            },
        )

    def handle_probe_completed(
        self, _event_type: str, payload: dict[str, Any]
    ) -> None:
        """PROBE_COMPLETED → run spec execution (Step #2)."""
        if "PROBE_COMPLETED" in self._fired:
            return
        self._fired.add("PROBE_COMPLETED")

        session_id = payload.get("session_id", "v2-runtime")
        workflow_id = payload.get("workflow_id", "unknown")
        tasks = payload.get("tasks", [])

        if tasks:
            execution = self._orch.run_spec_execution(
                tasks=tasks, session_id=session_id
            )
            exec_data = {
                "execution_id": execution.execution_id,
                "sub_agents": [
                    {
                        "task_id": a.task_id,
                        "agent_type": a.agent_type,
                        "output_label": a.output_label,
                    }
                    for a in execution.sub_agents
                ],
                "all_passed": execution.all_passed,
            }
        else:
            exec_data = {
                "execution_id": None,
                "sub_agents": [],
                "all_passed": True,
            }

        self._orch._execution._event_bus.publish(
            "EXECUTION_COMPLETED",
            {
                "session_id": session_id,
                "team_member": "pipeline_runner",
                "workflow_id": workflow_id,
                **exec_data,
                "workspace_path": payload.get("workspace_path"),
            },
        )

    def handle_execution_completed(
        self, _event_type: str, payload: dict[str, Any]
    ) -> None:
        """EXECUTION_COMPLETED → run review gate (Step #3)."""
        if "EXECUTION_COMPLETED" in self._fired:
            return
        self._fired.add("EXECUTION_COMPLETED")

        session_id = payload.get("session_id", "v2-runtime")
        workflow_id = payload.get("workflow_id", "unknown")
        workspace_path = payload.get("workspace_path")

        if workspace_path is not None:
            gate = self._orch.run_review_gate(
                workspace_path=workspace_path, session_id=session_id
            )
            gate_data = {
                "gate_id": gate.gate_id,
                "passed": gate.passed,
                "test_count": gate.test_count,
            }
        else:
            gate_data = {
                "gate_id": None,
                "passed": True,
                "test_count": 0,
            }

        self._orch._execution._event_bus.publish(
            "GATE_COMPLETED",
            {
                "session_id": session_id,
                "team_member": "pipeline_runner",
                "workflow_id": workflow_id,
                **gate_data,
            },
        )
