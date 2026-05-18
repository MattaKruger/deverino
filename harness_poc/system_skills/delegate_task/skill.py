from __future__ import annotations

import json
from typing import Any

from harness_poc.core.llm_client import LLMClient, Message
from harness_poc.core.skill_context import SkillContext, SkillResult


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    persona = str(arguments.get("persona") or arguments.get("template_name") or "")
    objective = str(arguments.get("objective") or "")
    memory_key = str(arguments.get("memory_key") or f"{persona}_result")
    context = str(arguments.get("context") or "")

    if not persona:
        msg = "delegate_task requires persona"
        raise ValueError(msg)
    if not objective:
        msg = "delegate_task requires objective"
        raise ValueError(msg)

    template = ctx.read_subagent_template(persona)
    response = LLMClient().chat(
        messages=_build_subagent_messages(
            persona_template=template,
            objective=objective,
            context=context,
        ),
        tools=None,
    )
    raw_content = response.content.strip()
    parsed_content = _parse_json_object(raw_content)
    status = str(parsed_content.get("status") or "completed")
    summary = str(parsed_content.get("summary") or raw_content)
    result = {
        "status": status,
        "summary": summary,
        "artifacts": {
            "persona": persona,
            "model_output": parsed_content or raw_content,
            "objective": objective,
            "received_context": context,
        },
    }
    ctx.database.write_memory(ctx.session_id, memory_key, result)

    return SkillResult(
        status="success" if status not in {"failed", "blocked"} else "failed",
        content=json.dumps(result, indent=2, sort_keys=True),
        artifacts={
            "memory_key": memory_key,
            "persona": persona,
            "objective": objective,
        },
    )


def _build_subagent_messages(
    *, persona_template: str, objective: str, context: str
) -> list[Message]:
    context_section = context or "No additional context was provided."
    return [
        {
            "role": "system",
            "content": persona_template,
        },
        {
            "role": "user",
            "content": (
                "Execute this delegated read-only research task.\n\n"
                f"Objective:\n{objective}\n\n"
                f"Context:\n{context_section}\n\n"
                "Return a concise JSON object with keys: status, summary, artifacts. "
                "Use artifacts for important findings, caveats, and suggested next steps."
            ),
        },
    ]


def _parse_json_object(content: str) -> dict[str, Any]:
    normalized = _strip_json_fence(content)
    try:
        decoded = json.loads(normalized)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return decoded


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < MIN_FENCED_JSON_LINES or not lines[-1].strip().startswith("```"):
        return stripped
    return "\n".join(lines[1:-1]).strip()


MIN_FENCED_JSON_LINES = 3
