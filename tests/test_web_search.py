from __future__ import annotations

from pathlib import Path

import pytest

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.skill_runner import SkillRunner


def test_web_search_requires_query(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    with pytest.raises(ValueError, match="web_search requires a query string"):
        runner.execute_skill(
            tool_name="web_search",
            arguments={},
            session_id=session_id,
        )


def test_web_search_returns_results(tmp_path: Path) -> None:
    """Works in both mock and live mode — returns success with results."""
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="web_search",
        arguments={"query": "PydanticAI"},
        session_id=session_id,
    )
    assert result.status == "success"
    assert "PydanticAI" in result.content
    assert isinstance(result.artifacts.get("results"), list)


def test_web_search_mock_mode_is_available(tmp_path: Path) -> None:
    """When no API key is configured, returns mock results with [MOCK] prefix."""
    # Test the mock output function directly to verify it works
    from skills.web_search.skill import _mock_result

    result = _mock_result("test query", 5)
    assert result.status == "success"
    assert "[MOCK]" in result.content
    assert "test query" in result.content
    assert result.artifacts.get("mock") is True
    assert len(result.artifacts["results"]) > 0


def test_web_search_count_clamping(tmp_path: Path) -> None:
    """Count is clamped between 1 and MAX_RESULTS (20)."""
    from skills.web_search.skill import _clamp_count

    assert _clamp_count(5) == 5
    assert _clamp_count(999) == 20  # MAX_RESULTS
    assert _clamp_count(0) == 1
    assert _clamp_count("abc") == 5  # DEFAULT_COUNT
    assert _clamp_count(None) == 5


def test_web_search_empty_query_raises(tmp_path: Path) -> None:
    runner, session_id, _ = _runner(tmp_path)
    with pytest.raises(ValueError, match="web_search requires a query string"):
        runner.execute_skill(
            tool_name="web_search",
            arguments={"query": "   "},
            session_id=session_id,
        )


def test_web_search_formats_results(tmp_path: Path) -> None:
    """Result formatting works regardless of live/mock mode."""
    runner, session_id, _ = _runner(tmp_path)
    result = runner.execute_skill(
        tool_name="web_search",
        arguments={"query": "format test", "count": 2},
        session_id=session_id,
    )
    assert "Web search results for: format test" in result.content


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
