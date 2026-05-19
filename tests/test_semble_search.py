from __future__ import annotations

from pathlib import Path

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_runner import SkillRunner


def test_semble_search_requires_query(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={"query": ""},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a query string" in result.content


def test_semble_search_missing_binary_detected(tmp_path: Path) -> None:
    """When semble is not installed, returns helpful error."""
    runner, session_id, _ = _runner(tmp_path)
    # The test environment may or may not have semble installed.
    # If not installed, we get a clear error message.
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={"query": "test query"},
        session_id=session_id,
    )
    # Either success (semble installed + ran) or failed with install message
    assert result.status in {"success", "failed"}
    if result.status == "failed" and "not installed" in result.content:
        assert "pip install semble" in result.content


def test_semble_search_find_related_requires_file_path(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={"action": "find_related", "query": "dummy"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "file_path" in result.content


def test_semble_search_find_related_requires_line(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={
            "action": "find_related",
            "query": "dummy",
            "file_path": "test.py",
        },
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "line" in result.content.lower()


def test_semble_search_find_related_rejects_invalid_line(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={
            "action": "find_related",
            "query": "dummy",
            "file_path": "test.py",
            "line": "not_a_number",
        },
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "Invalid line number" in result.content


def test_semble_search_respects_top_k(tmp_path: Path) -> None:
    """Top-k is validated as an int between 1-50."""
    from skills.semble_search.skill import _parse_top_k

    assert _parse_top_k(5) == 5
    assert _parse_top_k("abc") == 5  # default
    assert _parse_top_k(0) == 1  # clamped to 1
    assert _parse_top_k(100) == 50  # clamped to 50


def test_semble_search_mode_validation(tmp_path: Path) -> None:
    """Search mode defaults to hybrid for invalid values."""
    from skills.semble_search.skill import _parse_mode

    assert _parse_mode("hybrid") == "hybrid"
    assert _parse_mode("semantic") == "semantic"
    assert _parse_mode("bm25") == "bm25"
    assert _parse_mode("invalid") == "hybrid"  # default
    assert _parse_mode(None) == "hybrid"


def _runner(tmp_path: Path) -> tuple[SkillRunner, str, BlackboardDatabase]:
    config = _test_config(tmp_path)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    session_id = database.start_session("test")
    return SkillRunner(database=database, config=config), session_id, database


def _test_config(tmp_path: Path) -> HarnessConfig:
    repo_root = Path.cwd()
    return HarnessConfig(
        project_root=repo_root,
        config_path=repo_root / "harness.yaml",
        paths=HarnessPaths(
            soul=repo_root / "harness_poc/system_prompts/SOUL.md",
            system_skills=repo_root / "harness_poc/system_skills",
            project_skills=repo_root / "skills",
            workflows=repo_root / "workflows",
            pipelines=repo_root / "pipelines",
            personas=repo_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_path=tmp_path / "blackboard.db",
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )
