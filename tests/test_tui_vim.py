from __future__ import annotations

from dataclasses import dataclass, field

from harness_poc.tui_vim import (
    InputVimHandler,
    VimMode,
    VimPane,
    VimState,
    cycle_pane,
    format_status,
    normalize_key,
)


@dataclass
class FakeEditor:
    """Records action calls so InputVimHandler can be tested in isolation."""

    calls: list[str] = field(default_factory=list)
    text: str = ""
    cursor_location: tuple[int, int] = (0, 0)

    def _record(self, name: str) -> None:
        self.calls.append(name)

    def action_cursor_left(self) -> None:
        self._record("cursor_left")

    def action_cursor_right(self) -> None:
        self._record("cursor_right")

    def action_cursor_up(self) -> None:
        self._record("cursor_up")

    def action_cursor_down(self) -> None:
        self._record("cursor_down")

    def action_cursor_line_start(self) -> None:
        self._record("line_start")

    def action_cursor_line_end(self) -> None:
        self._record("line_end")

    def action_cursor_word_left(self) -> None:
        self._record("word_left")

    def action_cursor_word_right(self) -> None:
        self._record("word_right")

    def action_delete_right(self) -> None:
        self._record("delete_right")

    def action_delete_to_end_of_line(self) -> None:
        self._record("delete_end_of_line")

    def action_delete_line(self) -> None:
        self._record("delete_line")

    def action_undo(self) -> None:
        self._record("undo")

    def move_cursor(self, location: tuple[int, int]) -> None:
        self.cursor_location = location


def _state(enabled: bool = True, mode: VimMode = VimMode.NORMAL) -> VimState:
    return VimState(enabled=enabled, mode=mode, initial_mode=mode)


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


def test_cycle_pane_toggles_between_input_and_chat() -> None:
    state = VimState(enabled=True)
    assert cycle_pane(state) == VimPane.CHAT
    assert cycle_pane(state) == VimPane.INPUT


def test_normalize_key_maps_dollar() -> None:
    assert normalize_key("$") == "dollar_sign"
    assert normalize_key("j") == "j"


def test_insert_mode_escape_switches_to_normal() -> None:
    state = _state(mode=VimMode.INSERT)
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("escape", editor) is True
    assert state.mode == VimMode.NORMAL


def test_insert_mode_passes_through_printable_keys() -> None:
    state = _state(mode=VimMode.INSERT)
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("a", editor) is False
    assert handler.handle("j", editor) is False


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
    editor = FakeEditor()
    assert handler.handle("i", editor) is True
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


def test_normal_mode_d_followed_by_non_operator_clears_pending() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    handler.handle("d", editor)
    # `dx` is not a valid operator+motion in our minimal set; pending should clear.
    assert handler.handle("x", editor) is True
    assert state.pending == ""
    assert editor.calls == []


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
    """Printable keys in normal mode must not pass through to the TextArea."""
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    # `z` has no mapping but is printable; must be consumed so it does not
    # get typed into the buffer.
    assert handler.handle("z", editor) is True
    assert editor.calls == []


def test_normal_mode_lets_modifier_combos_through() -> None:
    state = _state()
    handler = InputVimHandler(state)
    editor = FakeEditor()
    # Multi-character key names (ctrl+d, super+enter, etc.) fall through so
    # existing app bindings (submit, copy) still fire.
    assert handler.handle("ctrl+d", editor) is False
    assert handler.handle("super+enter", editor) is False


def test_normal_mode_escape_clears_pending_and_count() -> None:
    state = _state()
    state.pending = "d"
    state.count = 5
    handler = InputVimHandler(state)
    editor = FakeEditor()
    assert handler.handle("escape", editor) is True
    assert state.pending == ""
    assert state.count is None
