from __future__ import annotations

import pytest

from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_delegate_task_uses_pydanticai_fallback_and_writes_memory(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "persona": "web_researcher",
            "objective": "Explain PydanticAI migration tradeoffs",
            "memory_key": "delegated_result",
            "context": "Current harness uses dynamic skills.",
            "use_mock": True,
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "delegated_result")
    assert result.status == "success"
    assert isinstance(memory, dict)
    assert memory["status"] == "completed"
    assert "Explain PydanticAI migration tradeoffs" in memory["summary"]
    assert memory["artifacts"]["persona"] == "web_researcher"
    assert memory["artifacts"]["objective"] == "Explain PydanticAI migration tradeoffs"
    assert memory["artifacts"]["received_context"] == "Current harness uses dynamic skills."
    assert memory["artifacts"]["model_output"]["status"] == "completed"


def test_delegate_task_accepts_template_name_alias(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "template_name": "web_researcher",
            "objective": "Summarize adapter design",
            "use_mock": True,
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "web_researcher_result")
    assert result.status == "success"
    assert isinstance(memory, dict)
    assert memory["artifacts"]["persona"] == "web_researcher"


def test_delegate_task_streams_summary_chunks(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    chunks: list[str] = []

    result = runner.execute_skill(
        tool_name="delegate_task",
        arguments={
            "persona": "web_researcher",
            "objective": "Stream delegated research",
            "use_mock": True,
        },
        session_id=session_id,
        on_text=chunks.append,
    )

    assert result.status == "success"
    assert "".join(chunks)
    assert "Stream delegated research" in "".join(chunks)


def test_delegate_task_requires_persona_and_objective(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    with pytest.raises(ValueError, match="delegate_task requires objective"):
        runner.execute_skill(
            tool_name="delegate_task",
            arguments={"persona": "web_researcher"},
            session_id=session_id,
        )
