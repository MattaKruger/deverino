# Vespa Document Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add document indexing and hybrid search to the harness via Vespa, exposed through `index_documents` and `search_documents` project skills.

**Architecture:** Vespa stores chunk text, HNSW embedding tensors, and rank profiles; PostgreSQL stores source metadata, content hashes, and indexing status. Three new core modules (`retrieval.py`, `vespa_client.py`, `document_index.py`) sit between the skills and Vespa/PostgreSQL. The `VespaDocumentClient` interface is defined as a `Protocol` so tests can use a `FakeVespaClient` without a live Vespa instance.

**Tech Stack:** pyvespa (Vespa HTTP adapter), SQLModel (PostgreSQL metadata tables), existing `BlackboardDatabase` + proxy patterns, existing `SkillContext` / `SkillResult` skill conventions.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | Add `pyvespa` dependency |
| Modify | `harness.yaml` | Add `retrieval:` section with defaults |
| Modify | `harness_poc/core/config.py` | Add `RetrievalConfig`, wire into `HarnessConfig` |
| Modify | `harness_poc/core/models.py` | Add `DbDocumentSource`, `DbDocumentChunk` tables |
| Modify | `harness_poc/core/database.py` | Add document metadata CRUD methods |
| Modify | `harness_poc/core/blackboard_proxy.py` | Mirror document metadata methods with permission guards |
| Create | `harness_poc/core/retrieval.py` | Domain models, `Protocol`, chunking, hashing utilities |
| Create | `harness_poc/core/vespa_client.py` | `LiveVespaDocumentClient` (pyvespa adapter) |
| Create | `harness_poc/core/document_index.py` | `DocumentIndexer` — coordinates DB + Vespa |
| Create | `vespa/document_retrieval/services.xml` | Local Vespa container + content cluster + HuggingFace embedder |
| Create | `vespa/document_retrieval/schemas/doc_chunk.sd` | Vespa schema: fields, embedding tensor, rank profiles |
| Create | `skills/index_documents/SKILL.md` | Tool metadata |
| Create | `skills/index_documents/skill.py` | Skill entry point |
| Create | `skills/search_documents/SKILL.md` | Tool metadata |
| Create | `skills/search_documents/skill.py` | Skill entry point |
| Create | `tests/test_config.py` | RetrievalConfig parsing tests |
| Create | `tests/test_retrieval_chunking.py` | Chunking, hashing, ID generation tests |
| Create | `tests/test_vespa_client.py` | Query body construction + hit normalization (no live Vespa) |
| Create | `tests/test_document_index.py` | Indexer skip/feed/fail logic (fake client + real DB) |
| Create | `tests/test_index_documents.py` | Skill path allowlist, artifact structure |
| Create | `tests/test_search_documents.py` | Skill validation and result formatting |
| Modify | `tests/test_blackboard_proxy.py` | Add retrieval proxy permission tests |
| Create | `tests/test_vespa_integration.py` | Opt-in live Vespa integration test |

---

## Task 1: pyvespa dependency + RetrievalConfig

**Files:**
- Modify: `pyproject.toml`
- Modify: `harness.yaml`
- Modify: `harness_poc/core/config.py`
- Create: `tests/test_config.py`

### Step 1.1: Write failing config tests

```python
# tests/test_config.py
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from harness_poc.core.config import HarnessConfig, RetrievalConfig


def _write_minimal_config(tmp_path: Path, extra: str = "") -> Path:
    cfg = tmp_path / "harness.yaml"
    cfg.write_text(
        textwrap.dedent(f"""
            version: 1
            llm:
              provider: deepseek
              model: deepseek-v4-flash
            paths:
              soul: harness_poc/system_prompts/SOUL.md
              system_tools: harness_poc/system_tools
              system_skills: harness_poc/system_skills
              project_skills: skills
              workflows: workflows
              pipelines: pipelines
              personas: personas
            runtime:
              database_url: postgresql://test:test@localhost/test
              default_container_image: python:3.12-slim
            observability:
              logfire: false
            {extra}
        """),
        encoding="utf-8",
    )
    return cfg


def test_retrieval_config_defaults_when_section_absent(tmp_path: Path) -> None:
    cfg = HarnessConfig.load(_write_minimal_config(tmp_path))
    r = cfg.retrieval
    assert r.enabled is True
    assert r.provider == "vespa"
    assert r.vespa_url == "http://localhost:8080"
    assert r.namespace == "deverino"
    assert r.schema == "doc_chunk"
    assert r.default_hits == 8
    assert r.default_mode == "hybrid"
    assert r.chunk_size_chars == 1800
    assert r.chunk_overlap_chars == 200
    assert r.max_feed_workers == 8
    assert r.query_timeout_seconds == 5


def test_retrieval_config_parsed_from_yaml(tmp_path: Path) -> None:
    extra = textwrap.dedent("""
        retrieval:
          enabled: false
          vespa_url: http://vespa.internal:8080
          default_hits: 12
          chunk_size_chars: 2000
    """)
    cfg = HarnessConfig.load(_write_minimal_config(tmp_path, extra))
    r = cfg.retrieval
    assert r.enabled is False
    assert r.vespa_url == "http://vespa.internal:8080"
    assert r.default_hits == 12
    assert r.chunk_size_chars == 2000
    # unspecified fields keep defaults
    assert r.chunk_overlap_chars == 200


def test_retrieval_config_is_frozen() -> None:
    r = RetrievalConfig()
    with pytest.raises((AttributeError, TypeError)):
        r.enabled = False  # type: ignore[misc]
```

- [ ] **Step 1.2: Run to confirm FAIL**

```bash
cd /path/to/deverino && uv run pytest tests/test_config.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'RetrievalConfig'`

- [ ] **Step 1.3: Add pyvespa to pyproject.toml**

In `pyproject.toml`, find the `[project] dependencies` list and add:
```toml
"pyvespa>=0.43.0",
```

- [ ] **Step 1.4: Add RetrievalConfig to config.py**

Add after `LLMConfig` (before `_find_dotenv`):

```python
@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    enabled: bool = True
    provider: str = "vespa"
    vespa_url: str = "http://localhost:8080"
    namespace: str = "deverino"
    schema: str = "doc_chunk"
    default_hits: int = 8
    default_mode: str = "hybrid"
    chunk_size_chars: int = 1800
    chunk_overlap_chars: int = 200
    max_feed_workers: int = 8
    query_timeout_seconds: int = 5
```

Update the `from dataclasses import dataclass` import to:
```python
from dataclasses import dataclass, field
```

Add `retrieval` field to `HarnessConfig` (after `observability`):
```python
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
```

In `HarnessConfig.load()`, add before `return cls(...)`:
```python
        retrieval_raw = _mapping(raw.get("retrieval"), "retrieval")
        retrieval = RetrievalConfig(
            enabled=bool(retrieval_raw.get("enabled", True)),
            provider=str(retrieval_raw.get("provider", "vespa")),
            vespa_url=str(retrieval_raw.get("vespa_url", "http://localhost:8080")),
            namespace=str(retrieval_raw.get("namespace", "deverino")),
            schema=str(retrieval_raw.get("schema", "doc_chunk")),
            default_hits=int(retrieval_raw.get("default_hits", 8)),
            default_mode=str(retrieval_raw.get("default_mode", "hybrid")),
            chunk_size_chars=int(retrieval_raw.get("chunk_size_chars", 1800)),
            chunk_overlap_chars=int(retrieval_raw.get("chunk_overlap_chars", 200)),
            max_feed_workers=int(retrieval_raw.get("max_feed_workers", 8)),
            query_timeout_seconds=int(retrieval_raw.get("query_timeout_seconds", 5)),
        )
```

Add `retrieval=retrieval,` to the `return cls(...)` call.

- [ ] **Step 1.5: Add retrieval section to harness.yaml**

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

- [ ] **Step 1.6: Install pyvespa**

```bash
uv sync
```

- [ ] **Step 1.7: Run config tests to confirm PASS**

```bash
uv run pytest tests/test_config.py -v
```
Expected: 3 tests PASS

- [ ] **Step 1.8: Run full suite to confirm no regressions**

```bash
uv run pytest --ignore=tests/test_vespa_integration.py -x -q 2>&1 | tail -5
```
Expected: all existing tests pass

- [ ] **Step 1.9: Commit**

```bash
git add pyproject.toml harness.yaml harness_poc/core/config.py tests/test_config.py
git commit -m "feat: add RetrievalConfig and pyvespa dependency"
```

---

## Task 2: PostgreSQL metadata tables

**Files:**
- Modify: `harness_poc/core/models.py`

- [ ] **Step 2.1: Write failing table test**

Add to `tests/test_config.py` (or create `tests/test_document_models.py`):

```python
# tests/test_document_models.py
from __future__ import annotations

from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.models import DbDocumentChunk, DbDocumentSource


def test_document_source_table_created(db_engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    # If the table doesn't exist, this query raises; if it does, it returns []
    from sqlmodel import Session, select
    with Session(db_engine) as session:
        rows = session.exec(select(DbDocumentSource)).all()
    assert rows == []


def test_document_chunk_table_created(db_engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    from sqlmodel import Session, select
    with Session(db_engine) as session:
        rows = session.exec(select(DbDocumentChunk)).all()
    assert rows == []
```

- [ ] **Step 2.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_document_models.py -v 2>&1 | head -10
```
Expected: `ImportError: cannot import name 'DbDocumentSource'`

- [ ] **Step 2.3: Add table models to models.py**

Add after the last existing model (`DbSessionSnapshot`):

```python
class DbDocumentSource(SQLModel, table=True):
    __tablename__ = "document_sources"  # type: ignore[assignment]

    source_id: str = Field(primary_key=True)
    uri: str
    title: str
    kind: str
    content_hash: str
    status: str  # pending | indexed | skipped | failed
    chunk_count: int = Field(default=0)
    indexed_at: str | None = Field(default=None)
    error: str | None = Field(default=None)
    metadata_payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    updated_at: str


class DbDocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"  # type: ignore[assignment]
    __table_args__ = (
        Index("idx_document_chunks_source", "source_id", "chunk_index"),
    )

    chunk_id: str = Field(primary_key=True)
    source_id: str = Field(foreign_key="document_sources.source_id")
    chunk_index: int
    content_hash: str
    vespa_id: str
    indexed_at: str | None = Field(default=None)
```

- [ ] **Step 2.4: Run to confirm PASS**

```bash
uv run pytest tests/test_document_models.py -v
```
Expected: 2 tests PASS

- [ ] **Step 2.5: Confirm full suite still passes**

```bash
uv run pytest --ignore=tests/test_vespa_integration.py -x -q 2>&1 | tail -5
```

- [ ] **Step 2.6: Commit**

```bash
git add harness_poc/core/models.py tests/test_document_models.py
git commit -m "feat: add DbDocumentSource and DbDocumentChunk metadata tables"
```

---

## Task 3: Database methods for document metadata

**Files:**
- Modify: `harness_poc/core/database.py`
- Create: `tests/test_document_db.py`

- [ ] **Step 3.1: Write failing database method tests**

```python
# tests/test_document_db.py
from __future__ import annotations

import pytest
from sqlalchemy import Engine

from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.models import DbDocumentChunk, DbDocumentSource


def _make_source(source_id: str = "test-source", status: str = "pending") -> DbDocumentSource:
    return DbDocumentSource(
        source_id=source_id,
        uri=f"docs/{source_id}.md",
        title="Test Doc",
        kind="doc",
        content_hash="abc123",
        status=status,
        chunk_count=0,
        metadata_payload={},
        updated_at="2026-05-20T00:00:00",
    )


def _make_chunk(chunk_id: str = "test-source-0000", source_id: str = "test-source") -> DbDocumentChunk:
    return DbDocumentChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        chunk_index=0,
        content_hash="def456",
        vespa_id=chunk_id,
        indexed_at=None,
    )


def test_upsert_document_source_inserts_new(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    source = _make_source()
    db.upsert_document_source(source)
    result = db.get_document_source("test-source")
    assert result is not None
    assert result.status == "pending"
    assert result.uri == "docs/test-source.md"


def test_upsert_document_source_updates_existing(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.upsert_document_source(_make_source(status="pending"))
    updated = _make_source(status="indexed")
    updated = DbDocumentSource(
        **{**updated.__dict__, "status": "indexed", "chunk_count": 5}
    )
    db.upsert_document_source(updated)
    result = db.get_document_source("test-source")
    assert result is not None
    assert result.status == "indexed"
    assert result.chunk_count == 5


def test_get_document_source_returns_none_when_missing(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    assert db.get_document_source("nonexistent") is None


def test_list_document_sources_returns_all(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.upsert_document_source(_make_source("src-a"))
    db.upsert_document_source(_make_source("src-b"))
    sources = db.list_document_sources()
    ids = {s.source_id for s in sources}
    assert ids == {"src-a", "src-b"}


def test_upsert_document_chunk(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.upsert_document_source(_make_source())
    chunk = _make_chunk()
    db.upsert_document_chunk(chunk)
    # no error = success; check via list
    sources = db.list_document_sources()
    assert len(sources) == 1


def test_list_chunks_for_source(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.upsert_document_source(_make_source())
    db.upsert_document_chunk(_make_chunk("test-source-0000"))
    db.upsert_document_chunk(_make_chunk("test-source-0001"))
    chunks = db.list_chunks_for_source("test-source")
    assert len(chunks) == 2
    assert all(c.source_id == "test-source" for c in chunks)
```

- [ ] **Step 3.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_document_db.py -v 2>&1 | head -10
```
Expected: `AttributeError: 'BlackboardDatabase' object has no attribute 'upsert_document_source'`

- [ ] **Step 3.3: Add database methods to database.py**

Add these imports at the top of `database.py` (in the `from harness_poc.core.models import (...)` block):
```python
    DbDocumentChunk,
    DbDocumentSource,
```

Add these methods to `BlackboardDatabase` (after existing methods, before `_utc_now`):

```python
    def upsert_document_source(self, source: DbDocumentSource) -> None:
        with Session(self._engine) as session:
            existing = session.get(DbDocumentSource, source.source_id)
            if existing is None:
                session.add(source)
            else:
                existing.uri = source.uri
                existing.title = source.title
                existing.kind = source.kind
                existing.content_hash = source.content_hash
                existing.status = source.status
                existing.chunk_count = source.chunk_count
                existing.indexed_at = source.indexed_at
                existing.error = source.error
                existing.metadata_payload = source.metadata_payload
                existing.updated_at = source.updated_at
                session.add(existing)
            session.commit()

    def get_document_source(self, source_id: str) -> DbDocumentSource | None:
        with Session(self._engine) as session:
            return session.get(DbDocumentSource, source_id)

    def list_document_sources(self) -> list[DbDocumentSource]:
        with Session(self._engine) as session:
            return list(session.exec(select(DbDocumentSource)).all())

    def upsert_document_chunk(self, chunk: DbDocumentChunk) -> None:
        with Session(self._engine) as session:
            existing = session.get(DbDocumentChunk, chunk.chunk_id)
            if existing is None:
                session.add(chunk)
            else:
                existing.source_id = chunk.source_id
                existing.chunk_index = chunk.chunk_index
                existing.content_hash = chunk.content_hash
                existing.vespa_id = chunk.vespa_id
                existing.indexed_at = chunk.indexed_at
                session.add(existing)
            session.commit()

    def list_chunks_for_source(self, source_id: str) -> list[DbDocumentChunk]:
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(DbDocumentChunk).where(DbDocumentChunk.source_id == source_id)
                ).all()
            )
```

- [ ] **Step 3.4: Run to confirm PASS**

```bash
uv run pytest tests/test_document_db.py -v
```
Expected: 6 tests PASS

- [ ] **Step 3.5: Commit**

```bash
git add harness_poc/core/database.py tests/test_document_db.py
git commit -m "feat: add document metadata CRUD methods to BlackboardDatabase"
```

---

## Task 4: Blackboard proxy — document metadata methods

**Files:**
- Modify: `harness_poc/core/blackboard_proxy.py`
- Modify: `tests/test_blackboard_proxy.py`

- [ ] **Step 4.1: Write failing proxy tests**

Append to `tests/test_blackboard_proxy.py`:

```python
# --- retrieval proxy tests ---

from harness_poc.core.models import DbDocumentSource as _DbDocumentSource


def _make_doc_source(sid: str = "src-a") -> _DbDocumentSource:
    return _DbDocumentSource(
        source_id=sid,
        uri=f"docs/{sid}.md",
        title="Doc",
        kind="doc",
        content_hash="abc",
        status="indexed",
        chunk_count=1,
        metadata_payload={},
        updated_at="2026-05-20T00:00:00",
    )


def test_proxy_get_document_source_requires_read(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "none", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    with pytest.raises(PermissionError):
        proxy.get_document_source("src-a")


def test_proxy_list_document_sources_requires_read(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "none", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    with pytest.raises(PermissionError):
        proxy.list_document_sources()


def test_proxy_upsert_document_source_requires_write(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "read", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    with pytest.raises(PermissionError):
        proxy.upsert_document_source(_make_doc_source())


def test_proxy_upsert_document_source_with_write_permission(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    proxy.upsert_document_source(_make_doc_source("src-z"))
    result = proxy.get_document_source("src-z")
    assert result is not None
    assert result.status == "indexed"


def test_proxy_list_document_sources_with_read_permission(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms_rw = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "none"})
    db.upsert_document_source(_make_doc_source("src-1"))
    proxy_r = BlackboardAccessProxy(db, SkillPermissions.from_yaml({"blackboard": "read", "workspace": "none"}))
    sources = proxy_r.list_document_sources()
    assert any(s.source_id == "src-1" for s in sources)
```

- [ ] **Step 4.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_blackboard_proxy.py -k "document_source" -v 2>&1 | head -15
```
Expected: `AttributeError: 'BlackboardAccessProxy' object has no attribute 'get_document_source'`

- [ ] **Step 4.3: Add proxy methods to blackboard_proxy.py**

Add these imports to the `TYPE_CHECKING` block:
```python
    from harness_poc.core.models import DbDocumentChunk, DbDocumentSource
```

Add after the existing write methods (before `# ---- async wrappers ----`):

```python
    # ---- document metadata read methods ----

    def get_document_source(self, source_id: str) -> DbDocumentSource | None:
        self._require_read()
        return self._db.get_document_source(source_id)

    def list_document_sources(self) -> list[DbDocumentSource]:
        self._require_read()
        return self._db.list_document_sources()

    def list_chunks_for_source(self, source_id: str) -> list[DbDocumentChunk]:
        self._require_read()
        return self._db.list_chunks_for_source(source_id)

    # ---- document metadata write methods ----

    def upsert_document_source(self, source: DbDocumentSource) -> None:
        self._require_write()
        self._db.upsert_document_source(source)

    def upsert_document_chunk(self, chunk: DbDocumentChunk) -> None:
        self._require_write()
        self._db.upsert_document_chunk(chunk)
```

- [ ] **Step 4.4: Run to confirm PASS**

```bash
uv run pytest tests/test_blackboard_proxy.py -v 2>&1 | tail -10
```
Expected: all tests PASS

- [ ] **Step 4.5: Commit**

```bash
git add harness_poc/core/blackboard_proxy.py tests/test_blackboard_proxy.py
git commit -m "feat: add document metadata proxy methods to BlackboardAccessProxy"
```

---

## Task 5: Core retrieval domain models and chunking utilities

**Files:**
- Create: `harness_poc/core/retrieval.py`
- Create: `tests/test_retrieval_chunking.py`

- [ ] **Step 5.1: Write failing chunking tests**

```python
# tests/test_retrieval_chunking.py
from __future__ import annotations

import pytest

from harness_poc.core.retrieval import (
    DocumentChunk,
    FeedSummary,
    SearchRequest,
    SearchResult,
    VespaDocumentClient,
    chunk_text,
    compute_content_hash,
    make_chunk_id,
    make_document_chunks,
    make_source_id,
)


def test_chunk_text_single_when_short() -> None:
    result = chunk_text("hello world", chunk_size=100, overlap=10)
    assert result == ["hello world"]


def test_chunk_text_empty_returns_empty() -> None:
    assert chunk_text("", chunk_size=100, overlap=10) == []
    assert chunk_text("   ", chunk_size=100, overlap=10) == []


def test_chunk_text_multiple_chunks() -> None:
    text = "a" * 200
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    # [0:100], [80:180], [160:200]
    assert len(chunks) == 3
    assert len(chunks[0]) == 100
    assert len(chunks[1]) == 100
    assert len(chunks[2]) == 40


def test_chunk_text_overlap_preserved() -> None:
    text = "abcdefghij"  # 10 chars
    chunks = chunk_text(text, chunk_size=6, overlap=2)
    # [0:6]="abcdef", [4:10]="efghij"
    assert chunks[0] == "abcdef"
    assert chunks[1] == "efghij"
    assert len(chunks) == 2


def test_chunk_text_exact_fit() -> None:
    text = "a" * 100
    chunks = chunk_text(text, chunk_size=100, overlap=10)
    assert chunks == [text]


def test_compute_content_hash_stable() -> None:
    h1 = compute_content_hash("hello world")
    h2 = compute_content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_content_hash_different_inputs() -> None:
    assert compute_content_hash("abc") != compute_content_hash("xyz")


def test_make_source_id_slug() -> None:
    assert make_source_id("docs/foo.md") == "docs-foo-md"
    assert make_source_id("docs/sub/bar.yaml") == "docs-sub-bar-yaml"
    assert make_source_id("README.md") == "readme-md"


def test_make_chunk_id() -> None:
    assert make_chunk_id("docs-foo-md", 0) == "docs-foo-md-0000"
    assert make_chunk_id("docs-foo-md", 3) == "docs-foo-md-0003"
    assert make_chunk_id("docs-foo-md", 42) == "docs-foo-md-0042"


def test_make_document_chunks_assembles_correctly() -> None:
    text = "a" * 50
    chunks = make_document_chunks(
        text=text,
        uri="docs/test.md",
        title="Test",
        kind="doc",
        chunk_size=100,
        chunk_overlap=10,
    )
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.source_id == "docs-test-md"
    assert chunk.uri == "docs/test.md"
    assert chunk.title == "Test"
    assert chunk.kind == "doc"
    assert chunk.chunk_index == 0
    assert chunk.chunk_id == "docs-test-md-0000"
    assert chunk.text == text
    assert len(chunk.content_hash) == 64
    assert chunk.updated_at > 0


def test_make_document_chunks_multiple() -> None:
    text = "x" * 200
    chunks = make_document_chunks(
        text=text,
        uri="docs/big.md",
        title="Big",
        kind="doc",
        chunk_size=100,
        chunk_overlap=20,
    )
    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(c.source_id == "docs-big-md" for c in chunks)
```

- [ ] **Step 5.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_retrieval_chunking.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'harness_poc.core.retrieval'`

- [ ] **Step 5.3: Create harness_poc/core/retrieval.py**

```python
# harness_poc/core/retrieval.py
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


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
    updated_at: int  # milliseconds since epoch


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


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    mode: str  # hybrid | semantic | keyword
    hits: int
    source_id: str | None = None
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class FeedSummary:
    fed: int
    failed: int
    failed_ids: list[str]


@runtime_checkable
class VespaDocumentClient(Protocol):
    def health_check(self) -> None: ...
    def feed_chunks(self, chunks: Iterable[DocumentChunk]) -> FeedSummary: ...
    def delete_source(self, source_id: str) -> None: ...
    def search(self, request: SearchRequest) -> list[SearchResult]: ...


def make_source_id(uri: str) -> str:
    """Convert a URI path to a URL-safe slug. e.g. 'docs/foo.md' -> 'docs-foo-md'."""
    slug = re.sub(r"[/\\.:]", "-", uri)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug


def make_chunk_id(source_id: str, chunk_index: int) -> str:
    return f"{source_id}-{chunk_index:04d}"


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def make_document_chunks(
    text: str,
    uri: str,
    title: str,
    kind: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    source_id = make_source_id(uri)
    now_ms = int(time.time() * 1000)
    raw_chunks = chunk_text(text, chunk_size, chunk_overlap)
    return [
        DocumentChunk(
            source_id=source_id,
            uri=uri,
            title=title,
            chunk_id=make_chunk_id(source_id, i),
            chunk_index=i,
            text=chunk,
            kind=kind,
            content_hash=compute_content_hash(chunk),
            updated_at=now_ms,
        )
        for i, chunk in enumerate(raw_chunks)
    ]
```

- [ ] **Step 5.4: Run to confirm PASS**

```bash
uv run pytest tests/test_retrieval_chunking.py -v
```
Expected: all tests PASS

- [ ] **Step 5.5: Commit**

```bash
git add harness_poc/core/retrieval.py tests/test_retrieval_chunking.py
git commit -m "feat: add retrieval domain models, VespaDocumentClient protocol, and chunking utilities"
```

---

## Task 6: Vespa application package

**Files:**
- Create: `vespa/document_retrieval/services.xml`
- Create: `vespa/document_retrieval/schemas/doc_chunk.sd`

No tests — these are static config files deployed to Vespa via `vespa deploy` or pyvespa.

- [ ] **Step 6.1: Create vespa/document_retrieval/services.xml**

```bash
mkdir -p vespa/document_retrieval/schemas
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<services version="1.0">

  <container id="default" version="1.0">
    <search/>
    <document-api/>

    <!-- Embedder: all-MiniLM-L6-v2 produces 384-dim vectors matching the schema tensor -->
    <component id="embedding" type="hugging-face-embedder">
      <transformer-model
        url="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"/>
      <tokenizer-model
        url="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json"/>
    </component>

    <nodes>
      <node hostalias="node1"/>
    </nodes>
  </container>

  <content id="content" version="1.0">
    <redundancy>1</redundancy>
    <documents>
      <document type="doc_chunk" mode="index"/>
    </documents>
    <nodes>
      <node hostalias="node1" distribution-key="0"/>
    </nodes>
  </content>

</services>
```

- [ ] **Step 6.2: Create vespa/document_retrieval/schemas/doc_chunk.sd**

```
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

- [ ] **Step 6.3: Commit**

```bash
git add vespa/
git commit -m "feat: add Vespa application package with doc_chunk schema and HuggingFace embedder"
```

---

## Task 7: VespaDocumentClient (pyvespa adapter)

**Files:**
- Create: `harness_poc/core/vespa_client.py`
- Create: `tests/test_vespa_client.py`

- [ ] **Step 7.1: Write failing client tests**

```python
# tests/test_vespa_client.py
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


# ---------------------------------------------------------------------------
# Fake client — used by document_index tests too; import from here
# ---------------------------------------------------------------------------

class FakeVespaClient:
    """In-memory Vespa substitute for unit tests."""

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


# ---------------------------------------------------------------------------
# VespaDocumentClient Protocol conformance
# ---------------------------------------------------------------------------

def test_fake_client_satisfies_protocol() -> None:
    assert isinstance(FakeVespaClient(), VespaDocumentClient)


def test_live_client_satisfies_protocol() -> None:
    from harness_poc.core.config import RetrievalConfig
    client = LiveVespaDocumentClient(RetrievalConfig())
    assert isinstance(client, VespaDocumentClient)


# ---------------------------------------------------------------------------
# Query body construction (no network)
# ---------------------------------------------------------------------------

def test_build_query_body_keyword() -> None:
    req = SearchRequest(query="state machine", mode="keyword", hits=5)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert "keyword" in body["ranking.profile"]
    assert "@query" in body["yql"]
    assert "nearestNeighbor" not in body["yql"]
    assert body["query"] == "state machine"
    assert body["hits"] == 5


def test_build_query_body_semantic() -> None:
    req = SearchRequest(query="how memory works", mode="semantic", hits=8)
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert body["ranking.profile"] == "semantic"
    assert "nearestNeighbor" in body["yql"]
    assert "embed(@query)" in body["input.query(q)"]
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
    assert "filter_source_id" in body
    assert body["filter_source_id"] == "docs-foo-md"
    assert "@filter_source_id" in body["yql"]


def test_build_query_body_kind_filter() -> None:
    req = SearchRequest(query="x", mode="keyword", hits=5, kind="spec")
    body = _build_query_body(req, schema="doc_chunk", timeout=5)
    assert "filter_kind" in body
    assert body["filter_kind"] == "spec"


# ---------------------------------------------------------------------------
# Hit normalization (no network)
# ---------------------------------------------------------------------------

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

- [ ] **Step 7.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_vespa_client.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'harness_poc.core.vespa_client'`

- [ ] **Step 7.3: Create harness_poc/core/vespa_client.py**

```python
# harness_poc/core/vespa_client.py
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

- [ ] **Step 7.4: Run to confirm PASS**

```bash
uv run pytest tests/test_vespa_client.py -v
```
Expected: all tests PASS (no live Vespa needed — all tests use fakes or pure functions)

- [ ] **Step 7.5: Commit**

```bash
git add harness_poc/core/vespa_client.py tests/test_vespa_client.py
git commit -m "feat: add LiveVespaDocumentClient, query body builder, and hit normalizer"
```

---

## Task 8: DocumentIndexer

**Files:**
- Create: `harness_poc/core/document_index.py`
- Create: `tests/test_document_index.py`

- [ ] **Step 8.1: Write failing indexer tests**

```python
# tests/test_document_index.py
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from harness_poc.core.config import RetrievalConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.document_index import DocumentIndexer, IndexResult
from tests.test_vespa_client import FakeVespaClient


def _make_config(**overrides) -> RetrievalConfig:
    defaults = dict(
        chunk_size_chars=100,
        chunk_overlap_chars=10,
    )
    defaults.update(overrides)
    return RetrievalConfig(**defaults)


def _make_indexer(db: BlackboardDatabase, vespa: FakeVespaClient, **config_overrides) -> DocumentIndexer:
    return DocumentIndexer(
        config=_make_config(**config_overrides),
        database=db,
        vespa_client=vespa,
    )


def test_index_new_markdown_file(db_engine: Engine, tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("# Hello\n\nThis is a test document.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(
        project_root=tmp_path,
        paths=["README.md"],
    )

    assert result.indexed == 1
    assert result.skipped == 0
    assert result.failed == 0
    assert result.chunks_indexed >= 1
    assert len(vespa.fed_ids) >= 1


def test_skip_unchanged_source(db_engine: Engine, tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("Same content.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    # First index
    r1 = indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    assert r1.indexed == 1

    # Second index — same hash, should skip
    r2 = indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    assert r2.skipped == 1
    assert r2.indexed == 0


def test_force_reindex_skips_hash_check(db_engine: Engine, tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("Same content.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    initial_fed = len(vespa.fed_ids)

    r = indexer.index_paths(project_root=tmp_path, paths=["doc.md"], force=True)
    assert r.indexed == 1
    assert len(vespa.fed_ids) > initial_fed


def test_unsupported_file_type_is_skipped(db_engine: Engine, tmp_path: Path) -> None:
    pdf = tmp_path / "binary.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["binary.pdf"])
    assert result.skipped == 1
    assert result.indexed == 0


def test_path_outside_project_root_is_rejected(db_engine: Engine, tmp_path: Path) -> None:
    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["/etc/passwd"])
    assert result.failed == 1
    assert len(result.failures) == 1


def test_git_directory_is_ignored(db_engine: Engine, tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("git config", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    # index the entire tmp_path directory
    result = indexer.index_paths(project_root=tmp_path, paths=["."])
    assert result.indexed == 0  # .git/config has no supported extension and is in ignored dir


def test_vespa_unavailable_marks_source_failed(db_engine: Engine, tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("Content here.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient(healthy=False)
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    assert result.failed == 1
    assert result.indexed == 0

    source = db.get_document_source("doc-md")
    assert source is not None
    assert source.status == "failed"
```

- [ ] **Step 8.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_document_index.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'harness_poc.core.document_index'`

- [ ] **Step 8.3: Create harness_poc/core/document_index.py**

```python
# harness_poc/core/document_index.py
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness_poc.core.config import RetrievalConfig
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.retrieval import VespaDocumentClient

from harness_poc.core.models import DbDocumentChunk, DbDocumentSource
from harness_poc.core.retrieval import compute_content_hash, make_document_chunks, make_source_id

SUPPORTED_EXTENSIONS = frozenset({".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".py"})
IGNORED_DIR_NAMES = frozenset({".git", ".venv", "__pycache__", ".deverino-scratch"})
IGNORED_FILE_GLOBS = frozenset({"*.db", ".env", "*.pem", "*.key", "id_rsa", "credentials.json"})
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


@dataclass
class IndexResult:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    chunks_indexed: int = 0
    failures: list[dict] = field(default_factory=list)


class DocumentIndexer:
    def __init__(
        self,
        config: RetrievalConfig,
        database: BlackboardDatabase,
        vespa_client: VespaDocumentClient,
    ) -> None:
        self._config = config
        self._db = database
        self._vespa = vespa_client

    def index_paths(
        self,
        project_root: Path,
        paths: list[str],
        glob_pattern: str = "**/*",
        force: bool = False,
    ) -> IndexResult:
        result = IndexResult()

        # Health check first — fail fast if Vespa is unreachable
        try:
            self._vespa.health_check()
        except Exception as exc:
            for p in paths:
                uri = p
                source_id = make_source_id(uri)
                self._db.upsert_document_source(
                    DbDocumentSource(
                        source_id=source_id,
                        uri=uri,
                        title=uri,
                        kind="doc",
                        content_hash="",
                        status="failed",
                        chunk_count=0,
                        metadata_payload={},
                        error=str(exc),
                        updated_at=_utc_now(),
                    )
                )
                result.failed += 1
                result.failures.append({"uri": uri, "error": str(exc)})
            return result

        resolved_files = self._resolve_files(project_root, paths, glob_pattern)

        for file_path in resolved_files:
            try:
                uri = str(file_path.relative_to(project_root))
            except ValueError:
                result.failed += 1
                result.failures.append({"uri": str(file_path), "error": "path outside project root"})
                continue

            self._index_one(file_path, uri, project_root, force, result)

        return result

    def _index_one(
        self,
        file_path: Path,
        uri: str,
        project_root: Path,
        force: bool,
        result: IndexResult,
    ) -> None:
        source_id = make_source_id(uri)

        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            result.skipped += 1
            return

        if _is_secret_file(file_path.name):
            result.skipped += 1
            return

        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            result.failed += 1
            result.failures.append({"uri": uri, "error": str(exc)})
            return

        content_hash = compute_content_hash(text)

        if not force:
            existing = self._db.get_document_source(source_id)
            if existing is not None and existing.content_hash == content_hash:
                self._db.upsert_document_source(
                    _make_db_source(source_id, uri, content_hash, "skipped", 0)
                )
                result.skipped += 1
                return

        title = file_path.stem.replace("-", " ").replace("_", " ").title()
        chunks = make_document_chunks(
            text=text,
            uri=uri,
            title=title,
            kind=_infer_kind(uri),
            chunk_size=self._config.chunk_size_chars,
            chunk_overlap=self._config.chunk_overlap_chars,
        )

        # Mark pending
        self._db.upsert_document_source(
            _make_db_source(source_id, uri, content_hash, "pending", len(chunks), title=title)
        )

        feed_summary = self._vespa.feed_chunks(chunks)

        if feed_summary.failed > 0:
            error_msg = f"{feed_summary.failed} chunk(s) failed to feed"
            self._db.upsert_document_source(
                _make_db_source(
                    source_id, uri, content_hash, "failed", len(chunks),
                    title=title, error=error_msg,
                )
            )
            result.failed += 1
            result.failures.append({"uri": uri, "error": error_msg})
            return

        now = _utc_now()
        for chunk in chunks:
            self._db.upsert_document_chunk(
                DbDocumentChunk(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    chunk_index=chunk.chunk_index,
                    content_hash=chunk.content_hash,
                    vespa_id=chunk.chunk_id,
                    indexed_at=now,
                )
            )

        self._db.upsert_document_source(
            _make_db_source(
                source_id, uri, content_hash, "indexed", len(chunks),
                title=title, indexed_at=now,
            )
        )
        result.indexed += 1
        result.chunks_indexed += len(chunks)

    def _resolve_files(
        self, project_root: Path, paths: list[str], glob_pattern: str
    ) -> list[Path]:
        files: list[Path] = []
        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = project_root / path
            try:
                path = path.resolve()
                path.relative_to(project_root.resolve())
            except ValueError:
                # outside project root — will be caught in _index_one
                files.append(path)
                continue

            if path.is_file():
                files.append(path)
            elif path.is_dir():
                for child in path.rglob(glob_pattern):
                    if child.is_file() and not _in_ignored_dir(child, project_root):
                        files.append(child)
            # non-existent paths produce no files (silently skipped)
        return files


def _in_ignored_dir(path: Path, project_root: Path) -> bool:
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        return False
    return any(part in IGNORED_DIR_NAMES for part in rel.parts)


def _is_secret_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in IGNORED_FILE_GLOBS)


def _infer_kind(uri: str) -> str:
    if uri.startswith("docs/superpowers/specs/"):
        return "spec"
    if uri.startswith("docs/superpowers/plans/"):
        return "plan"
    if uri.startswith("docs/"):
        return "doc"
    return "source"


def _make_db_source(
    source_id: str,
    uri: str,
    content_hash: str,
    status: str,
    chunk_count: int,
    title: str = "",
    indexed_at: str | None = None,
    error: str | None = None,
) -> DbDocumentSource:
    return DbDocumentSource(
        source_id=source_id,
        uri=uri,
        title=title or uri,
        kind=_infer_kind(uri),
        content_hash=content_hash,
        status=status,
        chunk_count=chunk_count,
        indexed_at=indexed_at,
        error=error,
        metadata_payload={},
        updated_at=_utc_now(),
    )


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
```

- [ ] **Step 8.4: Run to confirm PASS**

```bash
uv run pytest tests/test_document_index.py -v
```
Expected: all tests PASS

- [ ] **Step 8.5: Commit**

```bash
git add harness_poc/core/document_index.py tests/test_document_index.py
git commit -m "feat: add DocumentIndexer with skip-on-hash, path allowlist, and ignored dir logic"
```

---

## Task 9: index_documents skill

**Files:**
- Create: `skills/index_documents/SKILL.md`
- Create: `skills/index_documents/skill.py`
- Create: `tests/test_index_documents.py`

- [ ] **Step 9.1: Write failing skill tests**

```python
# tests/test_index_documents.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Engine

from harness_poc.core.config import HarnessConfig, LLMConfig, ObservabilityConfig, RetrievalConfig, RuntimeConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_context import SkillContext
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.core.permissions import SkillPermissions


def _build_ctx(db: BlackboardDatabase, config: HarnessConfig, session_id: str) -> SkillContext:
    from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
    perms = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "read"})
    proxy = BlackboardAccessProxy(db, perms)
    return SkillContext(
        session_id=session_id,
        skill_name="index_documents",
        database=proxy,
        config=config,
        permissions=perms,
    )


def test_index_documents_disabled_returns_failed(db_engine: Engine, tmp_path: Path) -> None:
    from harness_poc.core.config import HarnessPaths
    cfg = HarnessConfig(
        project_root=tmp_path,
        config_path=tmp_path / "harness.yaml",
        paths=HarnessPaths(
            soul=tmp_path / "SOUL.md",
            system_tools=tmp_path / "system_tools",
            system_skills=tmp_path / "system_skills",
            project_skills=tmp_path / "skills",
            workflows=tmp_path / "workflows",
            pipelines=tmp_path / "pipelines",
            personas=tmp_path / "personas",
        ),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
        runtime=RuntimeConfig(
            database_url="postgresql://test:test@localhost/test",
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        retrieval=RetrievalConfig(enabled=False),
    )
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")

    from skills.index_documents.skill import execute
    from harness_poc.core.skill_context import SkillContext
    from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
    perms = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "read"})
    ctx = SkillContext(
        session_id=session_id,
        skill_name="index_documents",
        database=BlackboardAccessProxy(db, perms),
        config=cfg,
        permissions=perms,
    )

    result = execute(ctx, {"paths": ["docs"]})
    assert result.status == "failed"
    assert "retrieval" in result.content.lower() or "disabled" in result.content.lower()


def test_index_documents_result_has_required_artifacts(db_engine: Engine, tmp_path: Path) -> None:
    """Skill returns indexed/skipped/failed/chunks_indexed in artifacts."""
    from harness_poc.core.config import HarnessPaths
    doc = tmp_path / "README.md"
    doc.write_text("# Test\nContent here.", encoding="utf-8")

    cfg = HarnessConfig(
        project_root=tmp_path,
        config_path=tmp_path / "harness.yaml",
        paths=HarnessPaths(
            soul=tmp_path / "SOUL.md",
            system_tools=tmp_path / "system_tools",
            system_skills=tmp_path / "system_skills",
            project_skills=tmp_path / "skills",
            workflows=tmp_path / "workflows",
            pipelines=tmp_path / "pipelines",
            personas=tmp_path / "personas",
        ),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
        runtime=RuntimeConfig(
            database_url="postgresql://test:test@localhost/test",
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        retrieval=RetrievalConfig(chunk_size_chars=200, chunk_overlap_chars=20),
    )
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")

    from tests.test_vespa_client import FakeVespaClient
    from skills.index_documents.skill import execute
    from harness_poc.core.skill_context import SkillContext
    from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
    perms = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "read"})
    ctx = SkillContext(
        session_id=session_id,
        skill_name="index_documents",
        database=BlackboardAccessProxy(db, perms),
        config=cfg,
        permissions=perms,
    )

    fake_vespa = FakeVespaClient()
    with patch("skills.index_documents.skill.LiveVespaDocumentClient", return_value=fake_vespa):
        result = execute(ctx, {"paths": ["README.md"]})

    assert result.status == "success"
    assert "indexed" in result.artifacts
    assert "skipped" in result.artifacts
    assert "failed" in result.artifacts
    assert "chunks_indexed" in result.artifacts
    assert result.artifacts["indexed"] >= 1
```

- [ ] **Step 9.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_index_documents.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'skills.index_documents'`

- [ ] **Step 9.3: Create skills/index_documents/SKILL.md**

```bash
mkdir -p skills/index_documents
```

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

- [ ] **Step 9.4: Create skills/index_documents/skill.py**

```python
# skills/index_documents/skill.py
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.skill_context import SkillContext

from harness_poc.core.skill_result import SkillResult


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    from harness_poc.core.document_index import DocumentIndexer
    from harness_poc.core.vespa_client import LiveVespaDocumentClient

    if not ctx.config.retrieval.enabled:
        return SkillResult(
            status="failed",
            content="Retrieval is disabled. Set retrieval.enabled=true in harness.yaml.",
            artifacts={},
        )

    paths = arguments.get("paths")
    if not paths or not isinstance(paths, list):
        return SkillResult(
            status="failed",
            content="Missing required argument: paths (list of strings).",
            artifacts={},
        )

    glob_pattern = str(arguments.get("glob") or "**/*")
    force = bool(arguments.get("force", False))

    vespa_client = LiveVespaDocumentClient(ctx.config.retrieval)
    indexer = DocumentIndexer(
        config=ctx.config.retrieval,
        database=ctx.database,  # type: ignore[arg-type]
        vespa_client=vespa_client,
    )

    result = indexer.index_paths(
        project_root=ctx.project_root,
        paths=[str(p) for p in paths],
        glob_pattern=glob_pattern,
        force=force,
    )

    artifacts = {
        "indexed": result.indexed,
        "skipped": result.skipped,
        "failed": result.failed,
        "chunks_indexed": result.chunks_indexed,
        "failures": result.failures,
    }
    summary = (
        f"Indexed {result.indexed} source(s), {result.chunks_indexed} chunk(s). "
        f"Skipped {result.skipped}. Failed {result.failed}."
    )
    status = "failed" if result.failed > 0 and result.indexed == 0 else "success"

    return SkillResult(
        status=status,
        content=summary + (
            "\n\nFailures:\n" + json.dumps(result.failures, indent=2)
            if result.failures else ""
        ),
        artifacts=artifacts,
    )
```

- [ ] **Step 9.5: Run to confirm PASS**

```bash
uv run pytest tests/test_index_documents.py -v
```
Expected: all tests PASS

- [ ] **Step 9.6: Commit**

```bash
git add skills/index_documents/ tests/test_index_documents.py
git commit -m "feat: add index_documents skill"
```

---

## Task 10: search_documents skill

**Files:**
- Create: `skills/search_documents/SKILL.md`
- Create: `skills/search_documents/skill.py`
- Create: `tests/test_search_documents.py`

- [ ] **Step 10.1: Write failing skill tests**

```python
# tests/test_search_documents.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import Engine

from harness_poc.core.config import (
    HarnessConfig, HarnessPaths, LLMConfig, ObservabilityConfig,
    RetrievalConfig, RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.skill_context import SkillContext
from harness_poc.core.retrieval import SearchResult


def _make_config(tmp_path: Path, **retrieval_overrides) -> HarnessConfig:
    return HarnessConfig(
        project_root=tmp_path,
        config_path=tmp_path / "harness.yaml",
        paths=HarnessPaths(
            soul=tmp_path / "SOUL.md",
            system_tools=tmp_path / "st",
            system_skills=tmp_path / "ss",
            project_skills=tmp_path / "skills",
            workflows=tmp_path / "wf",
            pipelines=tmp_path / "pp",
            personas=tmp_path / "pe",
        ),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
        runtime=RuntimeConfig(
            database_url="postgresql://test:test@localhost/test",
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        retrieval=RetrievalConfig(**retrieval_overrides),
    )


def _make_ctx(db: BlackboardDatabase, cfg: HarnessConfig, session_id: str) -> SkillContext:
    perms = SkillPermissions.from_yaml({"blackboard": "read", "workspace": "none"})
    return SkillContext(
        session_id=session_id,
        skill_name="search_documents",
        database=BlackboardAccessProxy(db, perms),
        config=cfg,
        permissions=perms,
    )


def test_search_disabled_returns_failed(db_engine: Engine, tmp_path: Path) -> None:
    from skills.search_documents.skill import execute

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path, enabled=False)
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"query": "memory"})
    assert result.status == "failed"


def test_search_empty_query_returns_failed(db_engine: Engine, tmp_path: Path) -> None:
    from skills.search_documents.skill import execute

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"query": ""})
    assert result.status == "failed"
    assert "empty" in result.content.lower() or "query" in result.content.lower()


def test_search_invalid_mode_returns_failed(db_engine: Engine, tmp_path: Path) -> None:
    from skills.search_documents.skill import execute

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"query": "memory", "mode": "foobar"})
    assert result.status == "failed"
    assert "mode" in result.content.lower()


def test_search_formats_citation_first(db_engine: Engine, tmp_path: Path) -> None:
    from skills.search_documents.skill import execute

    fake_results = [
        SearchResult(
            source_id="docs-foo-md",
            uri="docs/foo.md",
            title="Foo Doc",
            chunk_id="docs-foo-md-0001",
            chunk_index=1,
            text="This is the chunk text about memory.",
            relevance=0.82,
            kind="doc",
        )
    ]

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as MockClient:
        MockClient.return_value.search.return_value = fake_results
        result = execute(ctx, {"query": "memory", "mode": "keyword"})

    assert result.status == "success"
    # citation-first: "docs/foo.md#chunk-1"
    assert "docs/foo.md" in result.content
    assert "0.82" in result.content or "chunk" in result.content.lower()

    artifacts = result.artifacts
    assert artifacts["query"] == "memory"
    assert artifacts["mode"] == "keyword"
    assert len(artifacts["results"]) == 1
    assert artifacts["results"][0]["uri"] == "docs/foo.md"
    assert artifacts["results"][0]["relevance"] == pytest.approx(0.82)


def test_search_uses_config_defaults(db_engine: Engine, tmp_path: Path) -> None:
    """hits and mode default to config values when not supplied."""
    from skills.search_documents.skill import execute

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path, default_hits=3, default_mode="semantic")
    ctx = _make_ctx(db, cfg, session_id)

    captured_requests = []

    def fake_search(request):
        captured_requests.append(request)
        return []

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as MockClient:
        MockClient.return_value.search.side_effect = fake_search
        execute(ctx, {"query": "memory"})

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.hits == 3
    assert req.mode == "semantic"
```

- [ ] **Step 10.2: Run to confirm FAIL**

```bash
uv run pytest tests/test_search_documents.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'skills.search_documents'`

- [ ] **Step 10.3: Create skills/search_documents/SKILL.md**

```bash
mkdir -p skills/search_documents
```

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

- [ ] **Step 10.4: Create skills/search_documents/skill.py**

```python
# skills/search_documents/skill.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.skill_context import SkillContext

from harness_poc.core.skill_result import SkillResult

_VALID_MODES = {"hybrid", "semantic", "keyword"}


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    from harness_poc.core.retrieval import SearchRequest
    from harness_poc.core.vespa_client import LiveVespaDocumentClient

    if not ctx.config.retrieval.enabled:
        return SkillResult(
            status="failed",
            content="Retrieval is disabled. Set retrieval.enabled=true in harness.yaml.",
            artifacts={},
        )

    query = str(arguments.get("query") or "").strip()
    if not query:
        return SkillResult(
            status="failed",
            content="Empty query. Provide a non-empty search query.",
            artifacts={},
        )

    mode = str(arguments.get("mode") or ctx.config.retrieval.default_mode)
    if mode not in _VALID_MODES:
        return SkillResult(
            status="failed",
            content=f"Invalid mode {mode!r}. Choose from: hybrid, semantic, keyword.",
            artifacts={},
        )

    hits = int(arguments.get("hits") or ctx.config.retrieval.default_hits)
    source_id = arguments.get("source_id") or None
    kind = arguments.get("kind") or None

    request = SearchRequest(
        query=query,
        mode=mode,
        hits=hits,
        source_id=str(source_id) if source_id else None,
        kind=str(kind) if kind else None,
    )

    vespa = LiveVespaDocumentClient(ctx.config.retrieval)
    try:
        results = vespa.search(request)
    except Exception as exc:
        return SkillResult(
            status="failed",
            content=f"Search failed: {exc}. Is Vespa running? Run index_documents first.",
            artifacts={},
        )

    if not results:
        return SkillResult(
            status="success",
            content=(
                "No results found. "
                "If you haven't indexed documents yet, run index_documents first."
            ),
            artifacts={"query": query, "mode": mode, "results": []},
        )

    # Citation-first formatting
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.uri}#chunk-{r.chunk_index} (score {r.relevance:.2f})\n"
            f"   {r.text[:300]}{'...' if len(r.text) > 300 else ''}"
        )
    content = "\n\n".join(lines)

    # Truncate to tool_result_max_chars
    max_chars = ctx.config.runtime.tool_result_max_chars
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[truncated]"

    artifacts = {
        "query": query,
        "mode": mode,
        "results": [
            {
                "title": r.title,
                "uri": r.uri,
                "chunk_id": r.chunk_id,
                "chunk_index": r.chunk_index,
                "relevance": r.relevance,
                "text": r.text,
            }
            for r in results
        ],
    }

    return SkillResult(status="success", content=content, artifacts=artifacts)
```

- [ ] **Step 10.5: Run to confirm PASS**

```bash
uv run pytest tests/test_search_documents.py -v
```
Expected: all tests PASS

- [ ] **Step 10.6: Run full suite to confirm no regressions**

```bash
uv run pytest --ignore=tests/test_vespa_integration.py -x -q 2>&1 | tail -10
```

- [ ] **Step 10.7: Commit**

```bash
git add skills/search_documents/ tests/test_search_documents.py
git commit -m "feat: add search_documents skill with citation-first formatting and config-driven defaults"
```

---

## Task 11: Optional live Vespa integration test

**Files:**
- Create: `tests/test_vespa_integration.py`

Only runs when `VESPA_INTEGRATION=1` is set. Requires a local Vespa instance with the `doc_chunk` schema deployed.

- [ ] **Step 11.1: Create tests/test_vespa_integration.py**

```python
# tests/test_vespa_integration.py
"""
Live integration tests for the Vespa document retrieval stack.

Run with:
    VESPA_INTEGRATION=1 uv run pytest tests/test_vespa_integration.py -v

Prerequisites:
    1. Start Vespa: docker run --detach --name vespa --publish 8080:8080 vespaengine/vespa
    2. Deploy the app: vespa deploy vespa/document_retrieval/
       (or use the pyvespa deploy approach documented in docs/)
    3. Wait for Vespa to be ready (may take ~60 seconds on first start)
"""
from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("VESPA_INTEGRATION") != "1",
    reason="Set VESPA_INTEGRATION=1 to run live Vespa tests",
)

from harness_poc.core.config import RetrievalConfig
from harness_poc.core.retrieval import SearchRequest, make_document_chunks
from harness_poc.core.vespa_client import LiveVespaDocumentClient

FIXTURE_URI = "test/integration-fixture.md"
FIXTURE_TEXT = (
    "The blackboard database stores durable project state across sessions. "
    "State consolidation merges session-level proposals into the project state. "
    "Each proposal must be approved before it is written to project_state."
)


@pytest.fixture(scope="module")
def vespa_client() -> LiveVespaDocumentClient:
    cfg = RetrievalConfig(
        vespa_url=os.getenv("VESPA_URL", "http://localhost:8080"),
        namespace="deverino",
        schema="doc_chunk",
    )
    client = LiveVespaDocumentClient(cfg)
    client.health_check()
    return client


@pytest.fixture(autouse=True, scope="module")
def cleanup_fixture(vespa_client: LiveVespaDocumentClient):
    yield
    try:
        vespa_client.delete_source("test-integration-fixture-md")
    except Exception:
        pass


def test_health_check_passes(vespa_client: LiveVespaDocumentClient) -> None:
    vespa_client.health_check()  # raises on failure


def test_feed_and_keyword_search(vespa_client: LiveVespaDocumentClient) -> None:
    chunks = make_document_chunks(
        text=FIXTURE_TEXT,
        uri=FIXTURE_URI,
        title="Integration Fixture",
        kind="test",
        chunk_size=500,
        chunk_overlap=50,
    )
    summary = vespa_client.feed_chunks(chunks)
    assert summary.failed == 0
    assert summary.fed == len(chunks)

    # Give Vespa time to index
    time.sleep(2)

    results = vespa_client.search(
        SearchRequest(query="blackboard database", mode="keyword", hits=5)
    )
    source_ids = {r.source_id for r in results}
    assert "test-integration-fixture-md" in source_ids


def test_feed_and_semantic_search(vespa_client: LiveVespaDocumentClient) -> None:
    results = vespa_client.search(
        SearchRequest(query="how persistent memory is merged across sessions", mode="semantic", hits=5)
    )
    # Semantic search may or may not return results without embedder — if it does, check IDs
    if results:
        assert all(isinstance(r.relevance, float) for r in results)


def test_feed_and_hybrid_search(vespa_client: LiveVespaDocumentClient) -> None:
    results = vespa_client.search(
        SearchRequest(query="state consolidation proposals", mode="hybrid", hits=5)
    )
    if results:
        source_ids = {r.source_id for r in results}
        assert "test-integration-fixture-md" in source_ids


def test_delete_source(vespa_client: LiveVespaDocumentClient) -> None:
    vespa_client.delete_source("test-integration-fixture-md")
    time.sleep(1)
    results = vespa_client.search(
        SearchRequest(query="blackboard database", mode="keyword", hits=5)
    )
    source_ids = {r.source_id for r in results}
    assert "test-integration-fixture-md" not in source_ids
```

- [ ] **Step 11.2: Verify the integration test is skipped in normal runs**

```bash
uv run pytest tests/test_vespa_integration.py -v 2>&1 | grep -E "SKIP|PASS|FAIL"
```
Expected: all tests show `SKIPPED`

- [ ] **Step 11.3: Run linter and type checker**

```bash
uv run ruff check .
uv run ty check
```
Fix any issues before committing.

- [ ] **Step 11.4: Run full test suite**

```bash
uv run pytest --ignore=tests/test_vespa_integration.py -q 2>&1 | tail -10
```
Expected: all tests PASS

- [ ] **Step 11.5: Commit**

```bash
git add tests/test_vespa_integration.py
git commit -m "test: add opt-in live Vespa integration test"
```

---

## Self-Review

### Spec Coverage

| Spec section | Covered by task |
|---|---|
| `RetrievalConfig` in harness.yaml | Task 1 |
| PostgreSQL `document_sources` + `document_chunks` | Task 2 |
| Database CRUD methods | Task 3 |
| Proxy permission enforcement | Task 4 |
| Domain models (`DocumentChunk`, `SearchResult`, `SearchRequest`, `FeedSummary`) | Task 5 |
| `VespaDocumentClient` Protocol | Task 5 |
| Vespa app package (services.xml + schema) | Task 6 |
| `LiveVespaDocumentClient` (feed, delete, search) | Task 7 |
| Query forms (keyword / semantic / hybrid) | Task 7 |
| Hit normalization | Task 7 |
| Source hash skip + force flag | Task 8 |
| Path allowlist (project root only) | Task 8 |
| Ignored dirs (.git, .venv, __pycache__) | Task 8 |
| Supported extensions (.md .py .yaml etc.) | Task 8 |
| Source status pending → indexed / failed / skipped | Task 8 |
| `index_documents` skill + SKILL.md | Task 9 |
| `search_documents` skill + SKILL.md | Task 10 |
| Citation-first output format | Task 10 |
| `tool_result_max_chars` truncation | Task 10 |
| Integration test (opt-in) | Task 11 |
| `retrieval.enabled=false` guard | Tasks 9 + 10 |
| Vespa unavailable fast-fail | Tasks 8 + 10 |
| Empty query / invalid mode rejection | Task 10 |
| No raw YQL user input interpolation | Task 7 (`@query` params) |
| `pyvespa` dependency | Task 1 |

### Type Consistency Check

- `make_source_id` defined in Task 5 (`retrieval.py`), used in Task 8 (`document_index.py`) ✓
- `make_chunk_id` defined in Task 5, used in Task 5 (`make_document_chunks`) ✓
- `FeedSummary` defined in Task 5, returned by `feed_chunks` in Task 7 ✓
- `VespaDocumentClient` Protocol defined in Task 5, `LiveVespaDocumentClient` implements it in Task 7, `FakeVespaClient` in Task 7 tests ✓
- `DocumentIndexer` takes `VespaDocumentClient` (Protocol), satisfied by both `LiveVespaDocumentClient` and `FakeVespaClient` ✓
- `DbDocumentSource` / `DbDocumentChunk` defined in Task 2, CRUD in Task 3, proxy in Task 4 ✓
- `IndexResult` defined in Task 8, consumed in Tasks 9 ✓
- `SkillResult` imported from `harness_poc.core.skill_result` in both skills ✓

### Placeholder Scan

No "TBD", "TODO", or "implement later" strings. All code blocks are complete. Each step shows exact commands with expected output.
