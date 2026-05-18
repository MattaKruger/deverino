from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

from harness_poc.core.goal_runner import GoalRunResult
from harness_poc.core.pydantic_runtime import AgentRunResult
from harness_poc.repl import handle_chat_input, handle_goal_command

CHAT_EXCHANGE_MESSAGE_COUNT = 2


def test_handle_chat_input_uses_pydantic_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks: list[str] = []
    app_state = _FakeAppState()

    monkeypatch.setattr("harness_poc.repl._print_stream_chunk", chunks.append)
    monkeypatch.setattr("harness_poc.repl._finish_stream_line", lambda _content: None)

    handle_chat_input(cast("Any", app_state), "hello")

    assert app_state.pydantic_runtime.prompts == ["hello"]
    assert app_state.pydantic_runtime.histories == [[]]
    assert app_state.llm_client.stream_calls == 0
    assert app_state.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Pydantic response"},
    ]
    assert len(app_state.pydantic_messages) == CHAT_EXCHANGE_MESSAGE_COUNT
    assert chunks == ["Pydantic response"]


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
    ) -> AgentRunResult:
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


class _FakeLLMClient:
    stream_calls = 0

    def stream_chat(self, *_args: object, **_kwargs: object) -> None:
        self.stream_calls += 1
        msg = "Legacy LLM client should not be used for chat input"
        raise AssertionError(msg)


class _FakeAppState:
    def __init__(self) -> None:
        self.session_id = "test-session"
        self.messages: list[dict[str, str]] = []
        self.pydantic_messages: list[Any] = []
        self.pydantic_runtime = _FakeRuntime()
        self.llm_client = _FakeLLMClient()


class _FakeGoalRunner:
    def run(
        self,
        *,
        goal: str,
        app_state: object,
        on_text: Callable[[str], None] | None = None,
    ) -> GoalRunResult:
        del goal, app_state, on_text
        return GoalRunResult(
            status="completed",
            content="feat: migrate to pydantic-ai",
            iterations=1,
            total_tokens=0,
            events=[],
        )
