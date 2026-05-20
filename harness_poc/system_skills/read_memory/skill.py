"""Bridge skill — forwards to the built-in tool in system_tools/."""

from __future__ import annotations

from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult
from harness_poc.core.tool_context import ToolContext
from harness_poc.system_tools.read_memory import read_memory as _read_memory


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    """Forward to the system_tools implementation."""
    tool_ctx = ToolContext(
        session_id=ctx.session_id,
        project_root=ctx.config.project_root,
        database=ctx.database,  # type: ignore[arg-type]
        runtime_config=ctx.config.runtime,
    )
    memory_key = str(arguments.get("memory_key") or "")
    return _read_memory(tool_ctx, memory_key=memory_key)
