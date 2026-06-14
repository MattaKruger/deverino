from __future__ import annotations

from harness_poc.tui_vim import (
    ChatVisualSelection,
    VimMode,
    VimPane,
    VimState,
)

from .conftest import FakeChat, _chat_handler


# -------------------------------------------------------------- chat handler


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
