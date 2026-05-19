from __future__ import annotations

from unittest.mock import MagicMock

from harness_poc.app_factory import StreamingContext
from harness_poc.tui import ChatApp


def _make_app_state() -> object:
    state = MagicMock()
    state.config.llm.provider = "test-provider"
    state.config.llm.model = "test-model"
    state.streaming = StreamingContext()
    return state


async def test_chat_app_composes() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        assert pilot.app.query_one("#header")
        assert pilot.app.query_one("#chat")
        assert pilot.app.query_one("#spinner")
        assert pilot.app.query_one("#input")


async def test_chat_app_exit_on_quit() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        await pilot.press("q", "u", "i", "t", "enter")
