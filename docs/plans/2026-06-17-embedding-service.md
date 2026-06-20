# Spec: External Embedding Service

**Date**: 2026-06-17
**Status**: parked (awaiting cycle)

## Context

The harness loads `mixedbread-ai/mxbai-embed-large-v1` (~1.3 GB) via `sentence-transformers` in-process. This happens during `build_app_state()` auto-indexing and again whenever `search_documents` or `index_documents` skills run. Each cold load takes 4–12 seconds. During eval runs (16 tasks calling `build_app_state()` per task pre-fix), this was the dominant startup cost.

The eval runner was fixed to call `build_app_state()` once (2026-06-17), but the underlying architecture still couples the harness process lifecycle to the embedding model lifecycle.

## Problem

- Model loads on every harness process start (cold start penalty)
- Model occupies GPU memory in the harness process
- Harness restart = model reload
- The Vespa retrieval service already follows the external-service pattern; the embedding model should too

## Proposed Solution

A small HTTP service wrapping `SentenceTransformer` behind a single `/embed` endpoint. The `TextEmbedder` class gains a remote backend (HTTP client) behind the same interface. Callers are unchanged.

### Architecture

```
┌──────────────┐     HTTP POST /embed     ┌──────────────────┐
│   Harness    │ ──────────────────────▶  │  Embedding       │
│  TextEmbedder│ ◀──────────────────────  │  Service         │
│  (client)    │     {"embeddings": [...]} │  (container)     │
└──────────────┘                          │  port 8765       │
                                          │  GPU or CPU      │
                                          └──────────────────┘
```

### Files

| File | Purpose |
|---|---|
| `harness_poc/services/embedding_service.py` | FastAPI app, `/embed` POST endpoint |
| `Dockerfile.embedder` | Container image with `sentence-transformers` + model |
| `harness_poc/core/retrieval/embedder.py` | Add `RemoteEmbedder` class; `TextEmbedder` becomes factory |
| `harness_poc/core/config.py` | Add `embedding_url: str | None` to `RetrievalConfig` |
| `compose.yaml` | Add `embedder` service |

### API

```
POST /embed
Body:   {"texts": ["hello world", "foo bar"]}
Return: {"embeddings": [[0.123, ...], [0.456, ...]], "dim": 1024}
```

### Callers (zero changes)

All 4 call sites construct `TextEmbedder()` — they get the local backend when `embedding_url` is unset, remote when configured:

- `app_factory.py:279` — auto-index
- `skills/index_documents/skill.py:39` — on-demand indexing
- `skills/search_documents/skill.py:71` — semantic/hybrid search
- `context_map/copt_gate.py` — separate MiniLM model, out of scope for this spec

### Estimate

~80 lines of code, ~30 minutes of implementation.

## Decision

Parked 2026-06-17. The immediate pain point (16 model loads per eval run) was fixed by hoisting `build_app_state()` into a one-shot call. This spec remains for a future cycle when cold-start latency reduction becomes a priority.
