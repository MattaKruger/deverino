from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict


class Message(TypedDict):
    role: str
    content: str


class Usage(TypedDict, total=False):
    """API-reported token usage, including cache details."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int


class ToolCall(TypedDict):
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    kind: Literal["text", "tool_call"]
    content: str
    tool_call: ToolCall | None = None
    usage: Usage | None = None
