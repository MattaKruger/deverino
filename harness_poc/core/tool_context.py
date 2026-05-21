"""ToolContext — lightweight execution context for built-in tools.

Mirrors ``SkillContext`` but is designed for tool functions that
register in ``system_tools/``.  It carries only what tool code actually
uses: session identity, project layout, database access, and runtime
configuration.  No permissions model, no entrypoints, no streaming
callbacks — those are SkillRunner concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
    from harness_poc.core.config import RuntimeConfig

from harness_poc.core.skill_context import CancellationToken


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Execution context for ``system_tools/`` handler functions.

    Passed as the first positional argument to tools whose handlers
    have a ``ToolContext`` parameter.  ``ToolRunner`` constructs it
    from the session state and skips it for handlers that don't need
    one.
    """

    session_id: str
    project_root: Path
    database: BlackboardAccessProxy | None = None
    runtime_config: RuntimeConfig | None = None
    cancellation: CancellationToken = field(default_factory=CancellationToken)

    @property
    def cancelled(self) -> bool:
        return self.cancellation.cancelled
