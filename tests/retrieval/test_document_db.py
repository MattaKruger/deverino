from __future__ import annotations

from sqlalchemy import Engine

from harness_poc.core.storage import BlackboardDatabase, DbDocumentChunk, DbDocumentSource


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


def _make_chunk(
    chunk_id: str = "test-source-0000", source_id: str = "test-source"
) -> DbDocumentChunk:
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
    updated = DbDocumentSource(
        source_id="test-source",
        uri="docs/test-source.md",
        title="Test Doc",
        kind="doc",
        content_hash="abc123",
        status="indexed",
        chunk_count=5,
        metadata_payload={},
        updated_at="2026-05-20T00:00:01",
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
    db.upsert_document_chunk(_make_chunk())
    chunks = db.list_chunks_for_source("test-source")
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "test-source-0000"


def test_list_chunks_for_source(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.upsert_document_source(_make_source())
    db.upsert_document_chunk(_make_chunk("test-source-0000"))
    db.upsert_document_chunk(_make_chunk("test-source-0001"))
    chunks = db.list_chunks_for_source("test-source")
    assert len(chunks) == 2
    assert all(c.source_id == "test-source" for c in chunks)
