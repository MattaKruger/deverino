from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from textual.app import App, Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static, TextArea

from harness_poc.console import clear_tui_handlers, set_tui_handlers
from harness_poc.core.config import LLMConfig
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
    from textual.widget import Widget

    from harness_poc.app_factory import AppState

logger = logging.getLogger(__name__)

_TOKEN_MILLION = 1_000_000
_TOKEN_THOUSAND = 1_000

_SCROLL_END_EPSILON = 1.0
_HISTORY_MAX = 200
_QUEUE_MAX = 5
_STREAM_FAST = 2000
_STREAM_MED = 8000
_STREAM_SLOW = 16000


@dataclass
class ActivityState:
    """Live agent activity shown in the status bar."""

    phase: Literal["idle", "streaming", "tool", "thinking", "blocked"] = "idle"
    detail: str = ""
    token_count: int = 0

    @property
    def label(self) -> str:
        if self.phase == "idle":
            return ""
        base = f"\u25cf {self.phase}"
        if self.detail:
            base += f": {self.detail}"
        if self.token_count:
            base += f" \u00b7 {_format_tokens(self.token_count)}"
        return base


class ToolPanel(Static):
    """Collapsible tool-call event panel mounted in the chat area.

    Displays the last N tool events with status icons. When the agent
    response finishes, collapses to a one-line summary. When the next
    user message is submitted, the panel is removed.
    """

    MAX_VISIBLE = 5

    def __init__(self) -> None:
        super().__init__("", classes="tool-panel")
        self._events: list[tuple[str, str]] = []  # (message, status)

    @property
    def has_events(self) -> bool:
        return bool(self._events)

    def add(self, message: str, status: str = "running") -> None:
        self._events.append((message, status))
        self._refresh_display()

    def finish(self) -> str:
        """Collapse to summary line. Returns the summary text."""
        if not self._events:
            return ""
        tools = [msg for msg, _ in self._events]
        unique: list[str] = []
        for t in tools:
            if unique and unique[-1] == t:
                continue
            unique.append(t)
        max_summary_tools = 10
        summary = "\u2713 " + ", ".join(unique[:max_summary_tools])
        if len(unique) > max_summary_tools:
            summary += f" +{len(unique) - max_summary_tools} more"
        self.add_class("finished")
        return summary

    def dismiss(self) -> None:
        self._events.clear()
        self.update("")
        self.remove_class("finished")

    def _refresh_display(self) -> None:
        lines: list[str] = []
        for msg, status in self._events[-self.MAX_VISIBLE :]:
            icon = {"running": "\u2026", "success": "\u2713", "error": "\u2717"}.get(
                status, "\u2026"
            )
            lines.append(f"  {icon} {msg}")
        if len(self._events) > self.MAX_VISIBLE:
            lines.insert(0, f"  ... ({len(self._events) - self.MAX_VISIBLE} earlier)")
        self.update("\n".join(lines) if lines else "")


def _format_tokens(count: int) -> str:
    if count >= _TOKEN_MILLION:
        return f"{count / _TOKEN_MILLION:.1f}M"
    if count >= _TOKEN_THOUSAND:
        return f"{count / _TOKEN_THOUSAND:.1f}k"
    return str(count)


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
        # Phase 1: exit history navigation on non-history key presses
        if event.key not in ("up", "down") and app._history_index != -1:  # noqa: SLF001
            app._history_index = -1  # noqa: SLF001
            app._draft_text = ""  # noqa: SLF001
        # Phase 1: input history — up/down at boundary takes priority
        if event.key in ("up", "down") and not app._completion_visible:  # noqa: SLF001
            editor = cast("TextArea", self)
            row, col = editor.cursor_location
            lines = editor.text.splitlines() or [""]
            at_boundary = (event.key == "up" and row == 0 and col == 0) or (
                event.key == "down"
                and row == len(lines) - 1
                and (col == len(lines[-1]) if lines[-1] else True)
            )
            if at_boundary and app._navigate_history(event.key):  # noqa: SLF001
                event.stop()
                event.prevent_default()
                return
        # Vim handling (existing)
        if app.handle_vim_text_area_key(event):
            event.stop()
            event.prevent_default()


_HELP_TEXT = """\
[b]Global[/b]
  Ctrl+D        Submit
  Alt+Enter     Queue/Submit
  Super+Enter   Submit
  Super+C       Copy selection
  Super+Y       Copy last response
  Alt+Up        Restore queued
  Escape        Abort running agent
  ?             This help panel
  F2            Toggle Vim mode

[b]Completion Menu[/b]
  Tab           Next completion
  Shift+Tab     Previous completion
  Enter         Accept completion
"""

_HELP_TEXT_VIM = """\
[b]Global[/b]
  Ctrl+D        Submit
  Alt+Enter     Queue/Submit
  Super+Enter   Submit
  Super+C       Copy selection
  Super+Y       Copy last response
  Alt+Up        Restore queued
  Escape        Abort / dismiss
  ?             This help panel
  F2            Toggle Vim mode

[b]Vim Input[/b]
  i             Insert mode
  Escape        Normal mode
  h/j/k/l       Move cursor
  w / b         Word forward / back
  0 / $         Line start / end
  v             Visual mode
  y / d / p     Yank / Delete / Paste
  u             Undo
  /             Search
  n / N         Next / Prev match
  dd            Delete line

[b]Vim Chat[/b]
  j / k         Scroll down / up
  Ctrl+D / U    Page down / up
  gg / G        Top / bottom
  y             Copy selection
  i             Focus input
  ?             Search

[b]Completion Menu[/b]
  Tab           Next completion
  Shift+Tab     Previous completion
  Enter         Accept completion
"""


class ChatApp(App[None]):
    BINDINGS: ClassVar[list] = [
        Binding("super+c", "copy_smart", "Copy", priority=True, show=False),
        Binding("super+y", "copy_last_response", "Copy last response", priority=True, show=False),
        Binding("ctrl+d", "submit_editor", "Submit", priority=True, show=False),
        Binding("alt+enter", "queue_or_submit", "Queue/Submit", priority=True, show=False),
        Binding("super+enter", "submit_editor", "Submit", priority=True, show=False),
        Binding("alt+up", "restore_queued", "Restore queued", priority=True, show=False),
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
        # Phase 1: Escape abort (non-priority — Vim handler fires first)
        Binding("escape", "escape", "Abort/Dismiss", priority=False, show=False),
        # Phase 1: ? help (priority=True with typing guard in action handler)
        Binding("question_mark", "toggle_help", "Help", priority=True, show=False),
        # Phase 3: model cycling
        Binding("ctrl+l", "model_selector", "Model selector", priority=True, show=False),
        Binding("ctrl+p", "cycle_model_prev", "Previous model", priority=True, show=False),
        Binding("ctrl+shift+p", "cycle_model_next", "Next model", priority=True, show=False),
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
    #status-bar {
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
    .tool-panel {
        border: dashed $surface-lighten-1;
        padding: 0 1;
        margin: 1 0;
        color: $text-muted;
    }
    .tool-panel.finished {
        color: $success;
    }
    #help-panel {
        display: none;
        dock: top;
        height: 100%;
        background: $surface;
        color: $text;
        padding: 1 2;
        overflow-y: auto;
        layer: overlay;
    }
    """

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._activity = ActivityState()
        self._tool_panel: ToolPanel | None = None
        self._materializer_task: asyncio.Task[None] | None = None
        # Phase 1: input history
        self._history: list[str] = []
        self._history_index: int = -1
        self._draft_text: str = ""
        # Phase 1: abort
        self._abort_event = threading.Event()
        self._abort_finalized: bool = False
        # Phase 2: message queue and input decoupling
        self._worker_running: bool = False
        self._queued_messages: list[str] = []
        self._pending_command: str | None = None
        # Phase 3: model cycling
        self._llm_override: LLMConfig | None = None
        self._model_selector_active: bool = False
        self._session_picker_active: bool = False
        self._session_data: list[dict[str, object]] = []
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
        yield Static(id="help-panel")
        yield VerticalScroll(id="chat")
        with Vertical(id="footer"):
            yield Static("", id="status-bar")
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
        llm = self._effective_llm()
        tokens = self._app_state.streaming.session_tokens
        token_part = f" · {_format_tokens(tokens)}" if tokens > 0 else ""
        self.query_one("#header", Static).update(f"{llm.provider} · {llm.model}{token_part}")

    def _effective_llm(self) -> LLMConfig:
        """Return the effective LLM config (override if set, else config)."""
        if self._llm_override is not None:
            return self._llm_override
        return self._app_state.config.llm

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

    def _mount_chat(self, widget: Widget, *, scroll: bool = True) -> None:
        """Mount a widget into the chat area from any thread, preserving scroll position."""

        def _do() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            was_at_end = _is_chat_at_scroll_end(chat) if scroll else False
            chat.mount(widget)
            if scroll:
                _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

        self.call_from_thread(_do)

    def _set_activity(
        self, phase: Literal["idle", "streaming", "tool", "thinking", "blocked"], detail: str = ""
    ) -> None:
        self._activity.phase = phase
        self._activity.detail = detail
        self._activity.token_count = self._app_state.streaming.session_tokens
        self._render_status_bar()

    def _render_status_bar(self) -> None:
        parts: list[str] = []
        # Vim mode
        parts.append(format_status(self._vim))
        # Active mode
        parts.append(str(self._app_state.active_mode))
        # Activity
        if self._activity.phase != "idle":
            parts.append(self._activity.label)
        # Phase 2: queue depth
        if self._queued_messages:
            parts.append(f"{len(self._queued_messages)} queued")
        self.query_one("#status-bar", Static).update(" │ ".join(parts))

    def _update_vim_status(self) -> None:
        self._render_status_bar()

    def action_submit_editor(self) -> None:  # noqa: PLR0911
        # Phase 2: command detection runs first (even during streaming)
        editor = self.query_one("#input", TextArea)
        text = editor.text.strip()
        if text == "/resume" or text.startswith("/resume "):
            self._abort_and_defer_command("resume")
            return
        if text == "/compact" or text.startswith("/compact "):
            self._abort_and_defer_command("compact")
            return
        if text == "/model" or text.startswith("/model "):
            self._handle_model_command(text)
            return
        # exit/quit always allowed, even while worker is running
        if text.lower() in {"exit", "quit", "/exit", "/quit"}:
            editor.load_text("")
            self._auto_consolidate_check()
            self.exit()
            return
        # Phase 2: queue gating — if worker running, queue bypasses Vim
        if self._worker_running:
            self._queue_current_text()
            return
        # Vim gating (only when worker is idle):
        if (
            self._vim.enabled
            and self._vim.pane == VimPane.INPUT
            and self._vim.mode == VimMode.NORMAL
        ):
            return
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

    # --- Phase 1: Input History ---

    def _navigate_history(self, direction: str) -> bool:
        """Navigate input history. Returns True if navigation occurred."""
        if not self._history:
            return False
        editor = self.query_one("#input", TextArea)
        if direction == "up":
            if self._history_index == -1:
                self._draft_text = editor.text
                self._history_index = 0
            elif self._history_index < len(self._history) - 1:
                self._history_index += 1
            else:
                return False
        elif direction == "down":
            if self._history_index == -1:
                return False  # not navigating — no-op
            if self._history_index == 0:
                editor.load_text(self._draft_text)
                self._draft_text = ""
                self._history_index = -1
                # Move cursor to end
                lines = editor.text.splitlines() or [""]
                editor.move_cursor((len(lines) - 1, len(lines[-1]) if lines[-1] else 0))
                return True
            self._history_index -= 1
        else:
            return False
        editor.load_text(self._history[self._history_index])
        lines = editor.text.splitlines() or [""]
        editor.move_cursor((len(lines) - 1, len(lines[-1]) if lines[-1] else 0))
        return True

    # --- Phase 1: Escape Abort ---

    def action_escape(self) -> None:
        """Escape: dismiss help, abort worker, or no-op (Vim handled separately)."""
        help_panel = self.query_one("#help-panel", Static)
        if help_panel.display:
            help_panel.display = False
            return
        if self._activity.phase != "idle":
            self._abort_event.set()

    # --- Phase 1: Help Panel ---

    def action_toggle_help(self) -> None:
        """Toggle help panel, or insert ? if user is typing."""
        editor = self.query_one("#input", TextArea)
        if editor.has_focus:
            if not self._vim.enabled:
                editor.insert("?")
                return
            if self._vim.pane == VimPane.INPUT and self._vim.mode == VimMode.INSERT:
                editor.insert("?")
                return
        help_panel = self.query_one("#help-panel", Static)
        if help_panel.display:
            help_panel.display = False
        else:
            self._dismiss_all_overlays()
            help_text = _HELP_TEXT_VIM if self._vim.enabled else _HELP_TEXT
            help_panel.update(help_text)
            help_panel.display = True

    def _dismiss_all_overlays(self) -> None:
        """Hide all overlay widgets (help, session picker, model selector, completion)."""
        for widget_id in ("#help-panel", "#completion-menu", "#session-picker", "#model-selector"):
            try:
                w = self.query_one(widget_id)
            except Exception:  # noqa: S112 — widget may not exist yet (future phases)
                continue
            if hasattr(w, "display"):
                w.display = False

    # --- Phase 2: Message Queue ---

    def action_queue_or_submit(self) -> None:
        """Alt+Enter: submit if idle, queue if worker running."""
        if self._worker_running:
            self._queue_current_text()
        else:
            self.action_submit_editor()

    def action_restore_queued(self) -> None:
        """Alt+Up: restore last queued message to editor."""
        if not self._queued_messages:
            return
        text = self._queued_messages.pop()
        editor = self.query_one("#input", TextArea)
        editor.load_text(text)
        lines = editor.text.splitlines() or [""]
        editor.move_cursor((len(lines) - 1, len(lines[-1]) if lines[-1] else 0))
        self.notify("Restored from queue")

    def _queue_current_text(self) -> None:
        """Enqueue editor text. No-op if empty or queue full."""
        editor = self.query_one("#input", TextArea)
        text = editor.text.strip()
        if not text:
            return
        if len(self._queued_messages) >= _QUEUE_MAX:
            self.notify("Queue full (max 5)", severity="warning")
            return
        # Add to history before clearing (fix: queued messages are part of history)
        self._history.insert(0, editor.text.rstrip())
        if len(self._history) > _HISTORY_MAX:
            self._history.pop()
        self._history_index = -1
        self._draft_text = ""
        self._queued_messages.append(text)
        editor.load_text("")
        self._hide_completion_menu()
        self.notify("Queued")

    def _dequeue_next(self) -> None:
        """Submit the next queued message. Called via call_later from finalize/error paths."""
        if self._queued_messages:
            next_text = self._queued_messages.pop(0)
            self.query_one("#input", TextArea).load_text("")
            self._hide_completion_menu()
            self._dismiss_all_overlays()
            self._submit(next_text)

    def _auto_consolidate_check(self) -> None:
        """Check for unconsolidated session state before exit.

        If the session has pending state changes (dirty flag), print a
        reminder suggesting the user run /state consolidate.
        """
        db = self._app_state.database
        if db is None:
            return
        try:
            dirty = db.is_session_state_dirty(self._app_state.session_id)
        except Exception:
            return
        if not dirty:
            return
        self._mount_chat(
            Static(
                "[dim]Session state has unconsolidated changes. "
                "Run [bold]/state consolidate[/bold] to review and promote "
                "them to project state.[/dim]",
                markup=True,
            )
        )

    def _abort_and_defer_command(self, command: str) -> None:
        """Abort current worker and defer command to after finalization."""
        editor = self.query_one("#input", TextArea)
        if self._worker_running:
            self._abort_event.set()
            self._pending_command = command
            editor.load_text("")
        elif command == "resume":
            self.query_one("#input", TextArea).load_text("")
            self._handle_resume_command()
        elif command == "compact":
            self.query_one("#input", TextArea).load_text("")
            self._handle_compact_command()

    # --- Phase 3: Model Cycling ---

    def _handle_model_command(self, text: str) -> None:
        """Handle /model [provider/model] command."""
        editor = self.query_one("#input", TextArea)
        editor.load_text("")
        arg = text.removeprefix("/model").strip()
        if not arg:
            # Open selector (same as Ctrl+L)
            self.action_model_selector()
            return
        # Direct switch: /model provider/model
        self._set_model_override(arg)

    def action_model_selector(self) -> None:
        """Ctrl+L: open model selector."""
        models = self._app_state.config.tui.models or []
        effective = self._effective_llm()
        current_key = f"{effective.provider}/{effective.model}"
        # Build list: mark current with ●
        options: list[str] = []
        if not models:
            options = [f"● {current_key}"]
        else:
            for m in models:
                prefix = "● " if m == current_key else "  "
                options.append(f"{prefix}{m}")
        # Use completion menu as ad-hoc selector
        menu = self.query_one("#completion-menu", OptionList)
        menu.clear_options()
        menu.add_options(options)
        menu.highlighted = 0
        menu.display = True
        self._model_selector_active = True

    def action_cycle_model_prev(self) -> None:
        """Ctrl+P: cycle to previous model."""
        self._cycle_model(-1)

    def action_cycle_model_next(self) -> None:
        """Ctrl+Shift+P: cycle to next model."""
        self._cycle_model(1)

    def _cycle_model(self, direction: int) -> None:
        models = self._app_state.config.tui.models or []
        if len(models) < 2:  # noqa: PLR2004
            return
        effective = self._effective_llm()
        current_key = f"{effective.provider}/{effective.model}"
        try:
            idx = models.index(current_key)
        except ValueError:
            idx = 0
        new_idx = (idx + direction) % len(models)
        self._set_model_override(models[new_idx])

    def _set_model_override(self, model_spec: str) -> None:
        """Parse provider/model and set _llm_override."""
        parts = model_spec.split("/", 1)
        if len(parts) != 2:  # noqa: PLR2004
            self.notify(f"Invalid model: {model_spec}. Use provider/model", severity="warning")
            return
        provider, model = parts
        current = self._app_state.config.llm
        self._llm_override = LLMConfig(
            provider=provider,
            model=model,
            base_url=current.base_url,  # inherit custom endpoint
        )
        self._update_header()
        label = f"{provider}/{model}"
        self.notify(f"Model: {label}")

    # --- Phase 3: /resume Session Picker ---

    def _handle_resume_command(self) -> None:
        """Load session via picker or direct session ID."""
        db = self._app_state.database
        if db is None:
            self._mount_chat(Static("[red]No database connection available.[/red]", markup=True))
            return
        try:
            sessions = db.list_recent_sessions(limit=20)
        except Exception as exc:
            self._mount_chat(Static(f"[red]Error querying sessions: {exc}[/red]", markup=True))
            return
        if not sessions:
            self._mount_chat(Static("No recent sessions found.", markup=True))
            return
        self._open_session_picker(sessions)

    def _open_session_picker(self, sessions: list[dict[str, Any]]) -> None:
        """Mount session picker with the given session data."""
        self._dismiss_all_overlays()
        menu = self.query_one("#completion-menu", OptionList)
        self._session_data = sessions
        options = [
            f"[{s['message_count']} msgs] {s['objective']} — {s['created_at'][:16]}"
            for s in sessions
        ]
        menu.clear_options()
        menu.add_options(options)
        menu.highlighted = 0
        menu.display = True
        self._session_picker_active = True

    def _select_session(self) -> None:
        """Load the highlighted session from the picker."""
        menu = self.query_one("#completion-menu", OptionList)
        menu.display = False
        self._session_picker_active = False
        highlighted = menu.highlighted
        if highlighted is None or not self._session_data or highlighted >= len(self._session_data):
            return
        session = self._session_data[highlighted]
        sid = session["session_id"]
        try:
            messages = self._app_state.database.load_session_messages(sid)
        except Exception as exc:
            self._mount_chat(Static(f"[red]Error loading session: {exc}[/red]", markup=True))
            return
        # Replay messages into chat
        chat = self.query_one("#chat", VerticalScroll)
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                chat.mount(Static(f"[cyan]You:[/cyan] {content}", classes="user-msg", markup=True))
            elif role == "assistant":
                if _should_render_markdown(content):
                    linkified = _linkify_file_refs(
                        content, str(self._app_state.config.project_root)
                    )
                    chat.mount(Markdown(linkified, open_links=False))
                else:
                    chat.mount(Static(content, markup=False))
        self._mount_chat(Static(f"--- Resumed session {sid[:8]} ---", markup=True))
        self._app_state.identity.session_id = sid  # type: ignore[union-attr,misc]
        self._llm_override = None  # revert to config default
        self._update_header()

    # --- Phase 3: /compact ---

    async def _do_compact(self, text: str, _chat: VerticalScroll) -> None:
        """Compact chat history with optional focus instructions."""
        instructions = text.removeprefix("/compact").strip() or None
        messages = self._app_state.messages
        if not messages or len(messages) <= 1:
            self._mount_chat(Static("Nothing to compact.", markup=True))
            self._set_activity("idle")
            self._worker_running = False
            return
        system_prompt = (
            "You are a context-compaction assistant. Summarize the following "
            "conversation history into a structured compaction summary. "
            "Follow this format exactly:\n\n"
            "## Compaction Summary\n\n"
            "### Goal\n"
            "[What the user is trying to accomplish — infer from the conversation]\n\n"
            "### Progress\n"
            "[What has been done so far]\n\n"
            "### Key Decisions\n"
            "[Decisions made and their rationale]\n\n"
            "### Next Steps\n"
            "[What remains to be done]\n\n"
            "### Critical Context\n"
            "[Facts, constraints, or state that must not be lost]\n\n"
            "Be concise but preserve all critical details. The summary will replace "
            "the conversation history — nothing omitted here will be recoverable."
        )
        if instructions:
            system_prompt += f"\n\nFocus especially on: {instructions}"
        # Build full prompt from history
        history_text = "\n\n".join(
            f"[{m.get('role', '?')}]: {m.get('content', '')}" for m in messages
        )
        full_prompt = f"{system_prompt}\n\n--- Conversation history ---\n\n{history_text}"
        try:
            result = self._app_state.runtime.pydantic_runtime.run_text(
                full_prompt,
                message_history=None,
            )
            summary = result.content if hasattr(result, "content") else str(result)
            self._app_state.messages = [{"role": "system", "content": summary}]
            self._mount_chat(Static("--- Context compacted ---", markup=True))
        except Exception as exc:
            logger.exception("/compact failed")
            self._mount_chat(Static(f"[red]Compaction failed: {exc}[/red]", markup=True))
        self._set_activity("idle")
        self._worker_running = False
        if self._queued_messages:
            self.call_later(self._dequeue_next)

    # --- Phase 3: /compact forwarded from action_submit_editor ---

    def _handle_compact_command(self) -> None:
        """Submit a /compact command as a special chat_worker run."""
        self._set_activity("streaming")
        self._worker_running = True
        chat = self.query_one("#chat", VerticalScroll)
        self.run_worker(self._do_compact("/compact", chat))

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
        if (
            self._vim.enabled
            and self._vim.pane == VimPane.INPUT
            and self._vim.mode == VimMode.NORMAL
        ):
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
        # Phase 3: model selector active? handle that instead
        if self._model_selector_active:
            self._model_selector_active = False
            menu = self.query_one("#completion-menu", OptionList)
            menu.display = False
            selected = event.option
            if selected is not None:
                label = str(selected.prompt).lstrip("● ")
                self._set_model_override(label)
            return
        # Phase 3: session picker active?
        if self._session_picker_active:
            self._select_session()
            return
        self._accept_completion()

    def _submit_editor_text(self) -> None:
        editor = self.query_one("#input", TextArea)
        text = editor.text.strip()
        if not text:
            return
        # Phase 1: add to input history
        self._history.insert(0, editor.text.rstrip())
        if len(self._history) > _HISTORY_MAX:
            self._history.pop()
        self._history_index = -1
        self._draft_text = ""
        editor.load_text("")
        self._hide_completion_menu()
        if text.lower() in {"exit", "quit", "/exit", "/quit"}:
            self._auto_consolidate_check()
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
        self._abort_event.clear()  # Phase 1: clear stale abort before new worker
        self._abort_finalized = False  # Phase 1: reset guard
        self._worker_running = True  # Phase 2: mark worker active
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(f"[cyan]You:[/cyan] {text}", classes="user-msg", markup=True))
        self._chat_messages.append(f"You: {text}")
        self._set_activity("streaming")
        if self._tool_panel is not None:
            self._tool_panel.dismiss()
        self.run_worker(self._chat_worker(text, chat))

    async def _chat_worker(self, text: str, chat: VerticalScroll) -> None:  # noqa: PLR0915
        from harness_poc.repl import handle_repl_input  # noqa: PLC0415

        buffer: list[str] = []
        state: dict[str, Markdown | Static | None] = {"widget": None}

        _last_flush: list[float] = [0.0]
        _flush_lock = threading.Lock()
        flush_interval = 0.033  # ~30 fps

        # Phase 3: progressive debounce helper
        def _progressive_interval(current_len: int) -> float:
            if current_len < _STREAM_FAST:
                return 0.033
            if current_len < _STREAM_MED:
                return 0.100
            if current_len < _STREAM_SLOW:
                return 0.250
            return float("inf")  # Static fallback

        # Tool panel — created lazily on first tool event
        tool_panel = ToolPanel()
        self._tool_panel = tool_panel

        def _flush_to_ui() -> None:
            current = "".join(buffer)
            current_len = len(current)
            # Phase 3: progressive throttling — adjust interval after flush
            nonlocal flush_interval
            flush_interval = _progressive_interval(current_len)

            def _update() -> None:
                was_at_end = _is_chat_at_scroll_end(chat)
                if current_len > _STREAM_SLOW:
                    # Static fallback for very large responses
                    if state["widget"] is None:
                        w = Static(current, markup=False)
                        state["widget"] = w
                        chat.mount(
                            Static("[green]Agent:[/green]", classes="agent-label", markup=True)
                        )
                        chat.mount(w)
                    elif isinstance(state["widget"], Static):
                        state["widget"].update(current)
                    else:
                        # Replace Markdown with Static
                        state["widget"].remove()
                        w = Static(current, markup=False)
                        state["widget"] = w
                        chat.mount(w)
                elif state["widget"] is None:
                    w = Markdown(current, open_links=False)
                    state["widget"] = w
                    chat.mount(Static("[green]Agent:[/green]", classes="agent-label", markup=True))
                    chat.mount(w)
                elif isinstance(state["widget"], Markdown):
                    state["widget"].update(current)
                else:
                    # Replace Static with Markdown for streaming
                    state["widget"].remove()
                    w = Markdown(current, open_links=False)
                    state["widget"] = w
                    chat.mount(w)
                _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

            self.call_from_thread(_update)

        def on_text_chunk(chunk: str) -> None:
            # Phase 1: cooperative abort check
            if self._abort_event.is_set():
                if not self._abort_finalized:
                    self._abort_finalized = True
                    buffer.append("\n[interrupted]")
                    _flush_to_ui()
                    _finalize_response("")
                return
            buffer.append(chunk)
            now = time.monotonic()
            with _flush_lock:
                if now - _last_flush[0] >= flush_interval:
                    _last_flush[0] = now
                    _flush_to_ui()

        def on_tool_event(message: str) -> None:
            tool_panel.add(message, status="running")
            self._set_activity(
                "tool", detail=message.split(":", maxsplit=1)[0] if ":" in message else message
            )

            def _mount_tool() -> None:
                was_at_end = _is_chat_at_scroll_end(chat)
                if tool_panel not in chat.children:
                    chat.mount(tool_panel)
                _scroll_chat_end_if_following(chat, was_at_end=was_at_end)

            self.call_from_thread(_mount_tool)

        def _finalize_response(_final_content: str) -> None:
            """Called by on_finish — flush buffer, render Markdown, collapse tool panel."""

            def _do() -> None:  # noqa: PLR0912
                was_at_end = _is_chat_at_scroll_end(chat)
                # Collapse tool panel
                if tool_panel.has_events:
                    tool_panel.finish()
                # Flush remaining buffer, or use final content if buffer empty
                if state["widget"] is not None and isinstance(state["widget"], (Markdown, Static)):
                    final_text = "".join(buffer) or _final_content
                    if final_text:
                        state["widget"].update(final_text)
                response = "".join(buffer)
                # If no streaming chunks arrived, use the final content from on_finish
                if not response and _final_content:
                    response = _final_content
                if response:
                    # Phase 3: only replace widget if final type differs from streaming type
                    needs_markdown = _should_render_markdown(response)
                    current_is_markdown = isinstance(state["widget"], Markdown)
                    current_is_static = isinstance(state["widget"], Static)
                    if state["widget"] is None:
                        label = Static("[green]Agent:[/green]", classes="agent-label", markup=True)
                        chat.mount(label)
                        if needs_markdown:
                            linkified = _linkify_file_refs(
                                response, str(self._app_state.config.project_root)
                            )
                            chat.mount(Markdown(linkified, open_links=False))
                        else:
                            chat.mount(Static(response, markup=False))
                    elif needs_markdown and not current_is_markdown:
                        state["widget"].remove()
                        linkified = _linkify_file_refs(
                            response, str(self._app_state.config.project_root)
                        )
                        chat.mount(Markdown(linkified, open_links=False))
                    elif not needs_markdown and not current_is_static:
                        state["widget"].remove()
                        chat.mount(Static(response, markup=False))
                    self._chat_messages.append(f"Agent: {response}")
                self._set_activity("idle")
                _scroll_chat_end_if_following(chat, was_at_end=was_at_end)
                self._app_state.streaming.reset_callbacks()
                self._worker_running = False  # Phase 2: worker finished
                self._update_header()
                # Phase 2: auto-dequeue + pending command
                if self._pending_command is not None:
                    cmd = self._pending_command
                    self._pending_command = None
                    # Phase 3 will handle real commands; for now, notify and skip auto-dequeue.
                    # The return is intentional: a pending command is exclusive with queued messages.
                    if cmd == "resume":
                        self._handle_resume_command()
                    elif cmd == "compact":
                        self._handle_compact_command()
                    return
                if self._queued_messages:
                    self.call_later(self._dequeue_next)

            self.call_from_thread(_do)

        # Track whether a streaming on_finish callback fired.  Non-streaming
        # REPL commands (e.g. /debug, /help, /mode) return immediately without
        # ever calling _finalize_response, which would otherwise clear
        # _worker_running and _set_activity('idle').  Without this flag the
        # TUI stays stuck in "worker running" mode after any slash command.
        _streaming_finalized = False

        def _finalize_and_track(content: str) -> None:
            nonlocal _streaming_finalized
            _streaming_finalized = True
            _finalize_response(content)

        self._app_state.streaming.on_text = on_text_chunk
        self._app_state.streaming.on_tool_event = on_tool_event
        self._app_state.streaming.on_finish = _finalize_and_track

        loop = asyncio.get_running_loop()
        try:
            # Phase 3: rebuild runtime if model changed
            effective_llm = self._effective_llm()
            if effective_llm != self._app_state.config.llm:
                from harness_poc.app_factory import _TUI_BLOCKED_SKILLS  # noqa: PLC0415
                from harness_poc.core.runtime.pydantic_runtime import build_runtime  # noqa: PLC0415

                new_runtime = build_runtime(
                    session_id=self._app_state.session_id,
                    database=self._app_state.database,
                    config=self._app_state.config,
                    skill_runner=self._app_state.skill_runner,
                    tool_runner=self._app_state.runtime.tool_runner,
                    system_prompt="\n\n".join(
                        self._app_state.runtime.pydantic_runtime.agent._system_prompts  # noqa: SLF001
                    ),
                    llm=effective_llm,
                    enable_tools=True,
                    blocked_skills=_TUI_BLOCKED_SKILLS,
                    skill_catalog=self._app_state.runtime.skill_catalog,
                )
                self._app_state.runtime.pydantic_runtime = new_runtime
            # Phase 1: executor with abort polling fallback
            task = loop.run_in_executor(None, handle_repl_input, self._app_state, text)
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
                    break  # completed normally
                except TimeoutError:
                    if self._abort_event.is_set():
                        _finalize_and_track("")
                        return
        except Exception as exc:
            logger.exception("ChatApp worker raised", extra={"text": text})
            self._set_activity("idle")
            self._mount_chat(Static(f"[red]Error: {exc}[/red]", markup=True))
            self._worker_running = False  # Phase 2: clear flag on crash
            if self._queued_messages:  # Phase 2: auto-dequeue after error
                self.call_later(self._dequeue_next)
        self._app_state.streaming.reset_callbacks()
        # Non-streaming REPL commands (slash commands, etc.) return without
        # ever triggering on_finish, so _worker_running is never cleared.
        # Clean up the worker state here so the TUI doesn't get stuck.
        if not _streaming_finalized:
            self._set_activity("idle")
            self._worker_running = False
            self._update_header()
            if self._queued_messages:
                self.call_later(self._dequeue_next)

    def _tui_print_markdown(self, text: str) -> None:
        linkified = _linkify_file_refs(text, str(self._app_state.config.project_root))
        self._mount_chat(Markdown(linkified, open_links=False))

    def _tui_print_error(self, text: str) -> None:
        self._mount_chat(Static(f"[red]{text}[/red]", markup=True))

    def _tui_print_text(self, text: str, markup: bool = True) -> None:  # noqa: FBT001, FBT002
        self._mount_chat(Static(text, markup=markup))
