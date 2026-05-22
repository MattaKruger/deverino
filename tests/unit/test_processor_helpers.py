"""Unit tests for processor helper functions — pure, no I/O.

These functions extract and transform data in the async event
processors. Testing them in isolation catches parsing bugs without
needing the full async event loop.
"""

# ruff: noqa: ANN201

from harness_poc.core.events import AgentInputAdded, SkillCalled, SkillCompleted, SkillRequested
from harness_poc.core.processors.llm_worker import _parse_skill_request, _prompt_from_event
from harness_poc.core.processors.tool_worker import _cancel_reason, _skill_request_parts

# ---------------------------------------------------------------------------
# _prompt_from_event — LLM worker
# ---------------------------------------------------------------------------


def test_prompt_from_agent_input():
    """AgentInputAdded yields the user content as the prompt."""
    event = AgentInputAdded(session_id="s1", user_content="Summarise the project state.")
    prompt = _prompt_from_event(event)
    assert prompt == "Summarise the project state."


def test_prompt_from_skill_completed():
    """SkillCompleted yields a formatted prompt with status and content."""
    event = SkillCompleted(
        session_id="s1",
        tool_name="read_memory",
        status="success",
        content="Project has 3 active sessions.",
    )
    prompt = _prompt_from_event(event)
    assert "read_memory" in prompt
    assert "success" in prompt
    assert "3 active sessions" in prompt


def test_prompt_from_skill_completed_failed():
    """A failed skill still produces a prompt with the error content."""
    event = SkillCompleted(
        session_id="s1",
        tool_name="search_documents",
        status="failed",
        content="Vespa connection refused.",
    )
    prompt = _prompt_from_event(event)
    assert "failed" in prompt
    assert "Vespa connection refused" in prompt


def test_prompt_from_skill_uses_skill_name_fallback():
    """When tool_name is empty, skill_name is used."""
    event = SkillCompleted(
        session_id="s1",
        tool_name="",
        skill_name="read_memory",
        status="success",
        content="ok",
    )
    prompt = _prompt_from_event(event)
    assert "read_memory" in prompt


def test_prompt_from_skill_uses_result_fallback():
    """When content is empty, result is used."""
    event = SkillCompleted(
        session_id="s1",
        tool_name="read_memory",
        status="success",
        content="",
        result="fallback result",
    )
    prompt = _prompt_from_event(event)
    assert "fallback result" in prompt


# ---------------------------------------------------------------------------
# _parse_skill_request — LLM worker
# ---------------------------------------------------------------------------


def test_parse_skill_request_valid():
    """Valid JSON with skill_name and arguments is parsed."""
    result = _parse_skill_request(
        '{"skill_name": "read_memory", "arguments": {"memory_key": "test"}}'
    )
    assert result is not None
    assert result["skill_name"] == "read_memory"
    assert result["arguments"] == {"memory_key": "test"}


def test_parse_skill_request_with_tool_name():
    """tool_name is accepted as an alternative to skill_name."""
    result = _parse_skill_request(
        '{"tool_name": "read_memory", "arguments": {"key": "val"}}'
    )
    assert result is not None
    assert result["skill_name"] == "read_memory"


def test_parse_skill_request_tool_name_preferred_over_none_skill_name():
    """When skill_name is absent, tool_name fills in."""
    result = _parse_skill_request('{"tool_name": "search", "arguments": {}}')
    assert result is not None
    assert result["skill_name"] == "search"


def test_parse_skill_request_invalid_json():
    """Non-JSON content returns None."""
    result = _parse_skill_request("just thinking out loud...")
    assert result is None


def test_parse_skill_request_json_not_dict():
    """JSON that isn't a dict returns None."""
    result = _parse_skill_request('["list", "of", "items"]')
    assert result is None


def test_parse_skill_request_missing_skill_name():
    """JSON dict without skill_name or tool_name returns None."""
    result = _parse_skill_request('{"arguments": {"key": "val"}}')
    assert result is None


def test_parse_skill_request_arguments_not_dict():
    """Arguments that isn't a dict returns None."""
    result = _parse_skill_request(
        '{"skill_name": "read_memory", "arguments": "not a dict"}'
    )
    assert result is None


def test_parse_skill_request_skill_name_not_string():
    """Non-string skill_name returns None."""
    result = _parse_skill_request(
        '{"skill_name": 123, "arguments": {"key": "val"}}'
    )
    assert result is None


# ---------------------------------------------------------------------------
# _skill_request_parts — tool worker
# ---------------------------------------------------------------------------


def test_skill_request_parts_from_skill_called():
    """SkillCalled event yields tool_name and arguments."""
    event = SkillCalled(
        session_id="s1", tool_name="read_memory", arguments={"memory_key": "test"}
    )
    name, args = _skill_request_parts(event)
    assert name == "read_memory"
    assert args == {"memory_key": "test"}


def test_skill_request_parts_from_skill_requested():
    """SkillRequested event yields skill_name and arguments."""
    event = SkillRequested(
        session_id="s1", skill_name="delegate_task", arguments={"persona": "helper"}
    )
    name, args = _skill_request_parts(event)
    assert name == "delegate_task"
    assert args == {"persona": "helper"}


def test_skill_request_parts_empty_arguments():
    """Arguments default to empty dict when not provided."""
    event = SkillCalled(session_id="s1", tool_name="list_memory_keys")
    name, args = _skill_request_parts(event)
    assert name == "list_memory_keys"
    assert args == {}


# ---------------------------------------------------------------------------
# _cancel_reason — tool worker
# ---------------------------------------------------------------------------


def test_cancel_reason_with_prefix():
    """'cancelled:' prefix is stripped from the reason."""
    reason = _cancel_reason("cancelled: user interrupted")
    assert reason == "user interrupted"


def test_cancel_reason_with_prefix_no_space():
    """Prefix without trailing space still strips correctly."""
    reason = _cancel_reason("cancelled:timeout")
    assert reason == "timeout"


def test_cancel_reason_without_prefix():
    """Content without the prefix is returned as-is."""
    reason = _cancel_reason("task aborted")
    assert reason == "task aborted"


def test_cancel_reason_empty():
    """Empty content returns default 'cancelled'."""
    reason = _cancel_reason("")
    assert reason == "cancelled"


def test_cancel_reason_only_prefix():
    """Content that is exactly 'cancelled:' returns empty string."""
    reason = _cancel_reason("cancelled:")
    assert reason == ""
