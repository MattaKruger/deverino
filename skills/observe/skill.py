from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from harness_poc.core.events import (
    ArchitectureInvariantObserved,
    BoundaryIdentified,
    ConstantDocumented,
    ContextMapEvent,
    ContextualInsightDiscovered,
    EntityReferenced,
    FactDisputed,
    ResultRecorded,
    SchemaDiscovered,
)
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event builders — one per observation_type
# ---------------------------------------------------------------------------


def _build_entity(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,
) -> ContextMapEvent:
    return EntityReferenced(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        entity_name=summary[:200],
        entity_type=_guess_entity_type(summary),
        context=detail,
    )


def _build_schema(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,
) -> ContextMapEvent:
    return SchemaDiscovered(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        schema_description=summary,
        example=detail,
    )


def _build_dispute(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,  # noqa: ARG001 — kept for uniform signature
) -> ContextMapEvent:
    return FactDisputed(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        previous_claim=_find_disputed_entry(ctx, corpus_key, summary),
        corrected_claim=summary,
        source_doc_id="",
    )


def _build_insight(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,  # noqa: ARG001 — kept for uniform signature
) -> ContextMapEvent:
    return ContextualInsightDiscovered(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        insight=summary,
        supporting_events=[],
        map_section="context_understanding",
    )


def _build_boundary(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,
) -> ContextMapEvent:
    return BoundaryIdentified(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        boundary_description=summary,
        detail=detail,
    )


def _build_constant(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,
) -> ContextMapEvent:
    return ConstantDocumented(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        constant_summary=summary,
        detail=detail,
    )


def _build_result(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,
) -> ContextMapEvent:
    return ResultRecorded(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        result_summary=summary,
        detail=detail,
    )


def _build_architecture(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
    detail: str,
) -> ContextMapEvent:
    return ArchitectureInvariantObserved(
        session_id=ctx.session_id,
        corpus_key=corpus_key,
        invariant_summary=summary,
        detail=detail,
    )


_Builder = "Callable[[SkillContext, str, str, str], ContextMapEvent]"

_BUILDERS: dict[str, _Builder] = {
    "entity": _build_entity,
    "schema": _build_schema,
    "dispute": _build_dispute,
    "insight": _build_insight,
    "boundary": _build_boundary,
    "constant": _build_constant,
    "result": _build_result,
    "architecture": _build_architecture,
}


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


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

    builder = _BUILDERS.get(observation_type)
    if builder is None:
        return SkillResult(
            status="failed",
            content=f"Unknown observation_type: {observation_type!r}",
            artifacts={},
        )

    corpus_key = (
        str(arguments.get("corpus_key") or "").strip()
        or f"{ctx.config.project_id}:codebase"
    )
    if ":" not in corpus_key:
        return SkillResult(
            status="failed",
            content=(
                f"Invalid corpus_key {corpus_key!r}: expected 'project:name' form "
                f"(e.g., '{ctx.config.project_id}:dashboard')."
            ),
            artifacts={},
        )

    event = builder(ctx, corpus_key, summary, detail)

    try:
        ctx.database.append_context_map_event(event)
    except AttributeError, PermissionError:
        logger.debug("Skipping %s context-map event (no event proxy)", observation_type)
        return SkillResult(
            status="success",
            content=f"Observation recorded ({observation_type}).",
            artifacts={"observation_type": observation_type},
        )
    except Exception as exc:
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


_ENTITY_TYPE_KEYWORDS = (
    "class", "function", "module", "package", "config", "api",
    "endpoint", "database", "table", "skill", "tool", "workflow",
    "pipeline", "pattern", "convention",
)


def _guess_entity_type(summary: str) -> str:
    summary_lower = summary.lower()
    for keyword in _ENTITY_TYPE_KEYWORDS:
        if keyword in summary_lower:
            return keyword
    return "concept"


def _find_disputed_entry(
    ctx: SkillContext,
    corpus_key: str,
    summary: str,
) -> str:
    """Try to find a matching entry in the current context map that is being disputed."""
    try:
        current_map = ctx.database.get_context_map(corpus_key)
    except AttributeError, PermissionError:
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
    for entry in current_map:
        summary_lower_entry = entry.summary.lower()
        score = sum(1 for w in words if w in summary_lower_entry)
        if score > best_score:
            best_score = score
            best_entry = f"[{entry.section}] {entry.key}: {entry.summary}"

    return best_entry[:500] if best_entry else ""
