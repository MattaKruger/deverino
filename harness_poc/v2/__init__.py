"""V2 Module — event-sourced layering + persona-driven materialization.

Exports the contracts (protocols), engines (ContextEngine + ExecutionEngine),
and workflow orchestrator.
This is the v2 event-sourced layering engine.
"""

from harness_poc.v2.context_engine import (
    ContextEngine,
    ContextEngineError,
    PedagogyNotFoundError,
    PersonaNotFoundError,
)
from harness_poc.v2.contracts import (
    DEFAULT_RENDER_MODE,
    # SubAgentSpawner
    DELEGATED_OUTPUT_BLOCKED,
    DELEGATED_OUTPUT_COMPLETED,
    DELEGATED_OUTPUT_FAILED,
    DELEGATED_STATUS_FAILED,
    DELEGATED_STATUS_SUCCESS,
    # EventRuntime
    DELEGATED_TO_EXTERNAL_STATUS,
    GOAL_STATUS_BLOCKED,
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_TIMEOUT,
    GOAL_STATUSES,
    GOAL_TO_DELEGATED_STATUS,
    GOAL_TO_EXTERNAL_STATUS,
    RENDER_MODES,
    # ContextMap
    ContextMapMaterializer,
    CorpusNotFoundError,
    DbContextMap,
    DelegatedTaskOutput,
    DelegatedTaskResult,
    MaterializationError,
    SubAgentSpawner,
    map_delegated_to_external,
    map_goal_status_to_delegated,
)
from harness_poc.v2.execution_engine import (
    ExecutionEngine,
    ExecutionEngineError,
    GateFailureError,
    SubAgentPoolFullError,
    TaskCancelledError,
    TaskNotFoundError,
    TaskNotCompleteError,
)
from harness_poc.v2.workflow_orchestrator import (
    ExecutionResult,
    GateRejectedError,
    GateResult,
    ProbeError,
    ProbeResult,
    SpecExecutionError,
    SubAgentResult,
    WorkflowError,
    WorkflowOrchestrator,
    WorkflowResult,
)

__all__ = [
    "DEFAULT_RENDER_MODE",
    # Contracts — SubAgentSpawner
    "DELEGATED_OUTPUT_BLOCKED",
    "DELEGATED_OUTPUT_COMPLETED",
    "DELEGATED_OUTPUT_FAILED",
    "DELEGATED_STATUS_FAILED",
    "DELEGATED_STATUS_SUCCESS",
    # Contracts — EventRuntime
    "DELEGATED_TO_EXTERNAL_STATUS",
    "GOAL_STATUSES",
    "GOAL_STATUS_BLOCKED",
    "GOAL_STATUS_COMPLETED",
    "GOAL_STATUS_FAILED",
    "GOAL_STATUS_TIMEOUT",
    "GOAL_TO_DELEGATED_STATUS",
    "GOAL_TO_EXTERNAL_STATUS",
    "RENDER_MODES",
    # Engines — Context
    "ContextEngine",
    "ContextEngineError",
    # Contracts — ContextMap
    "ContextMapMaterializer",
    "CorpusNotFoundError",
    "DbContextMap",
    "DelegatedTaskOutput",
    "DelegatedTaskResult",

    "SubAgentPoolFullError",
    "SubAgentResult",
    "TaskCancelledError",
    "TaskNotFoundError",
    "TaskNotCompleteError",
    "ExecutionResult",
    "GateFailureError",
    "GateRejectedError",
    "GateResult",
    "MaterializationError",
    "PedagogyNotFoundError",
    "PersonaNotFoundError",
    "ProbeError",
    "ProbeResult",
    "SpecExecutionError",
    "SubAgentPoolFullError",
    "SubAgentResult",
    "SubAgentSpawner",
    "WorkflowError",
    # Workflow Orchestrator
    "WorkflowOrchestrator",
    "WorkflowResult",
    "map_delegated_to_external",
    "map_goal_status_to_delegated",
]
