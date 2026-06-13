from __future__ import annotations

import pytest

from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_summarize_memory_requires_memory_key(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    with pytest.raises(ValueError, match="summarize_memory requires memory_key"):
        runner.execute_skill(
            tool_name="summarize_memory",
            arguments={},
            session_id=session_id,
        )


def test_summarize_memory_fails_when_memory_missing(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    result = runner.execute_skill(
        tool_name="summarize_memory",
        arguments={"memory_key": "nonexistent_key"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "No memory found" in result.content


def test_summarize_memory_produces_summary_for_existing_memory(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(
        session_id,
        "research_key",
        {
            "topic": "PydanticAI migration",
            "findings": "run_stream stops at first text; use agent.iter() instead.",
        },
    )

    result = runner.execute_skill(
        tool_name="summarize_memory",
        arguments={"memory_key": "research_key"},
        session_id=session_id,
    )
    # Mock LLM (TestModel) produces deterministic output
    # The model returns the system prompt content since TestModel echoes
    assert result.status == "success"
    assert result.artifacts["memory_key"] == "research_key"
    assert isinstance(result.artifacts.get("summary"), str)


def test_summarize_memory_handles_string_payload(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "string_key", "A plain text memory value.")

    result = runner.execute_skill(
        tool_name="summarize_memory",
        arguments={"memory_key": "string_key"},
        session_id=session_id,
    )
    assert result.status == "success"


def test_summarize_memory_builds_messages_with_json_payload() -> None:
    from skills.summarize_memory.skill import _build_messages

    messages = _build_messages(
        memory_key="test_key",
        payload={"data": "test value", "nested": {"key": "val"}},
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "test_key" in messages[1]["content"]
    assert "test value" in messages[1]["content"]


def test_summarize_memory_builds_messages_with_string_payload() -> None:
    from skills.summarize_memory.skill import _build_messages

    messages = _build_messages(memory_key="test_key", payload="just a string payload")
    assert "just a string payload" in messages[1]["content"]
