from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from harness_poc.tui_vim import (
    ChatVimHandler,
    ChatVisualSelection,
    InputVimHandler,
    VimMode,
    VimPane,
    VimState,
    cycle_pane,
    format_status,
    normalize_key,
)

Location = tuple[int, int]


@dataclass
class FakeEditor:
    """Records action calls so InputVimHandler can be tested in isolation."""

    text: str = ""
    cursor_location: Location = (0, 0)
    selected_text: str = ""
    selection: tuple[Location, Location] = ((0, 0), (0, 0))
    calls: list[str] = field(default_factory=list)
    replace_calls: list[tuple[str, Location, Location]] = field(default_factory=list)
    move_calls: list[tuple[Location, bool]] = field(default_factory=list)

    def _record(self, name: str) -> None:
        self.calls.append(name)

    # action_*: simple cursor moves recorded by name.
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

    # Motion target helpers (used by visual mode + operator+motion).
    def get_cursor_left_location(self) -> Location:
        r, c = self.cursor_location
        return (r, max(c - 1, 0))

    def get_cursor_right_location(self) -> Location:
        r, c = self.cursor_location
        return (r, c + 1)

    def get_cursor_up_location(self) -> Location:
        r, c = self.cursor_location
        return (max(r - 1, 0), c)

    def get_cursor_down_location(self) -> Location:
        r, c = self.cursor_location
        return (r + 1, c)

    def get_cursor_line_start_location(self) -> Location:
        return (self.cursor_location[0], 0)

    def get_cursor_line_end_location(self) -> Location:
        return (self.cursor_location[0], 99)

    def get_cursor_word_left_location(self) -> Location:
        r, c = self.cursor_location
        return (r, max(c - 3, 0))

    def get_cursor_word_right_location(self) -> Location:
        r, c = self.cursor_location
        return (r, c + 3)

    def move_cursor(self, location: Location, *, select: bool = False) -> None:
        self.move_calls.append((location, select))
        if select:
            self.selection = (self.selection[0], location)
        else:
            self.selection = (location, location)
        self.cursor_location = location

    def replace(self, insert: str, start: Location, end: Location) -> None:
        self.replace_calls.append((insert, start, end))


def _state(enabled: bool = True, mode: VimMode = VimMode.NORMAL) -> VimState:
    return VimState(enabled=enabled, mode=mode, initial_mode=mode)


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


# -------------------------------------------------------------- chat handler


@dataclass
class FakeChat:
    scroll_y: float = 0.0
    max_scroll_y: float = 100.0
    calls: list[tuple[str, object]] = field(default_factory=list)

    def scroll_relative(self, *, y: float, animate: bool = False) -> None:
        del animate
        self.scroll_y += y
        self.calls.append(("relative", y))

    def scroll_home(self, *, animate: bool = False) -> None:
        del animate
        self.scroll_y = 0.0
        self.calls.append(("home", None))

    def scroll_end(self, *, animate: bool = False) -> None:
        del animate
        self.scroll_y = self.max_scroll_y
        self.calls.append(("end", None))

    def scroll_page_up(self, *, animate: bool = False) -> None:
        del animate
        self.calls.append(("page_up", None))

    def scroll_page_down(self, *, animate: bool = False) -> None:
        del animate
        self.calls.append(("page_down", None))


def _chat_handler(
    state: VimState | None = None,
    messages: list[str] | None = None,
) -> tuple[ChatVimHandler, dict[str, list]]:
    state = state or VimState(enabled=True, pane=VimPane.CHAT, mode=VimMode.NORMAL)
    records: dict[str, list] = {
        "copied": [],
        "focus_input": [],
        "copy_last": [],
    }
    handler = ChatVimHandler(
        state,
        copy_callback=cast("list[str]", records["copied"]).append,
        focus_input_insert=lambda: records["focus_input"].append(True),
        copy_last_response=lambda: records["copy_last"].append(True),
        message_texts=lambda: list(messages or []),
    )
    return handler, records


def test_chat_jk_scrolls_one_line() -> None:
    handler, _ = _chat_handler()
    chat = FakeChat()
    handler.handle("j", chat)
    handler.handle("k", chat)
    assert chat.calls == [("relative", 1), ("relative", -1)]


def test_chat_ctrl_u_half_page() -> None:
    """ctrl+u is handled by ChatVimHandler (ctrl+d is handled at the app level)."""
    handler, _ = _chat_handler()
    chat = FakeChat()
    handler.handle("ctrl+u", chat)
    assert chat.calls == [("page_up", None)]


def test_chat_gg_jumps_to_top() -> None:
    handler, _ = _chat_handler()
    chat = FakeChat()
    handler.handle("g", chat)
    handler.handle("g", chat)
    assert chat.calls == [("home", None)]


def test_chat_capital_g_jumps_to_bottom() -> None:
    handler, _ = _chat_handler()
    chat = FakeChat()
    handler.handle("G", chat)
    assert chat.calls == [("end", None)]


def test_chat_i_focuses_input_for_insert() -> None:
    handler, records = _chat_handler()
    handler.handle("i", FakeChat())
    assert records["focus_input"] == [True]


def test_chat_capital_y_copies_last_response() -> None:
    handler, records = _chat_handler()
    handler.handle("Y", FakeChat())
    assert records["copy_last"] == [True]


def test_chat_count_repeats_scroll() -> None:
    handler, _ = _chat_handler()
    chat = FakeChat()
    handler.handle("3", chat)
    handler.handle("j", chat)
    assert chat.calls == [("relative", 1)] * 3


def test_chat_ctrl_d_not_handled_by_vim_handler() -> None:
    """ctrl+d is handled at the app level (action_submit_editor), not by ChatVimHandler."""
    handler, _ = _chat_handler()
    chat = FakeChat()
    result = handler.handle("ctrl+d", chat)
    assert result is False  # not consumed by Vim handler
    assert chat.calls == []  # no scroll via handler


def test_chat_v_enters_visual_when_messages_present() -> None:
    state = VimState(enabled=True, pane=VimPane.CHAT, mode=VimMode.NORMAL)
    handler, _ = _chat_handler(state=state, messages=["one", "two", "three"])
    handler.handle("v", FakeChat())
    assert state.mode == VimMode.VISUAL
    assert handler.selection == ChatVisualSelection(anchor=2, head=2)


def test_chat_visual_jk_extends_range() -> None:
    state = VimState(enabled=True, pane=VimPane.CHAT, mode=VimMode.NORMAL)
    handler, _ = _chat_handler(state=state, messages=["a", "b", "c", "d"])
    handler.handle("v", FakeChat())
    handler.handle("k", FakeChat())
    handler.handle("k", FakeChat())
    sel = handler.selection
    assert sel is not None
    assert (sel.start, sel.end) == (1, 3)


def test_chat_visual_y_copies_joined_text_and_exits() -> None:
    state = VimState(enabled=True, pane=VimPane.CHAT, mode=VimMode.NORMAL)
    handler, records = _chat_handler(state=state, messages=["alpha", "beta", "gamma"])
    handler.handle("v", FakeChat())
    handler.handle("k", FakeChat())
    handler.handle("y", FakeChat())
    assert records["copied"] == ["beta\n\ngamma"]
    assert state.mode == VimMode.NORMAL
    assert handler.selection is None


def test_chat_visual_escape_clears() -> None:
    state = VimState(enabled=True, pane=VimPane.CHAT, mode=VimMode.NORMAL)
    handler, _ = _chat_handler(state=state, messages=["a", "b"])
    handler.handle("v", FakeChat())
    handler.handle("escape", FakeChat())
    assert state.mode == VimMode.NORMAL
    assert handler.selection is None


def test_chat_v_no_op_when_no_messages() -> None:
    state = VimState(enabled=True, pane=VimPane.CHAT, mode=VimMode.NORMAL)
    handler, _ = _chat_handler(state=state, messages=[])
    handler.handle("v", FakeChat())
    assert state.mode == VimMode.NORMAL
