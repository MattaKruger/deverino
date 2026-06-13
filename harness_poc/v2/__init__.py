"""V2 Module — event-sourced layering + persona-driven materialization.

Exports the contracts (protocols), handlers (pipeline glue), engines
(ContextEngine + ExecutionEngine), and schemas (Event, MaterializedContext).

This is the implementation surface for planning_specv2.md.
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
    # Soul
    REQUIRED_SECTIONS,
    # ContextMap
    ContextMapMaterializer,
    CorpusNotFoundError,
    DbContextMap,
    DelegatedTaskOutput,
    DelegatedTaskResult,
    EventBus,
    EventHandler,
    EventStore,
    EventStoreError,
    Goal,
    GoalExecutionError,
    GoalResult,
    GoalRunner,
    MaterializationError,
    SoulConstitution,
    SoulIntegrityError,
    SubAgentSpawner,
    map_delegated_to_external,
    map_goal_status_to_delegated,
)
from harness_poc.v2.execution_engine import (
    ExecutionEngine,
    ExecutionEngineError,
    GateFailureError,
    SubAgentPoolFullError,
)
from harness_poc.v2.schemas import Event, MaterializedContext
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
    # Contracts — Soul
    "REQUIRED_SECTIONS",
    # Engines — Context
    "ContextEngine",
    "ContextEngineError",
    # Contracts — ContextMap
    "ContextMapMaterializer",
    "CorpusNotFoundError",
    "DbContextMap",
    "DelegatedTaskOutput",
    "DelegatedTaskResult",
    # Schemas
    "Event",
    "EventBus",
    "EventHandler",
    "EventStore",
    "EventStoreError",
    # Engines — Execution
    "ExecutionEngine",
    "ExecutionEngineError",
    "ExecutionResult",
    "GateFailureError",
    "GateRejectedError",
    "GateResult",
    "Goal",
    "GoalExecutionError",
    "GoalResult",
    "GoalRunner",
    "MaterializationError",
    "MaterializedContext",
    "PedagogyNotFoundError",
    "PersonaNotFoundError",
    "ProbeError",
    "ProbeResult",
    "SoulConstitution",
    "SoulIntegrityError",
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
