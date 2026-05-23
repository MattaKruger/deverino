from __future__ import annotations

from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_evaluate_goal_echoes_inputs_when_complete(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    result = runner.execute_skill(
        tool_name="evaluate_goal",
        arguments={
            "is_complete": True,
            "reasoning": "All tasks done.",
            "final_answer": "The answer is 42.",
        },
        session_id=session_id,
    )
    assert result.status == "success"
    assert "complete=True" in result.content
    assert "All tasks done" in result.content
    assert result.artifacts["is_complete"] is True
    assert result.artifacts["reasoning"] == "All tasks done."
    assert result.artifacts["final_answer"] == "The answer is 42."


def test_evaluate_goal_echoes_inputs_when_incomplete(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    result = runner.execute_skill(
        tool_name="evaluate_goal",
        arguments={
            "is_complete": False,
            "reasoning": "Still working on the task.",
        },
        session_id=session_id,
    )
    assert result.status == "success"
    assert "complete=False" in result.content
    assert "Still working on the task" in result.content
    assert result.artifacts["is_complete"] is False


def test_evaluate_goal_handles_defaults(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    result = runner.execute_skill(
        tool_name="evaluate_goal",
        arguments={"is_complete": False, "reasoning": ""},
        session_id=session_id,
    )
    assert result.status == "success"
    assert result.artifacts["is_complete"] is False
    assert result.artifacts["reasoning"] == ""
