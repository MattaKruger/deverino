from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine

from harness_poc.core import document_index
from harness_poc.core.config import RetrievalConfig
from harness_poc.core.document_index import DocumentIndexer
from harness_poc.core.retrieval import (
    DocumentChunk,
    compute_content_hash,
    make_chunk_id,
    make_source_id,
)
from harness_poc.core.storage import BlackboardDatabase
from tests.test_vespa_client import FakeVespaClient


def _make_indexer(
    db: BlackboardDatabase,
    vespa: FakeVespaClient,
    config: RetrievalConfig | None = None,
) -> DocumentIndexer:
    return DocumentIndexer(
        config=config or RetrievalConfig(chunk_size_chars=100, chunk_overlap_chars=10),
        database=db,
        vespa_client=vespa,
    )


def test_index_new_markdown_file(db_engine: Engine, tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("# Hello\n\nThis is a test document.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["README.md"])

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

    first = indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    assert first.indexed == 1

    second = indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    assert second.skipped == 1
    assert second.indexed == 0


def test_has_indexable_changes_returns_false_for_unchanged_sources(
    db_engine: Engine, tmp_path: Path
) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("Same content.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    assert indexer.has_indexable_changes(project_root=tmp_path, paths=["doc.md"])

    first = indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    assert first.indexed == 1

    assert not indexer.has_indexable_changes(project_root=tmp_path, paths=["doc.md"])


def test_has_indexable_changes_retries_failed_sources(
    db_engine: Engine, tmp_path: Path
) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("Same content.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    source_id = make_source_id("doc.md")
    content_hash = document_index._compute_file_hash(doc)
    db.upsert_document_source(
        document_index._make_db_source(
            source_id=source_id,
            uri="doc.md",
            content_hash=content_hash,
            status="failed",
            chunk_count=0,
            title="Doc",
            error="previous failure",
        )
    )

    assert indexer.has_indexable_changes(project_root=tmp_path, paths=["doc.md"])


def test_force_reindex_skips_hash_check(db_engine: Engine, tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("Same content.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    indexer.index_paths(project_root=tmp_path, paths=["doc.md"])
    initial_fed = len(vespa.fed_ids)

    result = indexer.index_paths(project_root=tmp_path, paths=["doc.md"], force=True)
    assert result.indexed == 1
    assert len(vespa.fed_ids) > initial_fed


def test_index_pdf_file(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "guide.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    source_id = make_source_id("guide.pdf")
    fake_chunks = [
        DocumentChunk(
            source_id=source_id,
            uri="guide.pdf",
            title="Introduction",
            chunk_id=make_chunk_id(source_id, 0),
            chunk_index=0,
            text="Content about Vespa document indexing.",
            kind="source",
            content_hash=compute_content_hash("Content about Vespa document indexing."),
            updated_at=1_000_000,
        )
    ]

    mock_convert = MagicMock(return_value=fake_chunks)
    monkeypatch.setattr(document_index, "convert_pdf_to_chunks", mock_convert)

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["guide.pdf"])

    assert result.indexed == 1
    assert result.skipped == 0
    assert result.failed == 0
    assert result.chunks_indexed == 1
    fed_text = "\n".join(chunk.text for chunk in vespa._docs.values())
    assert "Vespa document indexing" in fed_text
    mock_convert.assert_called_once_with(
        file_path=pdf,
        uri="guide.pdf",
        title="Guide",
        kind="source",
        max_tokens=100,
    )


def test_index_blank_pdf_returns_failed(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "blank.pdf"
    pdf.write_bytes(b"%PDF-1.4 blank")

    monkeypatch.setattr(document_index, "convert_pdf_to_chunks", lambda **_kw: [])

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["blank.pdf"])

    assert result.failed == 1
    assert result.indexed == 0
    assert any("no content extracted" in f["error"] for f in result.failures)


def test_index_pdf_conversion_error_returns_failed(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"not a pdf")

    def _raise(**_kw: object) -> list[DocumentChunk]:
        msg = "PDF conversion failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(document_index, "convert_pdf_to_chunks", _raise)

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["corrupt.pdf"])

    assert result.failed == 1
    assert any("PDF conversion failed" in f["error"] for f in result.failures)


def test_skip_unchanged_pdf(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "guide.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    source_id = make_source_id("guide.pdf")
    fake_chunks = [
        DocumentChunk(
            source_id=source_id,
            uri="guide.pdf",
            title="Guide",
            chunk_id=make_chunk_id(source_id, 0),
            chunk_index=0,
            text="Stable content.",
            kind="source",
            content_hash=compute_content_hash("Stable content."),
            updated_at=1_000_000,
        )
    ]
    mock_convert = MagicMock(return_value=fake_chunks)
    monkeypatch.setattr(document_index, "convert_pdf_to_chunks", mock_convert)

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    first = indexer.index_paths(project_root=tmp_path, paths=["guide.pdf"])
    assert first.indexed == 1

    second = indexer.index_paths(project_root=tmp_path, paths=["guide.pdf"])
    assert second.skipped == 1
    assert second.indexed == 0
    assert mock_convert.call_count == 1


def test_unsupported_file_type_is_skipped(db_engine: Engine, tmp_path: Path) -> None:
    image = tmp_path / "binary.png"
    image.write_bytes(b"not a supported document")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(project_root=tmp_path, paths=["binary.png"])
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

    result = indexer.index_paths(project_root=tmp_path, paths=["."])
    assert result.indexed == 0


def test_configured_ignore_path_is_not_indexed(db_engine: Engine, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    generated = docs / "generated"
    generated.mkdir(parents=True)
    (docs / "guide.md").write_text("Index this.", encoding="utf-8")
    (generated / "output.md").write_text("Do not index this.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(
        db,
        vespa,
        RetrievalConfig(
            chunk_size_chars=100,
            chunk_overlap_chars=10,
            auto_index_ignore_paths=["docs/generated"],
        ),
    )

    result = indexer.index_paths(project_root=tmp_path, paths=["docs"])

    assert result.indexed == 1
    assert db.get_document_source("docs-guide-md") is not None
    assert db.get_document_source("docs-generated-output-md") is None


def test_exclude_dirs_argument_is_not_indexed(db_engine: Engine, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    generated = docs / "generated"
    generated.mkdir(parents=True)
    (docs / "guide.md").write_text("Index this.", encoding="utf-8")
    (generated / "output.md").write_text("Do not index this.", encoding="utf-8")

    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()
    indexer = _make_indexer(db, vespa)

    result = indexer.index_paths(
        project_root=tmp_path,
        paths=["docs"],
        exclude_dirs=["docs/generated"],
    )

    assert result.indexed == 1
    assert db.get_document_source("docs-guide-md") is not None
    assert db.get_document_source("docs-generated-output-md") is None


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
