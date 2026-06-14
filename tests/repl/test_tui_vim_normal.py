from __future__ import annotations

from harness_poc.tui_vim import (
    InputVimHandler,
    VimMode,
    VimState,
)

from .conftest import FakeEditor, _state


# ----------------------------------------------------------------- insert


def test_insert_mode_escape_switches_to_normal() -> None:
    state = _state(mode=VimMode.INSERT)
    handler = InputVimHandler(state)
    assert handler.handle("escape", FakeEditor()) is True
    assert state.mode == VimMode.NORMAL


def test_insert_mode_passes_through_printable_keys() -> None:
    state = _state(mode=VimMode.INSERT)
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("a", editor) is False
    assert handler.handle("j", editor) is False


# ----------------------------------------------------------------- normal


def test_normal_mode_hjkl_moves_cursor() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    for key, action in [
        ("h", "cursor_left"),
        ("j", "cursor_down"),
        ("k", "cursor_up"),
        ("l", "cursor_right"),
    ]:
        editor.calls.clear()
        assert handler.handle(key, editor) is True
        assert editor.calls == [action]


def test_normal_mode_i_enters_insert() -> None:
    state = _state()
    handler = InputVimHandler(state)
    assert handler.handle("i", FakeEditor()) is True
    assert state.mode == VimMode.INSERT


def test_normal_mode_a_moves_right_then_inserts() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("a", editor) is True
    assert editor.calls == ["cursor_right"]
    assert state.mode == VimMode.INSERT


def test_normal_mode_capital_a_goes_to_line_end() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("A", editor) is True
    assert editor.calls == ["line_end"]
    assert state.mode == VimMode.INSERT


def test_normal_mode_dd_deletes_line() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("d", editor) is True
    assert state.pending == "d"
    assert editor.calls == []
    assert handler.handle("d", editor) is True
    assert editor.calls == ["delete_line"]
    assert state.pending == ""


def test_normal_mode_capital_d_deletes_to_eol() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("D", editor) is True
    assert editor.calls == ["delete_end_of_line"]


def test_normal_mode_x_deletes_under_cursor() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("x", editor) is True
    assert editor.calls == ["delete_right"]


def test_normal_mode_u_undoes() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("u", editor) is True
    assert editor.calls == ["undo"]


def test_normal_mode_word_motions() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("w", editor)
    handler.handle("b", editor)
    assert editor.calls == ["word_right", "word_left"]


def test_normal_mode_line_edges() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("0", editor)
    handler.handle("dollar_sign", editor)
    assert editor.calls == ["line_start", "line_end"]


def test_normal_mode_swallows_unknown_printable_keys() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("z", editor) is True
    assert editor.calls == []


def test_normal_mode_lets_modifier_combos_through() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("ctrl+d", editor) is False
    assert handler.handle("super+enter", editor) is False


def test_normal_mode_escape_clears_pending_and_count() -> None:
    state = _state()
    state.pending = "d"
    state.count = 5
    handler = InputVimHandler(state)
    assert handler.handle("escape", FakeEditor()) is True
    assert state.pending == ""
    assert state.count is None
