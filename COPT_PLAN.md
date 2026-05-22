# CopT Gate: Context-aware Observation Processing & Throttling

## What & Why

Every materializer cycle calls **two LLMs** — Distiller then Cartographer. In practice, most event batches produce observations the agent has already seen. The second LLM call (Cartographer) wastes tokens when nothing is new.

**CopT** adds a cheap vector-similarity gate between Distiller and Cartographer. If the Distiller's observations are semantically redundant with the existing context map, Cartographer is skipped entirely. This cuts token consumption per boring batch by ~60–70%.

## The Gate

```
Events ──▶ Distiller ──▶ [CopT Gate] ──▶ Cartographer ──▶ Evictor ──▶ Map write
                              │                                  ▲
                              │ (skip if redundant)              │
                              └──────────────────────────────────┘
```

The gate:

1. Takes the Distiller's raw observations
2. Computes a 384-dim embedding for each
3. Queries pgvector for the most similar existing map entry per observation
4. If **all** observations have a match above `threshold` (default 0.92), the entire Cartographer pass is skipped
5. Events are marked processed, map is untouched, freeze timer resets

## Why pgvector, not Vespa

|                     | Vespa (existing)                    | pgvector (proposed)                   |
| ------------------- | ----------------------------------- | ------------------------------------- |
| **Stores**          | Document chunks from project files  | Distilled agent observations          |
| **Schema**          | 1024-dim tensors, BM25 fields       | 384-dim vectors, entry metadata       |
| **Consumer**        | Agent via `search_documents()` tool | Materializer pipeline (internal only) |
| **Lifecycle**       | Static — indexed once per file      | Ephemeral — evolves per batch         |
| **Embedding model** | Vespa-side HuggingFace pipeline     | Local `all-MiniLM-L6-v2` (CPU)        |

**No overlap.** These are different data with different purposes. The agent never touches the embeddings table. CopT is a private optimization inside the materializer — zero visibility to the agent, zero impact on Vespa queries.

## Why `all-MiniLM-L6-v2` (384-dim)

- Runs on CPU in ~2ms per string — no GPU, no latency concern
- Well-calibrated cosine similarity for short text (observations are 1–3 sentences)
- Same model family as many Vespa embedders, so dimensional alignment exists if we ever need cross-system queries
- 384-dim is half the size of Vespa's 1024-dim — faster queries, smaller table

## What changes

1. **One new table**: `context_map_embeddings` with a `VECTOR(384)` column
2. **One migration**: `CREATE EXTENSION IF NOT EXISTS vector` (handled at startup like the existing freeze column migration)
3. **One dependency**: `sentence-transformers` (pyproject.toml, optional — only imported on PostgreSQL)
4. **One config field**: `materializer_copt_threshold` in harness.yaml runtime section
5. **One insertion point**: ~15 lines in `skill.py` between Distiller and Cartographer calls
6. **One embedding sync**: after successful Cartographer → Evictor, upsert embeddings for new/changed entries

## SQLite path

The gate is disabled on SQLite (tests, dev):

```python
if db._engine.dialect.name == "sqlite":
    return False  # always run Cartographer
```

No `sentence-transformers`, no pgvector migration. Tests continue unchanged.

## Risks & Mitigations

| Risk                                                              | Mitigation                                                                                                                                                    |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gate fires when it shouldn't (false positive — misses novel info) | Default threshold 0.92 is conservative; tune via config. Worst case: stale map, recovered next batch.                                                         |
| Gate doesn't fire when it should (false negative — no savings)    | Zero correctness risk, just the usual cost.                                                                                                                   |
| `sentence-transformers` is slow to install                        | Lazy-imported, only on PostgreSQL. Container image handles it once.                                                                                           |
| Embedding drift over time                                         | Embeddings recomputed on every Cartographer run; stale entries from skipped runs are harmless (they're just not re-embedded until the next non-skipped pass). |

## Token savings model

| Scenario                     | Distiller  | Gate           | Cartographer     | Total            |
| ---------------------------- | ---------- | -------------- | ---------------- | ---------------- |
| Boring batch (all redundant) | 500 tokens | ~5ms, 0 tokens | **skipped**      | **500 tokens**   |
| Novel batch (new info)       | 500 tokens | ~5ms           | 1000–2000 tokens | 1500–2500 tokens |

At the current ~30s poll interval, most batches are boring. Savings compound over long-running sessions.
