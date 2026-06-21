"""ToolContext — lightweight execution context for built-in tools.

Mirrors ``SkillContext`` but is designed for tool functions that
register in ``system_tools/``.  It carries only what tool code actually
uses: session identity, project layout, database access, and runtime
configuration.  No permissions model, no entrypoints, no streaming
callbacks — those are SkillRunner concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.config import RuntimeConfig

from harness_poc.core.skills import CancellationToken


class ToolDatabase(Protocol):
    """Database methods used by built-in tools."""

    def read_memory(self, session_id: str, key: str) -> dict[str, Any] | str | None: ...

    def list_memory_keys(self, session_id: str) -> list[str]: ...

    def write_memory(self, session_id: str, key: str, payload: str | dict[str, Any]) -> None: ...

    def get_all_corpus_keys(self) -> list[str]: ...

    def get_pending_corpus_keys(self) -> list[str]: ...

    def get_context_maps(self, corpus_keys: list[str]) -> dict[str, list[Any]]: ...

    def get_cycles(self, corpus_keys: list[str]) -> dict[str, int]: ...

    def get_corpus_inventory(self, corpus_key: str) -> dict[str, Any] | None: ...

    # ── Project / session state ──
    # Return types are `Any` to avoid circular imports (StatePayload).

    def ensure_project_state(self) -> Any: ...  # noqa: ANN401

    def read_project_state(self) -> Any | None: ...  # noqa: ANN401

    def ensure_session_state(self, session_id: str) -> Any: ...  # noqa: ANN401

    def read_session_state(self, session_id: str) -> Any | None: ...  # noqa: ANN401

    def append_session_state(self, session_id: str, section: str, text: str) -> Any: ...  # noqa: ANN401

    def set_project_fact(self, key: str, value: str) -> Any: ...  # noqa: ANN401

    def get_project_fact(self, key: str) -> str | None: ...


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
    database: ToolDatabase | None = None
    runtime_config: RuntimeConfig | None = None
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    system_prompt: str = ""

    @property
    def cancelled(self) -> bool:
        return self.cancellation.cancelled
