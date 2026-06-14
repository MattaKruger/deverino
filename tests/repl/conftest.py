from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from harness_poc.tui_vim import (
    ChatVimHandler,
    ChatVisualSelection,
    VimMode,
    VimPane,
    VimState,
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
