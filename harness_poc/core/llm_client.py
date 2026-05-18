from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from openai import OpenAI
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from openai.types.chat import ChatCompletionMessageParam


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


class DeepSeekSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str | None = Field(
        default=None, validation_alias="DEEPSEEK_API_KEY"
    )
    base_url: str = Field(
        default="https://api.deepseek.com", validation_alias="DEEPSEEK_BASE_URL"
    )
    model: str = Field(
        default="deepseek-v4-flash", validation_alias="DEEPSEEK_MODEL"
    )
    reasoning_effort: str = Field(
        default="high", validation_alias="DEEPSEEK_REASONING"
    )
    thinking: Literal["enabled", "disabled"] = Field(
        default="enabled",
        validation_alias="DEEPSEEK_THINKING",
    )

    @classmethod
    def load(cls) -> DeepSeekSettings:
        env_path = find_dotenv()
        if env_path is None:
            return cls()
        settings_constructor = cast("Any", cls)
        return cast(
            "DeepSeekSettings", settings_constructor(_env_file=env_path)
        )

    def normalized_reasoning_effort(self) -> Literal["high", "max"]:
        if self.reasoning_effort in {"high", "max"}:
            return cast("Literal['high', 'max']", self.reasoning_effort)
        if self.reasoning_effort in {"low", "medium"}:
            return "high"
        if self.reasoning_effort == "xhigh":
            return "max"
        msg = (
            "DEEPSEEK_REASONING must be one of high, max, low, medium, or xhigh; "
            f"got {self.reasoning_effort!r}"
        )
        raise ValueError(msg)


class LLMClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        use_mock: bool | None = None,
        mock_response: (
            Callable[[list[Message], list[dict[str, Any]] | None], LLMResponse]
            | None
        ) = None,
    ) -> None:
        settings = DeepSeekSettings.load()
        resolved_api_key = api_key or settings.api_key
        self.model = settings.model if model == "deepseek-v4-flash" else model
        self.reasoning_effort = settings.normalized_reasoning_effort()
        self.thinking = settings.thinking
        self.mock_response = mock_response
        self.use_mock = (
            use_mock if use_mock is not None else resolved_api_key is None
        )
        self.client = (
            None
            if self.use_mock
            else OpenAI(
                api_key=resolved_api_key,
                base_url=settings.base_url
                if base_url == "https://api.deepseek.com"
                else base_url,
            )
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if self.use_mock:
            return self._mock_chat(messages=messages, tools=tools)
        return self._deepseek_chat(messages=messages, tools=tools)

    def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        if self.use_mock:
            return self._mock_stream_chat(
                messages=messages, tools=tools, on_text=on_text
            )
        return self._deepseek_stream_chat(
            messages=messages, tools=tools, on_text=on_text
        )

    def _deepseek_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if self.client is None:
            msg = "DeepSeek client is not initialized"
            raise RuntimeError(msg)

        create_completion = cast("Any", self.client.chat.completions.create)
        response = create_completion(
            **self._build_chat_request(
                messages=messages, tools=tools, stream=False
            ),
        )
        message = response.choices[0].message
        usage = (
            _extract_usage(response.usage)
            if hasattr(response, "usage") and response.usage
            else None
        )

        if message.tool_calls:
            tool_call = message.tool_calls[0]
            raw_arguments = tool_call.function.arguments or "{}"
            return LLMResponse(
                kind="tool_call",
                content=message.content or "",
                tool_call={
                    "name": tool_call.function.name,
                    "arguments": self._parse_tool_arguments(raw_arguments),
                },
                usage=usage,
            )

        return LLMResponse(
            kind="text", content=message.content or "", usage=usage
        )

    def _deepseek_stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        on_text: Callable[[str], None] | None,
    ) -> LLMResponse:
        if self.client is None:
            msg = "DeepSeek client is not initialized"
            raise RuntimeError(msg)

        create_completion = cast("Any", self.client.chat.completions.create)
        stream = cast(
            "Iterator[Any]",
            create_completion(
                **self._build_chat_request(
                    messages=messages, tools=tools, stream=True
                ),
            ),
        )
        content_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, str]] = {}
        usage: Usage | None = None

        for chunk in stream:
            # Check for usage on every chunk (final chunk may carry both
            # choices with empty delta AND the usage object).
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _extract_usage(chunk_usage)

            choices = getattr(chunk, "choices", [])
            if not choices:
                continue
            delta = choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                content_parts.append(str(content))
                if on_text is not None:
                    on_text(str(content))

            for tool_call_delta in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(tool_call_delta, "index", 0) or 0)
                tool_call = tool_call_parts.setdefault(
                    index, {"name": "", "arguments": ""}
                )
                function = getattr(tool_call_delta, "function", None)
                if function is None:
                    continue
                name = getattr(function, "name", None)
                arguments = getattr(function, "arguments", None)
                if name:
                    tool_call["name"] += str(name)
                if arguments:
                    tool_call["arguments"] += str(arguments)

        if tool_call_parts:
            first_tool_call = tool_call_parts[min(tool_call_parts)]
            return LLMResponse(
                kind="tool_call",
                content="".join(content_parts),
                tool_call={
                    "name": first_tool_call["name"],
                    "arguments": self._parse_tool_arguments(
                        first_tool_call["arguments"]
                    ),
                },
                usage=usage,
            )

        return LLMResponse(
            kind="text", content="".join(content_parts), usage=usage
        )

    def _mock_chat(  # noqa: PLR0911
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if self.mock_response is not None:
            return self.mock_response(messages, tools)
        latest_user_message = self._latest_user_content(messages)
        latest_tool_result = self._latest_tool_content(messages)
        prompt = latest_user_message.lower()

        if not tools:
            return LLMResponse(
                kind="text",
                content=self._mock_text_response(latest_user_message),
            )

        if latest_tool_result is not None:
            return LLMResponse(
                kind="text",
                content=f"Tool result received. Summary:\n{latest_tool_result}",
            )

        if any(
            keyword in prompt
            for keyword in ("delegate", "research", "subagent")
        ):
            return LLMResponse(
                kind="tool_call",
                content="",
                tool_call={
                    "name": "delegate_task",
                    "arguments": {
                        "persona": "web_researcher",
                        "objective": latest_user_message,
                        "memory_key": "web_researcher_result",
                        "context": "Mocked context from primary agent conversation.",
                    },
                },
            )

        if "spec_writer" in prompt or "spec writer" in prompt:
            mode = "gather" if "gather" in prompt else "draft"
            return LLMResponse(
                kind="tool_call",
                content="",
                tool_call={
                    "name": "spec_writer",
                    "arguments": {"mode": mode},
                },
            )

        if any(keyword in prompt for keyword in ("memory", "context", "read")):
            return LLMResponse(
                kind="tool_call",
                content="",
                tool_call={
                    "name": "read_memory",
                    "arguments": {"memory_key": "web_researcher_result"},
                },
            )

        return LLMResponse(
            kind="text",
            content=(
                "Mock primary agent response. Ask me to delegate research or read memory "
                "to exercise the tool loop."
            ),
        )

    @staticmethod
    def _mock_text_response(prompt: str) -> str:
        lower_prompt = prompt.lower()
        if "delegated result:" in lower_prompt and "verdict" in lower_prompt:
            return json.dumps(
                {
                    "verdict": "pass",
                    "summary": (
                        "The delegated result addresses the objective with a "
                        "substantive mock synthesis."
                    ),
                    "risks": [
                        "Mock mode cannot verify facts against live sources.",
                    ],
                    "evaluated_memory_key": "",
                },
                sort_keys=True,
            )
        objective = _extract_prompt_section(prompt, "Objective")
        topic = objective or prompt
        return json.dumps(
            {
                "status": "completed",
                "summary": (
                    f"Mock research synthesis for: {topic}. "
                    "In production this response is generated by the configured model."
                ),
                "artifacts": {
                    "key_points": [
                        "Viterbi processing commonly refers to dynamic-programming "
                        "maximum-likelihood sequence estimation.",
                        "It is used in convolutional-code decoding, hidden Markov "
                        "model decoding, and sequence detection over noisy channels.",
                        "Production research should cite domain sources and separate "
                        "algorithm basics from implementation tradeoffs.",
                    ],
                    "limitations": "Mock mode uses built-in fallback knowledge only.",
                },
            },
            sort_keys=True,
        )

    def _mock_stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        on_text: Callable[[str], None] | None,
    ) -> LLMResponse:
        response = self._mock_chat(messages=messages, tools=tools)
        if response.kind == "text" and on_text is not None:
            for chunk in _chunk_text(response.content):
                on_text(chunk)
        return response

    def _build_chat_request(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_provider_messages(messages),
            "reasoning_effort": self.reasoning_effort,
            "extra_body": {"thinking": {"type": self.thinking}},
            "stream": stream,
        }
        if stream:
            request["stream_options"] = {"include_usage": True}
        if tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        return request

    @staticmethod
    def _parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            msg = f"Model returned invalid tool arguments: {raw_arguments}"
            raise ValueError(msg) from exc
        if not isinstance(arguments, dict):
            msg = f"Model returned non-object tool arguments: {raw_arguments}"
            raise TypeError(msg)
        return cast("dict[str, Any]", arguments)

    @staticmethod
    def _to_provider_messages(
        messages: list[Message],
    ) -> list[ChatCompletionMessageParam]:
        provider_messages: list[dict[str, str]] = []
        for message in messages:
            if message["role"] == "tool":
                provider_messages.append(
                    {
                        "role": "user",
                        "content": f"Tool result:\n{message['content']}",
                    },
                )
                continue
            provider_messages.append(
                {"role": message["role"], "content": message["content"]}
            )
        return cast("list[ChatCompletionMessageParam]", provider_messages)

    @staticmethod
    def _latest_user_content(messages: list[Message]) -> str:
        for message in reversed(messages):
            if message["role"] == "user":
                return message["content"]
        return ""

    @staticmethod
    def _latest_tool_content(messages: list[Message]) -> str | None:
        for message in reversed(messages):
            if message["role"] == "tool":
                return message["content"]
        return None


def find_dotenv() -> Path | None:
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_path = directory / ".env"
        if env_path.exists():
            return env_path
    return None


def _chunk_text(text: str) -> Iterator[str]:
    for token in text.split(" "):
        yield f"{token} "


def _extract_prompt_section(prompt: str, heading: str) -> str:
    marker = f"{heading}:\n"
    if marker not in prompt:
        return ""
    after_marker = prompt.split(marker, maxsplit=1)[1]
    return after_marker.split("\n\n", maxsplit=1)[0].strip()


def _extract_usage(raw: object) -> Usage:
    """Convert API usage object into our Usage TypedDict, capturing cache details."""
    usage: Usage = {
        "prompt_tokens": _safe_int(raw, "prompt_tokens"),
        "completion_tokens": _safe_int(raw, "completion_tokens"),
        "total_tokens": _safe_int(raw, "total_tokens"),
    }

    # DeepSeek returns cache hits/misses as top-level fields.
    cache_hit = _safe_int(raw, "prompt_cache_hit_tokens")
    cache_miss = _safe_int(raw, "prompt_cache_miss_tokens")
    if cache_hit > 0 or cache_miss > 0:
        usage["cache_hit_tokens"] = cache_hit
        usage["cache_miss_tokens"] = cache_miss
        return usage

    # Older API format: nested under prompt_tokens_details.
    details = getattr(raw, "prompt_tokens_details", None)
    if details is not None:
        cached = _safe_int(details, "cached_tokens")
        if cached > 0:
            usage["cache_hit_tokens"] = cached
            prompt_tokens = usage.get("prompt_tokens", 0)
            usage["cache_miss_tokens"] = max(0, prompt_tokens - cached)

    return usage


def _safe_int(obj: object, attr: str) -> int:
    val = getattr(obj, attr, 0)
    return int(val) if val else 0
