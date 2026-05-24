"""Context Map Materializer skill — thin adapter over the Deterministic Cartographer engine.

See docs/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md §3.1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.context_map import (
    deterministic_cartographer,
    run_distiller,
)
from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.events import (
    ContextMapEvent,
    MapEntryEvicted,
    MapEntryInserted,
)
from harness_poc.core.runtime import build_model
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext


async def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    corpus_key = str(arguments.get("corpus_key") or "").strip()
    if not corpus_key:
        return SkillResult(
            status="failed",
            content="Missing required argument: corpus_key",
            artifacts={},
        )

    session_id = str(arguments.get("session_id") or "materializer")
    db = ctx.database
    pending = db.get_pending_context_map_events(corpus_key, limit=50)
    if not pending:
        return SkillResult(
            status="success",
            content=f"No pending events for {corpus_key}.",
            artifacts={
                "corpus_key": corpus_key,
                "events_processed": 0,
                "map_changed": False,
            },
        )

    current_map: list[MapEntry] = db.get_context_map(corpus_key) or []
    cycle_n = db.get_and_bump_cycle(corpus_key)
    distiller_model = build_model(
        ctx.config.llm, fallback_model=None
    )  # resolved_model handles the fallback

    events = _events_from_rows(pending, ctx.config.runtime.materializer_max_event_tokens)
    try:
        distilled = await run_distiller(events, distiller_model, ctx.config.distiller)
    except Exception as exc:
        return SkillResult(
            status="failed",
            content=f"Distiller failed: {exc}",
            artifacts={},
        )

    result = deterministic_cartographer(
        distilled, current_map, cycle_n, ctx.config.cartographer
    )

    # Emit MapEntryInserted for newly seen entries
    for entry in result.new_map:
        if entry.first_seen_cycle == cycle_n:
            db.append_context_map_event(
                MapEntryInserted(
                    session_id=session_id,
                    corpus_key=corpus_key,
                    entry_id=entry.entry_id,
                    entry_key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    cycle_n=cycle_n,
                )
            )

    # Emit MapEntryEvicted for each eviction record
    for eviction in result.evictions:
        db.append_context_map_event(
            MapEntryEvicted(
                session_id=session_id,
                corpus_key=corpus_key,
                entry_id=eviction.entry_id,
                entry_key=eviction.key,
                section=eviction.section,
                materialization_count=eviction.materialization_count,
                reason=eviction.reason,
            )
        )

    map_changed = _map_changed(current_map, result.new_map)
    token_count = sum(entry.token_estimate for entry in result.new_map)
    db.write_map_and_mark_processed(
        corpus_key,
        result.new_map,
        token_count,
        [row.event_id for row in pending],
    )

    return SkillResult(
        status="success",
        content=(
            f"Materialized {len(pending)} event(s) for {corpus_key}. "
            f"Map now {token_count} tokens."
        ),
        artifacts={
            "corpus_key": corpus_key,
            "events_processed": len(pending),
            "token_count": token_count,
            "map_changed": map_changed,
            "cycle_n": cycle_n,
        },
    )


def _events_from_rows(
    rows: list[Any], max_event_tokens: int
) -> list[ContextMapEvent]:
    """Deserialize pending event rows, respecting a token budget for the Distiller input."""
    import json
    import logging

    from harness_poc.core.events import deserialize_event

    logger = logging.getLogger(__name__)

    # Rough estimate: 4 chars per token
    budget_chars = max_event_tokens * 4
    result: list[ContextMapEvent] = []
    used = 0
    for row in rows:
        serialized = row.payload
        if used + len(serialized) > budget_chars:
            break
        try:
            data = json.loads(serialized)
            result.append(deserialize_event(data))
            used += len(serialized)
        except (json.JSONDecodeError, Exception):  # noqa: BLE001
            logger.debug("Failed to deserialize context map event row", exc_info=True)
            continue
    return result


def _map_changed(old_map: list[MapEntry], new_map: list[MapEntry]) -> bool:
    """Compare two maps, excluding last_updated which would force every cycle to look changed."""

    def _key(entry: MapEntry) -> str:
        return entry.key

    old_normalized = [
        entry.model_dump(exclude={"last_updated"})
        for entry in sorted(old_map, key=_key)
    ]
    new_normalized = [
        entry.model_dump(exclude={"last_updated"})
        for entry in sorted(new_map, key=_key)
    ]
    return old_normalized != new_normalized
