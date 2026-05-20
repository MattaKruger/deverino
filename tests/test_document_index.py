from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from harness_poc.core.config import RetrievalConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.document_index import DocumentIndexer
from tests.test_vespa_client import FakeVespaClient


def _make_config(**overrides: object) -> RetrievalConfig:
    defaults = {
        "chunk_size_chars": 100,
        "chunk_overlap_chars": 10,
    }
    defaults.update(overrides)
    return RetrievalConfig(**defaults)


def _make_indexer(
    db: BlackboardDatabase,
    vespa: FakeVespaClient,
    **config_overrides: object,
) -> DocumentIndexer:
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

    result = indexer.index_paths(project_root=tmp_path, paths=["."])
    assert result.indexed == 0


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
