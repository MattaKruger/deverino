from __future__ import annotations

import json
from typing import Any

from harness_poc.core.llm_client import LLMClient, Message
from harness_poc.core.skill_context import SkillContext, SkillResult


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    memory_key = str(arguments.get("memory_key") or "").strip()
    if not memory_key:
        msg = "summarize_memory requires memory_key"
        raise ValueError(msg)

    payload = ctx.database.read_memory(ctx.session_id, memory_key)
    if payload is None:
        return SkillResult(
            status="failed",
            content=f"No memory found for key: {memory_key}",
            artifacts={"memory_key": memory_key},
        )

    response = LLMClient().chat(
        messages=_build_messages(memory_key=memory_key, payload=payload),
        tools=None,
    )
    summary = response.content.strip()

    return SkillResult(
        status="success",
        content=summary,
        artifacts={
            "memory_key": memory_key,
            "summary": summary,
        },
    )


def _build_messages(*, memory_key: str, payload: dict[str, Any] | str) -> list[Message]:
    payload_text = (
        json.dumps(payload, indent=2, sort_keys=True) if isinstance(payload, dict) else payload
    )
    return [
        {
            "role": "system",
            "content": "Summarize blackboard memory compactly for a CLI user.",
        },
        {
            "role": "user",
            "content": (
                f"Memory key: {memory_key}\n\n"
                f"Payload:\n{payload_text}\n\n"
                "Return a concise human-readable summary with important caveats."
            ),
        },
    ]
