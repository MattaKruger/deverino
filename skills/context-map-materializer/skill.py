from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from harness_poc.core.context_map_events import (
    ContextMapEvent,
    MapEntryEvicted,
    MapEntryPromoted,
)
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
    candidate_map, applied_count = _apply_edits(current_map, edits)
    updated_map, evictions = _enforce_budget(candidate_map, token_budget)
    map_changed = _strip_empty_sections(updated_map) != _strip_empty_sections(current_map)

    session_id = str(arguments.get("session_id") or "materializer")
    derivation_events: list[ContextMapEvent] = [
        MapEntryEvicted(
            session_id=session_id,
            corpus_key=corpus_key,
            entry_id=eviction.get("entry_id"),
            entry_key=eviction["entry_key"],
            section=eviction["section"],
            reason=f"budget_eviction (priority={eviction['priority_score']})",
        )
        for eviction in evictions
    ]
    derivation_events.extend(
        [
            MapEntryPromoted(
                session_id=session_id,
                corpus_key=corpus_key,
                entry_id=promotion.get("entry_id"),
                entry_key=promotion["entry_key"],
                from_section=promotion["from_section"],
                to_section=promotion["to_section"],
            )
            for promotion in _detect_promotions(current_map, updated_map)
        ]
    )
    for event in derivation_events:
        db.append_context_map_event(event)

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
            "edits_applied": applied_count,
            "map_changed": map_changed,
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
) -> tuple[dict[str, Any], int]:
    result = _ensure_entry_ids(current_map)
    applied_count = 0
    for edit in edits:
        op = str(edit.get("op") or "").upper()
        section = str(edit.get("section") or "")
        entry_key = str(edit.get("entry_key") or "")
        if not section or not entry_key or section not in result:
            continue
        if op == "DELETE":
            if entry_key in result[section]:
                del result[section][entry_key]
                applied_count += 1
        elif op in ("ADD", "REPLACE"):
            existing = result[section].get(entry_key)
            if op == "ADD" or existing is None:
                entry_id = _generate_entry_id()
            else:
                entry_id = existing.get("entry_id") or _generate_entry_id()
            next_entry = {
                "entry_id": entry_id,
                "content": str(edit.get("content") or ""),
                "priority_score": float(edit.get("priority_score") or 0.5),
            }
            if result[section].get(entry_key) != next_entry:
                result[section][entry_key] = next_entry
                applied_count += 1
    return result, applied_count


def _ensure_entry_ids(map_data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section in _SECTION_PRIORITY:
        entries = dict(map_data.get(section) or {})
        result[section] = {}
        for entry_key, entry in entries.items():
            next_entry = dict(entry) if isinstance(entry, dict) else {"content": str(entry)}
            if not next_entry.get("entry_id"):
                next_entry["entry_id"] = _generate_entry_id()
            result[section][entry_key] = next_entry
    return result


def _strip_empty_sections(map_data: dict[str, Any]) -> dict[str, Any]:
    return {section: entries for section, entries in map_data.items() if entries}


def _enforce_budget(
    map_data: dict[str, Any],
    token_budget: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evictions: list[dict[str, Any]] = []
    char_budget = token_budget * _CHARS_PER_TOKEN
    while len(json.dumps(map_data, sort_keys=True)) > char_budget:
        evicted = False
        for section in reversed(_SECTION_PRIORITY):
            entries = map_data.get(section) or {}
            if not entries:
                continue
            lowest_key = min(entries, key=lambda key: entries[key].get("priority_score", 0.0))
            evictions.append(
                {
                    "entry_id": entries[lowest_key].get("entry_id"),
                    "entry_key": lowest_key,
                    "section": section,
                    "priority_score": entries[lowest_key].get("priority_score", 0.0),
                }
            )
            del map_data[section][lowest_key]
            evicted = True
            break
        if not evicted:
            break
    return map_data, evictions


def _detect_promotions(
    old: dict[str, Any],
    new: dict[str, Any],
) -> list[dict[str, Any]]:
    promotions: list[dict[str, Any]] = []
    old_sections = {key: set(value or {}) for key, value in old.items()}
    new_sections = {key: set(value or {}) for key, value in new.items()}
    for new_sec_idx, new_sec in enumerate(_SECTION_PRIORITY):
        if new_sec not in new_sections:
            continue
        for entry_key in new_sections[new_sec]:
            for old_sec_idx, old_sec in enumerate(_SECTION_PRIORITY):
                if old_sec not in old_sections or entry_key not in old_sections[old_sec]:
                    continue
                if new_sec_idx < old_sec_idx:
                    entry = new[new_sec][entry_key]
                    entry_id = entry.get("entry_id") if isinstance(entry, dict) else None
                    promotions.append(
                        {
                            "entry_id": entry_id,
                            "entry_key": entry_key,
                            "from_section": old_sec,
                            "to_section": new_sec,
                        }
                    )
                break
    return promotions


def _generate_entry_id() -> str:
    return uuid.uuid4().hex[:8]


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
