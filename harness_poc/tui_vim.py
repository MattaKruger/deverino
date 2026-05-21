"""Vim-style modal interaction layer for the Textual TUI.

This module owns the runtime state (``VimState``), enums (``VimMode``,
``VimPane``), and the pure key-handling logic for the input pane. The Textual
``ChatApp`` in :mod:`harness_poc.tui` wires this state into widgets and routes
key events; everything that can be unit-tested without a running Textual app
lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class VimMode(StrEnum):
    INSERT = "insert"
    NORMAL = "normal"
    VISUAL = "visual"


class VimPane(StrEnum):
    INPUT = "input"
    CHAT = "chat"


@dataclass(slots=True)
class VimState:
    enabled: bool
    pane: VimPane = VimPane.INPUT
    mode: VimMode = VimMode.INSERT
    pending: str = ""
    count: int | None = None
    initial_mode: VimMode = VimMode.INSERT

    def reset(self) -> None:
        """Reset transient state after a pane/mode change or toggle."""
        self.pending = ""
        self.count = None


def format_status(state: VimState) -> str:
    """Render the one-line status text shown in ``#vim-status``."""
    if not state.enabled:
        return "vim off"
    return f"{state.mode.value.upper()} {state.pane.value}"


class _Editor(Protocol):
    """Subset of :class:`textual.widgets.TextArea` used by the input handler."""

    text: str

    @property
    def cursor_location(self) -> tuple[int, int]: ...

    def action_cursor_left(self) -> None: ...
    def action_cursor_right(self) -> None: ...
    def action_cursor_up(self) -> None: ...
    def action_cursor_down(self) -> None: ...
    def action_cursor_line_start(self) -> None: ...
    def action_cursor_line_end(self) -> None: ...
    def action_cursor_word_left(self) -> None: ...
    def action_cursor_word_right(self) -> None: ...
    def action_delete_right(self) -> None: ...
    def action_delete_to_end_of_line(self) -> None: ...
    def action_delete_line(self) -> None: ...
    def action_undo(self) -> None: ...
    def move_cursor(self, location: tuple[int, int]) -> None: ...


# Keys that, in normal mode, are dispatched directly without operator/count parsing.
_INPUT_MOTION_ACTIONS: dict[str, str] = {
    "h": "action_cursor_left",
    "j": "action_cursor_down",
    "k": "action_cursor_up",
    "l": "action_cursor_right",
    "0": "action_cursor_line_start",
    "dollar_sign": "action_cursor_line_end",
    "w": "action_cursor_word_right",
    "b": "action_cursor_word_left",
}

# Single-key edits in normal mode.
_INPUT_EDIT_ACTIONS: dict[str, str] = {
    "x": "action_delete_right",
    "u": "action_undo",
}


class InputVimHandler:
    """Pure key handler for the input pane.

    Returns ``True`` from :meth:`handle` when a key was consumed by the Vim
    layer (the caller should ``event.stop()`` and ``event.prevent_default()``),
    and ``False`` when the key should fall through to the underlying widget.
    """

    def __init__(self, state: VimState) -> None:
        self._state = state

    def handle(self, key: str, editor: _Editor) -> bool:
        if self._state.mode == VimMode.INSERT:
            return self._handle_insert(key)
        if self._state.mode == VimMode.NORMAL:
            return self._handle_normal(key, editor)
        return False

    def _handle_insert(self, key: str) -> bool:
        if key == "escape":
            self._state.mode = VimMode.NORMAL
            self._state.reset()
            return True
        return False

    def _handle_normal(self, key: str, editor: _Editor) -> bool:  # noqa: PLR0911
        state = self._state

        if key == "escape":
            state.reset()
            return True

        # Mode entries: `i` (insert here), `a` (insert after), `A` (insert at line end).
        if key == "i":
            state.mode = VimMode.INSERT
            state.reset()
            return True
        if key == "a":
            editor.action_cursor_right()
            state.mode = VimMode.INSERT
            state.reset()
            return True
        if key == "A":
            editor.action_cursor_line_end()
            state.mode = VimMode.INSERT
            state.reset()
            return True

        # Operator-pending: `dd` deletes the current line.
        if state.pending == "d":
            state.pending = ""
            if key == "d":
                editor.action_delete_line()
            return True

        if key == "d":
            state.pending = "d"
            return True

        if key == "D":
            editor.action_delete_to_end_of_line()
            return True

        if key in _INPUT_MOTION_ACTIONS:
            getattr(editor, _INPUT_MOTION_ACTIONS[key])()
            return True

        if key in _INPUT_EDIT_ACTIONS:
            getattr(editor, _INPUT_EDIT_ACTIONS[key])()
            return True

        # In normal mode, swallow any other printable key so it does not get
        # inserted into the buffer. Non-printable keys (modifier combos, fn
        # keys) fall through so existing app bindings still work.
        return len(key) == 1 and key.isprintable()


def cycle_pane(state: VimState, *, backward: bool = False) -> VimPane:
    """Toggle pane focus between input and chat.

    ``backward`` is accepted but ignored: with only two panes the cycle is
    symmetric, and keeping the parameter makes the call site read naturally.
    """
    del backward
    state.pane = VimPane.CHAT if state.pane == VimPane.INPUT else VimPane.INPUT
    return state.pane


def normalize_key(key: str) -> str:
    """Map Textual key names to the short tokens used by the handler.

    Textual reports `$` as ``"dollar_sign"`` in some contexts and ``"$"`` in
    others; this normalizes both forms.
    """
    if key == "$":
        return "dollar_sign"
    return key
