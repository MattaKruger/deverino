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

from harness_poc.core.events.events import (
    ExecutionCompleted,
    GateCompleted,
    ProbeCompleted,
)

if TYPE_CHECKING:
    from harness_poc.core.events.events import (
        WorkflowStarted,
    )
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

    def __init__(
        self,
        orchestrator: WorkflowOrchestrator,
        event_bus: Any,  # noqa: ANN401
    ) -> None:
        self._orch = orchestrator
        self._bus = event_bus
        self._fired: set[str] = set()
        self._subscription_id: str | None = None
        self._workflow_id: str | None = None
        self._persona_id: str = "coder"
    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_workflow_started(self, event: WorkflowStarted) -> None:
        """WorkflowStarted → run fail-fast probe (Step #1)."""
        fired_key = event.__class__.__name__
        if fired_key in self._fired:
            return
        self._fired.add(fired_key)

        session_id = event.session_id
        workflow_id = event.workflow_id
        self._workflow_id = workflow_id
        self._persona_id = event.persona_id or "coder"
        probe_code = event.probe_code

        if probe_code is not None:
            probe = self._orch.run_exploration_probe(
                code=probe_code, session_id=session_id
            )
            probe_id = probe.probe_id
            success = probe.success
            exit_code = probe.exit_code
            constraints = probe.discovered_constraints
        else:
            probe_id = None
            success = True
            exit_code = 0
            constraints = []

        self._bus.publish(
            ProbeCompleted(
                session_id=session_id,
                workflow_id=workflow_id,
                probe_id=probe_id,
                success=success,
                exit_code=exit_code,
                constraints=constraints,
                tasks=event.tasks,
                workspace_path=event.workspace_path,
            )
        )

    def handle_probe_completed(self, event: ProbeCompleted) -> None:
        """ProbeCompleted → run spec execution (Step #2)."""
        fired_key = event.__class__.__name__
        if fired_key in self._fired:
            return
        self._fired.add(fired_key)

        session_id = event.session_id
        workflow_id = event.workflow_id
        tasks = event.tasks

        if tasks:
            execution = self._orch.run_spec_execution(
                tasks=tasks, session_id=session_id
            )
            execution_id = execution.execution_id
            sub_agents = [
                {
                    "task_id": a.task_id,
                    "agent_type": a.agent_type,
                    "output_label": a.output_label,
                }
                for a in execution.sub_agents
            ]
            all_passed = execution.all_passed
        else:
            execution_id = None
            sub_agents = []
            all_passed = True

        self._bus.publish(
            ExecutionCompleted(
                session_id=session_id,
                workflow_id=workflow_id,
                execution_id=execution_id,
                sub_agents=sub_agents,
                all_passed=all_passed,
                workspace_path=event.workspace_path,
            )
        )

    def handle_execution_completed(self, event: ExecutionCompleted) -> None:
        """ExecutionCompleted → run review gate (Step #3)."""
        fired_key = event.__class__.__name__
        if fired_key in self._fired:
            return
        self._fired.add(fired_key)

        session_id = event.session_id
        workflow_id = event.workflow_id
        workspace_path = event.workspace_path

        if workspace_path is not None:
            gate = self._orch.run_review_gate(
                workspace_path=workspace_path, session_id=session_id
            )
            gate_id = gate.gate_id
            passed = gate.passed
            if passed:
                self._orch._refresh_context_map(persona_id=self._persona_id)  # noqa: SLF001
            test_count = gate.test_count
        else:
            gate_id = None
            passed = True
            test_count = 0

        self._bus.publish(
            GateCompleted(
                session_id=session_id,
                workflow_id=workflow_id,
                gate_id=gate_id,
                passed=passed,
                test_count=test_count,
            )
        )
