from __future__ import annotations

from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    """Stub — GoalRunner intercepts evaluate_goal during autonomous loops.

    This only runs when called directly via /skill evaluate_goal outside a goal run.
    """
    del ctx
    is_complete = arguments.get("is_complete", False)
    reasoning = arguments.get("reasoning", "")

    return SkillResult(
        status="success",
        content=(
            f"Goal evaluation: complete={is_complete}."
            + (f" Reasoning: {reasoning}" if reasoning else "")
        ),
        artifacts={
            "is_complete": is_complete,
            "reasoning": reasoning,
        },
    )
