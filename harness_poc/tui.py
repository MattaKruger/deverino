from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, LoadingIndicator, Markdown, Static

from harness_poc.console import clear_tui_handlers, set_tui_handlers

if TYPE_CHECKING:
    from harness_poc.app_factory import AppState

logger = logging.getLogger(__name__)

_TOKEN_MILLION = 1_000_000
_TOKEN_THOUSAND = 1_000


def _format_tokens(count: int) -> str:
    if count >= _TOKEN_MILLION:
        return f"{count / _TOKEN_MILLION:.1f}M"
    if count >= _TOKEN_THOUSAND:
        return f"{count / _TOKEN_THOUSAND:.1f}k"
    return str(count)


class ChatApp(App[None]):
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
    .tool-line {
        color: $text-muted;
        padding: 0 2;
    }
    #input {
        dock: bottom;
        height: 3;
        border: tall $accent;
    }
    """

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield VerticalScroll(id="chat")
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
        loading = LoadingIndicator()
        chat.mount(loading)
        chat.scroll_end(animate=False)
        self.run_worker(self._chat_worker(text, chat, loading))

    async def _chat_worker(
        self,
        text: str,
        chat: VerticalScroll,
        loading: LoadingIndicator,
    ) -> None:
        from harness_poc.repl import handle_repl_input  # noqa: PLC0415

        buffer: list[str] = []

        def on_text_chunk(chunk: str) -> None:
            buffer.append(chunk)

        def on_tool_event(message: str) -> None:
            def _mount() -> None:
                chat.mount(Static(f"  ⚙ {message}", classes="tool-line"))

            self.call_from_thread(_mount)

        self._app_state.streaming.on_text = on_text_chunk
        self._app_state.streaming.on_tool_event = on_tool_event
        self._app_state.streaming.on_finish = lambda _: None

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, handle_repl_input, self._app_state, text)
        except Exception:
            logger.exception("ChatApp worker raised", extra={"text": text})

        response = "".join(buffer)
        await loading.remove()
        if response:
            await chat.mount(Markdown(response))
        chat.scroll_end(animate=False)
        self._app_state.streaming.reset_callbacks()
        self._update_header()

    def _tui_print_markdown(self, text: str) -> None:
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            chat.mount(Markdown(text))
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
