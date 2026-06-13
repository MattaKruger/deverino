"""Vim-style modal interaction layer for the Textual TUI.

Owns the runtime state (``VimState``), enums (``VimMode``, ``VimPane``), and
the pure key-handling logic for both the input and chat panes. The Textual
``ChatApp`` in :mod:`harness_poc.tui` wires this state into widgets and
routes key events; everything that can be unit-tested without a running
Textual app lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable

Location = tuple[int, int]


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

    def consume_count(self) -> int:
        """Return the count to apply to the next motion (defaults to 1) and clear it."""
        count = self.count if self.count and self.count > 0 else 1
        self.count = None
        return count


def format_status(state: VimState) -> str:
    """Render the one-line status text shown in ``#vim-status``."""
    if not state.enabled:
        return "vim off"
    return f"{state.mode.value.upper()} {state.pane.value}"


class _Editor(Protocol):
    """Subset of :class:`textual.widgets.TextArea` used by the input handler."""

    text: str
    selected_text: str

    @property
    def cursor_location(self) -> Location: ...
    @property
    def selection(self) -> object: ...

    def get_cursor_left_location(self) -> Location: ...
    def get_cursor_right_location(self) -> Location: ...
    def get_cursor_up_location(self) -> Location: ...
    def get_cursor_down_location(self) -> Location: ...
    def get_cursor_line_start_location(self) -> Location: ...
    def get_cursor_line_end_location(self) -> Location: ...
    def get_cursor_word_left_location(self) -> Location: ...
    def get_cursor_word_right_location(self) -> Location: ...

    def move_cursor(self, location: Location, *, select: bool = False) -> None: ...
    def replace(self, insert: str, start: Location, end: Location) -> object: ...

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


# Maps a normal-mode motion key to the matching ``action_cursor_*`` method.
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

# Maps a motion key to the ``get_cursor_*_location`` method that returns its
# target. Used for operator+motion (``dw``, ``d$``…) and visual extensions.
_MOTION_LOCATIONS: dict[str, str] = {
    "h": "get_cursor_left_location",
    "j": "get_cursor_down_location",
    "k": "get_cursor_up_location",
    "l": "get_cursor_right_location",
    "0": "get_cursor_line_start_location",
    "dollar_sign": "get_cursor_line_end_location",
    "w": "get_cursor_word_right_location",
    "b": "get_cursor_word_left_location",
}


def _ordered(a: Location, b: Location) -> tuple[Location, Location]:
    return (a, b) if a <= b else (b, a)


class InputVimHandler:
    """Pure key handler for the input pane.

    Returns ``True`` from :meth:`handle` when a key was consumed by the Vim
    layer (the caller should ``event.stop()`` and ``event.prevent_default()``)
    and ``False`` when the key should fall through to the underlying widget.
    """

    def __init__(
        self,
        state: VimState,
        copy_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._state = state
        self._copy = copy_callback or (lambda _text: None)

    def handle(self, key: str, editor: _Editor) -> bool:
        if self._state.mode == VimMode.INSERT:
            return self._handle_insert(key)
        if self._state.mode == VimMode.NORMAL:
            return self._handle_normal(key, editor)
        if self._state.mode == VimMode.VISUAL:
            return self._handle_visual(key, editor)
        return False

    # ------------------------------------------------------------------ insert

    def _handle_insert(self, key: str) -> bool:
        if key == "escape":
            self._state.mode = VimMode.NORMAL
            self._state.reset()
            return True
        return False

    # ------------------------------------------------------------------ normal

    def _handle_normal(self, key: str, editor: _Editor) -> bool:  # noqa: PLR0911, PLR0912
        state = self._state

        if key == "escape":
            state.reset()
            return True

        # Count prefix accumulation. `0` is only a count digit when a count
        # has already been started, otherwise it is the line-start motion.
        if key.isdigit() and (key != "0" or state.count is not None):
            state.count = (state.count or 0) * 10 + int(key)
            return True

        # Operator-pending dispatch.
        if state.pending in {"d", "c"}:
            return self._apply_operator(key, editor)

        # Mode entries.
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
        if key == "v":
            state.mode = VimMode.VISUAL
            # Selection starts empty at the cursor; subsequent motions extend it.
            editor.move_cursor(editor.cursor_location, select=False)
            state.reset()
            return True

        if key == "d":
            state.pending = "d"
            return True
        if key == "c":
            state.pending = "c"
            return True
        if key == "D":
            editor.action_delete_to_end_of_line()
            state.reset()
            return True
        if key == "u":
            editor.action_undo()
            state.reset()
            return True
        if key == "x":
            for _ in range(state.consume_count()):
                editor.action_delete_right()
            return True

        if key in _INPUT_MOTION_ACTIONS:
            for _ in range(state.consume_count()):
                getattr(editor, _INPUT_MOTION_ACTIONS[key])()
            return True

        # In normal mode, swallow any other printable key so it does not get
        # inserted into the buffer. Non-printable keys (modifier combos, fn
        # keys) fall through so existing app bindings still work.
        return len(key) == 1 and key.isprintable()

    def _apply_operator(self, key: str, editor: _Editor) -> bool:
        """Handle the motion (or doubled operator) after a pending ``d``/``c``."""
        state = self._state
        op = state.pending
        state.pending = ""

        # Doubled operator: `dd` deletes the line, `cc` clears it and enters insert.
        if key == op:
            count = state.consume_count()
            for _ in range(count):
                editor.action_delete_line()
            if op == "c":
                state.mode = VimMode.INSERT
            return True

        if key in _MOTION_LOCATIONS:
            count = state.consume_count()
            start = editor.cursor_location
            for _ in range(count):
                target = getattr(editor, _MOTION_LOCATIONS[key])()
                editor.move_cursor(target)
            end = editor.cursor_location
            lo, hi = _ordered(start, end)
            editor.replace("", lo, hi)
            if op == "c":
                state.mode = VimMode.INSERT
            return True

        # Unknown follow-up: discard the operator silently.
        state.count = None
        return True

    # ------------------------------------------------------------------ visual

    def _handle_visual(self, key: str, editor: _Editor) -> bool:
        state = self._state

        if key in {"escape", "v"}:
            editor.move_cursor(editor.cursor_location, select=False)
            state.mode = VimMode.NORMAL
            state.reset()
            return True

        if key in _MOTION_LOCATIONS:
            target = getattr(editor, _MOTION_LOCATIONS[key])()
            editor.move_cursor(target, select=True)
            return True

        if key == "y":
            self._copy(editor.selected_text)
            editor.move_cursor(editor.cursor_location, select=False)
            state.mode = VimMode.NORMAL
            state.reset()
            return True

        if key in {"d", "c"}:
            text = editor.selected_text
            self._copy(text)
            # ``selection`` exposes the (anchor, cursor) pair; use cursor + len
            # of selected text to compute the replace range robustly.
            sel = editor.selection
            start, end = _selection_range(sel)
            editor.replace("", start, end)
            state.mode = VimMode.INSERT if key == "c" else VimMode.NORMAL
            state.reset()
            return True

        return len(key) == 1 and key.isprintable()


def _selection_range(selection: object) -> tuple[Location, Location]:
    """Extract (start, end) ``Location``s from a Textual Selection or 2-tuple."""
    start = getattr(selection, "start", None)
    end = getattr(selection, "end", None)
    if start is None or end is None:
        # Fallback for plain 2-tuples (used by FakeEditor in tests).
        pair = cast("tuple[Location, Location]", selection)
        start, end = pair
    return _ordered(tuple(start), tuple(end))  # type: ignore[arg-type]


# ---------------------------------------------------------------------- chat


class _Chat(Protocol):
    """Subset of :class:`textual.containers.VerticalScroll` used by the chat handler."""

    def scroll_relative(self, *, y: float, animate: bool = False) -> None: ...
    def scroll_home(self, *, animate: bool = False) -> None: ...
    def scroll_end(self, *, animate: bool = False) -> None: ...
    def scroll_page_up(self, *, animate: bool = False) -> None: ...
    def scroll_page_down(self, *, animate: bool = False) -> None: ...


@dataclass(slots=True)
class ChatVisualSelection:
    """Inclusive index range into the chat's mounted message blocks."""

    anchor: int
    head: int

    @property
    def start(self) -> int:
        return min(self.anchor, self.head)

    @property
    def end(self) -> int:
        return max(self.anchor, self.head)


class ChatVimHandler:
    """Pure key handler for the chat/history pane.

    The handler delegates pane-level effects (focus changes, copying the
    latest assistant response, retrieving the list of message texts) through
    callbacks so the module stays free of Textual imports.
    """

    def __init__(
        self,
        state: VimState,
        *,
        copy_callback: Callable[[str], None],
        focus_input_insert: Callable[[], None],
        copy_last_response: Callable[[], None],
        message_texts: Callable[[], list[str]],
    ) -> None:
        self._state = state
        self._copy = copy_callback
        self._focus_input_insert = focus_input_insert
        self._copy_last_response = copy_last_response
        self._message_texts = message_texts
        self._selection: ChatVisualSelection | None = None

    @property
    def selection(self) -> ChatVisualSelection | None:
        return self._selection

    def handle(self, key: str, chat: _Chat) -> bool:
        if self._state.mode == VimMode.VISUAL:
            return self._handle_visual(key, chat)
        return self._handle_normal(key, chat)

    def _handle_normal(self, key: str, chat: _Chat) -> bool:  # noqa: PLR0911, PLR0912
        state = self._state

        if key == "escape":
            state.reset()
            return True

        if key.isdigit() and (key != "0" or state.count is not None):
            state.count = (state.count or 0) * 10 + int(key)
            return True

        # `gg` jumps to top; first `g` is operator-pending.
        if state.pending == "g":
            state.pending = ""
            if key == "g":
                chat.scroll_home()
            return True
        if key == "g":
            state.pending = "g"
            return True

        if key == "i":
            state.reset()
            self._focus_input_insert()
            return True

        if key == "v":
            messages = self._message_texts()
            if messages:
                last = len(messages) - 1
                self._selection = ChatVisualSelection(anchor=last, head=last)
                state.mode = VimMode.VISUAL
            state.reset()
            return True

        if key == "Y":
            self._copy_last_response()
            state.reset()
            return True

        if key == "G":
            chat.scroll_end()
            state.reset()
            return True

        if key == "j":
            for _ in range(state.consume_count()):
                chat.scroll_relative(y=1)
            return True
        if key == "k":
            for _ in range(state.consume_count()):
                chat.scroll_relative(y=-1)
            return True
        if key == "ctrl+d":
            chat.scroll_page_down()
            return True
        if key == "ctrl+u":
            chat.scroll_page_up()
            return True

        # Swallow other printable keys to avoid leaking them as text input
        # when the chat pane is focused.
        return len(key) == 1 and key.isprintable()

    def _handle_visual(self, key: str, chat: _Chat) -> bool:
        sel = self._selection
        messages = self._message_texts()
        if sel is None or not messages:
            self._exit_visual(chat)
            return True

        if key in {"escape", "v"}:
            self._exit_visual(chat)
            return True

        if key == "j":
            sel.head = min(sel.head + 1, len(messages) - 1)
            return True
        if key == "k":
            sel.head = max(sel.head - 1, 0)
            return True

        if key == "y":
            text = "\n\n".join(messages[sel.start : sel.end + 1])
            self._copy(text)
            self._exit_visual(chat)
            return True

        return len(key) == 1 and key.isprintable()

    def _exit_visual(self, chat: _Chat) -> None:
        del chat
        self._selection = None
        self._state.mode = VimMode.NORMAL
        self._state.reset()


# ---------------------------------------------------------------------- misc


def cycle_pane(state: VimState, *, backward: bool = False) -> VimPane:
    """Toggle pane focus between input and chat.

    ``backward`` is accepted but ignored: with only two panes the cycle is
    symmetric, and keeping the parameter makes the call site read naturally.
    """
    del backward
    state.pane = VimPane.CHAT if state.pane == VimPane.INPUT else VimPane.INPUT
    return state.pane


def normalize_key(key: str) -> str:
    """Map Textual key names to the short tokens used by the handler."""
    if key == "$":
        return "dollar_sign"
    return key
