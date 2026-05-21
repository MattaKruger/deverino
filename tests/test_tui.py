from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from textual.widgets import OptionList, TextArea

from harness_poc.app_factory import StreamingContext
from harness_poc.core.config import TuiConfig
from harness_poc.tui import ChatApp, _format_spinner_status, _should_render_markdown

if TYPE_CHECKING:
    import pytest

    from harness_poc.app_factory import AppState

EXPECTED_SKILL_COMPLETIONS = 2


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


async def test_vim_disabled_by_default() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        assert pilot.app._vim.enabled is False


async def test_vim_toggle_enables_and_resets_state() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        await pilot.press("f2")
        assert pilot.app._vim.enabled is True
        assert pilot.app._vim.mode.value == "insert"
        assert pilot.app._vim.pane.value == "input"
        # Toggle off again resets to disabled-default.
        await pilot.press("f2")
        assert pilot.app._vim.enabled is False
        assert pilot.app._vim.mode.value == "insert"


async def test_vim_initial_mode_normal_from_config() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="normal")))
    async with app.run_test() as pilot:
        assert pilot.app._vim.enabled is True
        assert pilot.app._vim.mode.value == "normal"


async def test_vim_tab_cycles_panes_when_completion_hidden() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        await pilot.press("tab")
        assert pilot.app._vim.pane.value == "chat"
        await pilot.press("tab")
        assert pilot.app._vim.pane.value == "input"


async def test_vim_visible_completion_menu_takes_priority_over_pane_cycling() -> None:
    """Per spec, while the completion menu is visible tab/shift+tab cycle options."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        # Open the menu via the same path tests use today: type a /command,
        # then force-open by calling the refresh helper directly. With Vim on,
        # tab alone cycles panes, so we open the menu programmatically to
        # exercise the precedence rule.
        await pilot.press("/", "s", "k", "i", "l", "l")
        pilot.app._refresh_completion_menu(force=True)
        await pilot.pause()
        menu = pilot.app.query_one("#completion-menu", OptionList)
        assert menu.display is True
        starting_pane = pilot.app._vim.pane
        await pilot.press("tab")
        # Menu still visible, pane unchanged.
        assert menu.display is True
        assert pilot.app._vim.pane == starting_pane


async def test_vim_normal_mode_escape_then_motion_does_not_insert_text() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("h", "i")
        assert editor.text == "hi"
        await pilot.press("escape")
        assert pilot.app._vim.mode.value == "normal"
        await pilot.press("j", "k", "h", "l")
        # None of these should have been typed into the buffer.
        assert editor.text == "hi"


async def test_vim_normal_mode_i_returns_to_insert() -> None:
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="normal")))
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("i")
        assert pilot.app._vim.mode.value == "insert"
        await pilot.press("a")
        assert editor.text == "a"


def test_spinner_status_combines_independent_icon_phrase_and_dots() -> None:
    status = _format_spinner_status("(งツ)ว", "doing the thing", "...")

    assert status.startswith("(งツ)ว")
    assert status.endswith("doing the thing...")
    assert "  doing the thing" in status
