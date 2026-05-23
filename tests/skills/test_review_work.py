from __future__ import annotations

import json

import pytest

from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_review_work_requires_memory_key(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    with pytest.raises(ValueError, match="review_work requires memory_key"):
        runner.execute_skill(
            tool_name="review_work",
            arguments={"objective": "Test objective"},
            session_id=session_id,
        )


def test_review_work_fails_when_memory_missing(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _database = session_runner

    result = runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Check missing result",
            "memory_key": "nonexistent_key",
        },
        session_id=session_id,
    )
    assert result.status == "failed"
    review = json.loads(result.content)
    assert review["verdict"] == "fail"
    assert "No result was found" in review["summary"]


def test_review_work_passes_when_memory_exists(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "result_key", {"output": "some work"})

    result = runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Verify result exists",
            "memory_key": "result_key",
        },
        session_id=session_id,
    )
    assert result.status == "success"
    review = json.loads(result.content)
    assert review["verdict"] == "pass"
    assert "A result exists" in review["summary"]


def test_review_work_writes_to_output_key(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "result_key", {"output": "work"})

    result = runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Check custom output",
            "memory_key": "result_key",
            "output_key": "my_review_output",
        },
        session_id=session_id,
    )
    assert result.status == "success"

    memory = database.read_memory(session_id, "my_review_output")
    assert isinstance(memory, dict)
    assert memory["verdict"] == "pass"


def test_review_work_uses_default_output_key(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "result_key", {"output": "work"})

    runner.execute_skill(
        tool_name="review_work",
        arguments={
            "objective": "Check default output key",
            "memory_key": "result_key",
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "result_key_review")
    assert isinstance(memory, dict)
    assert memory["verdict"] == "pass"
