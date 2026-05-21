from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sqlalchemy import Engine

from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RetrievalConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.skill_context import SkillContext
from skills.index_documents.skill import execute
from tests.test_vespa_client import FakeVespaClient


def _make_config(tmp_path: Path, retrieval: RetrievalConfig) -> HarnessConfig:
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
        retrieval=retrieval,
    )


def _make_ctx(db: BlackboardDatabase, config: HarnessConfig, session_id: str) -> SkillContext:
    perms = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "read"})
    return SkillContext(
        session_id=session_id,
        skill_name="index_documents",
        database=BlackboardAccessProxy(db, perms),
        config=config,
        permissions=perms,
    )


def test_index_documents_disabled_returns_failed(db_engine: Engine, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, RetrievalConfig(enabled=False))
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"paths": ["docs"]})
    assert result.status == "failed"
    assert "retrieval" in result.content.lower() or "disabled" in result.content.lower()


def test_index_documents_result_has_required_artifacts(db_engine: Engine, tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("# Test\nContent here.", encoding="utf-8")

    cfg = _make_config(
        tmp_path,
        RetrievalConfig(chunk_size_chars=200, chunk_overlap_chars=20),
    )
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    ctx = _make_ctx(db, cfg, session_id)

    fake_vespa = FakeVespaClient()
    with patch("skills.index_documents.skill.LiveVespaDocumentClient", return_value=fake_vespa):
        result = execute(ctx, {"paths": ["README.md"]})

    assert result.status == "success"
    assert "indexed" in result.artifacts
    assert "skipped" in result.artifacts
    assert "failed" in result.artifacts
    assert "chunks_indexed" in result.artifacts
    assert "failures" in result.artifacts
    assert result.artifacts["indexed"] >= 1


def test_index_documents_rejects_invalid_exclude_dirs(
    db_engine: Engine, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path, RetrievalConfig())
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"paths": ["README.md"], "exclude_dirs": "docs/generated"})

    assert result.status == "failed"
    assert "exclude_dirs" in result.content
