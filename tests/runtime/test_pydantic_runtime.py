from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai.models.test import TestModel
from sqlalchemy import Engine

from harness_poc.core.config import HarnessConfig, LLMConfig
from harness_poc.core.runtime import (
    MAX_SEMBLE_SEARCH_CALLS_PER_RUN,
    AgentDeps,
    build_model,
    build_runtime,
    build_skill_tools,
    execute_skill_as_tool,
)
from harness_poc.core.skills import SkillResult, SkillRunner
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
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    skill_runner, _database, _config, _session_id = _runtime_parts(test_config, db_engine)

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
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(test_config, db_engine)
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
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(test_config, db_engine)
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
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    _skill_runner, database, config, session_id = _runtime_parts(test_config, db_engine)
    calls = 0

    def fake_execute_skill(
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_event: Callable[[str], None] | None = None,
        call_id: str | None = None,
    ) -> SkillResult:
        del tool_name, arguments, session_id, on_text, on_tool_event, call_id
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


def test_runtime_can_run_with_test_model(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(test_config, db_engine)
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


def test_stream_text_calls_on_text_callback(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    skill_runner, database, config, session_id = _runtime_parts(test_config, db_engine)
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
    test_config: HarnessConfig, db_engine: Engine,
) -> tuple[SkillRunner, BlackboardDatabase, HarnessConfig, str]:
    database = BlackboardDatabase(db_engine)
    session_id = database.start_session("Pydantic runtime test session.")
    skill_runner = SkillRunner(database=database, config=test_config)

    return skill_runner, database, test_config, session_id


def _fake_run_context(deps: AgentDeps) -> RunContext[AgentDeps]:
    return cast("RunContext[AgentDeps]", _FakeRunContext(deps=deps))


class _FakeRunContext:
    def __init__(self, *, deps: AgentDeps) -> None:
        self.deps = deps
        self.tool_call_id: str | None = None


class _FakeSkillRunner:
    def __init__(self, execute_skill: object) -> None:
        self.execute_skill = execute_skill
