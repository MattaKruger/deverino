from __future__ import annotations

from harness_poc.tui_vim import (
    InputVimHandler,
    VimMode,
    VimState,
)

from .conftest import FakeEditor, _state


# ------------------------------------------------------------------ visual


def test_v_enters_visual_mode() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("v", editor) is True
    assert state.mode == VimMode.VISUAL


def test_visual_l_extends_selection_right() -> None:
    state = _state(mode=VimMode.VISUAL)
    handler = InputVimHandler(state)
    editor = FakeEditor()
    editor.cursor_location = (0, 1)
    assert handler.handle("l", editor) is True
    assert editor.move_calls == [((0, 2), True)]


def test_visual_y_copies_and_returns_to_normal() -> None:
    copied: list[str] = []
    state = _state(mode=VimMode.VISUAL)
    handler = InputVimHandler(state, copy_callback=copied.append)
    editor = FakeEditor(selected_text="hello world")
    assert handler.handle("y", editor) is True
    assert copied == ["hello world"]
    assert state.mode == VimMode.NORMAL


def test_visual_d_deletes_selection_and_returns_to_normal() -> None:
    state = _state(mode=VimMode.VISUAL)
    handler = InputVimHandler(state)
    editor = FakeEditor(
        selected_text="xyz",
        selection=((0, 1), (0, 4)),
        cursor_location=(0, 4),
    )
    assert handler.handle("d", editor) is True
    assert editor.replace_calls == [("", (0, 1), (0, 4))]
    assert state.mode == VimMode.NORMAL


def test_visual_c_deletes_and_enters_insert() -> None:
    state = _state(mode=VimMode.VISUAL)
    handler = InputVimHandler(state)
    editor = FakeEditor(
        selected_text="xyz",
        selection=((0, 1), (0, 4)),
        cursor_location=(0, 4),
    )
    assert handler.handle("c", editor) is True
    assert state.mode == VimMode.INSERT


def test_visual_escape_clears_selection() -> None:
    state = _state(mode=VimMode.VISUAL)
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("escape", editor) is True
    assert state.mode == VimMode.NORMAL


def test_visual_v_exits_back_to_normal() -> None:
    state = _state(mode=VimMode.VISUAL)
    handler = InputVimHandler(state)
    assert handler.handle("v", FakeEditor()) is True
    assert state.mode == VimMode.NORMAL
