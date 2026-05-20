from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from harness_poc.core.pydantic_runtime import build_model, chat_text
from harness_poc.core.skill_context import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.llm_client import Message
    from harness_poc.core.skill_context import SkillContext

_CHARS_PER_TOKEN = 4
_SECTION_PRIORITY = [
    "parsing_schema",
    "reusable_results",
    "domain_constants",
    "context_understanding",
    "context_roadmap",
]


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    corpus_key = str(arguments.get("corpus_key") or "").strip()
    if not corpus_key:
        return SkillResult(
            status="failed",
            content="Missing required argument: corpus_key",
            artifacts={},
        )

    max_event_tokens = int(arguments.get("max_event_tokens") or 8000)
    token_budget = int(arguments.get("token_budget") or 1024)

    db = ctx.database
    pending = db.get_pending_context_map_events(corpus_key, limit=50)
    if not pending:
        return SkillResult(
            status="success",
            content=f"No pending events for {corpus_key}.",
            artifacts={"corpus_key": corpus_key, "events_processed": 0},
        )

    current_map: dict[str, Any] = db.get_context_map(corpus_key) or {}
    model = build_model(ctx.config.llm)

    events_payload = _truncate_events(pending, max_event_tokens)
    try:
        distiller_raw = chat_text(
            _distiller_messages(events_payload, current_map),
            model=model,
        )
        distiller_output = _parse_json(distiller_raw)
    except Exception as exc:  # noqa: BLE001
        return SkillResult(status="failed", content=f"Distiller failed: {exc}", artifacts={})

    try:
        cartographer_raw = chat_text(
            _cartographer_messages(distiller_output, current_map),
            model=model,
        )
        cartographer_output = _parse_json(cartographer_raw)
    except Exception as exc:  # noqa: BLE001
        return SkillResult(status="failed", content=f"Cartographer failed: {exc}", artifacts={})

    edits: list[dict[str, Any]] = cartographer_output.get("edits") or []
    updated_map = _apply_edits(current_map, edits)
    updated_map = _enforce_budget(updated_map, token_budget)

    map_text = json.dumps(updated_map, sort_keys=True)
    token_count = len(map_text) // _CHARS_PER_TOKEN

    event_ids = [row.event_id for row in pending]
    db.write_map_and_mark_processed(corpus_key, updated_map, token_count, event_ids)

    return SkillResult(
        status="success",
        content=(
            f"Materialized {len(event_ids)} event(s) for {corpus_key}. "
            f"Map now ~{token_count} tokens."
        ),
        artifacts={
            "corpus_key": corpus_key,
            "events_processed": len(event_ids),
            "token_count": token_count,
            "edits_applied": len(edits),
        },
    )


def _truncate_events(rows: list[Any], max_event_tokens: int) -> list[dict[str, Any]]:
    budget_chars = max_event_tokens * _CHARS_PER_TOKEN
    result: list[dict[str, Any]] = []
    used = 0
    for row in rows:
        serialized = row.payload
        if used + len(serialized) > budget_chars:
            break
        result.append(json.loads(serialized))
        used += len(serialized)
    return result


def _distiller_messages(
    events: list[dict[str, Any]],
    current_map: dict[str, Any],
) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                "You are a Context Map Distiller. Examine a batch of interaction events "
                "from an agent working with a recurring external context. Determine what "
                "the agent learned about the context itself, not the task, and produce "
                "structured output.\n\n"
                'Output format: JSON with keys "diagnosis" (string), '
                '"tags" (object mapping entry_key to one of: helpful/harmful/neutral/stale), '
                'and "observations" (list of plain-language orientation facts).\n\n'
                "Do not assign sections or priority scores in observations. Those are "
                "Cartographer outputs. Record only what was learned."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Current context map:\n{json.dumps(current_map, indent=2)}\n\n"
                f"Unprocessed events:\n{json.dumps(events, indent=2)}\n\n"
                "Produce the JSON output now."
            ),
        },
    ]


def _cartographer_messages(
    distiller_output: dict[str, Any],
    current_map: dict[str, Any],
) -> list[Message]:
    return [
        {
            "role": "system",
            "content": (
                "You are a Context Map Cartographer. Translate distilled observations into "
                "structured map edits.\n\n"
                "Sections: context_roadmap, context_understanding, domain_constants, "
                "reusable_results, parsing_schema.\n\n"
                'Output format: JSON with key "edits", each edit having:\n'
                "op (ADD|DELETE|REPLACE), section, entry_key (string slug), "
                "content (string), priority_score (0.0-1.0), supporting_event_ids (list).\n\n"
                "Also DELETE any entry tagged harmful or stale by the Distiller."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Distiller output:\n{json.dumps(distiller_output, indent=2)}\n\n"
                f"Current context map:\n{json.dumps(current_map, indent=2)}\n\n"
                "Produce the JSON edits now."
            ),
        },
    ]


def _apply_edits(
    current_map: dict[str, Any],
    edits: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        section: dict(current_map.get(section) or {}) for section in _SECTION_PRIORITY
    }
    for edit in edits:
        op = str(edit.get("op") or "").upper()
        section = str(edit.get("section") or "")
        entry_key = str(edit.get("entry_key") or "")
        if not section or not entry_key or section not in result:
            continue
        if op == "DELETE":
            result[section].pop(entry_key, None)
        elif op in ("ADD", "REPLACE"):
            result[section][entry_key] = {
                "content": str(edit.get("content") or ""),
                "priority_score": float(edit.get("priority_score") or 0.5),
            }
    return result


def _enforce_budget(
    map_data: dict[str, Any],
    token_budget: int,
) -> dict[str, Any]:
    char_budget = token_budget * _CHARS_PER_TOKEN
    while len(json.dumps(map_data, sort_keys=True)) > char_budget:
        evicted = False
        for section in _SECTION_PRIORITY:
            entries = map_data.get(section) or {}
            if not entries:
                continue
            lowest_key = min(entries, key=lambda key: entries[key].get("priority_score", 0.0))
            del map_data[section][lowest_key]
            evicted = True
            break
        if not evicted:
            break
    return map_data


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    result = json.loads(text)
    if not isinstance(result, dict):
        msg = f"Expected JSON object, got {type(result).__name__}"
        raise TypeError(msg)
    return result
