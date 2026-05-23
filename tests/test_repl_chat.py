from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

from harness_poc.app_factory import StreamingContext
from harness_poc.core.events import AgentInputAdded, LLMActionEmitted, LLMTextEmitted
from harness_poc.core.runtime import AgentRunResult, GoalRunResult, estimate_message_tokens
from harness_poc.repl import handle_chat_input, handle_goal_command
from tests.helpers import RecordingEventBus

CHAT_EXCHANGE_MESSAGE_COUNT = 2
EXPECTED_TOTAL_TOKENS = 5


def test_handle_chat_input_uses_pydantic_runtime() -> None:
    chunks: list[str] = []
    app_state = _FakeAppState()
    app_state.streaming.on_text = chunks.append
    app_state.streaming.on_finish = lambda _: None

    handle_chat_input(cast("Any", app_state), "hello")

    assert app_state.pydantic_runtime.prompts == ["hello"]
    assert app_state.pydantic_runtime.histories == [[]]
    assert app_state.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Pydantic response"},
    ]
    assert len(app_state.pydantic_messages) == CHAT_EXCHANGE_MESSAGE_COUNT
    assert chunks == ["Pydantic response"]


def test_handle_chat_input_publishes_chat_events() -> None:
    app_state = _FakeAppState()
    app_state.streaming.on_finish = lambda _: None

    handle_chat_input(cast("Any", app_state), "hey")

    events = app_state.event_bus.events
    assert [event.event_type for event in events] == [
        "AgentInputAdded",
        "LLMActionEmitted",
        "AgentTurnRecorded",
        "LLMTextEmitted",
    ]
    assert isinstance(events[0], AgentInputAdded)
    assert events[0].user_content == "hey"
    assert isinstance(events[1], LLMActionEmitted)
    assert events[1].model == "fake-model"
    expected_new_tokens = estimate_message_tokens(
        [
            ModelRequest(parts=[UserPromptPart(content="hey")]),
            ModelResponse(parts=[TextPart(content="Pydantic response")]),
        ]
    )
    assert events[1].tokens_used == expected_new_tokens
    assert events[1].new_tokens == expected_new_tokens
    assert events[1].billable_tokens == EXPECTED_TOTAL_TOKENS
    assert app_state.streaming.session_tokens == expected_new_tokens
    assert isinstance(events[3], LLMTextEmitted)
    assert events[3].content == "Pydantic response"


def test_handle_chat_input_prunes_history_before_runtime_call() -> None:
    app_state = _FakeAppState()
    app_state.streaming.on_finish = lambda _: None
    app_state.pydantic_messages = [
        ModelRequest(parts=[UserPromptPart(content="old")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="semble_search",
                    content="x" * 10_000,
                    tool_call_id="call-1",
                )
            ]
        ),
        ModelRequest(parts=[UserPromptPart(content="recent")]),
    ]
    app_state.config.runtime.chat_history_max_tokens = 100
    app_state.config.runtime.chat_history_recent_turns = 1

    handle_chat_input(cast("Any", app_state), "next")

    history = app_state.pydantic_runtime.histories[0]
    assert "x" * 100 not in repr(history)


def test_handle_goal_command_adds_result_to_chat_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_state = _FakeAppState()

    monkeypatch.setattr("harness_poc.repl.GoalRunner", _FakeGoalRunner)

    handle_goal_command(cast("Any", app_state), '/goal "write a commit message"')

    assert app_state.messages[-2:] == [
        {"role": "user", "content": '/goal "write a commit message"'},
        {
            "role": "assistant",
            "content": (
                "Goal status: completed\n"
                "Iterations: 1\n"
                "Total tokens: 0\n\n"
                "feat: migrate to pydantic-ai"
            ),
        },
    ]
    assert len(app_state.pydantic_messages) == CHAT_EXCHANGE_MESSAGE_COUNT


class _FakeRuntime:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.histories: list[list[Any]] = []

    def stream_text(
        self,
        prompt: str,
        *,
        message_history: list[Any] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        del on_tool_event
        self.prompts.append(prompt)
        self.histories.append(list(message_history or []))
        if on_text is not None:
            on_text("Pydantic response")

        return AgentRunResult(
            content="Pydantic response",
            usage={
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "total_tokens": 5,
            },
            messages=[],
        )


class _FakeDatabase:
    def __init__(self) -> None:
        self.appended: list[tuple[str, list[dict[str, Any]]]] = []

    def append_session_messages(
        self, session_id: str, messages_blob: list[dict[str, Any]]
    ) -> int:
        self.appended.append((session_id, messages_blob))
        return len(self.appended)


class _FakeAppState:
    def __init__(self) -> None:
        self.session_id = "test-session"
        self.messages: list[dict[str, str]] = []
        self.pydantic_messages: list[Any] = []
        self.pydantic_runtime = _FakeRuntime()
        self.streaming = StreamingContext()
        self.event_bus = RecordingEventBus()
        self.database = _FakeDatabase()
        self.config = SimpleNamespace(
            llm=SimpleNamespace(model="fake-model"),
            runtime=SimpleNamespace(
                chat_history_max_tokens=24_000,
                chat_history_recent_turns=6,
                tool_result_max_chars=12_000,
            ),
        )


class _FakeGoalRunner:
    def run(
        self,
        *,
        goal: str,
        app_state: object,
        on_text: Callable[[str], None] | None = None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> GoalRunResult:
        del goal, app_state, on_text, on_tool_event
        return GoalRunResult(
            status="completed",
            content="feat: migrate to pydantic-ai",
            iterations=1,
            total_tokens=0,
            events=[],
        )
