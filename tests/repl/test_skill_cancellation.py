from __future__ import annotations

import asyncio
import json
import time
from threading import Event
from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel
from sqlalchemy import Engine

from harness_poc.core.config import HarnessConfig
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.runtime import build_runtime
from harness_poc.core.skills import CancellationToken, SkillResult, SkillRunner
from harness_poc.core.storage import BlackboardAccessProxy, BlackboardDatabase
from harness_poc.core.tools import ToolRunner
from harness_poc.system_tools import _registry

if TYPE_CHECKING:
    import pytest


async def test_tool_runner_cancels_long_running_builtin(
    test_config: HarnessConfig,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_runner, session_id, _database = _tool_runner(test_config, db_engine)
    tool_runner.discover_tools()
    started = Event()

    def cancellable_container_exec(
        command: str = "",
        container: str = "",
        cancellation: CancellationToken | None = None,
    ) -> SkillResult:
        del command, container
        started.set()
        while cancellation is not None and not cancellation.cancelled:
            time.sleep(0.01)
        reason = cancellation.reason if cancellation is not None else ""
        return SkillResult(status="cancelled", content=f"cancelled: {reason}")

    monkeypatch.setitem(
        _registry,
        "container_exec",
        {
            "name": "container_exec",
            "description": "test container exec",
            "parameters": {"type": "object", "properties": {}},
            "handler": cancellable_container_exec,
        },
    )

    task = asyncio.create_task(
        asyncio.to_thread(
            tool_runner.execute_tool,
            "container_exec",
            {"command": "sleep", "container": "test"},
            session_id=session_id,
            call_id="test-call-1",
        )
    )
    assert await asyncio.to_thread(started.wait, 1)

    tool_runner.cancel_call("test-call-1", "reload")
    raw = await asyncio.wait_for(task, timeout=1)

    result = json.loads(raw)
    assert result["status"] == "cancelled"
    assert result["content"] == "cancelled: reload"


def test_synthetic_tool_return_repairs_pending_tool_call(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    database = BlackboardDatabase(db_engine)
    database.create_tables()
    session_id = database.start_session("test")
    skill_runner = SkillRunner(database=database, config=test_config)
    runtime = build_runtime(
        session_id=session_id,
        database=database,
        config=test_config,
        skill_runner=skill_runner,
        system_prompt="You are a test agent.",
        model=TestModel(call_tools=[]),
    )
    call_id = "test-call-1"
    messages: list[ModelMessage] = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="execute_python",
                    args={"code": "import time; time.sleep(10)"},
                    tool_call_id=call_id,
                )
            ]
        )
    ]

    repaired = runtime.inject_synthetic_tool_return(
        messages,
        call_id=call_id,
        tool_name="execute_python",
        content="cancelled: reload",
    )

    assert len(repaired) == 2
    assert isinstance(repaired[-1], ModelRequest)
    part = repaired[-1].parts[0]
    assert isinstance(part, ToolReturnPart)
    assert part.tool_call_id == call_id
    assert part.content == "cancelled: reload"
    assert runtime.run_text("What just happened?", message_history=repaired).content


def _tool_runner(
    test_config: HarnessConfig, db_engine: Engine,
) -> tuple[ToolRunner, str, BlackboardDatabase]:
    database = BlackboardDatabase(db_engine)
    database.create_tables()
    session_id = database.start_session("test")
    proxy = BlackboardAccessProxy(
        database,
        SkillPermissions(blackboard="read_write", workspace="read_write"),
    )
    runner = ToolRunner(
        config=test_config,
        database=proxy,
        runtime_config=test_config.runtime,
    )
    return runner, session_id, database
