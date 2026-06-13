from __future__ import annotations

import asyncio
import contextlib
import inspect
import itertools
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from textual.app import App, Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static, TextArea

from harness_poc.console import clear_tui_handlers, set_tui_handlers
from harness_poc.repl_completion import completions_for_text
from harness_poc.tui_vim import (
    ChatVimHandler,
    InputVimHandler,
    VimMode,
    VimPane,
    VimState,
    cycle_pane,
    format_status,
    normalize_key,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from textual import events
    from textual.app import ComposeResult
    from textual.timer import Timer

    from harness_poc.app_factory import AppState

logger = logging.getLogger(__name__)

_TOKEN_MILLION = 1_000_000
_TOKEN_THOUSAND = 1_000

_SCROLL_END_EPSILON = 1.0

_SPINNER_ICONS = [
    "( ͡° ͜ʖ ͡°)",
    "(ง •̀_•́)ง",
    "¯\\_(ツ)_/¯",
    "(•̀ᴗ•́)و",
    "ʕ•ᴥ•ʔ",  # noqa: RUF001
    "(╯°□°）╯",  # noqa: RUF001
    "(*￣▽￣)b",
    "ヽ(•‿•)ノ",  # noqa: RUF001
    "(◕‿◕)✿",
    "(งツ)ว",
]

_SPINNER_PHRASES = [
    "cooking",
    "doing the thing",
    "it depends",
    "manifesting",
    "big brain time",
    "consulting the oracle",
    "works on my machine",
    "sending it",
    "on it chief",
    "staring into the void",
]


def _format_tokens(count: int) -> str:
    if count >= _TOKEN_MILLION:
        return f"{count / _TOKEN_MILLION:.1f}M"
    if count >= _TOKEN_THOUSAND:
        return f"{count / _TOKEN_THOUSAND:.1f}k"
    return str(count)


def _format_spinner_status(icon: str, phrase: str, dots: str) -> str:
    return f"{icon:<12}  {phrase}{dots}"


_FILE_REF_PATTERN = re.compile(r"\b([\w./-]+\.\w{1,10}):(\d+)(?:-(\d+))?\b")
_MARKDOWN_BLOCK_PATTERN = re.compile(r"(^|\n)(#{1,6}\s|[-*]\s|\d+\.\s|```|>\s|\|.+\|)")


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


def _should_render_markdown(text: str) -> bool:
    return bool(_MARKDOWN_BLOCK_PATTERN.search(text))


def _should_show_completions(line_before_cursor: str) -> bool:
    stripped = line_before_cursor.lstrip()
    return stripped.startswith("/") and "\t" not in stripped


def _is_chat_at_scroll_end(chat: VerticalScroll) -> bool:
    return chat.scroll_y >= chat.max_scroll_y - _SCROLL_END_EPSILON


def _scroll_chat_end_if_following(chat: VerticalScroll, *, was_at_end: bool) -> None:
    if was_at_end:
        chat.scroll_end(animate=False)


def _special_resource_completion(line_before_cursor: str) -> str | None:
    normalized = line_before_cursor.strip()
    if normalized in {"/skill", "skill"}:
        return "skills"
    if normalized in {"/workflow", "workflow"}:
        return "workflows"
    if normalized in {"/pipeline", "pipeline"}:
        return "pipelines"
    return None


def _apply_completion(before: str, after: str, completion: str) -> tuple[str, int]:
    special = _special_resource_completion(before)
    if special is not None:
        replacement = f"{before} {completion}"
        return f"{replacement}{after}", len(replacement)

    token_start = len(before) - len(before.rsplit(maxsplit=1)[-1]) if before.strip() else 0
    replacement = f"{before[:token_start]}{completion}"
    return f"{replacement}{after}", len(replacement)


def _workflow_names(app_state: AppState) -> tuple[str, ...]:
    workflows_dir = app_state.config.paths.workflows
    if not workflows_dir.exists():
        return ()
    return tuple(sorted(path.stem for path in workflows_dir.glob("*.yaml")))


def _skill_names(app_state: AppState) -> tuple[str, ...]:
    names: list[str] = []
    for tool in app_state.skill_runner.discover_skills():
        function = tool.get("function", {})
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return tuple(sorted(names))


class VimTextArea(TextArea):
    """TextArea subclass that lets ``ChatApp`` intercept keys when Vim is on.

    Textual's TextArea consumes printable keys before app-level ``on_key``
    handlers see them; in normal/visual mode we need first crack at every
    keystroke. The app exposes :meth:`ChatApp.handle_vim_text_area_key` and
    this subclass forwards each key to it before the widget runs its own
    handling.
    """

    async def _on_key(self, event: events.Key) -> None:
        app = cast("ChatApp", self.app)
        if app.handle_vim_text_area_key(event):
            event.stop()
            event.prevent_default()


class ChatApp(App[None]):
    BINDINGS: ClassVar[list] = [
        Binding("super+c", "copy_smart", "Copy", priority=True, show=False),
        Binding("super+y", "copy_last_response", "Copy last response", priority=True, show=False),
        Binding("ctrl+d", "submit_editor", "Submit", priority=True, show=False),
        Binding("alt+enter", "submit_editor", "Submit", priority=True, show=False),
        Binding("super+enter", "submit_editor", "Submit", priority=True, show=False),
        Binding("tab", "cycle_completion_forward", "Next completion", priority=True, show=False),
        Binding(
            "shift+tab",
            "cycle_completion_backward",
            "Previous completion",
            priority=True,
            show=False,
        ),
        Binding(
            "enter",
            "accept_completion_or_newline",
            "Accept completion",
            priority=True,
            show=False,
        ),
        Binding("f2", "toggle_vim", "Toggle Vim", priority=True, show=False),
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
        height: 11;
    }
    #spinner {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #vim-status {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #input {
        height: 5;
        border: tall $accent;
    }
    #completion-menu {
        height: 4;
        display: none;
        border: tall $surface;
    }
    """

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._spinner_timer: Timer | None = None
        self._materializer_task: asyncio.Task[None] | None = None
        tui_cfg = app_state.config.tui
        initial_mode = VimMode(tui_cfg.vim_initial_mode)
        self._vim = VimState(
            enabled=tui_cfg.vim_enabled,
            mode=initial_mode if tui_cfg.vim_enabled else VimMode.INSERT,
            initial_mode=initial_mode,
        )
        self._chat_messages: list[str] = []
        self._vim_input = InputVimHandler(self._vim, copy_callback=self.copy_to_clipboard)
        self._vim_chat = ChatVimHandler(
            self._vim,
            copy_callback=self.copy_to_clipboard,
            focus_input_insert=self._focus_input_for_insert,
            copy_last_response=self.action_copy_last_response,
            message_texts=lambda: list(self._chat_messages),
        )

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield VerticalScroll(id="chat")
        with Vertical(id="footer"):
            yield Static("", id="spinner")
            yield Static("", id="vim-status")
            yield VimTextArea(
                "",
                placeholder="> ",
                id="input",
                show_line_numbers=False,
                soft_wrap=True,
                tab_behavior="focus",
            )
            yield OptionList(id="completion-menu")

    def on_mount(self) -> None:
        set_tui_handlers(
            on_markdown=self._tui_print_markdown,
            on_error=self._tui_print_error,
            on_text=self._tui_print_text,
        )
        if self._app_state.materializer_runner is not None:
            maybe_coro = self._app_state.materializer_runner.run_forever()
            if inspect.isawaitable(maybe_coro):
                self._materializer_task = asyncio.create_task(
                    cast("Coroutine[Any, Any, None]", maybe_coro)
                )
        self._update_header()
        self._update_vim_status()
        self.query_one("#chat", VerticalScroll).can_focus = True
        self.query_one("#input", TextArea).focus()

    def on_unmount(self) -> None:
        if self._materializer_task is not None:
            self._materializer_task.cancel()
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
                self.query_one("#input", TextArea).action_copy()

    def action_copy_last_response(self) -> None:
        messages = self._app_state.messages
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                self.copy_to_clipboard(msg["content"])
                self.notify("Last response copied to clipboard")
                return
        self.notify("No response to copy", severity="warning")

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
        icon_cycle = itertools.cycle(_SPINNER_ICONS)
        phrase_cycle = itertools.cycle(_SPINNER_PHRASES)
        dot_cycle = itertools.cycle([".", "..", "..."])
        current_icon = [next(icon_cycle)]
        current_phrase = [next(phrase_cycle)]
        tick = [0]

        def _tick() -> None:
            tick[0] += 1
            if tick[0] % 4 == 0:
                current_icon[0] = next(icon_cycle)
            if tick[0] % 8 == 0:
                current_phrase[0] = next(phrase_cycle)
            spinner.update(
                _format_spinner_status(current_icon[0], current_phrase[0], next(dot_cycle))
            )

        spinner.update(_format_spinner_status(current_icon[0], current_phrase[0], "."))
        self._spinner_timer = self.set_interval(0.4, _tick)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self.query_one("#spinner", Static).update("")

    def action_submit_editor(self) -> None:
        if self._vim.enabled and self._vim.pane == VimPane.CHAT:
            # In chat-pane normal mode, ctrl+d is half-page scroll, not submit.
            self.query_one("#chat", VerticalScroll).scroll_page_down()
            return
        self._submit_editor_text()

    def action_toggle_vim(self) -> None:
        self._vim.enabled = not self._vim.enabled
        self._vim.pane = VimPane.INPUT
        self._vim.mode = self._vim.initial_mode if self._vim.enabled else VimMode.INSERT
        self._vim.reset()
        self._hide_completion_menu()
        self.query_one("#input", TextArea).focus()
        self._update_vim_status()

    def _update_vim_status(self) -> None:
        self.query_one("#vim-status", Static).update(format_status(self._vim))

    def handle_vim_text_area_key(self, event: events.Key) -> bool:
        """Route a key event from VimTextArea through the Vim handler.

        Returns True if the Vim layer consumed the key; the subclass then
        stops the event so the underlying widget never sees it.
        """
        if not self._vim.enabled or self._completion_visible:
            return False
        if self._vim.pane != VimPane.INPUT:
            return False
        if event.key in {"tab", "shift+tab"}:
            # Pane cycling is handled at the app level; let the binding fire.
            return False
        key = normalize_key(event.key)
        editor = self.query_one("#input", TextArea)
        handled = self._vim_input.handle(key, editor)
        if handled:
            self._update_vim_status()
        return handled

    def _cycle_vim_pane(self) -> None:
        next_pane = cycle_pane(self._vim)
        if next_pane == VimPane.INPUT:
            self.query_one("#input", TextArea).focus()
        else:
            self.query_one("#chat", VerticalScroll).focus()
            # Chat pane has no insert mode; force normal while focused there.
            self._vim.mode = VimMode.NORMAL
        self._vim.reset()
        self._update_vim_status()

    def _focus_input_for_insert(self) -> None:
        self._vim.pane = VimPane.INPUT
        self._vim.mode = VimMode.INSERT
        self._vim.reset()
        self.query_one("#input", TextArea).focus()
        self._update_vim_status()

    def on_key(self, event: events.Key) -> None:
        # Completion menu has priority over Vim while it is visible.
        if self._completion_visible:
            return
        if not self._vim.enabled:
            return
        if self._vim.pane != VimPane.CHAT:
            return
        if event.key in {"tab", "shift+tab"}:
            return  # handled by the cycle-completion actions
        chat = self.query_one("#chat", VerticalScroll)
        key = normalize_key(event.key)
        if self._vim_chat.handle(key, chat):
            self._update_vim_status()
            event.stop()
            event.prevent_default()

    def action_cycle_completion_forward(self) -> None:
        if self._vim.enabled and not self._completion_visible:
            self._cycle_vim_pane()
            return
        self._cycle_completion(forward=True)

    def action_cycle_completion_backward(self) -> None:
        if self._vim.enabled and not self._completion_visible:
            self._cycle_vim_pane()
            return
        self._cycle_completion(forward=False)

    def action_accept_completion_or_newline(self) -> None:
        if self._completion_visible:
            self._accept_completion()
            return
        self.query_one("#input", TextArea).insert("\n")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        del event
        if self._completion_visible:
            self._refresh_completion_menu()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        del event
        if self._completion_visible:
            self._refresh_completion_menu()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self._accept_completion()

    def _submit_editor_text(self) -> None:
        editor = self.query_one("#input", TextArea)
        text = editor.text.strip()
        if not text:
            return
        editor.load_text("")
        self._hide_completion_menu()
        if text.lower() in {"exit", "quit", "/exit", "/quit"}:
            self.exit()
            return
        self._submit(text)

    @property
    def _completion_visible(self) -> bool:
        return bool(self.query_one("#completion-menu", OptionList).display)

    def _cycle_completion(self, *, forward: bool) -> None:
        menu = self.query_one("#completion-menu", OptionList)
        if not self._completion_visible:
            self._refresh_completion_menu(force=True)
            return
        if menu.option_count == 0:
            return
        highlighted = menu.highlighted
        if highlighted is None:
            menu.highlighted = 0
            return
        delta = 1 if forward else -1
        menu.highlighted = (highlighted + delta) % menu.option_count

    def _accept_completion(self) -> None:
        menu = self.query_one("#completion-menu", OptionList)
        highlighted = menu.highlighted
        if highlighted is None or menu.option_count == 0:
            return
        option = menu.get_option_at_index(highlighted)
        self._replace_current_completion_context(str(option.prompt))
        self._hide_completion_menu()
        self.query_one("#input", TextArea).focus()

    def _refresh_completion_menu(self, *, force: bool = False) -> None:
        menu = self.query_one("#completion-menu", OptionList)
        line = self._current_line_before_cursor()
        completions = self._completion_texts(line, force=force)
        if not completions:
            self._hide_completion_menu()
            return
        menu.clear_options()
        menu.add_options(completions)
        menu.highlighted = 0
        menu.display = True

    def _completion_texts(self, line_before_cursor: str, *, force: bool) -> list[str]:
        if not force and not _should_show_completions(line_before_cursor):
            return []
        special = _special_resource_completion(line_before_cursor)
        if special == "skills":
            return list(_skill_names(self._app_state))
        if special == "workflows":
            return list(_workflow_names(self._app_state))
        if special == "pipelines":
            return list(self._app_state.pipeline_runner.list_pipelines())
        return [
            completion.text
            for completion in completions_for_text(self._app_state, line_before_cursor)
        ]

    def _hide_completion_menu(self) -> None:
        menu = self.query_one("#completion-menu", OptionList)
        menu.clear_options()
        menu.display = False

    def _current_line_before_cursor(self) -> str:
        editor = self.query_one("#input", TextArea)
        row, column = editor.cursor_location
        lines = editor.text.splitlines() or [""]
        if row >= len(lines):
            return ""
        return lines[row][:column]

    def _replace_current_completion_context(self, completion: str) -> None:
        editor = self.query_one("#input", TextArea)
        row, column = editor.cursor_location
        lines = editor.text.splitlines() or [""]
        while row >= len(lines):
            lines.append("")
        line = lines[row]
        before = line[:column]
        after = line[column:]
        replacement_line, cursor_column = _apply_completion(before, after, completion)
        lines[row] = replacement_line
        editor.load_text("\n".join(lines))
        editor.move_cursor((row, cursor_column))

    def _submit(self, text: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(f"[cyan]You:[/cyan] {text}", classes="user-msg", markup=True))
        self._chat_messages.append(f"You: {text}")
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
                was_at_end = _is_chat_at_scroll_end(chat)
                if state["widget"] is None:
                    self._stop_spinner()
                    w = Static(current, markup=False)
                    state["widget"] = w
                    chat.mount(Static("[green]Agent:[/green]", classes="agent-label", markup=True))
                    chat.mount(w)
                else:
                    state["widget"].update(current)
                _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

            self.call_from_thread(_update)

        def on_text_chunk(chunk: str) -> None:
            buffer.append(chunk)
            now = time.monotonic()
            with _flush_lock:
                if now - _last_flush[0] >= flush_interval:
                    _last_flush[0] = now
                    _flush_to_ui()

        tool_lines: list[str] = []
        max_tool_lines = 5  # Show last N tool iterations, collapse older ones
        tool_state: dict[str, Static | None] = {"widget": None}

        def on_tool_event(message: str) -> None:
            tool_lines.append(message)
            display_lines = list(tool_lines)
            if len(display_lines) > max_tool_lines:
                older = len(display_lines) - max_tool_lines
                summary = f"  ... ({older} earlier tool calls) ..."
                display_lines = [summary, *display_lines[-max_tool_lines:]]
            combined = "\n".join(f"  ⚙ {line}" for line in display_lines)

            def _update_tool() -> None:
                was_at_end = _is_chat_at_scroll_end(chat)
                if tool_state["widget"] is None:
                    w = Static(combined, classes="tool-line", markup=False)
                    tool_state["widget"] = w
                    chat.mount(w)
                else:
                    tool_state["widget"].update(combined)
                _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

            self.call_from_thread(_update_tool)

        self._app_state.streaming.on_text = on_text_chunk
        self._app_state.streaming.on_tool_event = on_tool_event
        self._app_state.streaming.on_finish = lambda _: None

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, handle_repl_input, self._app_state, text)
        except Exception as exc:
            logger.exception("ChatApp worker raised", extra={"text": text})
            self._stop_spinner()
            was_at_end = _is_chat_at_scroll_end(chat)
            await chat.mount(Static(f"[red]Error: {exc}[/red]", markup=True))
            _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

        # Flush any tokens buffered in the last throttle window
        if buffer and state["widget"] is not None:
            state["widget"].update("".join(buffer))

        # Replace live streaming Static with rendered Markdown
        response = "".join(buffer)
        was_at_end = _is_chat_at_scroll_end(chat)
        if state["widget"] is not None:
            await state["widget"].remove()
        if response:
            if state["widget"] is None:
                # no streaming happened — add the label now
                label = Static("[green]Agent:[/green]", classes="agent-label", markup=True)
                await chat.mount(label)
            if _should_render_markdown(response):
                linkified = _linkify_file_refs(response, str(self._app_state.config.project_root))
                await chat.mount(Markdown(linkified, open_links=False))
            else:
                await chat.mount(Static(response, markup=False))
            self._chat_messages.append(f"Agent: {response}")
        self._stop_spinner()
        _scroll_chat_end_if_following(chat, was_at_end=was_at_end)
        self._app_state.streaming.reset_callbacks()
        self._update_header()

    def _tui_print_markdown(self, text: str) -> None:
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            was_at_end = _is_chat_at_scroll_end(chat)
            linkified = _linkify_file_refs(text, str(self._app_state.config.project_root))
            chat.mount(Markdown(linkified, open_links=False))
            _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

        self.call_from_thread(_mount)

    def _tui_print_error(self, text: str) -> None:
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            was_at_end = _is_chat_at_scroll_end(chat)
            chat.mount(Static(f"[red]{text}[/red]", markup=True))
            _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

        self.call_from_thread(_mount)

    def _tui_print_text(self, text: str, markup: bool = True) -> None:  # noqa: FBT001, FBT002
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            was_at_end = _is_chat_at_scroll_end(chat)
            chat.mount(Static(text, markup=markup))
            _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

        self.call_from_thread(_mount)
