from __future__ import annotations

from harness_poc.tui_vim import (
    InputVimHandler,
    VimMode,
    VimPane,
    VimState,
    cycle_pane,
    format_status,
    normalize_key,
)

from .conftest import FakeEditor, _state


# --------------------------------------------------------------- core state


def test_vim_state_defaults_disabled() -> None:
    state = VimState(enabled=False)
    assert state.pane == VimPane.INPUT
    assert state.mode == VimMode.INSERT
    assert state.pending == ""
    assert state.count is None


def test_format_status_off() -> None:
    assert format_status(VimState(enabled=False)) == "vim off"


def test_format_status_shows_mode_and_pane() -> None:
    state = VimState(enabled=True, mode=VimMode.NORMAL, pane=VimPane.CHAT)
    assert format_status(state) == "NORMAL chat"


def test_format_status_visual() -> None:
    assert format_status(VimState(enabled=True, mode=VimMode.VISUAL)) == "VISUAL input"


def test_cycle_pane_toggles_between_input_and_chat() -> None:
    state = VimState(enabled=True)
    assert cycle_pane(state) == VimPane.CHAT
    assert cycle_pane(state) == VimPane.INPUT


def test_normalize_key_maps_dollar() -> None:
    assert normalize_key("$") == "dollar_sign"
    assert normalize_key("j") == "j"


def test_consume_count_returns_one_when_unset() -> None:
    state = VimState(enabled=True)
    assert state.consume_count() == 1


def test_consume_count_clears_after_read() -> None:
    state = VimState(enabled=True, count=4)
    assert state.consume_count() == 4
    assert state.count is None


# ------------------------------------------------------------------ counts


def test_count_repeats_motion() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("3", editor)
    assert state.count == 3
    handler.handle("j", editor)
    assert editor.calls == ["cursor_down"] * 3
    assert state.count is None


def test_count_zero_after_digit_appends_not_line_start() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("1", editor)
    handler.handle("0", editor)
    assert state.count == 10
    handler.handle("h", editor)
    assert editor.calls == ["cursor_left"] * 10


def test_count_zero_without_prefix_is_line_start() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("0", editor)
    assert editor.calls == ["line_start"]
    assert state.count is None


# ----------------------------------------------------- operator + motion


def test_dw_deletes_from_cursor_to_word_right() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    editor.cursor_location = (0, 2)
    handler.handle("d", editor)
    assert state.pending == "d"
    handler.handle("w", editor)
    # After motion, range was (start=(0,2), end=(0,5)).
    assert editor.replace_calls == [("", (0, 2), (0, 5))]
    assert state.pending == ""


def test_d_dollar_deletes_to_line_end() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    editor.cursor_location = (1, 3)
    handler.handle("d", editor)
    handler.handle("dollar_sign", editor)
    assert editor.replace_calls == [("", (1, 3), (1, 99))]


def test_cw_deletes_and_enters_insert() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    editor.cursor_location = (0, 0)
    handler.handle("c", editor)
    handler.handle("w", editor)
    assert editor.replace_calls == [("", (0, 0), (0, 3))]
    assert state.mode == VimMode.INSERT


def test_cc_clears_line_and_enters_insert() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("c", editor)
    handler.handle("c", editor)
    assert editor.calls == ["delete_line"]
    assert state.mode == VimMode.INSERT


def test_count_with_operator_motion() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    editor.cursor_location = (0, 0)
    handler.handle("d", editor)
    handler.handle("2", editor)
    handler.handle("w", editor)
    # Two word-right motions, so end column = 0 + 3 + 3 = 6.
    assert editor.replace_calls == [("", (0, 0), (0, 6))]


def test_operator_pending_invalid_followup_clears_state() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("d", editor)
    handler.handle("z", editor)
    assert state.pending == ""
    assert editor.replace_calls == []
