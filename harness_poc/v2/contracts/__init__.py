"""V2 Contracts — typed protocols for the four implemented components.

These protocols are the interfaces that ContextEngine and ExecutionEngine
depend on. Every contract is satisfied by existing Phase 1 implementations.
"""

from .context_map_pipeline import (
    DEFAULT_RENDER_MODE,
    RENDER_MODES,
    ContextMapMaterializer,
    CorpusNotFoundError,
    DbContextMap,
    MaterializationError,
)
from .event_runtime import (
    DELEGATED_TO_EXTERNAL_STATUS,
    GOAL_STATUS_BLOCKED,
    # Status constants
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_TIMEOUT,
    GOAL_STATUSES,
    # Status mapping
    GOAL_TO_DELEGATED_STATUS,
    GOAL_TO_EXTERNAL_STATUS,
    EventBus,
    # Event types
    EventHandler,
    # Protocols
    EventStore,
    EventStoreError,
    # Data types
    Goal,
    GoalExecutionError,
    GoalResult,
    GoalRunner,
    map_delegated_to_external,
    map_goal_status_to_delegated,
)
from .soul_constitution import (
    REQUIRED_SECTIONS,
    SoulConstitution,
    SoulIntegrityError,
)
from .sub_agent_spawner import (
    DELEGATED_OUTPUT_BLOCKED,
    DELEGATED_OUTPUT_COMPLETED,
    DELEGATED_OUTPUT_FAILED,
    DELEGATED_STATUS_FAILED,
    DELEGATED_STATUS_SUCCESS,
    DelegatedTaskOutput,
    DelegatedTaskResult,
    SubAgentSpawner,
)

__all__ = [
    "DEFAULT_RENDER_MODE",
    "DELEGATED_OUTPUT_BLOCKED",
    "DELEGATED_OUTPUT_COMPLETED",
    "DELEGATED_OUTPUT_FAILED",
    "DELEGATED_STATUS_FAILED",
    # SubAgentSpawner
    "DELEGATED_STATUS_SUCCESS",
    "DELEGATED_TO_EXTERNAL_STATUS",
    "GOAL_STATUSES",
    "GOAL_STATUS_BLOCKED",
    # EventRuntime — status
    "GOAL_STATUS_COMPLETED",
    "GOAL_STATUS_FAILED",
    "GOAL_STATUS_TIMEOUT",
    "GOAL_TO_DELEGATED_STATUS",
    "GOAL_TO_EXTERNAL_STATUS",
    "RENDER_MODES",
    # Soul
    "REQUIRED_SECTIONS",
    "ContextMapMaterializer",
    # ContextMap
    "CorpusNotFoundError",
    "DbContextMap",
    "DelegatedTaskOutput",
    "DelegatedTaskResult",
    "EventBus",
    # EventRuntime — protocols
    "EventHandler",
    "EventStore",
    "EventStoreError",
    # EventRuntime — data
    "Goal",
    "GoalExecutionError",
    "GoalResult",
    "GoalRunner",
    "MaterializationError",
    "SoulConstitution",
    "SoulIntegrityError",
    "SubAgentSpawner",
    "map_delegated_to_external",
    "map_goal_status_to_delegated",
]
