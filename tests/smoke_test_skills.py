"""Smoke-test all 13 Deverino skills through SkillRunner.

Usage:
    uv run python tests/smoke_test_skills.py

Tests each skill with minimal args. Skills that require external
services (LangSearch API, Semble CLI, Docker) are tested in their
graceful-failure / missing-dependency paths.
"""

from __future__ import annotations

import tempfile
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


def main() -> int:
    repo_root = Path.cwd()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    config = HarnessConfig(
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
            database_path=Path(db_path),
            default_container_image="python:3.12-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
    )

    database = BlackboardDatabase(db_path)
    database.create_tables()
    session_id = database.start_session("smoke-test")
    runner = SkillRunner(database=database, config=config)

    # Pre-populate some memory for read/write skill tests
    database.write_memory(session_id, "test_key", {"data": "test_value"})

    tests: list[tuple[str, dict, str, set[str]]] = [
        # (skill_name, args, description, expected_statuses)
        (
            "evaluate_goal",
            {"is_complete": True, "reasoning": "smoke test"},
            "evaluate_goal stub",
            {"success"},
        ),
        (
            "evaluate_goal",
            {"is_complete": False, "reasoning": "still working"},
            "evaluate_goal incomplete",
            {"success"},
        ),
        ("read_memory", {}, "read_memory list keys", {"success"}),
        (
            "read_memory",
            {"memory_key": "test_key"},
            "read_memory specific key",
            {"success"},
        ),
        (
            "read_memory",
            {"memory_key": "nonexistent"},
            "read_memory missing key",
            {"failed"},
        ),
        (
            "review_work",
            {"objective": "test", "memory_key": "test_key"},
            "review_work existing key",
            {"success"},
        ),
        (
            "review_work",
            {"objective": "test", "memory_key": "nonexistent"},
            "review_work missing key",
            {"failed"},
        ),
        (
            "summarize_memory",
            {"memory_key": "test_key"},
            "summarize_memory existing key",
            {"success"},
        ),
        (
            "summarize_memory",
            {"memory_key": "nonexistent"},
            "summarize_memory missing key",
            {"failed"},
        ),
        (
            "reflect_on_result",
            {"objective": "test", "memory_key": "nonexistent"},
            "reflect_on_result missing key",
            {"failed"},
        ),
        (
            "web_search",
            {"query": "Python testing", "count": 2},
            "web_search (live or mock)",
            {"success"},
        ),
        (
            "semble_search",
            {"query": "BlackboardDatabase"},
            "semble_search code search",
            {"success", "failed"},  # fails if semble not installed
        ),
        (
            "spec_writer",
            {"mode": "questions"},
            "spec_writer questions mode",
            {"needs_orchestrator_action"},
        ),
        (
            "spec_writer",
            {"goal": "Add export support", "context": "A Python harness.", "requirements": "Must be fast"},
            "spec_writer full draft",
            {"success"},
        ),
        (
            "consolidate_state",
            {"mode": "preview"},
            "consolidate_state preview",
            {"blocked", "success"},  # blocked if empty session
        ),
        (
            "delegate_task",
            {
                "persona": "web_researcher",
                "objective": "What is PydanticAI?",
                "use_mock": True,
            },
            "delegate_task mock",
            {"success"},
        ),
        (
            "container_spawn",
            {"image": "python:3.12-slim"},
            "container_spawn with image (may work if docker)",
            {"success", "failed"},
        ),
        (
            "container_exec",
            {"command": "", "container": "test"},
            "container_exec no command",
            {"failed"},
        ),
        (
            "container_destroy",
            {},
            "container_destroy no container",
            {"failed"},
        ),
    ]

    passed = 0
    failed = 0
    exceptions = 0

    print("=" * 60)
    print("Deverino Skill Smoke Test")
    print("=" * 60)

    for skill_name, args, desc, expected in tests:
        print(f"\n--- {desc} ---")
        try:
            result = runner.execute_skill(
                tool_name=skill_name, arguments=args, session_id=session_id
            )
            status = result.status
            content_preview = (
                result.content[:150] + "..."
                if len(result.content) > 150
                else result.content
            ).replace("\n", "\\n")
            print(f"  status: {status}")
            print(f"  content: {content_preview}")

            if status in expected:
                print(f"  ✓ PASS")
                passed += 1
            else:
                print(f"  ✗ FAIL — expected one of {expected}, got {status}")
                failed += 1
        except Exception as exc:
            import traceback

            print(f"  ✗ EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            exceptions += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {exceptions} exceptions")
    print("=" * 60)

    Path(db_path).unlink(missing_ok=True)
    return 0 if (failed == 0 and exceptions == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
