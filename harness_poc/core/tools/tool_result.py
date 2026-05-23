"""ToolResult — the return type for built-in (LLM-callable) tools.

Mirrors ``SkillResult`` in shape (status, content, artifacts) but omits
``requested_actions`` — tools are primitives that do work and return,
they don't chain-spawn additional work like delegate_task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ToolStatus = Literal["success", "failed"]


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: ToolStatus
    content: str
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "content": self.content,
            "artifacts": self.artifacts,
        }
