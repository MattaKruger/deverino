"""V2 Contracts — typed protocols for the three implemented components.

These protocols are the interfaces that ContextEngine and ExecutionEngine
depend on. The event runtime contracts (EventBus, EventStore, GoalRunner)
are satisfied by v1 implementations directly.
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
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_TIMEOUT,
    GOAL_STATUSES,
    GOAL_TO_DELEGATED_STATUS,
    GOAL_TO_EXTERNAL_STATUS,
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
    "DELEGATED_STATUS_SUCCESS",
    "DELEGATED_TO_EXTERNAL_STATUS",
    "GOAL_STATUSES",
    "GOAL_STATUS_BLOCKED",
    "GOAL_STATUS_COMPLETED",
    "GOAL_STATUS_FAILED",
    "GOAL_STATUS_TIMEOUT",
    "GOAL_TO_DELEGATED_STATUS",
    "GOAL_TO_EXTERNAL_STATUS",
    "RENDER_MODES",
    "REQUIRED_SECTIONS",
    "ContextMapMaterializer",
    "CorpusNotFoundError",
    "DbContextMap",
    "DelegatedTaskOutput",
    "DelegatedTaskResult",
    "MaterializationError",
    "SoulConstitution",
    "SoulIntegrityError",
    "SubAgentSpawner",
    "map_delegated_to_external",
    "map_goal_status_to_delegated",
]
