"""read_memory — retrieve data from the shared blackboard.

Migrated from ``system_skills/read_memory/skill.py`` (Phase 4).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from harness_poc.core.skill_context import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.tool_context import ToolContext


def read_memory(
    ctx: ToolContext,
    memory_key: str = "",
) -> SkillResult:
    """List all memory keys or read a specific value."""
    memory_key = (memory_key or "").strip()

    if ctx.database is None:
        return SkillResult(
            status="failed",
            content="Database not available for read_memory.",
        )

    if not memory_key:
        keys = ctx.database.list_memory_keys(ctx.session_id)
        return SkillResult(
            status="success",
            content=json.dumps({"memory_keys": keys}, indent=2, sort_keys=True),
            artifacts={"memory_keys": keys},
        )

    payload = ctx.database.read_memory(ctx.session_id, memory_key)
    if payload is None:
        return SkillResult(
            status="failed",
            content=f"No memory found for key: {memory_key}",
            artifacts={"memory_key": memory_key},
        )

    content = (
        json.dumps(payload, indent=2, sort_keys=True) if isinstance(payload, dict) else str(payload)
    )
    return SkillResult(
        status="success",
        content=content,
        artifacts={
            "memory_key": memory_key,
            "payload": payload,
        },
    )


# ── Register ──────────────────────────────────────────────────────────

from harness_poc.system_tools import register as _register  # noqa: E402

_register(
    name="read_memory",
    description=("Retrieves data stored in the shared blackboard for the current session."),
    parameters={
        "type": "object",
        "properties": {
            "memory_key": {
                "type": "string",
                "description": ("Key to read. Omit to list all available keys."),
            },
        },
    },
    handler=read_memory,
)
