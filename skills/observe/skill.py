from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from harness_poc.core.events import (
    ContextualInsightDiscovered,
    EntityReferenced,
    FactDisputed,
    SchemaDiscovered,
)
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext

logger = logging.getLogger(__name__)


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    observation_type = str(arguments.get("observation_type") or "").strip()
    summary = str(arguments.get("summary") or "").strip()
    detail = str(arguments.get("detail") or "").strip()

    if not observation_type:
        return SkillResult(status="failed", content="Missing observation_type.", artifacts={})
    if not summary:
        return SkillResult(status="failed", content="Missing summary.", artifacts={})
    if not detail:
        return SkillResult(status="failed", content="Missing detail.", artifacts={})

    corpus_key = f"{ctx.config.project_id}:codebase"

    if observation_type == "entity":
        event = EntityReferenced(
            session_id=ctx.session_id,
            corpus_key=corpus_key,
            entity_name=summary[:200],
            entity_type=_guess_entity_type(summary),
            context=detail,
        )
    elif observation_type == "schema":
        event = SchemaDiscovered(
            session_id=ctx.session_id,
            corpus_key=corpus_key,
            schema_description=summary,
            example=detail,
        )
    elif observation_type == "dispute":
        event = FactDisputed(
            session_id=ctx.session_id,
            corpus_key=corpus_key,
            previous_claim=_find_disputed_entry(ctx, corpus_key, summary),
            corrected_claim=summary,
            source_doc_id="",
        )
    elif observation_type == "insight":
        event = ContextualInsightDiscovered(
            session_id=ctx.session_id,
            corpus_key=corpus_key,
            insight=summary,
            supporting_events=[],
            map_section="context_understanding",
        )
    else:
        return SkillResult(
            status="failed",
            content=f"Unknown observation_type: {observation_type!r}",
            artifacts={},
        )

    try:
        ctx.database.append_context_map_event(event)
    except (AttributeError, PermissionError):
        logger.debug("Skipping %s context-map event (no event proxy)", observation_type)
        return SkillResult(
            status="success",
            content=f"Observation recorded ({observation_type}).",
            artifacts={"observation_type": observation_type},
        )
    except Exception as exc:  # noqa: BLE001
        return SkillResult(
            status="failed",
            content=f"Failed to record observation: {exc}",
            artifacts={},
        )

    return SkillResult(
        status="success",
        content=f"Observation recorded ({observation_type}): {summary[:120]}",
        artifacts={
            "observation_type": observation_type,
            "corpus_key": corpus_key,
            "event_id": event.event_id,
        },
    )


def _guess_entity_type(summary: str) -> str:
    """Heuristic: extract a short entity type from the summary."""
    summary_lower = summary.lower()
    hints = [
        ("class", "class"),
        ("function", "function"),
        ("module", "module"),
        ("package", "package"),
        ("config", "config"),
        ("api", "api"),
        ("endpoint", "endpoint"),
        ("database", "database"),
        ("table", "table"),
        ("skill", "skill"),
        ("tool", "tool"),
        ("workflow", "workflow"),
        ("pipeline", "pipeline"),
        ("pattern", "pattern"),
        ("convention", "convention"),
    ]
    for keyword, entity_type in hints:
        if keyword in summary_lower:
            return entity_type
    return "concept"


def _find_disputed_entry(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
) -> str:
    """Try to find a matching entry in the current context map that is being disputed."""
    try:
        current_map = ctx.database.get_context_map(corpus_key)
    except (AttributeError, PermissionError):
        return ""

    if not current_map:
        return ""

    # Search through all sections for an entry containing key words from the summary
    summary_lower = summary.lower()
    words = {w for w in summary_lower.split() if len(w) > 3}
    if not words:
        return ""

    best_entry = ""
    best_score = 0
    for section_name, entries in current_map.items():
        if not isinstance(entries, dict):
            continue
        for entry_key, entry_value in entries.items():
            if not isinstance(entry_value, str):
                continue
            entry_lower = entry_value.lower()
            score = sum(1 for w in words if w in entry_lower)
            if score > best_score:
                best_score = score
                best_entry = f"[{section_name}] {entry_key}: {entry_value}"

    return best_entry[:500] if best_entry else ""
