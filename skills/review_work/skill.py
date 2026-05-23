from __future__ import annotations

import json
from typing import Any

from harness_poc.core.skills import SkillContext, SkillResult


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    objective = str(arguments.get("objective") or "").strip()
    memory_key = str(arguments.get("memory_key") or "").strip()
    output_key = str(arguments.get("output_key") or f"{memory_key}_review").strip()

    if not memory_key:
        msg = "review_work requires memory_key"
        raise ValueError(msg)

    payload = ctx.database.read_memory(ctx.session_id, memory_key)
    if payload is None:
        review = {
            "verdict": "fail",
            "summary": f"No result was found under memory key '{memory_key}'.",
            "objective": objective,
            "evaluated_memory_key": memory_key,
            "issues": ["Missing result."],
        }
        ctx.database.write_memory(ctx.session_id, output_key, review)
        return SkillResult(
            status="failed",
            content=json.dumps(review, indent=2, sort_keys=True),
            artifacts={"memory_key": output_key, "review": review},
        )

    review = {
        "verdict": "pass",
        "summary": "A result exists for the requested memory key.",
        "objective": objective,
        "evaluated_memory_key": memory_key,
        "result_type": type(payload).__name__,
    }
    ctx.database.write_memory(ctx.session_id, output_key, review)

    return SkillResult(
        status="success",
        content=json.dumps(review, indent=2, sort_keys=True),
        artifacts={"memory_key": output_key, "review": review},
    )
