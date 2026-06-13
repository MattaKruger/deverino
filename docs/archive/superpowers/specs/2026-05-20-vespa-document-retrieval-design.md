# Vespa Document Retrieval Design Spec

**Date:** 2026-05-20
**Status:** Draft

## Overview

Add document embedding and search to the agent harness using Vespa as the retrieval
engine and PostgreSQL as the control-plane database. PostgreSQL remains canonical for
sessions, state, proposals, event history, and indexing metadata. Vespa stores the
searchable document chunks, text indexes, embedding tensors, and ranking configuration.

The harness exposes retrieval through project skills first:

- `index_documents`: ingest local documents into Vespa and record indexing metadata in
  PostgreSQL.
- `search_documents`: run keyword, semantic, or hybrid search and return compact cited
  chunks to the agent.

This keeps retrieval aligned with the current skill/tool architecture and avoids
coupling the main REPL loop directly to Vespa.

## Problem

The harness currently has durable state and skill execution, but it does not have a
first-class document memory layer. The agent can inspect the workspace with code-search
style tools, but it cannot maintain an embedded, queryable index of docs, plans,
knowledge files, source-adjacent text, or other project artifacts.

The retrieval system must:

- search long-lived project documents without stuffing them into prompt history;
- support semantic queries, exact keyword queries, and hybrid ranking;
- return source-grounded chunks with stable citations;
- avoid storing large vectors in PostgreSQL;
- be rebuildable if the Vespa index is dropped.

## Goals

- Add configurable Vespa connection settings to `harness.yaml`.
- Add a Vespa application package for chunk-level document search.
- Add PostgreSQL-backed indexing metadata tables through SQLModel.
- Add a core retrieval client and indexer with testable boundaries.
- Add `index_documents` and `search_documents` project skills.
- Default retrieval mode to hybrid search: BM25 text matching plus nearest-neighbor
  embedding search.
- Keep indexing deterministic with stable source IDs, chunk IDs, and content hashes.
- Keep all live Vespa calls behind interfaces that can be faked in tests.

## Non-Goals

- Replacing PostgreSQL blackboard state with Vespa.
- Storing embedding vectors in PostgreSQL.
- Adding a hosted Vespa Cloud deployment path in the first pass.
- Indexing binary formats such as PDF, DOCX, images, or notebooks in the first pass.
- Building a reranker or answer synthesis layer in this pass.
- Automatically indexing every workspace change with file watchers.

## Architecture

### Ownership Split

| Layer | Owns |
|---|---|
| PostgreSQL | source metadata, content hashes, indexing status, failure details, timestamps |
| Vespa | chunk text, searchable fields, embedding tensor, HNSW index, rank profiles |
| Harness skills | user-facing ingestion and search tools |
| Core retrieval modules | chunking, ID generation, query construction, feed/search adapters |

### New Modules

| Module | Responsibility |
|---|---|
| `harness_poc/core/retrieval.py` | Typed retrieval models, chunking, source hashing, result normalization |
| `harness_poc/core/vespa_client.py` | Thin Vespa adapter for feed, delete, search, and health checks |
| `harness_poc/core/document_index.py` | Coordinates PostgreSQL metadata, chunking, and Vespa feeding |

### Modified Modules

| File | Change |
|---|---|
| `harness_poc/core/config.py` | Add `RetrievalConfig` and parse `retrieval:` from `harness.yaml` |
| `harness_poc/core/models.py` | Add document source and chunk metadata tables |
| `harness_poc/core/database.py` | Add document-index metadata read/write methods |
| `harness_poc/core/blackboard_proxy.py` | Mirror retrieval metadata methods with permission enforcement |
| `pyproject.toml` | Add `pyvespa` dependency |
| `harness.yaml` | Add local Vespa retrieval defaults |

### New Project Files

| Path | Purpose |
|---|---|
| `vespa/document_retrieval/services.xml` | Local Vespa service configuration |
| `vespa/document_retrieval/schemas/doc_chunk.sd` | Chunk schema, embedding field, rank profiles |
| `skills/index_documents/SKILL.md` | Tool metadata for document ingestion |
| `skills/index_documents/skill.py` | Skill implementation |
| `skills/search_documents/SKILL.md` | Tool metadata for document search |
| `skills/search_documents/skill.py` | Skill implementation |

## Configuration

### `harness.yaml`

```yaml
retrieval:
  enabled: true
  provider: vespa
  vespa_url: http://localhost:8080
  namespace: deverino
  schema: doc_chunk
  default_hits: 8
  default_mode: hybrid
  chunk_size_chars: 1800
  chunk_overlap_chars: 200
  max_feed_workers: 8
  query_timeout_seconds: 5
```

### `RetrievalConfig`

```python
@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    enabled: bool
    provider: str
    vespa_url: str
    namespace: str
    schema: str
    default_hits: int
    default_mode: str
    chunk_size_chars: int
    chunk_overlap_chars: int
    max_feed_workers: int
    query_timeout_seconds: int
```

Add `retrieval: RetrievalConfig` to `HarnessConfig`.

## Vespa Application Package

### Schema: `doc_chunk`

Use one Vespa document per chunk. This avoids multi-vector complexity in the first
implementation and makes source citations straightforward.

```vespa
schema doc_chunk {
    document doc_chunk {
        field source_id type string {
            indexing: summary | attribute
        }

        field uri type string {
            indexing: summary | attribute
        }

        field title type string {
            indexing: summary | index
        }

        field chunk_id type string {
            indexing: summary | attribute
        }

        field chunk_index type int {
            indexing: summary | attribute
        }

        field text type string {
            indexing: summary | index
        }

        field kind type string {
            indexing: summary | attribute
        }

        field content_hash type string {
            indexing: summary | attribute
        }

        field updated_at type long {
            indexing: summary | attribute
        }
    }

    field embedding type tensor<bfloat16>(x[384]) {
        indexing: input text | embed | attribute | index
        attribute {
            distance-metric: angular
        }
        index {
            hnsw {
                max-links-per-node: 16
                neighbors-to-explore-at-insert: 200
            }
        }
    }

    fieldset default {
        fields: title, text
    }

    rank-profile semantic {
        inputs {
            query(q) tensor<bfloat16>(x[384])
        }
        first-phase {
            expression: closeness(field, embedding)
        }
    }

    rank-profile keyword {
        first-phase {
            expression: bm25(title) + bm25(text)
        }
    }

    rank-profile hybrid {
        inputs {
            query(q) tensor<bfloat16>(x[384])
        }
        first-phase {
            expression: closeness(field, embedding) * (1 + bm25(title) + bm25(text))
        }
    }
}
```

The schema assumes a Vespa embedder is configured in `services.xml`, so the Python
harness feeds text and queries use `embed(@query)` rather than sending vectors over the
wire. A later provider abstraction can support Python-side embeddings if needed.

### Query Forms

Keyword:

```json
{
  "yql": "select * from doc_chunk where default contains ({targetHits:100}text(@query))",
  "query": "state consolidation",
  "ranking.profile": "keyword",
  "hits": 8
}
```

Semantic:

```json
{
  "yql": "select * from doc_chunk where ({targetHits:20}nearestNeighbor(embedding,q))",
  "query": "how persistent project memory is merged",
  "input.query(q)": "embed(@query)",
  "ranking.profile": "semantic",
  "hits": 8
}
```

Hybrid:

```json
{
  "yql": "select * from doc_chunk where default contains ({targetHits:100}text(@query)) or ({targetHits:20}nearestNeighbor(embedding,q))",
  "query": "how persistent project memory is merged",
  "input.query(q)": "embed(@query)",
  "ranking.profile": "hybrid",
  "hits": 8
}
```

All user text must be passed through query parameters such as `@query`; do not
interpolate raw user text into YQL.

## PostgreSQL Metadata

Add SQLModel tables for index control data only.

```python
class DbDocumentSource(SQLModel, table=True):
    __tablename__ = "document_sources"

    source_id: str = Field(primary_key=True)
    uri: str
    title: str
    kind: str
    content_hash: str
    status: str
    chunk_count: int
    indexed_at: str | None = None
    error: str | None = None
    metadata_payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    updated_at: str


class DbDocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("idx_document_chunks_source", "source_id", "chunk_index"),
    )

    chunk_id: str = Field(primary_key=True)
    source_id: str = Field(foreign_key="document_sources.source_id")
    chunk_index: int
    content_hash: str
    vespa_id: str
    indexed_at: str | None = None
```

Statuses:

| Status | Meaning |
|---|---|
| `pending` | metadata row exists but Vespa feed has not completed |
| `indexed` | all chunks were fed successfully |
| `skipped` | source hash unchanged and `force=false` |
| `failed` | ingestion or Vespa feed failed; `error` is populated |

Use `SQLModel.metadata.create_all()` as the initial migration mechanism, consistent with
the current proof-of-concept. If a formal migration system is introduced later, these
tables should be migrated normally.

## Core Retrieval API

### Domain Models

```python
@dataclass(frozen=True, slots=True)
class DocumentChunk:
    source_id: str
    uri: str
    title: str
    chunk_id: str
    chunk_index: int
    text: str
    kind: str
    content_hash: str
    updated_at: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    source_id: str
    uri: str
    title: str
    chunk_id: str
    chunk_index: int
    text: str
    relevance: float
    kind: str
```

### Vespa Client Interface

```python
class VespaDocumentClient:
    def health_check(self) -> None: ...
    def feed_chunks(self, chunks: Iterable[DocumentChunk]) -> FeedSummary: ...
    def delete_source(self, source_id: str) -> None: ...
    def search(self, request: SearchRequest) -> list[SearchResult]: ...
```

Implementation notes:

- Use `pyvespa` for feed and query calls.
- Convert chunk IDs to Vespa-safe document IDs.
- Return normalized `SearchResult` objects, not raw Vespa JSON.
- Keep timeouts and worker counts from `RetrievalConfig`.
- Surface partial feed failures as `FeedSummary.failed > 0`; the indexer decides how to
  mark PostgreSQL state.

### Indexer Flow

```text
index_documents(paths, force)
  - resolve paths under project root
  - read supported text files
  - compute source_id and content_hash
  - skip unchanged sources unless force=true
  - split into deterministic overlapping chunks
  - upsert PostgreSQL source status=pending
  - feed chunks to Vespa
  - upsert chunk metadata
  - update source status=indexed | failed | skipped
```

Supported first-pass extensions:

- `.md`
- `.txt`
- `.rst`
- `.yaml`
- `.yml`
- `.json`
- `.toml`
- `.py`

Path rules:

- Resolve all local paths under `config.project_root`.
- Reject paths outside the project root.
- Ignore `.git/`, `.venv/`, `__pycache__/`, `.deverino-scratch/`, and
  `harness_poc/blackboard.db`.
- Do not follow symlinks outside the project root.

## Skills

### `index_documents`

`SKILL.md`:

```yaml
---
name: index_documents
type: tool
description: Index project documents into Vespa for semantic and hybrid search.
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    paths:
      type: array
      items:
        type: string
      description: Files or directories to index, relative to the project root.
    glob:
      type: string
      description: Optional glob used when a path is a directory.
      default: "**/*"
    force:
      type: boolean
      description: Reindex sources even when their content hash has not changed.
      default: false
  required:
    - paths
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: read
---
```

Return artifacts:

```json
{
  "indexed": 12,
  "skipped": 4,
  "failed": 1,
  "chunks_indexed": 87,
  "failures": [
    {"uri": "docs/example.md", "error": "..."}
  ]
}
```

### `search_documents`

`SKILL.md`:

```yaml
---
name: search_documents
type: tool
description: Search indexed project documents with keyword, semantic, or hybrid retrieval.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query.
    hits:
      type: integer
      description: Maximum chunks to return.
      default: 8
    mode:
      type: string
      description: Retrieval mode.
      enum:
        - hybrid
        - semantic
        - keyword
      default: hybrid
    source_id:
      type: string
      description: Optional source filter.
    kind:
      type: string
      description: Optional document kind filter.
  required:
    - query
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read
  workspace: none
---
```

Human-readable content should be citation-first:

```text
1. docs/workflow-runtime-design.md#chunk-3 (score 0.82)
   ...chunk excerpt...

2. docs/superpowers/specs/2026-05-18-event-driven-agents-design.md#chunk-1 (score 0.76)
   ...chunk excerpt...
```

Return artifacts:

```json
{
  "query": "state consolidation",
  "mode": "hybrid",
  "results": [
    {
      "title": "Workflow Runtime Design",
      "uri": "docs/workflow-runtime-design.md",
      "chunk_id": "docs-workflow-runtime-design-md-0003",
      "chunk_index": 3,
      "relevance": 0.82,
      "text": "..."
    }
  ]
}
```

## Error Handling

- `retrieval.enabled=false`: retrieval skills return `failed` with a concise setup message.
- Vespa unavailable: `health_check()` fails quickly and the skill returns `failed`; no
  source rows are marked `indexed`.
- Partial feed failure: mark the source `failed`, retain the failure details, and report
  failed chunk IDs.
- Unsupported file type: skip and report under `skipped`.
- Oversized single file: stream/read with a configured maximum size; fail that source
  with a clear message.
- Invalid query mode: reject before calling Vespa.
- Empty query: reject before calling Vespa.
- Empty index: return success with zero results and a setup hint to run `index_documents`.

## Security

- Do not store API keys or Vespa credentials in `harness.yaml`.
- Keep all path ingestion scoped to the project root.
- Do not index `.env`, private keys, SQLite/PostgreSQL dumps, or other configured secret
  patterns.
- Pass user query text as Vespa query parameters, never direct YQL interpolation.
- Truncate skill output according to `runtime.tool_result_max_chars`; full raw chunks
  remain in Vespa, not in the prompt.

## Testing

### Unit Tests

| Test File | Coverage |
|---|---|
| `tests/test_retrieval_chunking.py` | deterministic chunk boundaries, overlap, hash stability |
| `tests/test_vespa_client.py` | query body construction and Vespa response normalization with fake responses |
| `tests/test_document_index.py` | skip unchanged sources, failure status, metadata writes |
| `tests/test_search_documents.py` | skill argument validation, mode handling, formatted results |
| `tests/test_index_documents.py` | path allowlist, unsupported files, result artifacts |
| `tests/test_config.py` | retrieval config defaults and YAML parsing |
| `tests/test_blackboard_proxy.py` | retrieval metadata methods respect blackboard permissions |

### Integration Tests

Live Vespa tests are opt-in:

```bash
VESPA_INTEGRATION=1 uv run pytest tests/test_vespa_integration.py
```

These tests should:

- deploy or assume a local Vespa app;
- feed a tiny fixture corpus;
- assert keyword, semantic, and hybrid queries return expected source IDs;
- clean up fixture documents after the run.

### Standard Verification

```bash
uv run ruff check .
uv run ty check
uv run pytest
```

## Rollout Plan

1. Add `RetrievalConfig` parsing and defaults.
2. Add PostgreSQL metadata models and proxy methods.
3. Add retrieval domain models and deterministic chunking.
4. Add the Vespa app package.
5. Add `VespaDocumentClient` with fakeable feed/search boundaries.
6. Add `index_documents` skill.
7. Add `search_documents` skill.
8. Add focused unit tests.
9. Add optional live Vespa integration test.
10. Document local Vespa startup/deploy commands in a follow-up README or docs note.

## Acceptance Criteria

- A user can configure a local Vespa endpoint in `harness.yaml`.
- A user can run `index_documents` against `docs/` and receive counts for indexed,
  skipped, and failed sources.
- PostgreSQL records source indexing state and can skip unchanged files.
- Vespa stores chunk text and embedding tensors; PostgreSQL does not store vectors.
- A user can run `search_documents` with `mode=keyword`, `mode=semantic`, or
  `mode=hybrid`.
- Search results include stable source citations and relevance scores.
- The LLM can auto-invoke `search_documents` during normal chat.
- Unit tests pass without a live Vespa instance.

## References

- Vespa embedding documentation: <https://docs.vespa.ai/en/rag/embedding.html>
- Vespa approximate nearest-neighbor and HNSW documentation:
  <https://docs.vespa.ai/en/querying/approximate-nn-hnsw.html>
- Vespa hybrid search tutorial: <https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html>
- PyVespa application API: <https://vespa-engine.github.io/pyvespa/api/vespa/application.html>
