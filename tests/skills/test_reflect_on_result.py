# ruff: noqa: PLC0415
from __future__ import annotations

import json

import pytest

from harness_poc.core.skills import SkillRunner
from harness_poc.core.storage import BlackboardDatabase


def test_reflect_on_result_requires_objective(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    with pytest.raises(ValueError, match="reflect_on_result requires objective"):
        runner.execute_skill(
            tool_name="reflect_on_result",
            arguments={"memory_key": "some_key"},
            session_id=session_id,
        )


def test_reflect_on_result_requires_memory_key(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    with pytest.raises(ValueError, match="reflect_on_result requires memory_key"):
        runner.execute_skill(
            tool_name="reflect_on_result",
            arguments={"objective": "Test"},
            session_id=session_id,
        )


def test_reflect_on_result_fails_when_payload_missing(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner

    result = runner.execute_skill(
        tool_name="reflect_on_result",
        arguments={
            "objective": "Evaluate nonexistent result",
            "memory_key": "nonexistent_key",
        },
        session_id=session_id,
    )
    assert result.status == "failed"
    reflection = json.loads(result.content)
    assert reflection["verdict"] == "fail"
    assert "No result was found" in reflection["summary"]


def test_reflect_on_result_writes_to_memory(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(
        session_id, "result_key", {"output": "research completed", "status": "done"}
    )

    result = runner.execute_skill(
        tool_name="reflect_on_result",
        arguments={
            "objective": "Check completed research",
            "memory_key": "result_key",
            "output_key": "reflection_output",
        },
        session_id=session_id,
    )
    # Mock LLM produces some reflection
    assert result.status in {"success", "failed"}

    memory = database.read_memory(session_id, "reflection_output")
    assert isinstance(memory, dict)
    assert "verdict" in memory
    assert memory["verdict"] in {"pass", "fail"}


def test_reflect_on_result_uses_default_output_key(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, database = session_runner
    database.write_memory(session_id, "result_key", {"output": "work done"})

    runner.execute_skill(
        tool_name="reflect_on_result",
        arguments={
            "objective": "Check default output key",
            "memory_key": "result_key",
        },
        session_id=session_id,
    )

    memory = database.read_memory(session_id, "result_key_reflection")
    assert isinstance(memory, dict)


def test_strip_json_fence_removes_markdown_wrapper() -> None:
    from skills.reflect_on_result.skill import _strip_json_fence

    assert _strip_json_fence('{"key": "value"}') == '{"key": "value"}'
    assert _strip_json_fence('```json\n{"key": "value"}\n```') == '{"key": "value"}'
    # Not wrapped in fences
    assert _strip_json_fence("plain text") == "plain text"


def test_parse_json_object_handles_valid_and_invalid() -> None:
    from skills.reflect_on_result.skill import _parse_json_object

    assert _parse_json_object('{"verdict": "pass"}') == {"verdict": "pass"}
    assert _parse_json_object("not json") == {}
    assert _parse_json_object("[1, 2, 3]") == {}  # list, not dict
    assert _parse_json_object('```json\n{"verdict": "fail"}\n```') == {"verdict": "fail"}


def test_normalize_reflection_sanitizes_verdict() -> None:
    from skills.reflect_on_result.skill import _normalize_reflection

    result = _normalize_reflection(
        '{"verdict": "PASS", "summary": "All good", "risks": ["minor"]}',
        objective="Test objective",
        memory_key="test_key",
        payload={"status": "done"},
    )
    assert result["verdict"] == "pass"
    assert result["summary"] == "All good"
    assert result["risks"] == ["minor"]
    assert result["evaluated_memory_key"] == "test_key"


def test_normalize_reflection_falls_back_on_invalid_verdict() -> None:
    from skills.reflect_on_result.skill import _normalize_reflection

    result = _normalize_reflection(
        '{"verdict": "maybe", "summary": "Uncertain"}',
        objective="Test",
        memory_key="key",
        payload={"status": "failed"},
    )
    assert result["verdict"] == "fail"  # payload status failed → fail


def test_fallback_verdict_detects_failed_status() -> None:
    from skills.reflect_on_result.skill import _fallback_verdict

    assert _fallback_verdict({"status": "failed"}) == "fail"
    assert _fallback_verdict({"status": "blocked"}) == "fail"
    assert _fallback_verdict({"status": "success"}) == "pass"
    assert _fallback_verdict("just a string") == "pass"
