from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from harness_poc.core.config import HarnessConfig
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.event_bus import EventBus
from harness_poc.core.event_store import EventStore
from harness_poc.core.llm_client import LLMClient
from harness_poc.core.logging import configure_logging
from harness_poc.core.pydantic_runtime import (
    PydanticAgentRuntime,
    build_runtime,
)
from harness_poc.core.skill_runner import SkillRunner
from harness_poc.core.skill_scaffolder import SkillScaffolder
from harness_poc.core.state import build_state_context
from harness_poc.core.workflow_runner import WorkflowRunner

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

    from harness_poc.core.llm_client import Message


STARTUP_ERRORS = (
    OSError,
    RuntimeError,
    sqlite3.OperationalError,
    TypeError,
    ValueError,
    yaml.YAMLError,
)


@dataclass(slots=True)
class AppState:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    llm_client: LLMClient
    pydantic_runtime: PydanticAgentRuntime
    pydantic_messages: list[ModelMessage]
    goal_decision_model: Model | None
    messages: list[Message]
    tools: list[dict[str, Any]]
    event_bus: EventBus


def build_app_state() -> AppState:
    config = HarnessConfig.load()
    configure_logging(config.project_root)
    database = BlackboardDatabase(config.runtime.database_path)
    database.create_tables()
    system_prompt = config.paths.soul.read_text(encoding="utf-8")
    session_id = database.start_session("Interactive proof of concept session.")
    project_state = database.ensure_project_state()
    session_state = database.ensure_session_state(session_id)
    skill_runner = SkillRunner(database=database, config=config)
    workflow_runner = WorkflowRunner(skill_runner)
    messages: list[Message] = [
        {
            "role": "system",
            "content": "\n\n".join(
                [
                    system_prompt,
                    build_state_context(project_state, session_state),
                ],
            ),
        },
    ]
    tools = skill_runner.discover_skills()
    full_system_prompt = "\n\n".join(
        [
            system_prompt,
            build_state_context(project_state, session_state),
        ],
    )
    event_store = EventStore(config.runtime.database_path)
    event_bus = EventBus(event_store)

    return AppState(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        skill_scaffolder=SkillScaffolder(config),
        workflow_runner=workflow_runner,
        llm_client=LLMClient(),
        pydantic_runtime=build_runtime(
            session_id=session_id,
            database=database,
            config=config,
            skill_runner=skill_runner,
            system_prompt=full_system_prompt,
            enable_tools=True,
        ),
        pydantic_messages=[],
        goal_decision_model=None,
        messages=messages,
        tools=tools,
        event_bus=event_bus,
    )
