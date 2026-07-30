# Retrieval Design — Top-Tier RAG for the Deverino Harness

- **Status:** Design (Phase 0 ready for implementation)
- **Date:** 2026-06-23
- **Scope:** Vespa-backed document retrieval + PDF→text pipeline
- **Related:** `docs/plans/2026-06-17-embedding-service.md`, `docs/plans/2026-06-14-top-tier-hardening.md`

## 1. Problem

The retrieval subsystem indexes `docs/` (markdown, text, PDFs, code) into Vespa and serves hybrid/semantic/keyword search to the agent as a tool. A gap analysis (§2) found durability, accuracy, and consistency issues. This design hardens the pipeline along five dimensions — **durability, syncability, maintainability, accuracy, speed** — targeting top-tier agentic RAG.

Current pipeline lives in `harness_poc/core/retrieval/` (`retrieval.py`, `vespa_client.py`, `embedder.py`, `document_index.py`, `pdf_converter.py`); Vespa app package in `vespa/document_retrieval/`; OCR service in `scripts/ocr_service.py`.

## 2. Key gaps (from analysis)

- **Not rebuildable.** `DbDocumentChunk` (`harness_poc/core/storage/models.py:134-143`) stores only metadata — no text, no embedding. Vespa data loss requires re-parsing every source.
- **Index drift.** `changed_indexable_uris` (`document_index.py:79-123`) only walks on-disk files; deleted files leave orphan chunks in Vespa forever. No prune/reconcile.
- **PDF chunking.** pymupdf path uses 0 overlap + naive char windows, ignores `chunk_overlap_chars`, loses structure (`pdf_converter.py:70-79`). `chunk_size_chars` is consumed as a token limit by docling (`document_index.py:332`) — unit mismatch.
- **Hybrid ranking.** Multiplicative `closeness*(1+bm25)`, uncalibrated, bm25 scale dominates (`vespa/document_retrieval/schemas/doc_chunk.sd:72-79`).
- **OCR disabled** despite the "OCR service" naming (`pdf_converter.py:141`, `scripts/ocr_service.py:57`).
- **Dead/misleading code.** `embed_query` (`embedder.py:159`) uses a jina prompt invalid for the Snowflake model; never called. Stale jina docstrings throughout `embedder.py`.
- **Feed reliability.** No retry; partial-failure state ambiguous (`vespa_client.py:71-88`); `max_feed_workers` pinned to 1 (`harness.yaml:65`).

Note: a test suite already exists under `tests/retrieval/` (incl. `FakeVespaClient`); the real test gap is the absence of **retrieval-quality/accuracy** tests and **live ranking** assertions — not "zero tests."

## 3. Decisions (locked)

1. **Stay on Vespa** — enterprise-grade, extensible. Postgres+pgvector is the canonical manifest; Vespa is a rebuildable projection.
2. **pymupdf for digital PDFs only** — structural chunking derives from `page.get_text("dict")`, not docling. Scanned/image PDFs are out of scope (fail loudly, no OCR).
3. **Accuracy-first** — retrieve 100 → RRF → cross-encoder rerank top-20 → return top-8 (~250–400ms warm). Configurable.
4. **Git-aware sync** — `git diff --name-status <last_sha> HEAD` drives add/modify/delete; SHA stored as a project fact.

## 4. Architecture

**Principle:** Postgres is the source of truth; Vespa is a derived, rebuildable projection.

```
sources (git-tracked) + state
   │  extract + structural chunk          ← pymupdf dict / AST / md headers
   ▼
Postgres: document_chunks(text, embedding vector(1024), parent_id, parent_text,
                          heading_path, schema_version)        ← canonical, transactional
   │  project (feed, idempotent upsert by chunk_id)
   ▼
Vespa: doc_chunk + match-features(bm25, closeness)
   │
   ▼  top-100 → RRF → cross-encoder top-20 → top-8 + parent_text → agent
   ▲
   └── documents rebuild (from Postgres, no re-extract/re-embed)
```

- Extract + chunk → persist to Postgres (transactional: text + embedding + parent) → project to Vespa (idempotent upsert by `chunk_id`).
- Vespa is disposable: `documents rebuild` re-feeds from Postgres without re-extracting/re-embedding.
- pgvector is already proven in this repo via the CopT gate (`database.py:967` `copt_ensure_schema`; `_serialize_embedding` at `database.py:1092`); reuse that pattern.

## 5. Phase 0 — Canonical store + sync foundation

### 5.1 Schema

Extend `DbDocumentChunk` (`models.py:134-143`) with columns added via raw SQL like `copt_ensure_schema` (`database.py:967`), reusing `_serialize_embedding` (`database.py:1092`):

```
# document_chunks  (existing)        →  (added)
chunk_id (pk), source_id, chunk_index, content_hash, vespa_id, indexed_at,
text TEXT NOT NULL,                  # NEW — makes Vespa rebuildable
embedding vector(1024),             # NEW — pgvector, reuse CopT pattern
parent_id TEXT,                      # NEW — small-to-big retrieval
parent_text TEXT,                    # NEW — context returned to agent
heading_path TEXT,                   # NEW — breadcrumb, per-chunk title
schema_version INT NOT NULL DEFAULT 1  # NEW — safe rebuild on schema change
```

### 5.2 Write order

`_index_one_isolated` (`document_index.py:270`) persists to Postgres **first** (transactional), then feeds Vespa. Vespa feed failure no longer corrupts canonical state.

### 5.3 Commands (CLI `documents *`)

- `documents rebuild` — re-feed Vespa from Postgres (text+embedding already canonical). Fast, no re-parse. Makes Vespa disposable.
- `documents reconcile` — diff `document_sources` URIs vs git-tracked set; `delete_source` + drop rows for orphans. Closes the index-drift gap.
- `documents sync` — git-driven incremental (below).

**Git-aware sync** (replaces the hash-walk in `_resolve_files`, `document_index.py:459`):

```
last = db.get_project_fact("retrieval.last_indexed_commit")   # database.py:520
head = git("rev-parse", "HEAD")
if last is None: full index; db.set_project_fact(..., head); return
for status, path in git("diff", "--name-status", last, head):
    A/M → index path;  D → delete_source(make_source_id(path))
db.set_project_fact("retrieval.last_indexed_commit", head)    # database.py:494
```

Tracked-file set via `git ls-files` (respects `.gitignore` — no build artifacts). Thin git helper follows the `subprocess.run([...], capture_output=True, text=True, timeout=, check=False)` pattern from `file_tools._run_rg` (`harness_poc/system_tools/file_tools.py:199`). First run = full index; subsequent = diff only.

### 5.4 Feed reliability

`vespa_client.py:71-88`: bounded retry on 5xx/timeout (idempotent — Vespa upserts by `chunk_id`); a `pending`/`failed` sweeper resumes interrupted runs.

## 6. Phase 1 — Accuracy stack (under the pymupdf constraint)

1. **pymupdf structural chunker** — replaces `_extract_text_pymupdf` + the char-window call (`pdf_converter.py:70-79`). Use `page.get_text("dict")` → blocks → lines → spans with `size`/`flags`. Infer headings from font-size outliers + bold flag; maintain a heading breadcrumb. Chunk by blocks under the current heading up to target size, respecting page boundaries; carry the last block for overlap. Emits chunks directly with `heading_path` and `parent_id`/`parent_text` (the section) — like the old docling path did, but from pymupdf. Fixes the overlap=0, per-chunk-title, and char-vs-token gaps in one move.
2. **Other types** — `.py` → AST chunking (function/class boundaries); `.md` → header hierarchy. Same `parent_id` model.
3. **RRF fusion** — replaces the multiplicative `closeness*(1+bm25)` (`doc_chunk.sd:72-79`). Add `match-features: bm25(text), closeness(embedding)` to a rank profile; one query returns top-100 with both scores; client fuses by reciprocal rank. Scale-invariant.
4. **Cross-encoder rerank** (accuracy-first) — rerank the RRF top-20 with `BAAI/bge-reranker-v2-m3` (lazy-loaded like the embedder), return top-8 **with `parent_text`** for context. Configurable budget.
5. **Retrieval-quality eval** — reuse the existing `benchmark` pytest marker (`pyproject.toml`): a golden query→expected-source set. Makes "accurate" measurable instead of asserted.

## 7. Phase 2 — Live sync + speed

- Chunk-level incremental: per-chunk `content_hash` (already computed at `retrieval.py:75`); re-embed only changed chunks, not the whole file.
- Event-driven re-index on state writes (hook into `index_project_state`, `document_index.py:555`).
- Parallel async feed: raise `max_feed_workers` (currently 1, `harness.yaml:65`) once DB concurrency is verified safe.
- Observability: Logfire latency/freshness/failure metrics.

## 8. Dead code removal (given decisions)

With pymupdf-only + no OCR: `_convert_local_docling` (`pdf_converter.py:116`), `scripts/ocr_service.py`, and the `ocr_service_url` config field become vestigial. `docling`/`docling-core` deps likely removable (audit other uses first). Also delete `embed_query` and fix the jina docstrings (`embedder.py:1-10,159`).

## 9. Non-goals

- Scanned/image PDF OCR (out of scope by decision 2). Image-only PDFs fail with a clear "scanned PDF not supported" reason rather than silent "no content extracted".
- Replacing Vespa.

## 10. Open / future

- Re-rank budget tuning (100/20/8) informed by the eval harness.
- Parent granularity: section vs page.
- Whether `documents sync` should also handle untracked (non-git) files.
