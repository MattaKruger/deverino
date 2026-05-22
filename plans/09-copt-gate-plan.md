# Plan: CopT Gate for Context Map Materializer

**Date:** 2025-07-16
**Status:** Proposed
**Primary DB:** PostgreSQL (SQLite is fallback for `pytest`)

---

## Problem

The context map materializer runs **two LLM calls per batch**:

```
Events → Distiller (LLM) → Cartographer (LLM) → Evictor → Write
```

Most batches are boring — the agent re-learns what it already knows. But every batch pays the full Cartographer cost (~1000–2000 tokens). Over hundreds of sessions, this is significant wasted spend and latency.

**Goal:** Skip the Cartographer when the Distiller's observations are redundant with the existing context map. Reduce LLM calls from 2 to 1 for boring batches.

## Approach

Insert a **CopT gate** (Cosine-over-Threshold) between Distiller and Cartographer. The gate:

1. Takes the Distiller's observations (plain-text facts like "user prefers pytest fixtures")
2. Embeds them with a lightweight local model (`all-MiniLM-L6-v2`, 384-dim, CPU, ~2ms per string)
3. Queries pgvector for the most similar existing entry in the context map
4. **Skips Cartographer entirely** if `max_similarity > threshold` (default 0.92)

```
Events → Distiller (LLM) → [CopT Gate: pgvector check] ──── skip → mark processed, return
                                   │ (novel info)
                                   ▼
                              Cartographer (LLM) → Evictor → Write
```

## Why pgvector (not a second LLM call)

| Approach | Cost per boring batch | Latency | Complexity |
|---|---|---|---|
| Ask LLM "is this redundant?" | 500–1000 tokens | ~3s | Low |
| **pgvector cosine similarity** | **~5ms** | **~5ms** | Moderate |
| Hash-based dedup | 0 tokens | 0ms | Low, but can't detect semantic near-duplicates |

The LLM-as-judge approach costs almost as much as running Cartographer — defeating the purpose. pgvector is near-free.

## Why all-MiniLM-L6-v2 (not Vespa's embedder)

Vespa uses a 1024-dim HuggingFace embedder configured server-side. Hitting Vespa just to embed 2–5 short strings per batch is heavy (HTTP round-trip + queue). A local CPU model avoids network calls and stays fast. The 384-dim MiniLM is the standard for this use case — same family as Sentence-BERT, runs anywhere.

The dimensions don't need to match Vespa — they serve different data:
- Vespa: document chunks → RAG for agents
- pgvector: agent observations → materializer internal gate

## What stays unchanged

| Component | Status |
|---|---|
| `DbContextMap` table | Unchanged |
| `DbContextMapEvent` table | Unchanged |
| Distiller prompt | Unchanged |
| Cartographer prompt | Unchanged |
| Evictor logic | Unchanged |
| `write_map_and_mark_processed()` | Unchanged |
| Vespa document retrieval | Unchanged |
| All agent tools (`search_documents`, etc.) | Unchanged |
| SQLite test suite | Unchanged (gate disabled on SQLite) |

## What changes

| File | Change |
|---|---|
| `harness_poc/core/models.py` | +1 table: `DbContextMapEmbedding` with pgvector column |
| `harness_poc/core/database.py` | +3 methods on `BlackboardDatabase`: `copt_upsert_embeddings()`, `copt_query_similarity()`, `copt_ensure_schema()` |
| `harness_poc/core/db_engine.py` | Load pgvector extension on PostgreSQL connect |
| `skills/context-map-materializer/skill.py` | +CopT gate after Distiller, +embedding upsert after Cartographer |
| `harness_poc/core/config.py` | +1 field: `materializer_copt_threshold` |
| `harness.yaml` (project root) | Optional new config key |
| `requirements.txt` | +`sentence-transformers` |

## Success criteria

1. **Boring batches**: 1 LLM call instead of 2. Map unchanged, events marked processed.
2. **Novel batches**: Same behavior as today (2 LLM calls), plus embeddings persisted for future batches.
3. **Zero false skips**: The gate uses a conservative default (0.92). Real differences — even subtle ones — should score well below the threshold.
4. **SQLite tests pass**: Gate is a no-op on SQLite. Existing test suite runs without `sentence-transformers`.
5. **Latency**: Embedding + pgvector query adds <50ms per batch when gate fires. No perceivable impact on agent session time.

## Non-goals

- Not replacing Vespa for document retrieval
- Not adding vector search as an agent-accessible tool
- Not doing any cross-system queries (Vespa ↔ pgvector)
- Not adding an embedding model download pipeline — `sentence-transformers` handles this with its own cache
