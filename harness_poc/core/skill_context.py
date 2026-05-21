from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from harness_poc.core.permissions import SkillPermissions

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.database import BlackboardDatabase


SkillStatus = Literal["success", "failed", "blocked", "cancelled", "needs_orchestrator_action"]


@dataclass(slots=True)
class CancellationToken:
    _cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str) -> None:
        self._cancelled = True
        self.reason = reason

    @property
    def cancelled(self) -> bool:
        return self._cancelled


@dataclass(frozen=True, slots=True)
class SkillRequest:
    requested_skill: str
    arguments: dict[str, Any]
    reason: str


@dataclass(frozen=True, slots=True)
class SkillResult:
    status: SkillStatus
    content: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    requested_actions: list[SkillRequest] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "content": self.content,
            "artifacts": self.artifacts,
            "requested_actions": [
                {
                    "requested_skill": request.requested_skill,
                    "arguments": request.arguments,
                    "reason": request.reason,
                }
                for request in self.requested_actions
            ],
        }


@dataclass(frozen=True, slots=True)
class SkillContext:
    session_id: str
    skill_name: str
    database: BlackboardDatabase | BlackboardAccessProxy
    config: HarnessConfig
    permissions: SkillPermissions = field(default_factory=SkillPermissions)
    stream_text: Callable[[str], None] | None = None
    on_tool_event: Callable[[str], None] | None = None
    cancellation: CancellationToken = field(default_factory=CancellationToken)

    @property
    def cancelled(self) -> bool:
        return self.cancellation.cancelled

    @property
    def project_root(self) -> Path:
        """Read-only view of the project directory.

        Raises PermissionError when the skill's workspace permission is ``"none"``.
        """
        if not self.permissions.can_read_workspace:
            msg = (
                f"Skill '{self.skill_name}' has workspace="
                f"{self.permissions.workspace!r} — cannot access project files."
            )
            raise PermissionError(msg)
        return self.config.project_root

    @property
    def scratch_dir(self) -> Path:
        """Writable scratch directory for skills with ``workspace=read_write``.

        Created on first access. Scoped to the session so concurrent sessions
        don't collide.
        """
        if not self.permissions.can_write_workspace:
            msg = (
                f"Skill '{self.skill_name}' has workspace="
                f"{self.permissions.workspace!r} — cannot write files."
            )
            raise PermissionError(msg)
        scratch = self.config.project_root / ".deverino-scratch" / self.session_id
        scratch.mkdir(parents=True, exist_ok=True)
        return scratch

    def read_subagent_template(self, persona: str) -> str:
        normalized = persona.removesuffix(".md")
        candidates = (
            self.config.paths.personas / f"{normalized}.md",
            self.config.paths.personas / f"{normalized.replace('_', '-')}.md",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        msg = f"Subagent persona template not found: {persona}"

        raise FileNotFoundError(msg)

    def emit_text(self, chunk: str) -> None:
        if self.stream_text is not None and chunk:
            self.stream_text(chunk)

    def emit_tool_event(self, message: str) -> None:
        if self.on_tool_event is not None and message:
            self.on_tool_event(message)
