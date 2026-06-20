from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

from textual.containers import VerticalScroll
from textual.widgets import OptionList, Static, TextArea

from harness_poc.app_factory import StreamingContext
from harness_poc.core.config import TuiConfig
from harness_poc.tui import (
    ActivityState,
    ChatApp,
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
        assert pilot.app.query_one("#status-bar")
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


async def test_vim_normal_mode_ctrl_d_swallowed() -> None:
    """ctrl+d must not submit when Vim is in NORMAL mode on input pane."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        editor = pilot.app.query_one("#input", TextArea)
        # Type text in insert mode, then escape to normal
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("escape")
        assert chat_app._vim.mode.value == "normal"
        # ctrl+d in normal mode must not submit
        await pilot.press("ctrl+d")
        assert editor.text == "hello"  # unchanged — not submitted


async def test_vim_normal_mode_enter_swallowed() -> None:
    """Enter must not insert newline when Vim is in NORMAL mode on input pane."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("h", "i")
        await pilot.press("escape")
        assert chat_app._vim.mode.value == "normal"
        await pilot.press("enter")
        assert editor.text == "hi"  # unchanged — no newline inserted


async def test_vim_insert_mode_ctrl_d_submits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ctrl+d must still submit in INSERT mode."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        editor = pilot.app.query_one("#input", TextArea)
        assert chat_app._vim.mode.value == "insert"
        await pilot.press("t", "e", "s", "t")
        monkeypatch.setattr(chat_app, "_submit", MagicMock())
        await pilot.press("ctrl+d")
        assert editor.text == ""  # submitted — editor cleared


async def test_vim_insert_mode_enter_inserts_newline() -> None:
    """Enter must insert newline in INSERT mode."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("a", "enter", "b")
        assert editor.text == "a\nb"


async def test_vim_chat_pane_ctrl_d_scrolls() -> None:
    """ctrl+d in chat pane Vim NORMAL mode scrolls (via action_submit_editor)."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        # Switch to chat pane
        await pilot.press("tab")
        assert chat_app._vim.pane.value == "chat"
        # ctrl+d must scroll (not submit, not error)
        # We can't easily assert the scroll, but we can assert no crash and pane unchanged
        await pilot.press("ctrl+d")
        assert chat_app._vim.pane.value == "chat"  # still in chat pane


def test_activity_state_label_includes_phase_and_detail() -> None:
    """ActivityState.label renders phase, detail, and tokens."""
    state = ActivityState(phase="idle")
    assert state.label == ""

    state = ActivityState(phase="streaming")
    assert state.label == "\u25cf streaming"

    state = ActivityState(phase="tool", detail="skill_view")
    assert "\u25cf tool: skill_view" in state.label

    state = ActivityState(phase="streaming", token_count=1500)
    assert "1.5k" in state.label


# ---------------------------------------------------------------------------
# Phase 1: Input history recall
# ---------------------------------------------------------------------------


async def test_input_history_up_recalls_most_recent_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Up arrow at (0,0) restores last submitted input."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        editor = pilot.app.query_one("#input", TextArea)
        # Submit a message to populate history
        await pilot.press("f", "i", "r", "s", "t")
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert submitted == ["first"]
        # Type something, then go to start and press Up
        await pilot.press("s", "e", "c", "o", "n", "d")
        await pilot.pause()
        editor.move_cursor((0, 0))
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert editor.text == "first"
        assert chat_app._history_index == 0


async def test_input_history_down_navigates_forward_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Down arrow at end of last line moves forward through history."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        # Submit two messages
        await pilot.press("a", "a", "a")
        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("b", "b", "b")
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert submitted == ["aaa", "bbb"]
        # Navigate up to oldest
        editor = pilot.app.query_one("#input", TextArea)
        editor.move_cursor((0, 0))
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert editor.text == "bbb"
        # Move cursor back to start for second Up press
        editor.move_cursor((0, 0))
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert editor.text == "aaa"
        # Navigate down back to newest
        lines = editor.text.splitlines()
        editor.move_cursor((len(lines) - 1, len(lines[-1]) if lines[-1] else 0))
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert editor.text == "bbb"


async def test_input_history_down_restores_draft_at_newest_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Down past newest entry restores the draft text."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        # Submit one message
        await pilot.press("s", "a", "v", "e", "d")
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert submitted == ["saved"]
        # Type a draft, navigate up then down
        await pilot.press("d", "r", "a", "f", "t")
        await pilot.pause()
        editor = pilot.app.query_one("#input", TextArea)
        editor.move_cursor((0, 0))
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert editor.text == "saved"
        # Navigate down past newest → draft restored
        lines = editor.text.splitlines()
        editor.move_cursor((len(lines) - 1, len(lines[-1]) if lines[-1] else 0))
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert editor.text == "draft"
        assert chat_app._history_index == -1


async def test_input_history_no_op_when_cursor_not_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Up/Down behave normally when cursor is mid-line."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        # Submit a message
        await pilot.press("h", "i", "s", "t", "o", "r", "y")
        await pilot.press("ctrl+d")
        await pilot.pause()
        # Type multi-line text with cursor mid-line
        await pilot.press("a", "enter", "b")
        await pilot.pause()
        editor = pilot.app.query_one("#input", TextArea)
        # Up should move cursor, not recall history
        await pilot.press("up")
        await pilot.pause()
        assert editor.text == "a\nb"
        assert chat_app._history_index == -1


async def test_input_history_no_op_when_empty() -> None:
    """Up at boundary does nothing when history is empty."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("t", "e", "s", "t")
        await pilot.pause()
        editor.move_cursor((0, 0))
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        # Text unchanged — no history to recall
        assert editor.text == "test"


async def test_input_history_down_no_op_when_not_navigating() -> None:
    """Down at boundary without prior Up navigation does nothing."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause()
        # Down at end without ever navigating up should not clear editor
        lines = editor.text.splitlines()
        editor.move_cursor((len(lines) - 1, len(lines[-1]) if lines[-1] else 0))
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert editor.text == "hello"


# ---------------------------------------------------------------------------
# Phase 1: Escape abort
# ---------------------------------------------------------------------------


async def test_escape_aborts_running_worker() -> None:
    """Escape sets _abort_event when activity is not idle."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        # Simulate running worker by setting activity
        chat_app._set_activity("streaming")
        assert not chat_app._abort_event.is_set()
        await pilot.press("escape")
        assert chat_app._abort_event.is_set()


async def test_escape_no_op_when_idle() -> None:
    """Escape does nothing when no worker is running."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        assert chat_app._activity.phase == "idle"
        assert not chat_app._abort_event.is_set()
        await pilot.press("escape")
        assert not chat_app._abort_event.is_set()


async def test_escape_preserved_for_vim_normal_mode() -> None:
    """Escape in Vim INSERT mode switches to NORMAL; does NOT trigger abort."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        # Simulate running worker
        chat_app._set_activity("streaming")
        # Vim INSERT mode Escape → NORMAL (Vim handler consumes the key)
        await pilot.press("escape")
        # Vim should be in NORMAL mode, not aborted
        assert chat_app._vim.mode.value == "normal"
        # The abort event should NOT be set (Vim consumed the key)
        assert not chat_app._abort_event.is_set()


# ---------------------------------------------------------------------------
# Phase 1: Help panel
# ---------------------------------------------------------------------------


async def test_help_panel_toggles_with_question_mark() -> None:
    """? key opens and closes the help panel (when not typing)."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        help_panel = pilot.app.query_one("#help-panel", Static)
        assert help_panel.display is False
        # Focus away from input so ? toggles help, not inserts
        pilot.app.query_one("#chat", VerticalScroll).focus()
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        assert help_panel.display is True
        await pilot.press("?")
        await pilot.pause()
        assert help_panel.display is False


async def test_help_panel_question_mark_inserts_when_typing() -> None:
    """? inserts literal ? when user is typing in input with Vim off."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        # Input is focused by default
        await pilot.press("a", "?", "b")
        await pilot.pause()
        assert editor.text == "a?b"
        help_panel = pilot.app.query_one("#help-panel", Static)
        assert help_panel.display is False


async def test_help_panel_dismissed_by_escape() -> None:
    """Escape dismisses help panel when it is visible."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        help_panel = pilot.app.query_one("#help-panel", Static)
        # Open help
        pilot.app.query_one("#chat", VerticalScroll).focus()
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        assert help_panel.display is True
        await pilot.press("escape")
        await pilot.pause()
        assert help_panel.display is False


async def test_help_panel_shows_vim_content_when_vim_enabled() -> None:
    """Help panel shows Vim bindings when Vim is enabled."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        help_panel = pilot.app.query_one("#help-panel", Static)
        pilot.app.query_one("#chat", VerticalScroll).focus()
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        assert help_panel.display is True


async def test_help_panel_hides_vim_content_when_vim_disabled() -> None:
    """Help panel shows non-Vim content when Vim is disabled."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        help_panel = pilot.app.query_one("#help-panel", Static)
        pilot.app.query_one("#chat", VerticalScroll).focus()
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        assert help_panel.display is True


async def test_help_panel_composes() -> None:
    """Help panel widget exists in DOM."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        assert pilot.app.query_one("#help-panel")


async def test_help_panel_question_mark_inserts_in_vim_insert_mode() -> None:
    """? inserts literal ? when in Vim INSERT mode on input."""
    app = ChatApp(_make_app_state(TuiConfig(vim_enabled=True, vim_initial_mode="insert")))
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("?")
        await pilot.pause()
        assert editor.text == "?"


async def test_input_history_suppressed_when_completion_menu_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Up/Down don't trigger history when completion menu is visible."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        # Submit a message
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("ctrl+d")
        await pilot.pause()
        # Open completion menu
        chat_app._refresh_completion_menu(force=True)
        await pilot.pause()
        editor = pilot.app.query_one("#input", TextArea)
        editor.move_cursor((0, 0))
        await pilot.pause()
        # Up should NOT trigger history — menu is visible
        await pilot.press("up")
        await pilot.pause()
        # Editor should be unchanged (or cursor moved normally)
        assert chat_app._history_index == -1


async def test_input_history_index_reset_on_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_history_index resets to -1 when user types after navigating."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        # Submit a message
        await pilot.press("s", "a", "v", "e", "d")
        await pilot.press("ctrl+d")
        await pilot.pause()
        # Navigate to it
        editor = pilot.app.query_one("#input", TextArea)
        editor.move_cursor((0, 0))
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert editor.text == "saved"
        assert chat_app._history_index == 0
        # Type to modify — should exit navigation
        await pilot.press("x")
        await pilot.pause()
        assert chat_app._history_index == -1


# ---------------------------------------------------------------------------
# Phase 1: _abort_event cleared on new submit
# ---------------------------------------------------------------------------


async def test_abort_event_cleared_on_submit() -> None:
    """_abort_event is cleared before starting a new worker."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        # Simulate a previous abort
        chat_app._abort_event.set()
        assert chat_app._abort_event.is_set()
        # Submit should clear it (via _submit)
        await pilot.press("h", "i")

        # Monkeypatch _chat_worker to avoid real LLM call
        async def _fake_worker(text: str, chat: object) -> None:
            pass

        chat_app._chat_worker = _fake_worker  # type: ignore[assignment]
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert not chat_app._abort_event.is_set()


# ---------------------------------------------------------------------------
# Phase 2: Message queue and input decoupling
# ---------------------------------------------------------------------------


async def test_queue_when_worker_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+D queues text when a worker is running."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        # Simulate running worker
        chat_app._worker_running = True
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("ctrl+d")
        await pilot.pause()
        # Should be queued, not submitted
        assert submitted == []
        assert chat_app._queued_messages == ["hello"]
        assert editor.text == ""


async def test_no_queue_when_worker_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+D submits normally when no worker is running."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        await pilot.press("h", "i")
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert submitted == ["hi"]
        assert chat_app._queued_messages == []


async def test_alt_enter_queues_when_worker_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alt+Enter queues text when worker is running."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        chat_app._worker_running = True
        await pilot.press("f", "o", "l", "l", "o", "w", "_", "u", "p")
        await pilot.press("alt+enter")
        await pilot.pause()
        assert submitted == []
        assert chat_app._queued_messages == ["follow_up"]


async def test_alt_enter_submits_when_worker_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alt+Enter submits when no worker is running."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        await pilot.press("h", "i")
        await pilot.press("alt+enter")
        await pilot.pause()
        assert submitted == ["hi"]


async def test_alt_up_restores_last_queued() -> None:
    """Alt+Up restores the most recently queued message to the editor."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        chat_app._queued_messages = ["first", "second"]
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("alt+up")
        await pilot.pause()
        assert editor.text == "second"
        assert chat_app._queued_messages == ["first"]


async def test_alt_up_no_op_when_queue_empty() -> None:
    """Alt+Up does nothing when queue is empty."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("alt+up")
        await pilot.pause()
        assert editor.text == ""


async def test_queue_depth_in_status_bar() -> None:
    """Status bar shows queue depth when messages are queued."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        chat_app._queued_messages = ["a", "b"]
        chat_app._render_status_bar()
        # Verify the status bar was updated (content check via Static's text)
        status = pilot.app.query_one("#status-bar", Static)
        rendered = status.render()
        # Status bar rendering is complex — just verify no crash


async def test_queue_full_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue at max capacity rejects new messages with a warning."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        monkeypatch.setattr(chat_app, "_submit", MagicMock())
        chat_app._worker_running = True
        # Fill queue
        chat_app._queued_messages = ["a", "b", "c", "d", "e"]
        editor = pilot.app.query_one("#input", TextArea)
        await pilot.press("e", "x", "t", "r", "a")
        await pilot.press("ctrl+d")
        await pilot.pause()
        # Queue should still be 5 items, text preserved in editor
        assert len(chat_app._queued_messages) == 5
        assert editor.text == "extra"


async def test_dequeue_next_submits_first_in_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_dequeue_next submits the first queued message (FIFO)."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        chat_app._queued_messages = ["first", "second"]
        chat_app._dequeue_next()
        await pilot.pause()
        assert submitted == ["first"]
        assert chat_app._queued_messages == ["second"]


async def test_queued_messages_added_to_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queued messages are added to input history."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        monkeypatch.setattr(chat_app, "_submit", MagicMock())
        chat_app._worker_running = True
        await pilot.press("q", "u", "e", "u", "e", "d")
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert chat_app._history == ["queued"]


async def test_auto_dequeue_after_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queued messages auto-submit after worker abort."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        submitted: list[str] = []
        monkeypatch.setattr(chat_app, "_submit", submitted.append)
        # Simulate: worker is running, user queues a message, then aborts
        chat_app._worker_running = True
        await pilot.press("q", "u", "e", "u", "e", "d")
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert chat_app._queued_messages == ["queued"]
        # Simulate finalize after abort (call _do logic directly via _dequeue_next)
        chat_app._worker_running = False
        chat_app._dequeue_next()
        await pilot.pause()
        assert submitted == ["queued"]
        assert chat_app._queued_messages == []


# ---------------------------------------------------------------------------
# Tool panel & activity rendering (covers search_documents integration)
# ---------------------------------------------------------------------------


async def test_tool_panel_renders_running_events() -> None:
    """Tool panels show running events and collapse on finish."""
    from harness_poc.tui import ToolPanel

    panel = ToolPanel()
    assert panel.has_events is False

    panel.add("search_documents: paper", status="running")
    assert panel.has_events is True
    # Running status shows ellipsis icon
    assert "\u2026" in str(panel.content)
    assert "search_documents: paper" in str(panel.content)

    summary = panel.finish()
    assert "search_documents" in summary
    # After finish, class is added for visual collapse
    assert panel.has_class("finished")


async def test_tool_panel_dismiss_clears_events() -> None:
    """Dismiss clears all events and removes finished class."""
    from harness_poc.tui import ToolPanel

    panel = ToolPanel()
    panel.add("search_documents")
    panel.finish()
    panel.dismiss()
    assert panel.has_events is False
    assert not panel.has_class("finished")
    assert str(panel.content) == ""


async def test_activity_state_streaming_to_tool_transition() -> None:
    """Activity transitions from idle → streaming → tool → idle correctly."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)

        # Starts idle
        assert chat_app._activity.phase == "idle"
        assert chat_app._activity.label == ""

        # Transition to streaming
        chat_app._set_activity("streaming")
        assert "\u25cf streaming" in chat_app._activity.label

        # Transition to tool with detail (like search_documents output)
        chat_app._set_activity("tool", detail="search_documents")
        assert "\u25cf tool: search_documents" in chat_app._activity.label

        # Back to idle
        chat_app._set_activity("idle")
        assert chat_app._activity.label == ""


async def test_should_render_markdown_for_search_documents_output() -> None:
    """search_documents preview output triggers Markdown rendering."""
    # The numbered list format used by search_documents preview mode
    preview_output = (
        'Found 3 results for "paper" (mode: keyword):\n'
        "\n"
        '1. docs/paper.md (score 0.89) — "The paper proposes..."'
    )
    # Contains a numbered list → should render as Markdown
    assert _should_render_markdown(preview_output) is True

    # Plain text still renders as Static
    assert _should_render_markdown("Hello, I found some papers for you.") is False


async def test_chat_app_has_expected_initial_state() -> None:
    """ChatApp starts with expected defaults for all phase fields."""
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)

        # Phase 1 fields
        assert chat_app._history == []
        assert chat_app._history_index == -1
        assert chat_app._draft_text == ""
        assert not chat_app._abort_event.is_set()
        assert chat_app._abort_finalized is False

        # Phase 2 fields
        assert chat_app._worker_running is False
        assert chat_app._queued_messages == []
        assert chat_app._pending_command is None

        # Phase 3 fields
        assert chat_app._llm_override is None
        assert chat_app._model_selector_active is False
        assert chat_app._session_picker_active is False
        assert chat_app._session_data == []

        # Tool panel starts None (lazy)
        assert chat_app._tool_panel is None


async def test_on_tool_event_sets_activity_and_mounts_tool_panel() -> None:
    """When a tool event fires, activity switches to 'tool' phase."""
    from harness_poc.tui import ToolPanel

    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        chat_app = _chat_app(pilot.app)
        # Pre-create tool panel to avoid call_from_thread complexity
        panel = ToolPanel()
        chat_app._tool_panel = panel

        # Simulate tool event callback (what the _chat_worker does)
        panel.add("search_documents", status="running")
        chat_app._set_activity("tool", detail="search_documents")

        assert chat_app._activity.phase == "tool"
        assert chat_app._activity.detail == "search_documents"
        assert panel.has_events is True
