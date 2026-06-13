"""Unit tests for the LLM client types — the model communication contract.

LLMResponse, Message, ToolCall, and Usage are the fundamental types
that every LLM interaction flows through.
"""


from dataclasses import FrozenInstanceError

import pytest

from harness_poc.core.runtime import LLMResponse, Message, ToolCall, Usage

# ---------------------------------------------------------------------------
# LLMResponse — construction and immutability
# ---------------------------------------------------------------------------


def test_text_response():
    """A plain text response has no tool_call."""
    r = LLMResponse(kind="text", content="Hello, world.")
    assert r.kind == "text"
    assert r.content == "Hello, world."
    assert r.tool_call is None
    assert r.usage is None


def test_tool_call_response():
    """A tool_call response carries the tool name and arguments."""
    r = LLMResponse(
        kind="tool_call",
        content="Calling read_memory...",
        tool_call={"name": "read_memory", "arguments": {"memory_key": "test"}},
    )
    assert r.kind == "tool_call"
    assert r.tool_call is not None
    assert r.tool_call["name"] == "read_memory"
    assert r.tool_call["arguments"] == {"memory_key": "test"}


def test_response_with_usage():
    """A response can carry token usage metadata."""
    usage: Usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    r = LLMResponse(kind="text", content="ok", usage=usage)
    assert r.usage == usage
    assert r.usage["total_tokens"] == 150  # ty:ignore[not-subscriptable]


def test_response_with_cache_usage():
    """Usage can include cache hit/miss details."""
    usage: Usage = {
        "prompt_tokens": 200,
        "completion_tokens": 30,
        "total_tokens": 230,
        "cache_hit_tokens": 150,
        "cache_miss_tokens": 50,
    }
    r = LLMResponse(kind="text", content="cached response", usage=usage)
    assert r.usage["cache_hit_tokens"] == 150  # ty:ignore[not-subscriptable]
    assert r.usage["cache_miss_tokens"] == 50  # ty:ignore[not-subscriptable]


def test_llm_response_is_immutable():
    """LLMResponse is frozen — fields cannot be reassigned."""
    r = LLMResponse(kind="text", content="original")
    with pytest.raises(FrozenInstanceError):
        r.content = "modified"  # ty:ignore[invalid-assignment]


def test_llm_response_equality():
    """Two responses with the same fields are equal."""
    r1 = LLMResponse(kind="text", content="same")
    r2 = LLMResponse(kind="text", content="same")
    assert r1 == r2


def test_llm_response_inequality_different_content():
    """Responses with different content are not equal."""
    r1 = LLMResponse(kind="text", content="a")
    r2 = LLMResponse(kind="text", content="b")
    assert r1 != r2


# ---------------------------------------------------------------------------
# ToolCall and Message — TypedDict shapes
# ---------------------------------------------------------------------------


def test_tool_call_typeddict_shape():
    """ToolCall has name and arguments fields."""
    tc: ToolCall = {"name": "search", "arguments": {"query": "test"}}
    assert tc["name"] == "search"
    assert tc["arguments"]["query"] == "test"


def test_message_typeddict_shape():
    """Message has role and content fields."""
    msg: Message = {"role": "user", "content": "Hello"}
    assert msg["role"] == "user"
    assert msg["content"] == "Hello"


def test_message_with_assistant_role():
    """Messages can represent assistant turns."""
    msg: Message = {"role": "assistant", "content": "Hi there!"}
    assert msg["role"] == "assistant"


def test_message_with_system_role():
    """Messages can represent system prompts."""
    msg: Message = {"role": "system", "content": "You are a helpful agent."}
    assert msg["role"] == "system"


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_tool_call_defaults_to_none():
    """A text response has tool_call=None by default."""
    r = LLMResponse(kind="text", content="no tool")
    assert r.tool_call is None


def test_usage_defaults_to_none():
    """Usage is None when not provided."""
    r = LLMResponse(kind="text", content="no usage")
    assert r.usage is None
