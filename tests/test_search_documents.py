from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sqlalchemy import Engine

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RetrievalConfig,
    RuntimeConfig,
)
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.retrieval import SearchRequest, SearchResult
from harness_poc.core.skills import SkillContext
from harness_poc.core.storage import BlackboardAccessProxy, BlackboardDatabase
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
            default_container_image="python:3.14-slim",
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


# -- Error / validation tests (unchanged behaviour) ------------------------------------


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


def test_search_no_results_returns_success(db_engine: Engine, tmp_path: Path) -> None:
    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.return_value = []
        result = execute(ctx, {"query": "zzz_nonexistent_zzz"})

    assert result.status == "success"
    assert "no results" in result.content.lower()
    assert result.artifacts["results"] == []


# -- Preview mode tests ----------------------------------------------------------------


def test_search_preview_mode_returns_needs_orchestrator_action(
    db_engine: Engine, tmp_path: Path
) -> None:
    """Default (preview) mode returns a compact preview and asks the user to confirm."""
    fake_results = [
        SearchResult(
            source_id="docs-foo-md",
            uri="docs/foo.md",
            title="Foo Doc",
            chunk_id="docs-foo-md-0001",
            chunk_index=1,
            text="This is the chunk text about memory management in modern systems.",
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

    assert result.status == "needs_orchestrator_action"
    # Preview includes the URI and score
    assert "docs/foo.md" in result.content
    assert "0.82" in result.content
    # Preview asks the user to choose
    assert "load" in result.content.lower()
    # Artifacts still contain the full result data
    assert result.artifacts["query"] == "memory"
    assert result.artifacts["mode"] == "keyword"
    assert result.artifacts["result_count"] == 1
    assert len(result.artifacts["results"]) == 1
    assert result.artifacts["results"][0]["uri"] == "docs/foo.md"


def test_search_preview_uses_short_excerpts(db_engine: Engine, tmp_path: Path) -> None:
    """Preview excerpts are capped at ~80 chars to keep the prompt compact."""
    long_text = "A" * 500
    fake_results = [
        SearchResult(
            source_id="s1",
            uri="a.md",
            title="T",
            chunk_id="s1-0001",
            chunk_index=1,
            text=long_text,
            relevance=0.9,
            kind="doc",
        )
    ]

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.return_value = fake_results
        result = execute(ctx, {"query": "test"})

    # The full 500-char text should NOT appear in the preview
    assert long_text not in result.content
    # But a truncated version with "..." should
    assert "..." in result.content


def test_search_preview_config_defaults(db_engine: Engine, tmp_path: Path) -> None:
    """Hits and mode default to config values when not supplied (still works in preview)."""
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


# -- Expand mode tests ----------------------------------------------------------------


def test_search_expand_mode_returns_full_excerpts(
    db_engine: Engine, tmp_path: Path
) -> None:
    """expand=[...] returns full (300-char) excerpts for selected indices with success."""
    fake_results = [
        SearchResult(
            source_id="s0",
            uri="a.md",
            title="A",
            chunk_id="s0-0001",
            chunk_index=0,
            text="First result text about apples.",
            relevance=0.95,
            kind="doc",
        ),
        SearchResult(
            source_id="s1",
            uri="b.md",
            title="B",
            chunk_id="s1-0001",
            chunk_index=0,
            text="Second result text about bananas.",
            relevance=0.80,
            kind="doc",
        ),
        SearchResult(
            source_id="s2",
            uri="c.md",
            title="C",
            chunk_id="s2-0001",
            chunk_index=0,
            text="Third result text about cherries.",
            relevance=0.60,
            kind="doc",
        ),
    ]

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.return_value = fake_results
        result = execute(ctx, {"query": "fruit", "expand": [1, 3]})

    assert result.status == "success"
    # Should contain first and third results (1-based indices 1 and 3)
    assert "apples" in result.content
    assert "cherries" in result.content
    # Should NOT contain the second result
    assert "bananas" not in result.content
    # Expand format uses chunk citation
    assert "a.md#chunk-0" in result.content
    assert "c.md#chunk-0" in result.content
    # Artifacts only include selected results
    assert len(result.artifacts["results"]) == 2


def test_search_expand_empty_indices_returns_failed(
    db_engine: Engine, tmp_path: Path
) -> None:
    """Empty or invalid expand indices return a failed result."""
    fake_results = [
        SearchResult(
            source_id="s0",
            uri="a.md",
            title="A",
            chunk_id="s0-0001",
            chunk_index=0,
            text="Some text.",
            relevance=0.9,
            kind="doc",
        )
    ]

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.return_value = fake_results
        result = execute(ctx, {"query": "test", "expand": []})

    assert result.status == "failed"
    assert "no valid" in result.content.lower() or "indices" in result.content.lower()


def test_search_expand_out_of_range_indices_ignored(
    db_engine: Engine, tmp_path: Path
) -> None:
    """Out-of-range expand indices are silently ignored."""
    fake_results = [
        SearchResult(
            source_id="s0",
            uri="a.md",
            title="A",
            chunk_id="s0-0001",
            chunk_index=0,
            text="Only result.",
            relevance=0.9,
            kind="doc",
        )
    ]

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.return_value = fake_results
        # Index 5 is out of range (only 1 result), index 1 is valid
        result = execute(ctx, {"query": "test", "expand": [1, 5]})

    assert result.status == "success"
    assert "Only result." in result.content
    assert len(result.artifacts["results"]) == 1  # only index 1 was valid


def test_search_expand_deduplicates_indices(
    db_engine: Engine, tmp_path: Path
) -> None:
    """Duplicate expand indices are de-duplicated."""
    fake_results = [
        SearchResult(
            source_id="s0",
            uri="a.md",
            title="A",
            chunk_id="s0-0001",
            chunk_index=0,
            text="Only result.",
            relevance=0.9,
            kind="doc",
        )
    ]

    db = BlackboardDatabase(db_engine)
    session_id = db.start_session("test")
    cfg = _make_config(tmp_path)
    ctx = _make_ctx(db, cfg, session_id)

    with patch("skills.search_documents.skill.LiveVespaDocumentClient") as mock_client:
        mock_client.return_value.search.return_value = fake_results
        result = execute(ctx, {"query": "test", "expand": [1, 1, 1]})

    assert result.status == "success"
    assert len(result.artifacts["results"]) == 1
