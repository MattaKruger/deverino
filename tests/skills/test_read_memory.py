from __future__ import annotations

from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_read_memory_lists_keys_when_no_key_provided(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "key1", "value1")
    database.write_memory(session_id, "key2", {"nested": True})

    result = runner.execute_skill(tool_name="read_memory", arguments={}, session_id=session_id)
    assert result.status == "success"
    assert "key1" in result.content
    assert "key2" in result.content


def test_read_memory_returns_empty_list_when_no_memory(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    result = runner.execute_skill(tool_name="read_memory", arguments={}, session_id=session_id)
    assert result.status == "success"
    assert "memory_keys" in result.content


def test_read_memory_returns_payload_for_specific_key(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "my_key", {"data": "test payload"})

    result = runner.execute_skill(
        tool_name="read_memory",
        arguments={"memory_key": "my_key"},
        session_id=session_id,
    )
    assert result.status == "success"
    assert "test payload" in result.content
    assert result.artifacts["memory_key"] == "my_key"


def test_read_memory_returns_failed_when_key_missing(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    result = runner.execute_skill(
        tool_name="read_memory",
        arguments={"memory_key": "nonexistent"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "No memory found" in result.content


def test_read_memory_handles_string_payload(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "string_key", "just a string")

    result = runner.execute_skill(
        tool_name="read_memory",
        arguments={"memory_key": "string_key"},
        session_id=session_id,
    )
    assert result.status == "success"
    assert "just a string" in result.content
