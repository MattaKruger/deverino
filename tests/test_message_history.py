from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

from harness_poc.core.message_history import (
    estimate_message_tokens,
    prune_message_history,
    sanitize_new_messages,
)


def test_sanitize_new_messages_truncates_tool_return_content() -> None:
    messages: list[ModelMessage] = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="semble_search",
                    content="x" * 100,
                    tool_call_id="call-1",
                )
            ]
        )
    ]

    sanitized = sanitize_new_messages(messages, tool_result_max_chars=12)

    part = sanitized[0].parts[0]
    assert isinstance(part, ToolReturnPart)
    content = str(part.content)
    assert "tool result truncated" in content
    assert "original_chars=100" in content
    assert content.endswith("x" * 12)
    original_part = messages[0].parts[0]
    assert isinstance(original_part, ToolReturnPart)
    assert original_part.content == "x" * 100


def test_prune_message_history_drops_oldest_turns_until_under_budget() -> None:
    messages = [
        *_turn("old", "x" * 500),
        *_turn("middle", "y" * 500),
        *_turn("new", "z" * 20),
    ]
    max_tokens = estimate_message_tokens(_turn("new", "z" * 20)) + 20

    pruned = prune_message_history(messages, max_tokens=max_tokens, recent_turns=1)

    serialized = repr(pruned)
    assert "old" not in serialized
    assert "middle" not in serialized
    assert "new" in serialized


def test_prune_message_history_noops_when_under_budget() -> None:
    messages = _turn("hello", "world")

    pruned = prune_message_history(messages, max_tokens=10_000, recent_turns=2)

    assert pruned == messages


def _turn(user: str, assistant: str) -> list[ModelRequest | ModelResponse]:
    return [
        ModelRequest(parts=[UserPromptPart(content=user)]),
        ModelResponse(parts=[TextPart(content=assistant)]),
    ]
