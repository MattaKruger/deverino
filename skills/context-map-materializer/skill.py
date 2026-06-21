"""Context Map Materializer skill — thin adapter over the Deterministic Cartographer engine.

See docs/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md §3.1.

Two CopT gates (plans/09-copt-gate-plan.md):
- Pre-Distiller gate: embeds raw event payloads and compares against stored
  embeddings.  Skips the expensive Distiller LLM call entirely when all events
  are semantically redundant (max_similarity > threshold, default 0.92).
- Post-Distiller gate: embeds distilled summaries and bypasses the Cartographer
  stage when all observations are redundant with the existing context map.
Both use all-MiniLM-L6-v2 via sentence-transformers for embedding and numpy
for batched cosine-similarity computation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from harness_poc.core.context_map import (
    deterministic_cartographer,
    embed_summaries,
    run_distiller,
)
from harness_poc.core.events import (
    MapEntryEvicted,
    MapEntryInserted,
)
from harness_poc.core.runtime import build_model
from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.context_map.schema import MapEntry
    from harness_poc.core.events import ContextMapEvent
    from harness_poc.core.skills import SkillContext
    from harness_poc.core.storage.blackboard_proxy import BlackboardAccessProxy
    from harness_poc.core.storage.database import BlackboardDatabase

logger = logging.getLogger(__name__)


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
    copt_threshold = ctx.config.runtime.materializer_copt_threshold

    # ---- Pre-Distiller CopT Gate: skip LLM call if raw events are redundant ----
    if (
        db.copt_is_available()
        and events
        and current_map
        and _events_all_redundant(events, corpus_key, copt_threshold, db)
    ):
        logger.info(
            "Pre-distiller CopT gate: all %d event(s) redundant for %s — skipping Distiller",
            len(events),
            corpus_key,
        )
        db.write_map_and_mark_processed(
            corpus_key,
            current_map,
            sum(e.token_estimate for e in current_map),
            [row.event_id for row in pending],
        )
        return SkillResult(
            status="success",
            content=(
                f"Pre-distiller CopT gate: all {len(events)} event(s) redundant "
                f"for {corpus_key}. Skipped Distiller LLM call. "
                f"Map unchanged at {sum(e.token_estimate for e in current_map)} tokens."
            ),
            artifacts={
                "corpus_key": corpus_key,
                "events_processed": len(pending),
                "token_count": sum(e.token_estimate for e in current_map),
                "map_changed": False,
                "cycle_n": cycle_n,
                "pre_distiller_copt_skipped": True,
            },
        )

    try:
        distilled = await run_distiller(
            events, distiller_model, ctx.config.distiller, current_map=current_map
        )
    except Exception as exc:
        return SkillResult(
            status="failed",
            content=f"Distiller failed: {exc}",
            artifacts={},
        )

    # ---- CopT Gate: skip Cartographer if all observations are redundant ----
    if db.copt_is_available() and distilled and current_map:
        all_redundant = _copt_all_redundant(distilled, corpus_key, copt_threshold, db)
        if all_redundant:
            db.write_map_and_mark_processed(
                corpus_key,
                current_map,
                sum(e.token_estimate for e in current_map),
                [row.event_id for row in pending],
            )
            return SkillResult(
                status="success",
                content=(
                    f"CopT gate: skipped Cartographer for {corpus_key} "
                    f"({len(distilled)} observation(s) redundant). "
                    f"Map unchanged at {sum(e.token_estimate for e in current_map)} tokens."
                ),
                artifacts={
                    "corpus_key": corpus_key,
                    "events_processed": len(pending),
                    "token_count": sum(e.token_estimate for e in current_map),
                    "map_changed": False,
                    "cycle_n": cycle_n,
                    "copt_skipped": True,
                },
            )

    result = deterministic_cartographer(distilled, current_map, cycle_n, ctx.config.cartographer)

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

    # ---- CopT Gate: upsert embeddings for future batches ----
    if db.copt_is_available() and distilled:
        try:
            summaries = [entry.summary for entry in distilled]
            embeddings = embed_summaries(summaries)
            embedding_pairs = [
                (entry.key, emb) for entry, emb in zip(distilled, embeddings, strict=True)
            ]
            db.copt_upsert_embeddings(corpus_key, embedding_pairs)
        except Exception:
            logger.warning("CopT embedding upsert failed", exc_info=True)

    return SkillResult(
        status="success",
        content=(
            f"Materialized {len(pending)} event(s) for {corpus_key}. Map now {token_count} tokens."
        ),
        artifacts={
            "corpus_key": corpus_key,
            "events_processed": len(pending),
            "token_count": token_count,
            "map_changed": map_changed,
            "cycle_n": cycle_n,
        },
    )


def _copt_all_redundant(
    distilled: list[Any],
    corpus_key: str,
    threshold: float,
    db: BlackboardDatabase | BlackboardAccessProxy,
) -> bool:
    """Check if all distilled entries are redundant with stored embeddings.

    Batch-embeds all summaries, fetches stored embeddings in one query,
    and computes cosine similarities in Python with numpy.
    This replaces N individual embed + pgvector roundtrips with a single
    batch embed + single DB fetch + vectorized numpy computation.
    """
    import numpy as np

    summaries = [entry.summary for entry in distilled]
    query_embeddings = embed_summaries(summaries)  # (N, 384) normalized

    stored = db.copt_get_all_embeddings(corpus_key)
    if not stored:
        return False  # no stored embeddings, all entries are novel

    stored_matrix = np.array([emb for _key, emb in stored], dtype=np.float64)  # (M, 384)
    query_matrix = np.array(query_embeddings, dtype=np.float64)  # (N, 384)

    # Cosine similarity of L2-normalized vectors = dot product
    # similarities shape: (N, M) — each query against each stored embedding
    similarities = query_matrix @ stored_matrix.T
    max_sims = similarities.max(axis=1)  # best match per query

    return bool(np.all(max_sims >= threshold))


def _events_all_redundant(
    events: list[Any],
    corpus_key: str,
    threshold: float,
    db: BlackboardDatabase | BlackboardAccessProxy,
) -> bool:
    """Pre-Distiller gate: check if raw events are semantically redundant.

    Serializes each event to JSON, batch-embeds the payloads, and compares
    against stored CopT embeddings.  If all events are similar to known
    entries, the expensive Distiller LLM call can be skipped entirely.
    """
    import json

    import numpy as np

    event_texts = [json.dumps(e.model_dump(), default=str) for e in events]
    query_embeddings = embed_summaries(event_texts)  # (N, 384) normalized

    stored = db.copt_get_all_embeddings(corpus_key)
    if not stored:
        return False  # no stored embeddings, all events are novel

    stored_matrix = np.array([emb for _key, emb in stored], dtype=np.float64)  # (M, 384)
    query_matrix = np.array(query_embeddings, dtype=np.float64)  # (N, 384)

    similarities = query_matrix @ stored_matrix.T
    max_sims = similarities.max(axis=1)

    return bool(np.all(max_sims >= threshold))


def _events_from_rows(rows: list[Any], max_event_tokens: int) -> list[ContextMapEvent]:
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
        except json.JSONDecodeError, Exception:
            logger.debug("Failed to deserialize context map event row", exc_info=True)
            continue
    return result


def _map_changed(old_map: list[MapEntry], new_map: list[MapEntry]) -> bool:
    """Compare two maps, excluding last_updated which would force every cycle to look changed."""

    def _key(entry: MapEntry) -> str:
        return entry.key

    old_normalized = [
        entry.model_dump(exclude={"last_updated"}) for entry in sorted(old_map, key=_key)
    ]
    new_normalized = [
        entry.model_dump(exclude={"last_updated"}) for entry in sorted(new_map, key=_key)
    ]
    return old_normalized != new_normalized
