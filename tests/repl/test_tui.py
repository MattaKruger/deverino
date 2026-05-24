from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

from textual.widgets import OptionList, TextArea

from harness_poc.app_factory import StreamingContext
from harness_poc.core.config import TuiConfig
from harness_poc.tui import (
    ChatApp,
    _format_spinner_status,
    _is_chat_at_scroll_end,
    _scroll_chat_end_if_following,
    _should_render_markdown,
)

if TYPE_CHECKING:
    import pytest

    from harness_poc.app_factory import AppState

EXPECTED_SKILL_COMPLETIONS = 2


@dataclass
class FakeScroll:
    scroll_y: float
    max_scroll_y: float
    calls: list[str] = field(default_factory=list)

    def scroll_end(self, *, animate: bool = False) -> None:
        del animate
        self.calls.append("scroll_end")


def _make_app_state(tui: TuiConfig | None = None) -> AppState:
    state = MagicMock()
    state.config.llm.provider = "test-provider"
    state.config.llm.model = "test-model"
    state.config.tui = tui or TuiConfig()
    state.streaming = StreamingContext()
    state.skill_runner.discover_skills.return_value = [
        {"function": {"name": "execute_python"}},
        {"function": {"name": "summarize_memory"}},
    ]
    state.pipeline_runner.list_pipelines.return_value = ["research_and_write"]
    state.config.paths.workflows.exists.return_value = True
    state.config.paths.workflows.glob.return_value = []
    return cast("AppState", state)


def _chat_app(app: object) -> ChatApp:
    return cast("ChatApp", app)


async def test_chat_app_composes() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        assert pilot.app.query_one("#header")
        assert pilot.app.query_one("#chat")
        assert pilot.app.query_one("#spinner")
        assert pilot.app.query_one("#input")
        assert pilot.app.query_one("#completion-menu")


async def test_chat_app_exit_on_quit() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        await pilot.press("q", "u", "i", "t", "super+enter")


async def test_chat_app_tab_opens_skill_menu_and_enter_selects_without_submit() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        await pilot.press("/", "s", "k", "i", "l", "l", "tab")

        menu = pilot.app.query_one("#completion-menu", OptionList)
        assert menu.display is True
        assert menu.option_count == EXPECTED_SKILL_COMPLETIONS

        await pilot.press("enter")

        editor = pilot.app.query_one("#input", TextArea)
        assert editor.text == "/skill execute_python"
        assert menu.display is False


async def test_chat_app_enter_inserts_newline_and_ctrl_d_submits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = ChatApp(_make_app_state())
    submitted: list[str] = []
    monkeypatch.setattr(app, "_submit", submitted.append)

    async with app.run_test() as pilot:
        await pilot.press("h", "i", "enter", "t", "h", "e", "r", "e")

        editor = pilot.app.query_one("#input", TextArea)
        assert editor.text == "hi\nthere"

        await pilot.press("ctrl+d")

        assert submitted == ["hi\nthere"]
        assert editor.text == ""


def test_tui_renders_plain_first_paragraph_without_markdown() -> None:
    assert _should_render_markdown("Hey! Welcome. What can I help with?") is False
    assert _should_render_markdown("Question. The project is a natural fit.") is False


def test_tui_keeps_markdown_for_block_content() -> None:
    assert _should_render_markdown("| A | B |\n|---|---|") is True
    assert _should_render_markdown("```python\nprint('x')\n```") is True
    assert _should_render_markdown("- item") is True


def test_tui_auto_scrolls_when_chat_was_already_at_bottom() -> None:
    chat = FakeScroll(scroll_y=100.0, max_scroll_y=100.0)

    assert _is_chat_at_scroll_end(cast("Any", chat)) is True
    _scroll_chat_end_if_following(cast("Any", chat), was_at_end=True)

    assert chat.calls == ["scroll_end"]


def test_tui_does_not_auto_scroll_when_user_has_scrolled_up() -> None:
    chat = FakeScroll(scroll_y=90.0, max_scroll_y=100.0)

    assert _is_chat_at_scroll_end(cast("Any", chat)) is False
    _scroll_chat_end_if_following(cast("Any", chat), was_at_end=False)

    assert chat.calls == []


async def test_vim_disabled_by_default() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        assert chat_app._vim.enabled is False


async def test_vim_toggle_enables_and_resets_state() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        await pilot.press("f2")
        assert chat_app._vim.enabled is True
        assert chat_app._vim.mode.value == "insert"
        assert chat_app._vim.pane.value == "input"
        # Toggle off again resets to disabled-default.
        await pilot.press("f2")
        assert chat_app._vim.enabled is False
        assert chat_app._vim.mode.value == "insert"


async def test_vim_initial_mode_normal_from_config() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="normal")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        assert chat_app._vim.enabled is True
        assert chat_app._vim.mode.value == "normal"


async def test_vim_tab_cycles_panes_when_completion_hidden() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        await pilot.press("tab")
        assert chat_app._vim.pane.value == "chat"
        await pilot.press("tab")
        assert chat_app._vim.pane.value == "input"


async def test_vim_visible_completion_menu_takes_priority_over_pane_cycling() -> None:
    """Per spec, while the completion menu is visible tab/shift+tab cycle options."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        # Open the menu via the same path tests use today: type a /command,
        # then force-open by calling the refresh helper directly. With Vim on,
        # tab alone cycles panes, so we open the menu programmatically to
        # exercise the precedence rule.
        await pilot.press("/", "s", "k", "i", "l", "l")
        chat_app._refresh_completion_menu(force=True)
        await pilot.pause()
        menu = pilot.app.query_one("#completion-menu", OptionList)
        assert menu.display is True
        starting_pane = chat_app._vim.pane
        await pilot.press("tab")
        # Menu still visible, pane unchanged.
        assert menu.display is True
        assert chat_app._vim.pane == starting_pane


async def test_vim_normal_mode_escape_then_motion_does_not_insert_text() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("h", "i")
        assert editor.text == "hi"
        await pilot.press("escape")
        assert chat_app._vim.mode.value == "normal"
        await pilot.press("j", "k", "h", "l")
        # None of these should have been typed into the buffer.
        assert editor.text == "hi"


async def test_vim_normal_mode_i_returns_to_insert() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="normal")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("i")
        assert chat_app._vim.mode.value == "insert"
        await pilot.press("a")
        assert editor.text == "a"


async def test_vim_visual_mode_y_copies_selection_and_returns_normal() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("escape")  # → normal
        await pilot.press("0")  # cursor to line start
        await pilot.press("v")
        assert chat_app._vim.mode.value == "visual"
        await pilot.press("l", "l", "l")  # extend 3 right
        assert editor.selected_text != ""
        await pilot.press("y")
        assert chat_app._vim.mode.value == "normal"


async def test_vim_visual_mode_d_deletes_selection() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("a", "b", "c", "d", "e")
        await pilot.press("escape", "0", "v", "l", "l", "d")
        # "ab" should be deleted, leaving "cde".
        assert editor.text == "cde"
        assert chat_app._vim.mode.value == "normal"


async def test_vim_count_prefix_repeats_motion_in_textarea() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("escape", "0")
        # Move right 3 times via count prefix, then delete the next char.
        await pilot.press("3", "l", "x")
        # Started at col 0 of "hello", moved to col 3 (over 'l'), x removed it.
        assert editor.text == "helo"


async def test_vim_chat_pane_j_scrolls_does_not_type_into_editor() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        await pilot.press("tab")  # focus → chat
        assert chat_app._vim.pane.value == "chat"
        editor = pilot.app.query_one("#input", TextArea)
        before = editor.text
        await pilot.press("j", "j", "k")
        # j/k must not leak into the input buffer while chat is focused.
        assert editor.text == before


async def test_vim_chat_i_returns_focus_to_input_in_insert() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        await pilot.press("tab")
        assert chat_app._vim.pane.value == "chat"
        await pilot.press("i")
        assert chat_app._vim.pane.value == "input"
        assert chat_app._vim.mode.value == "insert"
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("x")
        assert editor.text == "x"


def test_spinner_status_combines_independent_icon_phrase_and_dots() -> None:
    status = _format_spinner_status("(งツ)ว", "doing the thing", "...")

    assert status.startswith("(งツ)ว")
    assert status.endswith("doing the thing...")
    assert "  doing the thing" in status
