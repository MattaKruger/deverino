from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from harness_poc.core.pydantic_runtime import build_model, chat_text
from harness_poc.core.skill_context import SkillContext, SkillResult

if TYPE_CHECKING:
    from harness_poc.core.llm_client import Message


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    objective = str(arguments.get("objective") or "")
    memory_key = str(arguments.get("memory_key") or "")
    output_key = str(arguments.get("output_key") or f"{memory_key}_reflection")

    if not objective:
        msg = "reflect_on_result requires objective"
        raise ValueError(msg)
    if not memory_key:
        msg = "reflect_on_result requires memory_key"
        raise ValueError(msg)

    payload = ctx.database.read_memory(ctx.session_id, memory_key)
    if payload is None:
        reflection = {
            "verdict": "fail",
            "objective": objective,
            "summary": f"No result was found under memory key '{memory_key}'.",
            "risks": ["Missing subagent result."],
        }
    else:
        try:
            response = chat_text(
                _build_reviewer_messages(objective=objective, payload=payload),
                model=build_model(ctx.config.llm),
            )
        except Exception as exc:
            return SkillResult(
                status="failed",
                content=f"LLM reflection failed: {exc}",
                artifacts={
                    "memory_key": memory_key,
                    "error": str(exc),
                },
            )
        reflection = _normalize_reflection(
            response,
            objective=objective,
            memory_key=memory_key,
            payload=payload,
        )

    ctx.database.write_memory(ctx.session_id, output_key, reflection)
    return SkillResult(
        status="success" if reflection["verdict"] == "pass" else "failed",
        content=json.dumps(reflection, indent=2, sort_keys=True),
        artifacts={
            "memory_key": output_key,
            "verdict": reflection["verdict"],
        },
    )


def _build_reviewer_messages(*, objective: str, payload: dict[str, Any] | str) -> list[Message]:
    payload_text = (
        json.dumps(payload, indent=2, sort_keys=True) if isinstance(payload, dict) else payload
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a strict workflow reviewer. Decide whether a delegated "
                "research result satisfies the original objective. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Objective:\n{objective}\n\n"
                f"Delegated result:\n{payload_text}\n\n"
                "Return a JSON object with keys: verdict, summary, risks, "
                "evaluated_memory_key. verdict must be pass or fail. The summary "
                "must mention the actual substance of the delegated result."
            ),
        },
    ]


def _normalize_reflection(
    content: str,
    *,
    objective: str,
    memory_key: str,
    payload: dict[str, Any] | str,
) -> dict[str, Any]:
    decoded = _parse_json_object(content)
    verdict = str(decoded.get("verdict") or "").lower()
    if verdict not in {"pass", "fail"}:
        verdict = _fallback_verdict(payload)
    risks = decoded.get("risks")
    return {
        "verdict": verdict,
        "objective": objective,
        "summary": str(decoded.get("summary") or content.strip()),
        "risks": [item for item in risks if isinstance(item, str)]
        if isinstance(risks, list)
        else [],
        "evaluated_memory_key": memory_key,
    }


def _fallback_verdict(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, dict) and payload.get("status") in {
        "failed",
        "blocked",
    }:
        return "fail"
    return "pass"


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
