from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.app import App, Binding, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Markdown, Static

from harness_poc.console import clear_tui_handlers, set_tui_handlers

if TYPE_CHECKING:
    from textual.timer import Timer

    from harness_poc.app_factory import AppState

logger = logging.getLogger(__name__)

_TOKEN_MILLION = 1_000_000
_TOKEN_THOUSAND = 1_000

_SPINNER_FRAMES = [
    "( ͡° ͜ʖ ͡°)  cooking",
    "(ง •̀_•́)ง  doing the thing",
    "¯\\_(ツ)_/¯  it depends",
    "(•̀ᴗ•́)و   manifesting",
    "ʕ•ᴥ•ʔ     big brain time",  # noqa: RUF001
    "(╯°□°）╯  consulting the oracle",  # noqa: RUF001
    "(*￣▽￣)b  works on my machine",
    "ヽ(•‿•)ノ  sending it",  # noqa: RUF001
    "(◕‿◕)✿   on it chief",
    "(งツ)ว     staring into the void",
]


def _format_tokens(count: int) -> str:
    if count >= _TOKEN_MILLION:
        return f"{count / _TOKEN_MILLION:.1f}M"
    if count >= _TOKEN_THOUSAND:
        return f"{count / _TOKEN_THOUSAND:.1f}k"
    return str(count)


_FILE_REF_PATTERN = re.compile(
    r"\b([\w./-]+\.\w{1,10}):(\d+)(?:-(\d+))?\b"
)


def _linkify_file_refs(text: str, project_root: str) -> str:
    """Convert ``path/file.py:123`` patterns into clickable Markdown links."""
    def _replace(match: re.Match[str]) -> str:
        rel = match.group(1)
        line = match.group(2)
        raw = match.group(0)
        # Resolve the path against project root
        candidate = Path(project_root) / rel.lstrip("/")
        if not candidate.is_file():
            return raw  # don't linkify non-existent paths
        return f"[{raw}](file-line:{candidate}:{line})"
    return _FILE_REF_PATTERN.sub(_replace, text)


class ChatApp(App[None]):
    BINDINGS: ClassVar[list] = [
        Binding("super+c", "copy_smart", "Copy", priority=True, show=False),
    ]

    DEFAULT_CSS = """
    #header {
        height: 1;
        dock: top;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #chat {
        height: 1fr;
        padding: 0 1;
    }
    .user-msg {
        margin-top: 1;
        color: $accent;
    }
    .agent-label {
        margin-top: 1;
        color: $success;
    }
    .tool-line {
        color: $text-muted;
        padding: 0 2;
    }
    #footer {
        dock: bottom;
        height: 4;
    }
    #spinner {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #input {
        height: 3;
        border: tall $accent;
    }
    """

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._spinner_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield VerticalScroll(id="chat")
        with Vertical(id="footer"):
            yield Static("", id="spinner")
            yield Input(placeholder="> ", id="input")

    def on_mount(self) -> None:
        set_tui_handlers(
            on_markdown=self._tui_print_markdown,
            on_error=self._tui_print_error,
            on_text=self._tui_print_text,
        )
        self._update_header()
        self.query_one(Input).focus()

    def on_unmount(self) -> None:
        clear_tui_handlers()

    def _update_header(self) -> None:
        llm = self._app_state.config.llm
        tokens = self._app_state.streaming.session_tokens
        token_part = f" · {_format_tokens(tokens)}" if tokens > 0 else ""
        self.query_one("#header", Static).update(f"{llm.provider} · {llm.model}{token_part}")

    def action_copy_smart(self) -> None:
        """Copy: prefer screen text selection, fall back to input field copy."""
        selected = self.screen.get_selected_text()
        if selected:
            self.copy_to_clipboard(selected)
        else:
            with contextlib.suppress(Exception):
                self.query_one("#input", Input).action_copy()

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        """Open ``file-line:`` links in Zed editor."""
        href = event.href
        if href.startswith("file-line:"):
            path = href.removeprefix("file-line:")
            editor = shutil.which("zed-preview") or shutil.which("zed") or "open"
            if editor == "open":
                subprocess.run(["open", path], check=False)  # noqa: S603, S607
            else:
                # zed supports file:line syntax: zed path:123
                subprocess.run([editor, path], check=False)  # noqa: S603
            return
        # All other links (http, https, etc.) → default browser
        self.open_url(event.href)

    def _start_spinner(self) -> None:
        spinner = self.query_one("#spinner", Static)
        frame_cycle = itertools.cycle(_SPINNER_FRAMES)
        dot_cycle = itertools.cycle([".", "..", "..."])
        current_frame = [next(frame_cycle)]
        tick = [0]

        def _tick() -> None:
            tick[0] += 1
            if tick[0] % 8 == 0:  # switch phrase every ~3.2 s
                current_frame[0] = next(frame_cycle)
            spinner.update(f"{current_frame[0]}{next(dot_cycle)}")

        spinner.update(f"{current_frame[0]}.")
        self._spinner_timer = self.set_interval(0.4, _tick)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self.query_one("#spinner", Static).update("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        if text.lower() in {"exit", "quit", "/exit", "/quit"}:
            self.exit()
            return
        self._submit(text)

    def _submit(self, text: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(f"[cyan]You:[/cyan] {text}", classes="user-msg", markup=True))
        self._start_spinner()
        chat.scroll_end(animate=False)
        self.run_worker(self._chat_worker(text, chat))

    async def _chat_worker(self, text: str, chat: VerticalScroll) -> None:  # noqa: PLR0915
        from harness_poc.repl import handle_repl_input  # noqa: PLC0415

        buffer: list[str] = []
        state: dict[str, Static | None] = {"widget": None}

        _last_flush: list[float] = [0.0]
        _flush_lock = threading.Lock()
        flush_interval = 0.033  # ~30 fps

        def _flush_to_ui() -> None:
            current = "".join(buffer)

            def _update() -> None:
                if state["widget"] is None:
                    self._stop_spinner()
                    w = Static(current, markup=False)
                    state["widget"] = w
                    chat.mount(Static("[green]Agent:[/green]", classes="agent-label", markup=True))
                    chat.mount(w)
                else:
                    state["widget"].update(current)
                chat.scroll_end(animate=False)

            self.call_from_thread(_update)

        def on_text_chunk(chunk: str) -> None:
            buffer.append(chunk)
            now = time.monotonic()
            with _flush_lock:
                if now - _last_flush[0] >= flush_interval:
                    _last_flush[0] = now
                    _flush_to_ui()

        def on_tool_event(message: str) -> None:
            def _mount() -> None:
                chat.mount(Static(f"  ⚙ {message}", classes="tool-line"))
                chat.scroll_end(animate=False)

            self.call_from_thread(_mount)

        self._app_state.streaming.on_text = on_text_chunk
        self._app_state.streaming.on_tool_event = on_tool_event
        self._app_state.streaming.on_finish = lambda _: None

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, handle_repl_input, self._app_state, text)
        except Exception:
            logger.exception("ChatApp worker raised", extra={"text": text})

        # Flush any tokens buffered in the last throttle window
        if buffer and state["widget"] is not None:
            state["widget"].update("".join(buffer))

        # Replace live streaming Static with rendered Markdown
        response = "".join(buffer)
        if state["widget"] is not None:
            await state["widget"].remove()
        if response:
            if state["widget"] is None:
                # no streaming happened — add the label now
                label = Static("[green]Agent:[/green]", classes="agent-label", markup=True)
                await chat.mount(label)
            linkified = _linkify_file_refs(response, str(self._app_state.config.project_root))
            await chat.mount(Markdown(linkified, open_links=False))
        self._stop_spinner()
        chat.scroll_end(animate=False)
        self._app_state.streaming.reset_callbacks()
        self._update_header()

    def _tui_print_markdown(self, text: str) -> None:
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            linkified = _linkify_file_refs(text, str(self._app_state.config.project_root))
            chat.mount(Markdown(linkified, open_links=False))
            chat.scroll_end(animate=False)

        self.call_from_thread(_mount)

    def _tui_print_error(self, text: str) -> None:
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            chat.mount(Static(f"[red]{text}[/red]", markup=True))
            chat.scroll_end(animate=False)

        self.call_from_thread(_mount)

    def _tui_print_text(self, text: str, markup: bool = True) -> None:  # noqa: FBT001, FBT002
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            chat.mount(Static(text, markup=markup))
            chat.scroll_end(animate=False)

        self.call_from_thread(_mount)
