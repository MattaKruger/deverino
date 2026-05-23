"""Smoke-test all Deverino skills through SkillRunner.

Parametrized pytest version — uses the shared session_runner fixture
from conftest.py instead of an ad-hoc database setup.

Skills that require external services (LangSearch API, Semble CLI,
Docker) are tested in their graceful-failure / missing-dependency paths.
"""

from __future__ import annotations

import pytest

from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase

SMOKE_CASES: list[tuple[str, dict, set[str]]] = [
    ("evaluate_goal", {"is_complete": True, "reasoning": "smoke test"}, {"success"}),
    ("evaluate_goal", {"is_complete": False, "reasoning": "still working"}, {"success"}),
    ("read_memory", {}, {"success"}),
    ("read_memory", {"memory_key": "nonexistent"}, {"failed"}),
    ("review_work", {"objective": "test", "memory_key": "nonexistent"}, {"failed"}),
    ("summarize_memory", {"memory_key": "nonexistent"}, {"failed"}),
    ("reflect_on_result", {"objective": "test", "memory_key": "nonexistent"}, {"failed"}),
    ("web_search", {"query": "Python testing", "count": 2}, {"success"}),
    ("semble_search", {"query": "BlackboardDatabase"}, {"success", "failed"}),
    ("spec_writer", {"mode": "questions"}, {"needs_orchestrator_action"}),
    ("spec_writer", {
        "goal": "Add export support",
        "context": "A Python harness.",
        "requirements": "Must be fast",
    }, {"success"}),
    ("consolidate_state", {"mode": "preview"}, {"blocked", "success"}),
    ("delegate_task", {
        "persona": "web_researcher",
        "objective": "What is PydanticAI?",
        "use_mock": True,
    }, {"success"}),
    ("container_spawn", {"image": "python:3.14-slim"}, {"success", "failed"}),
    ("container_exec", {"command": "", "container": "test"}, {"failed"}),
    ("container_destroy", {}, {"failed"}),
]


@pytest.mark.parametrize("skill_name,arguments,expected", SMOKE_CASES)
def test_skill_smoke(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
    skill_name: str,
    arguments: dict,
    expected: set[str],
) -> None:
    runner, session_id, database = session_runner

    # Pre-populate memory for read/write skill tests
    database.write_memory(session_id, "test_key", {"data": "test_value"})

    # review_work and summarize_memory need test_key when not testing missing keys
    if arguments.get("memory_key") == "nonexistent":
        pass  # intentionally missing
    elif skill_name in {"review_work", "summarize_memory", "reflect_on_result"}:
        arguments = {**arguments, "memory_key": "test_key"}

    result = runner.execute_skill(
        tool_name=skill_name, arguments=arguments, session_id=session_id
    )
    assert result.status in expected, (
        f"{skill_name}: expected status in {expected}, got {result.status}"
    )
