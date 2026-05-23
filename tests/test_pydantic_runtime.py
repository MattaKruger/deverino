from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai.models.test import TestModel
from sqlalchemy import Engine

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.pydantic_runtime import (
    MAX_SEMBLE_SEARCH_CALLS_PER_RUN,
    AgentDeps,
    build_model,
    build_runtime,
    build_skill_tools,
    execute_skill_as_tool,
)
from harness_poc.core.skill_context import SkillResult
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.core.storage import BlackboardDatabase

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from pydantic_ai import RunContext


def test_build_model_uses_test_model_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("harness_poc.core.config._find_dotenv", lambda: None)
    config = LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None)

    model = build_model(config)

    assert isinstance(model, TestModel)


def test_build_skill_tools_reuses_discovered_skill_schema(
    db_engine: Engine,
) -> None:
    skill_runner, _database, _config, _session_id = _runtime_parts(db_engine)

    tools = build_skill_tools(skill_runner)
    tool_by_name = {tool.name: tool for tool in tools}

    assert "read_memory" in tool_by_name
    read_memory_tool = tool_by_name["read_memory"]
    assert read_memory_tool.description is not None
    assert read_memory_tool.description.startswith("Retrieves data")
    assert (
        read_memory_tool.function_schema.json_schema["properties"]["memory_key"]["type"] == "string"
    )


def test_execute_skill_as_tool_returns_raw_content_for_success(
    db_engine: Engine,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(db_engine)
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

    # Success returns raw content, not JSON-wrapped
    assert isinstance(raw_result, str)
    assert "stored" in raw_result


def test_execute_skill_as_tool_marks_human_action_required(
    db_engine: Engine,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(db_engine)
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


def test_execute_skill_as_tool_enforces_semble_search_budget(
    db_engine: Engine,
) -> None:
    _skill_runner, database, config, session_id = _runtime_parts(db_engine)
    calls = 0

    def fake_execute_skill(
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> SkillResult:
        del tool_name, arguments, session_id, on_text, on_tool_event
        nonlocal calls
        calls += 1
        return SkillResult(status="success", content="search result")

    skill_runner = cast("SkillRunner", _FakeSkillRunner(fake_execute_skill))
    ctx = _fake_run_context(
        AgentDeps(
            session_id=session_id,
            database=database,
            config=config,
            skill_runner=skill_runner,
        ),
    )

    outputs = [
        execute_skill_as_tool(ctx, "semble_search", {"query": f"q{i}"})
        for i in range(MAX_SEMBLE_SEARCH_CALLS_PER_RUN + 1)
    ]

    assert outputs[:MAX_SEMBLE_SEARCH_CALLS_PER_RUN] == (
        ["search result"] * MAX_SEMBLE_SEARCH_CALLS_PER_RUN
    )
    assert outputs[-1].startswith("[blocked] semble_search call budget reached")
    assert calls == MAX_SEMBLE_SEARCH_CALLS_PER_RUN


def test_runtime_can_run_with_test_model(db_engine: Engine) -> None:
    skill_runner, database, config, session_id = _runtime_parts(db_engine)
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


def test_stream_text_calls_on_text_callback(db_engine: Engine) -> None:
    skill_runner, database, config, session_id = _runtime_parts(db_engine)
    runtime = build_runtime(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        system_prompt="You are a test agent.",
        model=TestModel(call_tools=[]),
    )

    chunks: list[str] = []
    result = runtime.stream_text("hello", on_text=chunks.append)

    assert chunks, "on_text callback must be called at least once"
    assert result.content == "".join(chunks)


def _runtime_parts(
    engine: Engine,
) -> tuple[SkillRunner, BlackboardDatabase, HarnessConfig, str]:
    config = _test_config(engine)
    database = BlackboardDatabase(engine)
    session_id = database.start_session("Pydantic runtime test session.")
    skill_runner = SkillRunner(database=database, config=config)

    return skill_runner, database, config, session_id


def _test_config(engine: Engine) -> HarnessConfig:
    project_root = Path.cwd()
    return HarnessConfig(
        project_root=project_root,
        config_path=project_root / "harness.yaml",
        paths=HarnessPaths(
            soul=project_root / "harness_poc/system_prompts/SOUL.md",
            system_tools=project_root / "harness_poc/system_tools",
            system_skills=project_root / "harness_poc/system_skills",
            project_skills=project_root / "skills",
            workflows=project_root / "workflows",
            pipelines=project_root / "pipelines",
            personas=project_root / "personas",
        ),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
        runtime=RuntimeConfig(
            database_url=engine.url.render_as_string(hide_password=False),
            default_container_image="python:3.14-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
    )


def _fake_run_context(deps: AgentDeps) -> RunContext[AgentDeps]:
    return cast("RunContext[AgentDeps]", _FakeRunContext(deps=deps))


class _FakeRunContext:
    def __init__(self, *, deps: AgentDeps) -> None:
        self.deps = deps


class _FakeSkillRunner:
    def __init__(self, execute_skill: object) -> None:
        self.execute_skill = execute_skill
