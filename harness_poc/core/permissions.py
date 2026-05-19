from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

BlackboardPermission = Literal["read", "read_write", "none"]
WorkspacePermission = Literal["read", "read_write", "none"]

_BLACKBOARD_VALUES: frozenset[str] = frozenset({"read", "read_write", "none"})
_WORKSPACE_VALUES: frozenset[str] = frozenset({"read", "read_write", "none"})

# Directories and files that no skill may write to, regardless of workspace permission.
# These are structural invariants of the harness — protected paths are not configurable.
PROTECTED_PATHS: tuple[str, ...] = (
    "skills",
    "harness_poc/system_skills",
    "harness_poc/system_prompts",
    ".env",
    "harness.yaml",
    "harness_poc/blackboard.db",
    "pyproject.toml",
    "uv.lock",
)


@dataclass(frozen=True, slots=True)
class SkillPermissions:
    """Parsed and validated permissions from a skill's SKILL.md frontmatter.

    Enforcement points:
      - ``blackboard`` gated by ``BlackboardAccessProxy``
      - ``workspace`` gated by ``SkillContext.project_root`` / ``SkillContext.scratch_dir``
      - ``PROTECTED_PATHS`` enforced at the container mount level (read-only bind mount)
    """

    blackboard: BlackboardPermission = "none"
    workspace: WorkspacePermission = "none"

    @classmethod
    def from_yaml(cls, raw: dict[str, str] | None) -> SkillPermissions:
        """Parse from a SKILL.md frontmatter ``permissions`` dict.

        Invalid values are silently treated as ``"none"`` (safe-by-default).
        """
        if not isinstance(raw, dict):
            return cls()
        bb = raw.get("blackboard", "none")
        ws = raw.get("workspace", "none")
        if bb not in _BLACKBOARD_VALUES:
            bb = "none"
        if ws not in _WORKSPACE_VALUES:
            ws = "none"
        return cls(
            blackboard=cast("BlackboardPermission", bb),
            workspace=cast("WorkspacePermission", ws),
        )

    @property
    def can_read_blackboard(self) -> bool:
        return self.blackboard in ("read", "read_write")

    @property
    def can_write_blackboard(self) -> bool:
        return self.blackboard == "read_write"

    @property
    def can_read_workspace(self) -> bool:
        return self.workspace in ("read", "read_write")

    @property
    def can_write_workspace(self) -> bool:
        return self.workspace == "read_write"
