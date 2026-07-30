"""Semantic corpus retrieval — query composition, retrieval, and rendering.

Called by the dynamic @agent.system_prompt decorator in pydantic_runtime.py.
Two ranking strategies:
  - "semantic": embed query, cosine similarity vs pre-computed bge embeddings
  - "deterministic": priority-based ranking (same as _render_cross_corpus, per-turn)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from typing import Any

    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.context_map.config import CartographerConfig
    from harness_poc.core.context_map.schema import MapEntry
    from harness_poc.core.storage.database import BlackboardDatabase

logger = logging.getLogger(__name__)


def compose_query(
    messages: list[Any],
    n_turns: int,
    max_chars: int,
) -> str:
    """Compose a query string from the last N user turns.

    Args:
        messages: PydanticAI ModelMessage list (or any objects with .role/.content).
        n_turns: Maximum number of user turns to include.
        max_chars: Truncate the composed query to this length.

    Returns:
        Concatenated user turn texts, or empty string if no user turns.
    """
    user_texts: list[str] = []
    for msg in reversed(messages):
        role = getattr(msg, "role", None)
        # PydanticAI ModelMessage objects don't have .role — check for content
        # on ModelRequest parts.
        if role == "user":
            content = getattr(msg, "content", "")
            if content:
                user_texts.append(str(content))
        elif hasattr(msg, "parts"):
            # PydanticAI ModelRequest has .parts list with UserPart
            for part in msg.parts:
                part_type = type(part).__name__
                if "User" in part_type:
                    content = getattr(part, "content", "")
                    if content:
                        user_texts.append(str(content))
        if len(user_texts) >= n_turns:
            break

    user_texts.reverse()
    query = "\n".join(user_texts)
    if len(query) > max_chars:
        query = query[:max_chars]
    return query


def semantic_retrieve(
    db: BlackboardDatabase,
    config: HarnessConfig,
    active_corpus_key: str,
    query_embedding: list[float],
) -> list[tuple[MapEntry, float]]:
    """Retrieve related corpus entries by cosine similarity to the query.

    For each related corpus, fetches pre-computed embeddings, computes cosine
    similarity, filters by min_similarity, sorts descending, takes top_k.
    Merges across corpora, caps at cross_corpus_max_entries.

    Falls back to priority_retrieve() for corpora without embeddings.
    """
    cc = config.cartographer
    related = _get_related_corpora(db, cc, active_corpus_key)
    if not related:
        return []

    query_vec = np.array(query_embedding, dtype=np.float32)
    results: list[tuple[MapEntry, float]] = []

    for corpus_key in related:
        # Fetch embeddings for this corpus
        embeddings = db.retrieval_get_embeddings(corpus_key)
        if not embeddings:
            # No embeddings — fall back to priority for this corpus
            priority_entries = _priority_entries(db, cc, corpus_key)
            results.extend(priority_entries)
            continue

        # Fetch full map entries for this corpus
        map_entries = db.get_context_map(corpus_key) or []
        if not map_entries:
            continue
        entry_by_key = {e.entry_id.replace("-", ""): e for e in map_entries}

        # Compute similarities
        scored: list[tuple[MapEntry, float]] = []
        for entry_key, emb in embeddings:
            entry = entry_by_key.get(entry_key.replace("-", ""))
            if entry is None:
                entry = entry_by_key.get(entry_key)
            if entry is None:
                continue
            emb_vec = np.array(emb, dtype=np.float32)
            sim = float(np.dot(query_vec, emb_vec))
            if sim >= cc.cross_corpus_min_similarity:
                scored.append((entry, sim))

        scored.sort(key=lambda x: -x[1])
        results.extend(scored[: cc.cross_corpus_semantic_top_k])

    # Cap total
    results.sort(key=lambda x: -x[1])
    return results[: cc.cross_corpus_max_entries]


def priority_retrieve(
    db: BlackboardDatabase,
    config: HarnessConfig,
    active_corpus_key: str,
) -> list[tuple[MapEntry, float]]:
    """Retrieve related corpus entries by priority (deterministic mode).

    Same logic as _render_cross_corpus() but returns (MapEntry, priority) tuples
    instead of rendered text.
    """
    cc = config.cartographer
    related = _get_related_corpora(db, cc, active_corpus_key)
    if not related:
        return []

    results: list[tuple[MapEntry, float]] = []
    for corpus_key in related:
        entries = _priority_entries(db, cc, corpus_key)
        results.extend(entries)

    results.sort(key=lambda x: -x[1])
    return results[: cc.cross_corpus_max_entries]


def render_block(
    entries_with_scores: list[tuple[MapEntry, float]],
    mode: str,
) -> str:
    """Render cross-corpus entries as a text block for system prompt injection.

    Format matches _render_cross_corpus() output for citation compatibility.
    """
    if not entries_with_scores:
        return ""

    parts: list[str] = ["\n\n# Related Corpora"]
    for entry, score in entries_with_scores:
        summary_one_line = " ".join(entry.summary.split())
        if mode == "semantic":
            parts.append(
                f"  - [entry:{entry.entry_id.replace('-', '')}] "
                f"(sim={score:.2f}) [{entry.section}] {summary_one_line}"
            )
        else:
            parts.append(
                f"  - [entry:{entry.entry_id.replace('-', '')}] "
                f"(p={score:.2f}) [{entry.section}] {summary_one_line}"
            )

    if len(parts) <= 1:
        return ""
    return "\n".join(parts)


def _get_related_corpora(
    db: BlackboardDatabase,
    cc: CartographerConfig,
    active_corpus_key: str,
) -> list[str]:
    """Resolve related corpus keys from config or auto-discover."""
    if not cc.cross_corpus_enabled:
        return []
    if cc.cross_corpus_auto_discover:
        all_keys = db.get_all_corpus_keys()
        return [k for k in all_keys if k != active_corpus_key]
    return cc.cross_corpus_related_corpora.get(active_corpus_key, [])


def _priority_entries(
    db: BlackboardDatabase,
    cc: CartographerConfig,
    corpus_key: str,
) -> list[tuple[MapEntry, float]]:
    """Fetch entries for a corpus, filtered by min_priority, sorted by priority."""
    entries = db.get_context_map(corpus_key) or []
    filtered = [e for e in entries if e.priority >= cc.cross_corpus_min_priority]
    filtered.sort(key=lambda e: -e.priority)
    capped = filtered[: cc.cross_corpus_max_entries]
    return [(e, e.priority) for e in capped]
