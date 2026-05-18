from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.config import HarnessConfig


SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ScaffoldedSkill:
    skill_name: str
    skill_dir: Path
    created_files: list[Path]


class SkillScaffolder:
    def __init__(self, config: HarnessConfig) -> None:
        self.config = config

    def create_skill(self, skill_name: str, description: str) -> ScaffoldedSkill:
        normalized_name = skill_name.strip()
        normalized_description = description.strip()
        if not SKILL_NAME_PATTERN.fullmatch(normalized_name):
            msg = "Skill name must match /^[a-z][a-z0-9_]*$/"
            raise ValueError(msg)
        if not normalized_description:
            msg = "Skill description is required"
            raise ValueError(msg)

        skill_dir = self.config.paths.project_skills / normalized_name
        if skill_dir.exists():
            msg = f"Skill already exists: {normalized_name}"
            raise FileExistsError(msg)

        skill_dir.mkdir(parents=True)
        files = {
            skill_dir / "__init__.py": f'"""Generated {normalized_name} skill plugin."""\n',
            skill_dir / "SKILL.md": _render_skill_markdown(normalized_name, normalized_description),
            skill_dir / "skill.py": _render_skill_python(normalized_name),
        }
        for path, content in files.items():
            path.write_text(content, encoding="utf-8")
        return ScaffoldedSkill(
            skill_name=normalized_name,
            skill_dir=skill_dir,
            created_files=list(files),
        )


def _render_skill_markdown(skill_name: str, description: str) -> str:
    title = skill_name.replace("_", " ").title()
    return f"""---
name: {skill_name}
description: {description}
version: "1.0"
parameters:
  type: object
  properties: {{}}
  required: []
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: none
  workspace: none
---

# Skill: {title}

## Purpose
{description}

## Behavior
Describe what this skill does.

## Expected Output
Returns a `SkillResult`.
"""


def _render_skill_python(skill_name: str) -> str:
    return f"""from __future__ import annotations

from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    del ctx
    return SkillResult(
        status="success",
        content="Skill {skill_name} scaffold exists. Implement behavior in skill.py.",
        artifacts={{
            "skill_name": "{skill_name}",
            "arguments": arguments,
        }},
    )
"""
