from __future__ import annotations

import json
from typing import Any

from harness_poc.core.skill_context import SkillContext, SkillResult


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    memory_key = str(arguments.get("memory_key") or "").strip()
    if not memory_key:
        memory_keys = ctx.database.list_memory_keys(ctx.session_id)
        return SkillResult(
            status="success",
            content=json.dumps({"memory_keys": memory_keys}, indent=2, sort_keys=True),
            artifacts={"memory_keys": memory_keys},
        )

    payload = ctx.database.read_memory(ctx.session_id, memory_key)
    if payload is None:
        return SkillResult(
            status="failed",
            content=f"No memory found for key: {memory_key}",
            artifacts={"memory_key": memory_key},
        )

    content = (
        json.dumps(payload, indent=2, sort_keys=True) if isinstance(payload, dict) else payload
    )
    return SkillResult(
        status="success",
        content=content,
        artifacts={
            "memory_key": memory_key,
            "payload": payload,
        },
    )
