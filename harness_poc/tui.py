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
from textual.widgets import Markdown, OptionList, Static, TextArea

from harness_poc.console import clear_tui_handlers, set_tui_handlers
from harness_poc.repl_completion import completions_for_text

if TYPE_CHECKING:
    from textual.timer import Timer

    from harness_poc.app_factory import AppState

logger = logging.getLogger(__name__)

_TOKEN_MILLION = 1_000_000
_TOKEN_THOUSAND = 1_000

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


class ChatApp(App[None]):
    BINDINGS: ClassVar[list] = [
        Binding("super+c", "copy_smart", "Copy", priority=True, show=False),
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
        height: 10;
    }
    #spinner {
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

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield VerticalScroll(id="chat")
        with Vertical(id="footer"):
            yield Static("", id="spinner")
            yield TextArea(
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
        self._update_header()
        self.query_one(TextArea).focus()

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
                self.query_one("#input", TextArea).action_copy()

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
        self._submit_editor_text()

    def action_cycle_completion_forward(self) -> None:
        self._cycle_completion(forward=True)

    def action_cycle_completion_backward(self) -> None:
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

        tool_lines: list[str] = []
        MAX_TOOL_LINES = 5  # Show last N tool iterations, collapse older ones
        tool_state: dict[str, Static | None] = {"widget": None}

        def on_tool_event(message: str) -> None:
            tool_lines.append(message)
            display_lines = list(tool_lines)
            if len(display_lines) > MAX_TOOL_LINES:
                older = len(display_lines) - MAX_TOOL_LINES
                summary = f"  ... ({older} earlier tool calls) ..."
                display_lines = [summary] + display_lines[-MAX_TOOL_LINES:]
            combined = "\n".join(f"  ⚙ {line}" for line in display_lines)

            def _update_tool() -> None:
                if tool_state["widget"] is None:
                    w = Static(combined, classes="tool-line", markup=False)
                    tool_state["widget"] = w
                    chat.mount(w)
                else:
                    tool_state["widget"].update(combined)
                chat.scroll_end(animate=False)

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
            await chat.mount(Static(f"[red]Error: {exc}[/red]", markup=True))
            chat.scroll_end(animate=False)

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
            if _should_render_markdown(response):
                linkified = _linkify_file_refs(response, str(self._app_state.config.project_root))
                await chat.mount(Markdown(linkified, open_links=False))
            else:
                await chat.mount(Static(response, markup=False))
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
