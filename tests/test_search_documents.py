from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
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
from harness_poc.core.retrieval import SearchRequest, SearchResult
from harness_poc.core.skill_context import SkillContext
from skills.search_documents.skill import execute


def _make_config(
    tmp_path: Path,
    *,
    enabled: bool = True,
    default_hits: int = 8,
    default_mode: str = "hybrid",
    tool_result_max_chars: int = 12_000,
) -> HarnessConfig:
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
            tool_result_max_chars=tool_result_max_chars,
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        retrieval=RetrievalConfig(
            enabled=enabled,
            default_hits=default_hits,
            default_mode=default_mode,
        ),
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
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path, enabled=False)
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"query": "memory"})
    assert result.status == "failed"


def test_search_empty_query_returns_failed(db_engine: Engine, tmp_path: Path) -> None:
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"query": ""})
    assert result.status == "failed"
    assert "empty" in result.content.lower() or "query" in result.content.lower()


def test_search_invalid_mode_returns_failed(db_engine: Engine, tmp_path: Path) -> None:
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    result = execute(ctx, {"query": "memory", "mode": "foobar"})
    assert result.status == "failed"
    assert "mode" in result.content.lower()


def test_search_formats_citation_first(db_engine: Engine, tmp_path: Path) -> None:
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

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.return_value = fake_results
        result = execute(ctx, {"query": "memory", "mode": "keyword"})

    assert result.status == "success"
    assert "1. docs/foo.md#chunk-1" in result.content
    assert "0.82" in result.content

    artifacts = result.artifacts
    assert artifacts["query"] == "memory"
    assert artifacts["mode"] == "keyword"
    assert len(artifacts["results"]) == 1
    assert artifacts["results"][0]["uri"] == "docs/foo.md"
    assert artifacts["results"][0]["relevance"] == pytest.approx(0.82)


def test_search_uses_config_defaults(db_engine: Engine, tmp_path: Path) -> None:
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path, default_hits=3, default_mode="semantic")
    ctx = _make_ctx(db, cfg, session_id)

    captured_requests: list[SearchRequest] = []

    def fake_search(request: SearchRequest) -> list[SearchResult]:
        captured_requests.append(request)
        return []

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.side_effect = fake_search
        execute(ctx, {"query": "memory"})

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.hits == 3
    assert req.mode == "semantic"
