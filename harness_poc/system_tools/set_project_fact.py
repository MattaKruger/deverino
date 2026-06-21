"""set_project_fact — set facts in durable project state (merge, not overwrite).

Accepts a dict of key-value facts and merges them into existing project
state in a single atomic write.  Multiple facts can be set at once.
Existing keys not in the new dict are preserved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.tools import ToolContext


def set_project_fact(
    ctx: ToolContext,
    facts: dict[str, str] | None = None,
) -> SkillResult:
    """Set one or more facts in project state (merged with existing facts).

    Args:
        ctx: Tool execution context.
        facts: Dict of key-value pairs to merge into project facts.
               Pass multiple pairs to set them all in a single atomic write.
               E.g. {"api_version": "v2", "primary_language": "python"}
    """
    facts = facts or {}
    facts = {k.strip(): v.strip() for k, v in facts.items() if k.strip()}

    if not facts:
        return SkillResult(
            status="failed",
            content="Facts dict must not be empty. Pass at least one key-value pair.",
        )

    if ctx.database is None:
        return SkillResult(
            status="failed",
            content="Database not available for set_project_fact.",
        )

    try:
        for key, value in facts.items():
            ctx.database.set_project_fact(key, value)
    except Exception as exc:
        return SkillResult(
            status="failed",
            content=f"Failed to set fact: {exc}",
        )

    keys = list(facts.keys())
    count = len(keys)
    if count == 1:
        summary = f"Set fact **{keys[0]}** = `{facts[keys[0]]}` in project state (merged)."
    else:
        joined = ", ".join(f"**{k}**" for k in keys)
        summary = f"Set {count} facts ({joined}) in project state (merged)."

    return SkillResult(
        status="success",
        content=summary,
        artifacts={"facts": facts},
    )


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="set_project_fact",
    description=(
        "Set facts in durable project state (merged with existing). "
        "Accepts a dict of key-value pairs — all are written atomically. "
        "Existing facts not in the new dict are preserved. "
        "Use for structured metadata like api_version, primary_language, etc. "
        "Read facts with read_project_state(section='facts')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "facts": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": (
                    "Dict of key-value facts to merge into project state. "
                    "E.g. {\"api_version\": \"v2\", \"primary_language\": \"python\"}"
                ),
            },
        },
        "required": ["facts"],
    },
    handler=set_project_fact,
)
