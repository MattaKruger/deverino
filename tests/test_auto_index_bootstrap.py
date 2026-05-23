from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from harness_poc.app_factory import bootstrap_document_index
from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RetrievalConfig,
    RuntimeConfig,
)
from harness_poc.core.retrieval import DocumentIndexer
from harness_poc.core.storage import BlackboardDatabase
from tests.test_vespa_client import FakeVespaClient


def _make_config(tmp_path: Path) -> HarnessConfig:
    return HarnessConfig(
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
            default_container_image="python:3.14-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        retrieval=RetrievalConfig(auto_index_paths=["docs"]),
    )


def test_bootstrap_skips_vespa_when_auto_index_sources_unchanged(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_SKIP_AUTO_INDEX", raising=False)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("Stable docs.", encoding="utf-8")

    config = _make_config(tmp_path)
    db = BlackboardDatabase(db_engine)
    indexer = DocumentIndexer(
        config=config.retrieval,
        database=db,
        vespa_client=FakeVespaClient(),
    )
    result = indexer.index_paths(project_root=tmp_path, paths=["docs"])
    assert result.indexed == 1

    health_checks = 0
    index_runs = 0

    def _record_health(_config: HarnessConfig) -> None:
        nonlocal health_checks
        health_checks += 1

    def _record_index(
        _config: HarnessConfig, _database: BlackboardDatabase, _paths: list[str]
    ) -> None:
        nonlocal index_runs
        index_runs += 1

    monkeypatch.setattr("harness_poc.app_factory._check_vespa_health", _record_health)
    monkeypatch.setattr("harness_poc.app_factory._run_auto_index", _record_index)

    bootstrap_document_index(config, db)

    assert health_checks == 0
    assert index_runs == 0


def test_bootstrap_indexes_only_changed_auto_index_sources(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_SKIP_AUTO_INDEX", raising=False)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "stable.md").write_text("Stable docs.", encoding="utf-8")
    (docs / "new.md").write_text("New docs.", encoding="utf-8")

    config = _make_config(tmp_path)
    db = BlackboardDatabase(db_engine)
    indexer = DocumentIndexer(
        config=config.retrieval,
        database=db,
        vespa_client=FakeVespaClient(),
    )
    result = indexer.index_paths(project_root=tmp_path, paths=["docs/stable.md"])
    assert result.indexed == 1

    index_paths: list[str] = []

    def _record_health(_config: HarnessConfig) -> None:
        return None

    def _record_index(
        _config: HarnessConfig, _database: BlackboardDatabase, paths: list[str]
    ) -> None:
        index_paths.extend(paths)

    monkeypatch.setattr("harness_poc.app_factory._check_vespa_health", _record_health)
    monkeypatch.setattr("harness_poc.app_factory._run_auto_index", _record_index)

    bootstrap_document_index(config, db)

    assert index_paths == ["docs/new.md"]


def test_bootstrap_partial_index_uses_only_missing_sources_in_real_indexer(
    db_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("HARNESS_SKIP_AUTO_INDEX", raising=False)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "already.md").write_text("Already indexed.", encoding="utf-8")
    (docs / "missing.md").write_text("Missing from metadata.", encoding="utf-8")

    config = _make_config(tmp_path)
    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()

    preindexer = DocumentIndexer(
        config=config.retrieval,
        database=db,
        vespa_client=vespa,
    )
    result = preindexer.index_paths(project_root=tmp_path, paths=["docs/already.md"])
    assert result.indexed == 1
    capsys.readouterr()
    fed_before_bootstrap = list(vespa.fed_ids)

    def _fake_live_vespa(_retrieval: RetrievalConfig) -> FakeVespaClient:
        return vespa

    monkeypatch.setattr("harness_poc.app_factory.LiveVespaDocumentClient", _fake_live_vespa)

    bootstrap_document_index(config, db)
    output = capsys.readouterr().out

    assert "Indexing 1 file(s)" in output
    assert "indexed docs/missing.md" in output
    assert "docs/already.md" not in output
    assert vespa.fed_ids == [*fed_before_bootstrap, "docs-missing-md-0000"]


def test_bootstrap_second_run_does_not_reindex_unchanged_sources(
    db_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("HARNESS_SKIP_AUTO_INDEX", raising=False)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("Stable guide.", encoding="utf-8")
    (docs / "plan.md").write_text("Stable plan.", encoding="utf-8")

    config = _make_config(tmp_path)
    db = BlackboardDatabase(db_engine)
    vespa = FakeVespaClient()

    def _fake_live_vespa(_retrieval: RetrievalConfig) -> FakeVespaClient:
        return vespa

    monkeypatch.setattr("harness_poc.app_factory.LiveVespaDocumentClient", _fake_live_vespa)

    bootstrap_document_index(config, db)
    first_output = capsys.readouterr().out
    first_fed_ids = list(vespa.fed_ids)

    bootstrap_document_index(config, db)
    second_output = capsys.readouterr().out

    assert "Indexing 2 file(s)" in first_output
    assert len(first_fed_ids) == 2
    assert vespa.fed_ids == first_fed_ids
    assert "Indexing project documents" not in second_output
    assert "Indexing 2 file(s)" not in second_output
