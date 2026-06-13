# Vespa Document Retrieval — Handoff

**Plan:** `docs/superpowers/plans/2026-05-20-vespa-document-retrieval.md`
**Branch:** main
**Date:** 2026-05-20

## Completed Tasks ✅

| Task | Commit | What was done |
|------|--------|---------------|
| 1 | 56bcb72 | `RetrievalConfig` frozen dataclass in `config.py`, `retrieval:` section in `harness.yaml`, `pyvespa>=0.43.0` in `pyproject.toml`, `tests/test_config.py` |
| 2 | 75c0360 | `DbDocumentSource` + `DbDocumentChunk` SQLModel tables in `models.py`, `tests/test_document_models.py` |
| 3 | da42da2 | `upsert_document_source`, `get_document_source`, `list_document_sources`, `upsert_document_chunk`, `list_chunks_for_source` in `BlackboardDatabase`, `tests/test_document_db.py` |
| 4 | 9b24efb | Proxy methods in `BlackboardAccessProxy` (read-guarded: get/list, write-guarded: upsert), added to `tests/test_blackboard_proxy.py` |
| 5 | b812d8c | `harness_poc/core/retrieval.py`: `DocumentChunk`, `SearchResult`, `SearchRequest`, `FeedSummary`, `VespaDocumentClient` Protocol, `chunk_text`, `make_source_id`, `make_chunk_id`, `compute_content_hash`, `make_document_chunks`. `tests/test_retrieval_chunking.py` |
| 6 | e2d46d2 | `vespa/document_retrieval/services.xml` (HuggingFace embedder, container+content cluster), `vespa/document_retrieval/schemas/doc_chunk.sd` (schema + 3 rank profiles) |

## Remaining Tasks

### Task 7: VespaDocumentClient (pyvespa adapter)

Create **`harness_poc/core/vespa_client.py`** and **`tests/test_vespa_client.py`**.

The test file must include a `FakeVespaClient` class that other tests (Tasks 8-10) import via `from tests.test_vespa_client import FakeVespaClient`.

**`harness_poc/core/vespa_client.py`** — full content:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from harness_poc.core.config import RetrievalConfig

from harness_poc.core.retrieval import (
    DocumentChunk,
    FeedSummary,
    SearchRequest,
    SearchResult,
)


class LiveVespaDocumentClient:
    """Thin pyvespa adapter implementing the VespaDocumentClient protocol."""

    def __init__(self, config: RetrievalConfig) -> None:
        self._url = config.vespa_url
        self._namespace = config.namespace
        self._schema = config.schema
        self._max_workers = config.max_feed_workers
        self._timeout = config.query_timeout_seconds

    def health_check(self) -> None:
        from vespa.application import Vespa
        app = Vespa(url=self._url)
        response = app.get_application_status()
        if response.status_code != 200:
            raise RuntimeError(f"Vespa health check failed: HTTP {response.status_code}")

    def feed_chunks(self, chunks: Iterable[DocumentChunk]) -> FeedSummary:
        from vespa.application import Vespa
        app = Vespa(url=self._url)
        fed = 0
        failed = 0
        failed_ids: list[str] = []
        with app.syncio(connections=self._max_workers) as session:
            for chunk in chunks:
                fields = {
                    "source_id": chunk.source_id,
                    "uri": chunk.uri,
                    "title": chunk.title,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "kind": chunk.kind,
                    "content_hash": chunk.content_hash,
                    "updated_at": chunk.updated_at,
                }
                response = session.feed_data_point(
                    schema=self._schema,
                    data_id=chunk.chunk_id,
                    fields=fields,
                    namespace=self._namespace,
                )
                if response.status_code in (200, 201):
                    fed += 1
                else:
                    failed += 1
                    failed_ids.append(chunk.chunk_id)
        return FeedSummary(fed=fed, failed=failed, failed_ids=failed_ids)

    def delete_source(self, source_id: str) -> None:
        from vespa.application import Vespa
        app = Vespa(url=self._url)
        with app.syncio() as session:
            result = session.query(
                body={
                    "yql": f"select chunk_id from {self._schema} where source_id = @source_id",
                    "source_id": source_id,
                    "hits": 10_000,
                    "timeout": str(self._timeout),
                }
            )
            for hit in result.hits:
                chunk_id = hit["fields"]["chunk_id"]
                session.delete_data(
                    schema=self._schema,
                    data_id=chunk_id,
                    namespace=self._namespace,
                )

    def search(self, request: SearchRequest) -> list[SearchResult]:
        from vespa.application import Vespa
        body = _build_query_body(request, schema=self._schema, timeout=self._timeout)
        app = Vespa(url=self._url)
        with app.syncio() as session:
            result = session.query(body=body)
        return [_normalize_hit(h) for h in result.hits]


def _build_query_body(request: SearchRequest, schema: str, timeout: int) -> dict:
    filter_clauses: list[str] = []
    extra_params: dict = {}

    if request.source_id:
        filter_clauses.append("source_id = @filter_source_id")
        extra_params["filter_source_id"] = request.source_id
    if request.kind:
        filter_clauses.append("kind = @filter_kind")
        extra_params["filter_kind"] = request.kind

    filter_str = (" and " + " and ".join(filter_clauses)) if filter_clauses else ""

    if request.mode == "keyword":
        where = f"default contains ({{targetHits:100}}text(@query)){filter_str}"
        body: dict = {
            "yql": f"select * from {schema} where {where}",
            "query": request.query,
            "ranking.profile": "keyword",
            "hits": request.hits,
            "timeout": str(timeout),
        }
    elif request.mode == "semantic":
        where = f"({{targetHits:20}}nearestNeighbor(embedding,q)){filter_str}"
        body = {
            "yql": f"select * from {schema} where {where}",
            "query": request.query,
            "input.query(q)": "embed(@query)",
            "ranking.profile": "semantic",
            "hits": request.hits,
            "timeout": str(timeout),
        }
    else:  # hybrid
        where = (
            f"(default contains ({{targetHits:100}}text(@query))"
            f" or ({{targetHits:20}}nearestNeighbor(embedding,q))){filter_str}"
        )
        body = {
            "yql": f"select * from {schema} where {where}",
            "query": request.query,
            "input.query(q)": "embed(@query)",
            "ranking.profile": "hybrid",
            "hits": request.hits,
            "timeout": str(timeout),
        }

    body.update(extra_params)
    return body


def _normalize_hit(hit: dict) -> SearchResult:
    fields = hit.get("fields", {})
    return SearchResult(
        source_id=str(fields.get("source_id", "")),
        uri=str(fields.get("uri", "")),
        title=str(fields.get("title", "")),
        chunk_id=str(fields.get("chunk_id", "")),
        chunk_index=int(fields.get("chunk_index", 0)),
        text=str(fields.get("text", "")),
        relevance=float(hit.get("relevance", 0.0)),
        kind=str(fields.get("kind", "")),
    )
```

**`tests/test_vespa_client.py`** — tests + FakeVespaClient used by later tasks:

```python
from __future__ import annotations

from typing import Iterable

import pytest

from harness_poc.core.retrieval import (
    DocumentChunk,
    FeedSummary,
    SearchRequest,
    SearchResult,
    VespaDocumentClient,
)
from harness_poc.core.vespa_client import LiveVespaDocumentClient, _build_query_body, _normalize_hit


class FakeVespaClient:
    """In-memory Vespa substitute for unit tests. Imported by test_document_index, test_index_documents, test_search_documents."""

    def __init__(self, healthy: bool = True) -> None:
        self._healthy = healthy
        self._docs: dict[str, DocumentChunk] = {}
        self.fed_ids: list[str] = []
        self.deleted_sources: list[str] = []

    def health_check(self) -> None:
        if not self._healthy:
            raise RuntimeError("Vespa unavailable")

    def feed_chunks(self, chunks: Iterable[DocumentChunk]) -> FeedSummary:
        fed = 0
        for chunk in chunks:
            self._docs[chunk.chunk_id] = chunk
            self.fed_ids.append(chunk.chunk_id)
            fed += 1
        return FeedSummary(fed=fed, failed=0, failed_ids=[])

    def delete_source(self, source_id: str) -> None:
        self.deleted_sources.append(source_id)
        to_del = [k for k, v in self._docs.items() if v.source_id == source_id]
        for k in to_del:
            del self._docs[k]

    def search(self, request: SearchRequest) -> list[SearchResult]:
        results = [
            SearchResult(
                source_id=c.source_id,
                uri=c.uri,
                title=c.title,
                chunk_id=c.chunk_id,
                chunk_index=c.chunk_index,
                text=c.text,
                relevance=1.0,
                kind=c.kind,
            )
            for c in self._docs.values()
            if request.query.lower() in c.text.lower()
        ]
        return results[: request.hits]


def test_fake_client_satisfies_protocol() -> None:
    assert isinstance(FakeVespaClient(), VespaDocumentClient)


def test_live_client_satisfies_protocol() -> None:
    from harness_poc.core.config import RetrievalConfig
    client = LiveVespaDocumentClient(RetrievalConfig())
    assert isinstance(client, VespaDocumentClient)


def test_build_query_body_keyword() -> None:
    req = SearchRequest(query="state machine", mode="keyword", hits=5)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["ranking.profile"] == "keyword"
    assert "@query" in body["yql"]
    assert "nearestNeighbor" not in body["yql"]
    assert body["query"] == "state machine"
    assert body["hits"] == 5


def test_build_query_body_semantic() -> None:
    req = SearchRequest(query="how memory works", mode="semantic", hits=8)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["ranking.profile"] == "semantic"
    assert "nearestNeighbor" in body["yql"]
    assert body["input.query(q)"] == "embed(@query)"
    assert "text(@query)" not in body["yql"]


def test_build_query_body_hybrid() -> None:
    req = SearchRequest(query="memory", mode="hybrid", hits=8)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["ranking.profile"] == "hybrid"
    assert "nearestNeighbor" in body["yql"]
    assert "text(@query)" in body["yql"]


def test_build_query_body_source_filter() -> None:
    req = SearchRequest(query="x", mode="keyword", hits=5, source_id="docs-foo-md")
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["filter_source_id"] == "docs-foo-md"
    assert "@filter_source_id" in body["yql"]


def test_build_query_body_kind_filter() -> None:
    req = SearchRequest(query="x", mode="keyword", hits=5, kind="spec")
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["filter_kind"] == "spec"


def test_normalize_hit_extracts_fields() -> None:
    raw_hit = {
        "id": "id:deverino:doc_chunk::docs-foo-md-0001",
        "relevance": 0.87,
        "fields": {
            "source_id": "docs-foo-md",
            "uri": "docs/foo.md",
            "title": "Foo",
            "chunk_id": "docs-foo-md-0001",
            "chunk_index": 1,
            "text": "Some text here.",
            "kind": "doc",
        },
    }
    result = _normalize_hit(raw_hit)
    assert result.source_id == "docs-foo-md"
    assert result.uri == "docs/foo.md"
    assert result.relevance == pytest.approx(0.87)
    assert result.chunk_index == 1


def test_normalize_hit_missing_fields_defaults() -> None:
    raw_hit = {"id": "id:ns:schema::x", "relevance": 0.0, "fields": {}}
    result = _normalize_hit(raw_hit)
    assert result.source_id == ""
    assert result.text == ""
    assert result.relevance == 0.0
```

**Verification:** `uv run pytest tests/test_vespa_client.py -v` — all tests should pass with no live Vespa.
**Commit message:** `"feat: add LiveVespaDocumentClient, query body builder, and hit normalizer"`

---

### Task 8: DocumentIndexer

Create **`harness_poc/core/document_index.py`** and **`tests/test_document_index.py`**.

See plan Task 8 for full code. Key points:
- `DocumentIndexer(config, database, vespa_client)` class with `index_paths(project_root, paths, glob_pattern, force) -> IndexResult`
- Health-check first; mark source `failed` on health-check failure
- Skip files not in `SUPPORTED_EXTENSIONS = frozenset({".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".py"})`
- Skip if content hash unchanged and `force=False` → status `"skipped"`
- Ignore dirs: `.git`, `.venv`, `__pycache__`, `.deverino-scratch`
- Reject paths outside project root
- `IndexResult` dataclass with: indexed, skipped, failed, chunks_indexed, failures (list of dicts)
- Tests import `FakeVespaClient` from `tests.test_vespa_client`
- **Commit message:** `"feat: add DocumentIndexer with skip-on-hash, path allowlist, and ignored dir logic"`

---

### Task 9: index_documents skill

Create:
- **`skills/index_documents/SKILL.md`** — YAML frontmatter with name, type=tool, auto_invokable=false, parameters (paths array required, glob optional, force bool optional), permissions blackboard=read_write workspace=read
- **`skills/index_documents/skill.py`** — `execute(ctx, arguments) -> SkillResult`; checks `ctx.config.retrieval.enabled`; creates `LiveVespaDocumentClient` + `DocumentIndexer`; returns artifacts: indexed/skipped/failed/chunks_indexed/failures
- **`tests/test_index_documents.py`** — test disabled returns failed; test result has correct artifact keys; patch `LiveVespaDocumentClient` with `FakeVespaClient`
- **Commit message:** `"feat: add index_documents skill"`

---

### Task 10: search_documents skill

Create:
- **`skills/search_documents/SKILL.md`** — type=tool, auto_invokable=true, parameters (query required, hits/mode/source_id/kind optional), permissions blackboard=read workspace=none
- **`skills/search_documents/skill.py`** — `execute(ctx, arguments) -> SkillResult`; validates query non-empty and mode in {hybrid,semantic,keyword}; uses config defaults for hits/mode; citation-first content format: `"N. uri#chunk-N (score X.XX)\n   text excerpt"`; truncates to `ctx.config.runtime.tool_result_max_chars`; artifacts: query/mode/results list
- **`tests/test_search_documents.py`** — test disabled/empty-query/invalid-mode return failed; test citation format; test config defaults used
- **Commit message:** `"feat: add search_documents skill with citation-first formatting and config-driven defaults"`

---

### Task 11: Integration test (opt-in)

Create **`tests/test_vespa_integration.py`** — all tests skipped unless `VESPA_INTEGRATION=1` env var set. Tests: health_check, feed+keyword search, feed+semantic search, feed+hybrid search, delete_source. Uses `FakeVespaClient` fixture in module scope, cleans up after.
- **Commit message:** `"test: add opt-in live Vespa integration test"`

---

## How to continue

Read the full plan at `docs/superpowers/plans/2026-05-20-vespa-document-retrieval.md` for complete code. Then execute Tasks 7–11 using `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

After all tasks done, run:
```bash
uv run ruff check .
uv run ty check
uv run pytest --ignore=tests/test_vespa_integration.py -q
```
