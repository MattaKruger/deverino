"""V2 runtime — typed container for mode-specific engines and subscribers.

Replaces the ad-hoc dict returned by ``build_v2_runtime`` with a single
dataclass that holds whichever engines/subscribers are relevant for the
active mode.  Callers branch on ``.mode`` and access the corresponding
fields directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness_poc.core.events.event_bus import EventBus
    from harness_poc.v2.context_engine import ContextEngine
    from harness_poc.v2.execution_engine import ExecutionEngine
    from harness_poc.v2.subscribers.circuit_breaker import CircuitBreaker
    from harness_poc.v2.subscribers.goal_evaluator import GoalEvaluator
    from harness_poc.v2.subscribers.llm_worker import LlmWorker
    from harness_poc.v2.subscribers.tool_worker import ToolWorker
    from harness_poc.v2.workflow_orchestrator import WorkflowOrchestrator


@dataclass(slots=True)
class V2Runtime:
    """Container for a v2 mode's engines and subscribers.

    Every instance has a ``.bus`` (the shared v1 ``EventBus``).  The
    remaining fields are populated based on ``.mode``:

    * ``"pipeline"`` → ``context_engine``, ``execution_engine``, ``orchestrator``
    * ``"react"``    → ``llm_worker``, ``tool_worker``, ``circuit_breaker``, ``goal_evaluator``
    """

    mode: str
    bus: EventBus

    # Pipeline mode
    context_engine: ContextEngine | None = None
    execution_engine: ExecutionEngine | None = None
    orchestrator: WorkflowOrchestrator | None = None

    # ReAct mode
    llm_worker: LlmWorker | None = None
    tool_worker: ToolWorker | None = None
    circuit_breaker: CircuitBreaker | None = None
    goal_evaluator: GoalEvaluator | None = None
