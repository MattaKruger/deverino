"""Tests for the auto-observe post-turn hook.

Covers the turn filter, content builder, and observation extractor.
No live LLM calls — classifier behaviour is tested via monkeypatched chat_text.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import ModelRequest, ToolReturnPart

import harness_poc.core.runtime.pydantic_runtime as pydantic_runtime_mod
from harness_poc.core.runtime.pydantic_runtime import extract_observations_from_turn
from harness_poc.repl import _build_turn_content, _turn_has_signal_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(*tool_parts: tuple[str, str]) -> list[ModelRequest]:
    """Build ModelRequest messages from (tool_name, content) pairs."""
    return [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name=name,
                    content=content,
                    tool_call_id=f"call_{i}",
                )
                for i, (name, content) in enumerate(tool_parts)
            ]
        ),
    ]


def _setup_extractor_test(
    monkeypatch: pytest.MonkeyPatch,
    fake_output: str,
    live: bool = True,
) -> MagicMock:
    """Configure monkeypatches and return a mock SkillRunner."""
    monkeypatch.setattr(
        pydantic_runtime_mod, "is_live_model", lambda _model: live
    )

    def _fake_chat_text(
        messages: object,  # noqa: ARG001
        *,
        model: object,  # noqa: ARG001
    ) -> str:
        return fake_output

    monkeypatch.setattr(pydantic_runtime_mod, "chat_text", _fake_chat_text)
    return MagicMock()


# ---------------------------------------------------------------------------
# _turn_has_signal_tools
# ---------------------------------------------------------------------------


def test_turn_has_signal_tools_true() -> None:
    """A ModelRequest with a ToolReturnPart from semble_search returns True."""
    messages = _make_messages(("semble_search", "Found 3 results in harness_poc/repl.py"))
    assert _turn_has_signal_tools(messages) is True


def test_turn_has_signal_tools_false_for_non_signal() -> None:
    """A turn with only a non-signal tool (read_memory) returns False."""
    messages = _make_messages(("read_memory", '{"key": "value"}'))
    assert _turn_has_signal_tools(messages) is False


def test_turn_has_signal_tools_empty() -> None:
    """An empty message list returns False."""
    assert _turn_has_signal_tools([]) is False


def test_turn_has_signal_tools_mixed_tools() -> None:
    """Only the presence of at least one signal tool matters — mixed returns True."""
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_memory",
                    content="...",
                    tool_call_id="call_1",
                ),
                ToolReturnPart(
                    tool_name="search_documents",
                    content="chunks...",
                    tool_call_id="call_2",
                ),
            ]
        ),
    ]
    assert _turn_has_signal_tools(messages) is True


# ---------------------------------------------------------------------------
# _build_turn_content
# ---------------------------------------------------------------------------


def test_build_turn_content_includes_tool_output() -> None:
    """Returned string contains [tool: <name>] and the content."""
    messages = _make_messages(("semble_search", "Found 3 results in harness_poc/repl.py"))
    result = _build_turn_content(messages, "")
    assert "[tool: semble_search]" in result
    assert "Found 3 results in harness_poc/repl.py" in result


def test_build_turn_content_appends_final_text() -> None:
    """The final_text arg appears as [agent final] ..."""
    result = _build_turn_content([], "All done.")
    assert "[agent final] All done." in result


def test_build_turn_content_empty_turn() -> None:
    """Empty messages and empty final_text returns the sentinel string."""
    result = _build_turn_content([], "")
    assert result == "(empty turn)"


def test_build_turn_content_truncates_long_output() -> None:
    """Tool output longer than 4000 chars is truncated."""
    long_content = "x" * 5000
    messages = _make_messages(("read_file", long_content))
    result = _build_turn_content(messages, "")
    assert len(long_content) > 4000
    assert "x" * 4000 in result
    assert "x" * 4001 not in result


# ---------------------------------------------------------------------------
# extract_observations_from_turn — pure-logic tests (no live LLM)
# ---------------------------------------------------------------------------


def test_extract_observations_skips_test_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When is_live_model returns False, no observe calls are made."""
    skill_runner = _setup_extractor_test(monkeypatch, "{}", live=False)

    extract_observations_from_turn(
        "some turn content",
        model=MagicMock(),
        skill_runner=skill_runner,
        session_id="s1",
    )

    skill_runner.execute_skill.assert_not_called()


def test_extract_observations_handles_code_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classifier output wrapped in ```json ... ``` is parsed correctly."""
    entry_json = {
        "entries": [
            {
                "key": "codebase-entry",
                "observation_type": "entity",
                "summary": "Found main entry point.",
                "detail": "Knowing the entry point helps bootstrap analysis.",
            }
        ]
    }
    raw_output = "```json\n" + json.dumps(entry_json) + "\n```"
    skill_runner = _setup_extractor_test(monkeypatch, raw_output)

    extract_observations_from_turn(
        "some turn",
        model=MagicMock(),
        skill_runner=skill_runner,
        session_id="s1",
    )

    skill_runner.execute_skill.assert_called_once()
    call_args = skill_runner.execute_skill.call_args
    assert call_args.kwargs["arguments"]["observation_type"] == "entity"


def test_extract_observations_swallows_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-JSON classifier output logs but does not raise."""
    skill_runner = _setup_extractor_test(monkeypatch, "not valid json at all!!!")

    # Must not raise
    extract_observations_from_turn(
        "some turn",
        model=MagicMock(),
        skill_runner=skill_runner,
        session_id="s1",
    )

    skill_runner.execute_skill.assert_not_called()


def test_extract_observations_forwards_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful parse calls observe with distinct summary and detail."""
    entry_json = {
        "entries": [
            {
                "key": "config-shape",
                "observation_type": "schema",
                "summary": "Config has a runtime.database_url field.",
                "detail": (
                    "This field controls the PostgreSQL connection. "
                    "Agents must treat it as local runtime state, not source data."
                ),
            }
        ]
    }
    skill_runner = _setup_extractor_test(monkeypatch, json.dumps(entry_json))

    extract_observations_from_turn(
        "some turn",
        model=MagicMock(),
        skill_runner=skill_runner,
        session_id="s1",
    )

    skill_runner.execute_skill.assert_called_once()
    call_args = skill_runner.execute_skill.call_args
    assert call_args.kwargs["tool_name"] == "observe"
    arguments = call_args.kwargs["arguments"]
    assert arguments["observation_type"] == "schema"
    assert arguments["summary"] == "Config has a runtime.database_url field."
    assert "PostgreSQL connection" in arguments["detail"]
    # detail must be distinct from summary
    assert arguments["detail"] != arguments["summary"]


def test_extract_observations_empty_entries_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """{"entries": []} returns without calling observe."""
    skill_runner = _setup_extractor_test(monkeypatch, '{"entries": []}')

    extract_observations_from_turn(
        "some turn",
        model=MagicMock(),
        skill_runner=skill_runner,
        session_id="s1",
    )

    skill_runner.execute_skill.assert_not_called()


def test_extract_observations_multiple_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple entries each trigger a separate observe call."""
    entry_json = {
        "entries": [
            {
                "key": "entry-1",
                "observation_type": "entity",
                "summary": "First observation.",
                "detail": "Detail for first.",
            },
            {
                "key": "entry-2",
                "observation_type": "insight",
                "summary": "Second observation.",
                "detail": "Detail for second.",
            },
        ]
    }
    skill_runner = _setup_extractor_test(monkeypatch, json.dumps(entry_json))

    extract_observations_from_turn(
        "some turn",
        model=MagicMock(),
        skill_runner=skill_runner,
        session_id="s1",
    )

    assert skill_runner.execute_skill.call_count == 2
    first_call = skill_runner.execute_skill.call_args_list[0]
    second_call = skill_runner.execute_skill.call_args_list[1]
    assert first_call.kwargs["arguments"]["observation_type"] == "entity"
    assert second_call.kwargs["arguments"]["observation_type"] == "insight"
