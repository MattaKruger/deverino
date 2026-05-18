from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.database import BlackboardDatabase


SkillStatus = Literal[
    "success", "failed", "blocked", "needs_orchestrator_action"
]


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
    database: BlackboardDatabase
    config: HarnessConfig

    @property
    def project_root(self) -> Path:
        return self.config.project_root

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
