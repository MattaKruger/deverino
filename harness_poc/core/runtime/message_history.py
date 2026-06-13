from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ToolReturnPart,
    UserPromptPart,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.messages import (
        ModelMessage,
    )

TOKEN_CHAR_RATIO = 4
TOKENS_PER_MESSAGE = 3
TRUNCATION_PREFIX_TEMPLATE = (
    "[tool result truncated: original_chars={original_chars} retained_chars={retained_chars}]\n"
)


def estimate_message_tokens(messages: list[ModelMessage]) -> int:
    """Return a conservative approximate token count for Pydantic AI messages."""
    if not messages:
        return 0
    try:
        payload = ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8")
    except (TypeError, ValueError, UnicodeDecodeError):
        payload = repr(messages)
    return max(1, len(payload) // TOKEN_CHAR_RATIO) + (len(messages) * TOKENS_PER_MESSAGE)


def sanitize_new_messages(
    messages: Sequence[ModelMessage],
    *,
    tool_result_max_chars: int,
) -> list[ModelMessage]:
    """Return message copies with oversized tool-return content made history-safe."""
    if tool_result_max_chars <= 0:
        return list(messages)

    return [_sanitize_message(message, tool_result_max_chars) for message in messages]


def prune_message_history(
    messages: Sequence[ModelMessage],
    *,
    max_tokens: int,
    recent_turns: int,
) -> list[ModelMessage]:
    """Drop oldest complete chat turns until history is under the token budget."""
    if max_tokens <= 0 or not messages:
        return []
    message_list = _strip_leading_orphan_tool_returns(list(messages))
    if not message_list:
        return []
    if estimate_message_tokens(message_list) <= max_tokens:
        return message_list

    turns = split_chat_turns(message_list)
    min_turns = max(1, recent_turns)
    pruned_turns = list(turns)

    while len(pruned_turns) > min_turns:
        candidate = [message for turn in pruned_turns[1:] for message in turn]
        if estimate_message_tokens(candidate) > max_tokens:
            pruned_turns = pruned_turns[1:]
            continue
        return candidate

    while len(pruned_turns) > 1:
        candidate = [message for turn in pruned_turns[1:] for message in turn]
        if estimate_message_tokens(candidate) <= max_tokens:
            return candidate
        pruned_turns = pruned_turns[1:]

    return [message for turn in pruned_turns for message in turn]


def _sanitize_message(message: ModelMessage, max_chars: int) -> ModelMessage:
    if not isinstance(message, ModelRequest):
        return message

    changed = False
    parts: list[Any] = []
    for part in message.parts:
        if isinstance(part, ToolReturnPart):
            content = _truncate_tool_content(part.content, max_chars)
            if content != part.content:
                changed = True
                parts.append(replace(part, content=content))
            else:
                parts.append(part)
        else:
            parts.append(part)

    if not changed:
        return message
    return replace(message, parts=parts)


def _truncate_tool_content(content: object, max_chars: int) -> object:
    text = content if isinstance(content, str) else _serialize_tool_content(content)
    if len(text) <= max_chars:
        return content

    prefix = TRUNCATION_PREFIX_TEMPLATE.format(
        original_chars=len(text),
        retained_chars=max_chars,
    )
    return f"{prefix}{text[:max_chars]}"


def _serialize_tool_content(content: object) -> str:
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(content)


def split_chat_turns(messages: list[ModelMessage]) -> list[list[ModelMessage]]:
    """Split message list into chat turns, each starting when a user message appears."""
    turns: list[list[ModelMessage]] = []
    current: list[ModelMessage] = []

    for message in messages:
        if _is_user_prompt_request(message) and current:
            turns.append(current)
            current = [message]
        else:
            current.append(message)

    if current:
        turns.append(current)
    return turns


def _strip_leading_orphan_tool_returns(
    messages: list[ModelMessage],
) -> list[ModelMessage]:
    """Remove leading messages that would create orphaned tool returns.

    DeepSeek (and other providers) require every 'tool' role message to be
    preceded by an 'assistant' message with 'tool_calls'.  If the history
    starts with a ModelRequest containing only ToolReturnParts — which can
    happen after a raw message-count slice drops the preceding ModelResponse —
    we strip those orphaned tool returns to keep the conversation valid.
    """
    idx = 0
    for msg in messages:
        if _is_tool_return_only_request(msg):
            idx += 1
        else:
            break
    if idx == 0:
        return messages
    return messages[idx:]


def _is_tool_return_only_request(message: ModelMessage) -> bool:
    """Return True when the message is a ModelRequest that contains only ToolReturnParts."""
    if not isinstance(message, ModelRequest):
        return False
    parts = list(message.parts)
    if not parts:
        return False
    return all(isinstance(p, ToolReturnPart) for p in parts)


def _is_user_prompt_request(message: ModelMessage) -> bool:
    return isinstance(message, ModelRequest) and any(
        isinstance(part, UserPromptPart) for part in message.parts
    )
