from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic_ai.models.test import TestModel

from harness_poc.core.config import HarnessConfig, HarnessPaths, RuntimeConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.llm_client import DeepSeekSettings
from harness_poc.core.pydantic_runtime import (
    AgentDeps,
    build_model,
    build_runtime,
    build_skill_tools,
    execute_skill_as_tool,
)
from harness_poc.core.skill_runner import SkillRunner

if TYPE_CHECKING:
    from pydantic_ai import RunContext


def test_build_model_uses_test_model_without_api_key() -> None:
    settings = DeepSeekSettings(api_key=None)

    model = build_model(settings)

    assert isinstance(model, TestModel)


def test_build_skill_tools_reuses_discovered_skill_schema(tmp_path: Path) -> None:
    skill_runner, _database, _config, _session_id = _runtime_parts(tmp_path)

    tools = build_skill_tools(skill_runner)
    tool_by_name = {tool.name: tool for tool in tools}

    assert "read_memory" in tool_by_name
    read_memory_tool = tool_by_name["read_memory"]
    assert read_memory_tool.description is not None
    assert read_memory_tool.description.startswith("Retrieves data")
    assert (
        read_memory_tool.function_schema.json_schema["properties"]["memory_key"]["type"] == "string"
    )


def test_execute_skill_as_tool_returns_structured_skill_result(
    tmp_path: Path,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(tmp_path)
    database.write_memory(session_id, "note", {"value": "stored"})
    ctx = _fake_run_context(
        AgentDeps(
            session_id=session_id,
            database=database,
            config=config,
            skill_runner=skill_runner,
        ),
    )

    raw_result = execute_skill_as_tool(ctx, "read_memory", {"memory_key": "note"})

    result = json.loads(raw_result)
    assert result["status"] == "success"
    assert result["artifacts"]["memory_key"] == "note"
    assert "stored" in result["content"]


def test_execute_skill_as_tool_marks_human_action_required(
    tmp_path: Path,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(tmp_path)
    ctx = _fake_run_context(
        AgentDeps(
            session_id=session_id,
            database=database,
            config=config,
            skill_runner=skill_runner,
        ),
    )

    raw_result = execute_skill_as_tool(ctx, "spec_writer", {"mode": "gather"})

    result = json.loads(raw_result)
    assert result["status"] == "needs_orchestrator_action"
    assert result["orchestrator_action_required"] is True
    assert "Stop and surface content" in result["orchestrator_instruction"]


def test_runtime_can_run_with_test_model(tmp_path: Path) -> None:
    skill_runner, database, config, session_id = _runtime_parts(tmp_path)
    runtime = build_runtime(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        system_prompt="You are a test agent.",
        model=TestModel(call_tools=[]),
    )

    result = runtime.run_text("hello")

    assert result.content == "success (no tool calls)"
    assert result.usage is not None
    assert result.messages


def _runtime_parts(
    tmp_path: Path,
) -> tuple[SkillRunner, BlackboardDatabase, HarnessConfig, str]:
    config = _test_config(tmp_path)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    session_id = database.start_session("Pydantic runtime test session.")
    skill_runner = SkillRunner(database=database, config=config)

    return skill_runner, database, config, session_id


def _test_config(tmp_path: Path) -> HarnessConfig:
    project_root = Path.cwd()
    return HarnessConfig(
        project_root=project_root,
        config_path=project_root / "harness.yaml",
        paths=HarnessPaths(
            soul=project_root / "harness_poc/system_prompts/SOUL.md",
            system_skills=project_root / "harness_poc/system_skills",
            project_skills=project_root / "skills",
            workflows=project_root / "workflows",
            personas=project_root / "personas",
        ),
        runtime=RuntimeConfig(
            database_path=tmp_path / "blackboard.db",
            default_container_image="python:3.12-slim",
        ),
    )


def _fake_run_context(deps: AgentDeps) -> RunContext[AgentDeps]:
    return cast("RunContext[AgentDeps]", _FakeRunContext(deps=deps))


class _FakeRunContext:
    def __init__(self, *, deps: AgentDeps) -> None:
        self.deps = deps
