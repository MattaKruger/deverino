---
title: "TUI QoL Improvements — Implementation Spec (Refined, v2)"
date: 2026-06-17
status: impl-spec
kind: spec
parent: specs/20260617-tui-qol-improvements.md
---

# TUI QoL Improvements — Implementation Spec

Refined from `20260617-tui-qol-improvements.md`. This document fills implementation gaps, resolves ambiguities, and provides concrete code-level guidance. Design decisions (§D1–D7) from the parent spec are incorporated; only gaps, inconsistencies, and missing edge cases are addressed here.

---

## Critical Pre-Implementation Issue: Frozen Config and Runtime Model Switching (GAP-1, NEW-BLOCKING-1, NEW-BLOCKING-2)

**Problem:** `LLMConfig` is `frozen=True, slots=True` (config.py L56). `HarnessConfig` is also frozen (L118). Mutating `app_state.config.llm` raises `FrozenInstanceError`. Even if mutation worked, `handle_chat_input` uses `app_state.pydantic_runtime` — a `PydanticAgentRuntime` built at startup with the original `config.llm`. Swapping `config.llm` after construction has zero effect on the already-built agent.

**Resolution: Rebuild the runtime on model change. Do not mutate config.**

The codebase already has the right plumbing: `build_runtime()` (`pydantic_runtime.py` L346-384) accepts an optional `llm: LLMConfig | None` parameter and passes it to `build_primary_agent` (L378). When the model changes, rebuild `app_state.pydantic_runtime` with the new LLM config.

```python
# In ChatApp.__init__:
self._llm_override: LLMConfig | None = None

# Helper — returns the effective LLM config:
def _effective_llm(self) -> LLMConfig:
    return self._llm_override if self._llm_override is not None else self._app_state.config.llm

# On model switch (Ctrl+L select or Ctrl+P cycle):
# Inherit base_url from current config to preserve custom endpoints (NEW-MEDIUM-1 fix)
current = self._app_state.config.llm
self._llm_override = LLMConfig(
    provider="deepseek",
    model="deepseek-v4-flash",
    base_url=current.base_url,  # inherit custom endpoint if set
)

# On /model reset or session resume:
self._llm_override = None  # fall back to config
```

**In `_chat_worker`, rebuild runtime if model changed:**

```python
async def _chat_worker(self, text: str, chat: VerticalScroll) -> None:
    from harness_poc.repl import handle_repl_input
    from harness_poc.pydantic_runtime import build_runtime

    effective_llm = self._effective_llm()
    if effective_llm != self._app_state.config.llm:
        # Model was changed — rebuild the agent runtime with new model
        self._app_state.pydantic_runtime = build_runtime(
            self._app_state, llm=effective_llm
        )

    # ... rest of worker ...
```

This approach:
- Never mutates frozen config (`config.llm` is untouched).
- Uses the existing `build_runtime(llm=...)` infrastructure.
- `handle_repl_input` → `handle_chat_input` reads `app_state.pydantic_runtime` which now has the new model.
- `_update_header` uses `_effective_llm()` directly (no config mutation needed).

**Assumption:** `AppState.pydantic_runtime` is a mutable attribute (not a frozen dataclass field). This is confirmed by the existing code pattern `app_state.streaming.on_text = ...` (tui.py L717-719) which mutates streaming callbacks on AppState at runtime.

**Config schema:** `TuiConfig.models` (G10) stores the available models list; `_llm_override` stores the active selection. The initial model comes from `llm.provider`/`llm.model` in `harness.yaml`.

---

## G1: Escape Abort Mechanism (was: naive future.cancel)

**Problem:** The parent spec proposes wrapping `loop.run_in_executor` in a 100ms polling loop and calling `future.cancel()` on abort. This doesn't work — `Future.cancel()` only prevents a future from *starting*; once `handle_repl_input` is running synchronously in the executor thread, `cancel()` returns `False` and the thread continues.

**Resolution: Cooperative abort via streaming callbacks + executor polling fallback.**

### Primary path: cooperative abort via `on_text_chunk`

`on_text_chunk` fires from the executor thread while the model streams tokens. This is the normal-path abort:

```python
def on_text_chunk(chunk: str) -> None:
    if self._abort_event.is_set():
        # Append abort marker to buffer, then finalize
        buffer.append("\n[interrupted]")
        _flush_to_ui()
        _finalize_response()
        return  # stop processing further chunks
    buffer.append(chunk)
    # ... existing debounce logic ...
```

**Key detail (GAP-2 fix):** The `[interrupted]` suffix is appended to `buffer` BEFORE calling `_finalize_response`. `_finalize_response` reads from the closure's `buffer` (tui.py L698: `response = "".join(buffer)`), so the suffix is included in the rendered output. The `_final_content` parameter is unused in the abort path — this is the correct fix because `_finalize_response` already ignores its parameter in favor of `buffer`.

**Why this works:** `on_text_chunk` is a callback invoked by `handle_repl_input` during LLM streaming. It runs on the executor thread. When it detects abort, it finalizes and stops appending. The remaining executor work (the LLM call continues but its outputs hit the default callbacks — reset after `_finalize_response`) is harmless. The executor thread leaks but terminates when the LLM call finishes.

**Stream cancellation mechanism (GAP-5 fix):** There is no `StreamingContext.cancel()` method. The cooperative abort works because `on_text_chunk` stops processing when `_abort_event` is set. After `_finalize_response` calls `self._app_state.streaming.reset_callbacks()`, subsequent chunks from the leaking executor hit the default callbacks (which print to stdout in CLI mode, or are no-ops in TUI mode since `_default_on_text` does `print(chunk, end="")` — acceptable for PoC). No additional stream-cancellation API is needed.

### Fallback path: executor timeout polling

If the LLM call blocks without emitting chunks (e.g., network hang before first token), the cooperative path never fires. The polling fallback handles this:

```python
# In _chat_worker, replace:
#   await loop.run_in_executor(None, handle_repl_input, self._app_state, text)
# with:
task = loop.run_in_executor(None, handle_repl_input, self._app_state, text)
while True:
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
        break  # completed normally
    except TimeoutError:
        if self._abort_event.is_set():
            _finalize_response()
            return  # leaked executor thread is harmless
```

**Performance note (CODE-2):** The 100ms polling adds 10 TimeoutError raises/catches per second to the event loop. This is acceptable for a proof-of-concept. Textual's frame rendering is not measurably affected at this rate.

### Escape key routing (INC-1 fix)

The `Escape` binding is added to `BINDINGS` with `priority=False`. In Textual, a non-priority binding means the focused widget's key handler fires first. Key routing:

1. **Vim INSERT mode, input focused:** `VimTextArea._on_key` → `handle_vim_text_area_key` → Vim handler consumes `Escape`, switches to NORMAL mode, calls `event.stop()`. **The app-level `action_escape` does NOT fire.** This is correct per R2.3 — Vim's Escape behavior is preserved.

2. **Vim disabled, or Vim NORMAL mode, or chat pane focused:** Vim handler doesn't consume `Escape`. The app-level `action_escape` fires.

3. **Help panel visible:** `action_escape` checks `#help-panel` visibility first. If visible, dismisses help and stops. Does not abort the worker (even if one is running). The user can press Escape again to abort.

4. **No help panel, worker running:** `action_escape` sets `_abort_event` and returns.

5. **No help panel, no worker:** `action_escape` is a no-op.

6. **Tool panel during abort (STILL-UNRESOLVED-1 / EDGE-3):** When abort fires, `_finalize_response` collapses the tool panel (same as normal completion). Any in-progress tool calls are interrupted without completion or error reporting in the panel. This is acceptable — the user explicitly chose to abort.

### Race condition fix (EDGE-2)

`_abort_event` must be cleared BEFORE the worker starts, not inside the worker. Clear it in `_submit`:

```python
def _submit(self, text: str) -> None:
    self._abort_event.clear()  # ← clear here, before worker starts
    chat = self.query_one("#chat", VerticalScroll)
    chat.mount(Static(f"[cyan]You:[/cyan] {text}", classes="user-msg", markup=True))
    self._chat_messages.append(f"You: {text}")
    self._set_activity("streaming")
    if self._tool_panel is not None:
        self._tool_panel.dismiss()
    self.run_worker(self._chat_worker(text, chat))
```

This prevents a stale abort event from the previous worker killing the new one.

---

## G2: Incremental Markdown Performance

**Problem:** Textual's `Markdown.update()` re-parses the full text on every call. At 30fps with 10k+ token responses, this could introduce rendering lag.

**Resolution: Progressive Markdown with length-based throttling.**

| Buffer size | Debounce interval | Effective FPS | Rationale |
|---|---|---|---|
| < 2000 chars | 33ms | ~30fps | Cheap to parse |
| 2000–8000 chars | 100ms | ~10fps | Noticeable but responsive |
| 8000–16000 chars | 250ms | ~4fps | Large responses, accept slower |
| > 16000 chars | N/A | Static fallback | Switch to `Static` widget; render final Markdown on complete |

Implementation: In `_flush_to_ui`, check `len(current)` and dynamically adjust `flush_interval` stored in the `_last_flush` closure.

**Rendering behavior change (CODE-3):** In Phase 3, `_flush_to_ui` always uses `Markdown` for streaming (falling to `Static` above 16k chars). This means even plain-text responses render through the Markdown parser during streaming. The final render still respects `_should_render_markdown` — plain text responses get `Static` after completion. The streaming intermediate may show plain text as Markdown-parsed plain text (functionally identical visually). Acceptable.

**Layout jank (EDGE-7):** When `Markdown.update()` changes content height, the chat scroll position may jump. The existing `_scroll_chat_end_if_following` logic mitigates this but cannot eliminate it entirely. Accept as known limitation for PoC.

---

## G3: `/resume` Picker vs. Completion Menu Coexistence

**Problem:** Both use `OptionList` in the `#footer` area. Need defined coexistence.

**Resolution: Separate `#session-picker` widget.**

Add a second `OptionList(id="session-picker")` to `compose()`, sibling to `#completion-menu`. Both start with `display: none`. Only one overlay (help panel, session picker, model selector, completion menu) is visible at a time (ORDER-4 fix).

- `/resume` command is detected in `_submit_editor_text`. If the text (stripped) equals `/resume` or starts with `/resume `, call `_open_session_picker()` and return (do not submit to worker).
- `_open_session_picker()`:
  1. Dismiss any visible overlay (help panel, model selector, completion menu).
  2. Query `db.list_recent_sessions(limit=20)`.
  3. If query fails or database is unavailable (EDGE-5), show error: `_mount_chat(Static("[red]No database connection available.[/red]", markup=True))` and return.
  4. If zero results (EDGE-4), show message: `_mount_chat(Static("No recent sessions found.", markup=True))` and return.
  5. Populate `#session-picker` with rows: `f"[{msg_count} msgs] {objective} — {created_at[:16]}"`.
  6. Set `display: true`.
- Typing after the picker is open filters the list. Override `on_text_area_changed` to check if `#session-picker` is visible before completion logic (NEW-LOW-2). Filtering method: for each keystroke, re-query the session list with the input text as a filter (case-insensitive substring match on `objective` and `session_id`). Disable completion menu entirely while picker is visible.
- `Enter` selects (via `on_option_list_option_selected`), `Escape` dismisses.
- **During streaming (GAP-7):** If `/resume` is typed while a worker is running, `action_submit_editor` calls `_abort_and_defer_command("resume")` — sets `_abort_event` and defers execution to `_finalize_response._do()` (§G7). The queued-text path is bypassed for explicit commands.

**Database query** (`BlackboardDatabase.list_recent_sessions`):

```sql
SELECT s.session_id, s.global_objective, s.created_at,
       (SELECT COUNT(*) FROM session_messages m WHERE m.session_id = s.session_id) as message_count
FROM sessions s
WHERE s.status = 'active'
ORDER BY s.created_at DESC
LIMIT :limit
```

Returns `list[dict]` with keys: `session_id`, `objective` (from `global_objective`), `created_at`, `message_count`.

**Session load on selection:**
1. Call `db.load_session_messages(session_id)`.
2. Clear current chat messages and `app_state.messages`.
3. Replay each message as a `Static` widget (user: cyan, agent: green for plain text, or Markdown if content has block formatting).
4. Mount `"--- Resumed session {session_id[:8]} ---"` marker.
5. Update `app_state.session_id`.
6. Reset `_llm_override` to `None` (revert to config's default model).

---

## G4: `/compact` LLM Call Details

**Resolved strategy:** Handle in `_chat_worker`, before `handle_repl_input` (strategy #3 from v1). The other proposed strategies (repl.py dispatch, `_submit_editor_text` transformation) are rejected.

**Why:** The worker already has access to the LLM call infrastructure and chat context. Intercepting before `handle_repl_input` is the least invasive change — no new dispatch paths needed.

**Implementation:**

1. **Detection:** At the top of `_chat_worker`, before the executor call:
   ```python
   if text.startswith("/compact"):
       await self._do_compact(text, chat)
       return
   ```

2. **`_do_compact(text, chat)`:**
   - If `app_state.messages` is empty or has ≤ 1 message: mount "Nothing to compact." and return.
   - Extract optional instructions: `instructions = text.removeprefix("/compact").strip()` or `None`.
   - Construct system prompt:
     ```
     You are a context-compaction assistant. Summarize the following conversation history
     into a structured compaction summary. Follow this format exactly:

     ## Compaction Summary

     ### Goal
     [What the user is trying to accomplish — infer from the conversation]

     ### Progress
     [What has been done so far]

     ### Key Decisions
     [Decisions made and their rationale]

     ### Next Steps
     [What remains to be done]

     ### Critical Context
     [Facts, constraints, or state that must not be lost]

     Be concise but preserve all critical details. The summary will replace the
     conversation history — nothing omitted here will be recoverable.
     ```
   - If `instructions` is non-empty, append: `\n\nFocus especially on: {instructions}`.
   - Build messages list: system prompt + existing `app_state.messages`.
   - Call the LLM (using `_effective_llm()`). This reuses the same provider client that normal chat uses.
   - On success: Replace `app_state.messages` with `[{"role": "system", "content": summary_text}]`. Mount `"--- Context compacted ---"` marker in chat.
   - On error: Mount error message, leave messages unchanged.
   - Reset activity to idle.

3. **During streaming (GAP-7):** If `/compact` is typed while a worker is running, `action_submit_editor` calls `_abort_and_defer_command("compact")` — same race-safe deferral as `/resume`.

---

## G5: Model Cycling Keybinding Conflicts

**Problem:** `Ctrl+L` (clear-screen in terminals), `Ctrl+P` (previous-command in readline), `Shift+Ctrl+P` (command palette in editors) may conflict.

**Resolution: Keep the keys. Document conflicts. Add `/model` fallback.**

- `Ctrl+L` for model selector — least common operation, conflict unlikely to cause issues in a TUI context (the TUI owns the terminal).
- `Ctrl+P` / `Shift+Ctrl+P` for quick cycle — convenience bindings. Primary interface is `Ctrl+L` → pick.
- Add `/model` text command: `/model deepseek/deepseek-v4-flash` switches directly without opening the selector. `/model` alone opens the selector (same as `Ctrl+L`).
- Help panel shows both keybindings and the `/model` command.

**During streaming (GAP-7):** Model cycling keybindings work while a worker is running. The change takes effect on the next submit — the current worker is unaffected. No abort needed. The header updates immediately to show the pending model change (distinguish with "→" prefix or dimmed style — defer to implementation).

**Empty/tui.models list:** If `tui.models` is empty or absent, the selector shows only `"{effective_llm.provider}/{effective_llm.model}"` with a `●` marker. `Ctrl+P`/`Ctrl+Shift+P` are no-ops.

---

## G6: Alt+Enter Binding Migration

**Problem:** `Alt+Enter` is currently bound to `"submit_editor"`. Phase 2 changes it to `"queue_or_submit"`. Old behavior must be preserved when idle.

**Resolution:** Pure superset — identical behavior when idle, new behavior when worker running.

```python
# Old binding (Phase 1):
Binding("alt+enter", "submit_editor", "Submit", priority=True, show=False),

# New binding (Phase 2):
Binding("alt+enter", "queue_or_submit", "Queue/Submit", priority=True, show=False),
```

```python
def action_queue_or_submit(self) -> None:
    """Alt+Enter: submit if idle, queue if worker running."""
    if self._worker_running:
        self._queue_current_text()
    else:
        self.action_submit_editor()
```

---

## G7: Input History + Vim NORMAL Mode Interaction

**Problem (EDGE-1):** History navigation fires while completion menu is visible. Must guard.
**Problem (EDGE-6):** Draft text preservation mechanism under-specified.
**Problem (INC-3):** Submit key behavior when worker is running vs Vim mode gating.

### Arrow-key history navigation (revised)

History navigation fires for Up/Down arrow keys only. Vim's `k`/`j` do NOT trigger history navigation — only physical arrow keys.

**Completion menu guard (EDGE-1 fix):** History navigation is suppressed when the completion menu is visible.

**Draft preservation (EDGE-6 fix):**
- `_history_index: int = -1` means "not currently navigating history."
- `_draft_text: str = ""` stores the text that was in the editor when navigation began.
- On first Up press at boundary (when `_history_index == -1`): save `editor.text` as `_draft_text`, set `_history_index = 0`, load `_history[0]`.
- On subsequent Up presses: `_history_index += 1` (capped at `len(_history) - 1`), load entry.
- On Down press: `_history_index -= 1`. If `_history_index < 0`, set to `-1` and restore `_draft_text`.
- On text submission: `_history_index = -1`, `_draft_text = ""`.
- On cursor movement away from boundary (arrow keys, mouse click, typing): `_history_index = -1`, `_draft_text = ""` (exit navigation mode).

**Revised `VimTextArea._on_key`:**

```python
async def _on_key(self, event: events.Key) -> None:
    app = cast("ChatApp", self.app)

    # Input history: up/down at boundary takes priority (EDGE-1: skip if completion visible)
    if event.key in ("up", "down") and not app._completion_visible:
        editor = cast("TextArea", self)
        row, col = editor.cursor_location
        lines = editor.text.splitlines() or [""]
        at_boundary = (
            (event.key == "up" and row == 0 and col == 0) or
            (event.key == "down" and row == len(lines) - 1 and (
                col == len(lines[-1]) if lines[-1] else True
            ))
        )
        if at_boundary and app._navigate_history(event.key):
            event.stop()
            event.prevent_default()
            return

    # Vim handling (existing)
    if app.handle_vim_text_area_key(event):
        event.stop()
        event.prevent_default()
```

**Cursor placement after history recall (EDGE-8):** After loading a history entry into the editor, set cursor to `(row_count - 1, len(last_line))` — end of entire text.

### Submit key gating order (INC-3 fix, NEW-HIGH-1 fix)

Command detection (`/resume`, `/compact`, `/model`) runs BEFORE the `_worker_running` check. These commands abort the current worker and execute immediately — they never enter the message queue. The full gating order in `action_submit_editor`:

```python
def action_submit_editor(self) -> None:
    # 1. Command detection — always runs first, even during streaming
    text = self.query_one("#input", TextArea).text.strip()
    if text in ("/resume",) or text.startswith("/resume "):
        self._abort_and_defer_command("resume")
        return
    if text in ("/compact",) or text.startswith("/compact "):
        self._abort_and_defer_command("compact")
        return
    if text in ("/model",) or text.startswith("/model "):
        self._handle_model_command(text)
        return

    # 2. Queue gating: if worker running, queue (bypasses Vim gating)
    if self._worker_running:
        self._queue_current_text()
        return

    # 3. Vim gating (only applies when worker is idle):
    if self._vim.enabled and self._vim.pane == VimPane.INPUT and self._vim.mode == VimMode.NORMAL:
        return
    if self._vim.enabled and self._vim.pane == VimPane.CHAT:
        self.query_one("#chat", VerticalScroll).scroll_page_down()
        return

    self._submit_editor_text()
```

### Race-safe command execution during streaming (NEW-MEDIUM-3 fix)

When `/resume` or `/compact` is typed during streaming, the worker must be aborted AND its finalization must complete before the command executes (both modify chat state). Defer command execution to `_finalize_response._do()`:

```python
# In ChatApp.__init__:
self._pending_command: str | None = None  # "resume" | "compact" | None

# Called from action_submit_editor for /resume or /compact:
def _abort_and_defer_command(self, command: str) -> None:
    """Abort current worker and defer command to after finalization."""
    if self._worker_running:
        self._abort_event.set()
        self._pending_command = command
    else:
        # No worker running — execute immediately
        if command == "resume":
            self._handle_resume_command()
        else:
            self._handle_compact_command()

# In _finalize_response._do(), after activity reset and _worker_running = False:
if self._pending_command is not None:
    cmd = self._pending_command
    self._pending_command = None
    if cmd == "resume":
        self._handle_resume_command()
    elif cmd == "compact":
        self._handle_compact_command()
```

This ensures the worker's finalization (tool panel collapse, buffer flush, activity reset) completes before the new command modifies chat state.

---

## G8: Message Queue Behavior After Abort

**Resolution: Auto-submit after abort.** The queued message was intentionally queued by the user. Aborting doesn't negate that intent.

At the end of `_finalize_response._do()`, after activity reset:
```python
self._worker_running = False
if self._message_queue:
    self.call_later(self._dequeue_next)
```

**Exception path (GAP-3 fix):** If `_chat_worker` raises an exception, the queue must still drain. Add dequeue logic to the exception handler:

```python
except Exception as exc:
    logger.exception("ChatApp worker raised", extra={"text": text})
    self._set_activity("idle")
    self._mount_chat(Static(f"[red]Error: {exc}[/red]", markup=True))
    self._worker_running = False
    if self._message_queue:                   # ← GAP-3 fix
        self.call_later(self._dequeue_next)
```

**`_dequeue_next` method:**
```python
def _dequeue_next(self) -> None:
    """Submit the next queued message. Called via call_later from finalize/error paths."""
    if self._message_queue:
        next_text = self._message_queue.pop(0)
        # Clear editor and overlays (user may have typed while waiting) (NEW-MEDIUM-2)
        self.query_one("#input", TextArea).load_text("")
        self._hide_completion_menu()
        self._dismiss_all_overlays()
        self._submit(next_text)
```

Using `call_later` avoids nested `run_worker` scheduling inside `call_from_thread` callbacks.

---

## G9: Thread Safety for Abort Coordination

**Resolution:** `threading.Event` is thread-safe for set/check. `call_from_thread` is Textual's thread-safe UI bridge. No additional synchronization needed.

**Pre-existing bug (CODE-4):** `on_tool_event` at tui.py L679 calls `self._set_activity("tool", ...)` directly from the executor thread, NOT via `call_from_thread`. This is a pre-existing issue, not introduced by this spec. Noted; not fixed here.

---

## G10: `tui.models` Config with Empty List

Add to `TuiConfig` (config.py L66-68):
```python
@dataclass(frozen=True, slots=True)
class TuiConfig:
    vim_enabled: bool = False
    vim_initial_mode: str = "insert"
    models: list[str] = field(default_factory=list)  # ← new
```

Parse from `harness.yaml` in `HarnessConfig.load` (config.py ~L222-233):
```python
tui_raw = _mapping(raw.get("tui"), "tui")
# ... existing vim parsing ...
models_raw = tui_raw.get("models")
if models_raw is not None:
    if not isinstance(models_raw, list):
        raise TypeError("harness.yaml tui.models must be a list of strings")
    models = [str(m) for m in models_raw]
else:
    models = []
tui = TuiConfig(
    vim_enabled=...,
    vim_initial_mode=...,
    models=models,  # ← new
)
```

Empty list → selector shows only current model. `Ctrl+P`/`Shift+Ctrl+P` are no-ops.

---

## G11: Status Bar Rendering with Queue Depth

Queue depth is separate from `ActivityState`. Modify `_render_status_bar`:

```python
def _render_status_bar(self) -> None:
    parts: list[str] = []
    parts.append(format_status(self._vim))
    parts.append(str(self._app_state.active_mode))
    if self._activity.phase != "idle":
        parts.append(self._activity.label)
    if self._message_queue:
        parts.append(f"{len(self._message_queue)} queued")
    self.query_one("#status-bar", Static).update(" \u2502 ".join(parts))
```

---

## G12: Worker-Running State Tracking

Add to `ChatApp.__init__`:
```python
self._worker_running: bool = False
```

Set `True` in `_submit`, after mounting the user message, before `run_worker`.
Set `False` in `_finalize_response._do()` AND in `_chat_worker`'s exception handler (GAP-3 fix).

```python
def _submit(self, text: str) -> None:
    self._abort_event.clear()  # EDGE-2 fix
    chat = self.query_one("#chat", VerticalScroll)
    chat.mount(Static(f"[cyan]You:[/cyan] {text}", classes="user-msg", markup=True))
    self._chat_messages.append(f"You: {text}")
    self._set_activity("streaming")
    if self._tool_panel is not None:
        self._tool_panel.dismiss()
    self._worker_running = True
    self.run_worker(self._chat_worker(text, chat))
```

---

## G13: Help Panel Widget Details

**Keybinding conflict (NEW-LOW-1 fix):** With `priority=False`, `?` is consumed by TextArea as a literal character. With `priority=True`, the user can't type `?`. Resolution: `priority=True` binding that manually inserts `?` when the user is typing:

```python
# BINDINGS entry:
Binding("question_mark", "toggle_help", "Help", priority=True, show=False),

# Action handler:
def action_toggle_help(self) -> None:
    """Open help panel, or insert ? if user is typing in input."""
    editor = self.query_one("#input", TextArea)
    if editor.has_focus and not self._vim.enabled:
        # User is typing in input with Vim off — insert ? literally
        editor.insert("?")
        return
    if self._vim.enabled and self._vim.pane == VimPane.INPUT and self._vim.mode == VimMode.INSERT:
        # User is typing in Vim INSERT mode — insert ? literally
        editor.insert("?")
        return
    # Otherwise: toggle help panel
    if self.query_one("#help-panel", VerticalScroll).display:
        self.query_one("#help-panel", VerticalScroll).display = False
    else:
        self._dismiss_all_overlays()
        help_text = self._HELP_TEXT_VIM if self._vim.enabled else self._HELP_TEXT
        self.query_one("#help-panel", VerticalScroll).update(help_text)
        self.query_one("#help-panel", VerticalScroll).display = True
```

This handles all states: typing with Vim off → insert `?`; typing in Vim INSERT → insert `?`; chat focused or Vim NORMAL → toggle help.

Mount in `compose()`:
```python
yield VerticalScroll(id="help-panel")
```

CSS:
```css
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
```

Two content variants selected at render time: `_HELP_TEXT` (Vim disabled) and `_HELP_TEXT_VIM` (Vim enabled). Content is a hardcoded multi-line string organized by context group (Global, Vim Input, Vim Chat, Completion Menu).

**Vim toggle while help is visible (GAP-8):** Accept as-is. The user can close and reopen help with `?` to see updated content. No dynamic refresh.

**Overlay exclusivity (ORDER-4):** Opening help dismisses any visible session picker or model selector. Only one overlay visible at a time.

---

## G14: Message Queue Storage and Edge Cases

- `_message_queue: list[str]` (not `deque` — list suffices for max 5).
- **Enqueue:** `_message_queue.append(text)`. If `len(_message_queue) >= 5`, show transient warning via Textual's `self.notify("Queue full (max 5)", severity="warning")` and don't append (GAP-6 fix).
- **Dequeue (auto-submit):** `_message_queue.pop(0)` — FIFO, first queued runs first.
- **Restore last (Alt+Up):** `_message_queue.pop()` — LIFO, restores most recently queued.
- **Visibility:** `len(self._message_queue) > 0` → shown in status bar.
- **Lifetime:** Per-session, in-memory. Cleared on `/exit` (TUI shutdown). Not persisted.

---

## G15: Auto-Dequeue Trigger Point

At the end of `_finalize_response._do()`, after activity reset and `_worker_running = False`:

```python
# Auto-dequeue (G15)
if self._message_queue:
    self.call_later(self._dequeue_next)
```

And in the exception handler (GAP-3 fix):
```python
except Exception as exc:
    logger.exception(...)
    self._set_activity("idle")
    self._mount_chat(Static(f"[red]Error: {exc}[/red]", markup=True))
    self._worker_running = False
    if self._message_queue:
        self.call_later(self._dequeue_next)
```

`_dequeue_next` runs on the main event loop via `call_later`, avoiding nested scheduling issues.

---

## G16: Streaming Markdown and Abort Suffix Compatibility (ORDER-1 fix)

In Phase 1, `[interrupted]` is appended to buffer in `on_text_chunk` before calling `_finalize_response`. `_finalize_response._do()` reads from `buffer` (tui.py L698: `response = "".join(buffer)`), so the suffix renders correctly in the Phase 1 `Static` widget.

In Phase 3, `_flush_to_ui` updates the `Markdown` widget directly. When `on_text_chunk` appends `"\n[interrupted]"` to buffer and calls `_flush_to_ui()`, the Markdown widget receives the buffered text INCLUDING the suffix. `_finalize_response._do()` no longer replaces the widget — it only collapses the tool panel and resets activity. The suffix is already rendered.

**No Phase 3 changes to `_finalize_response` break Phase 1's abort suffix.** The suffix is in the buffer, which both phases render (Phase 1 via `Static.update()`, Phase 3 via `Markdown.update()`).

---

## G17: Overlay Widget Stacking (ORDER-4 fix)

Multiple overlay-capable widgets exist: `#help-panel`, `#session-picker`, `#model-selector`, `#completion-menu`. Rule: **only one overlay visible at a time.** Opening a new overlay dismisses any currently visible overlay.

Implementation: Add a helper `_dismiss_all_overlays()` that hides `#help-panel`, `#session-picker`, `#model-selector`, and `#completion-menu`. Call it before showing any overlay.

Exception: `#completion-menu` is auto-managed (shows/hides based on typing). Session picker and model selector should dismiss the completion menu when they open.

---

## Implementation Plan (Revised)

### Phase 1: Cheapest Wins (3–5 hours)

| File | Change | Details |
|---|---|---|
| `harness_poc/tui.py` | `ChatApp.__init__`: add `_history`, `_history_index`, `_draft_text`, `_abort_event` | `_history: list[str]`, `_history_index: int = -1`, `_draft_text: str = ""` |
| `harness_poc/tui.py` | `_navigate_history(direction: str) -> bool` | Ring of 200; draft preservation (§G7); returns True if navigation occurred |
| `harness_poc/tui.py` | `VimTextArea._on_key`: check up/down at boundary, guard against completion menu (§G7) | — |
| `harness_poc/tui.py` | `_submit_editor_text`: append submitted text to `_history` (before clearing editor) | Trim to 200; reset `_history_index = -1`, `_draft_text = ""` |
| `harness_poc/tui.py` | `_submit`: clear `_abort_event` before `run_worker` (§G1, EDGE-2) | — |
| `harness_poc/tui.py` | `_chat_worker`: cooperative abort in `on_text_chunk`; executor polling fallback (§G1) | Append `"\n[interrupted]"` to buffer on abort |
| `harness_poc/tui.py` | `action_escape`: new handler (§G1) | Non-priority binding; dismiss help first, then abort worker, else no-op |
| `harness_poc/tui.py` | `HelpPanel` widget: `VerticalScroll(id="help-panel")` | Two content variants; `_HELP_TEXT`, `_HELP_TEXT_VIM` |
| `harness_poc/tui.py` | `action_toggle_help`: show/hide; dismiss other overlays (§G17) | — |
| `harness_poc/tui.py` | `_dismiss_all_overlays`: helper for overlay exclusivity (§G17) | — |
| `harness_poc/tui.py` | `compose()`: add `#help-panel` to DOM | `display: none` |
| `harness_poc/tui.py` | CSS: add `#help-panel` styles | Overlay, fullscreen, z-index |
| `harness_poc/tui.py` | BINDINGS: add `Escape` (non-priority), `question_mark` → `toggle_help` (priority=True) | See §G13 for `?` typing guard |
| `tests/repl/test_tui.py` | Tests: history recall (up/down, boundary gating, draft preservation), Escape abort (worker interrupted, partial text with suffix, Vim Escape preserved), `?` help (open/dismiss, Vim toggle, overlay exclusivity) | Use `pilot.press` + monkeypatch |

### Phase 2: Message Queue + Input Decoupling (1–2 days)

| File | Change | Details |
|---|---|---|
| `harness_poc/tui.py` | `ChatApp.__init__`: add `_message_queue`, `_worker_running` | `list[str]`, `bool = False` |
| `harness_poc/tui.py` | `_submit`: set `_worker_running = True` after mount, before `run_worker` | — |
| `harness_poc/tui.py` | `_finalize_response._do()`: set `_worker_running = False`; auto-dequeue via `call_later` (§G15) | — |
| `harness_poc/tui.py` | `_chat_worker` exception handler: set `_worker_running = False`; auto-dequeue (§G8, GAP-3) | — |
| `harness_poc/tui.py` | `_dequeue_next`: new method — pops and submits next queued message | — |
| `harness_poc/tui.py` | `action_submit_editor`: `_worker_running` check first, then Vim gating, then commands, then normal submit (§G7, INC-3) | — |
| `harness_poc/tui.py` | `action_queue_or_submit`: new action for `Alt+Enter` (§G6) | — |
| `harness_poc/tui.py` | `action_restore_queued`: pop last from queue, load into editor | — |
| `harness_poc/tui.py` | `_queue_current_text`: enqueue with max-5 check, clear editor, notify (§G14) | `self.notify("Queued")` |
| `harness_poc/tui.py` | `_render_status_bar`: show queue depth (§G11) | — |
| `harness_poc/tui.py` | BINDINGS: replace `Alt+Enter` → `queue_or_submit`; add `Alt+Up` → `restore_queued` | — |
| `tests/repl/test_tui.py` | Tests: queuing while worker runs, auto-dequeue after finish, auto-dequeue after error, `Alt+Enter` queue, `Alt+Up` restore, queue depth in status bar, queue-full warning, no-queue when worker idle | — |

### Phase 3: Streaming + Session Management (2–3 days)

| File | Change | Details |
|---|---|---|
| `harness_poc/tui.py` | `ChatApp.__init__`: add `_llm_override` (§Critical Issue) | `LLMConfig | None = None` |
| `harness_poc/tui.py` | `_effective_llm()`: new helper | — |
| `harness_poc/tui.py` | `_update_header`: use `_effective_llm()` | — |
| `harness_poc/tui.py` | `_chat_worker`: rebuild runtime via `build_runtime(llm=...)` if model changed (§Critical Issue) | — |
| `harness_poc/tui.py` | `_flush_to_ui`: swap `Static` for `Markdown`; progressive debounce (§G2) | Length-based throttling |
| `harness_poc/tui.py` | `_finalize_response._do()`: remove `Static`→`Markdown` replacement; keep tool collapse + activity reset | Abort suffix already in buffer (§G16) |
| `harness_poc/tui.py` | `/resume` handling: detect in `action_submit_editor`, open `#session-picker` (§G3) | Separate widget, overlay exclusivity |
| `harness_poc/tui.py` | `_open_session_picker`, `_filter_session_picker`, `_select_session` | — |
| `harness_poc/tui.py` | `_handle_resume_command`: parse text, open picker (§G3) | Called from `_abort_and_defer_command` or `_finalize_response._do()` |
| `harness_poc/tui.py` | `/compact` handling: intercept in `_chat_worker` before executor call (§G4) | — |
| `harness_poc/tui.py` | `_do_compact(text, chat)`: construct prompt, call LLM, replace messages | — |
| `harness_poc/tui.py` | `_handle_compact_command`: parse text, submit to worker (§G4) | Called from `_abort_and_defer_command` or `_finalize_response._do()` |
| `harness_poc/tui.py` | Model cycling: `Ctrl+L` → selector, `Ctrl+P` / `Shift+Ctrl+P` → cycle (§G5) | Use `_llm_override` |
| `harness_poc/tui.py` | `_model_selector`, `_cycle_model(direction)`, `/model` command handler | — |
| `harness_poc/tui.py` | `compose()`: add `#session-picker`, `#model-selector` OptionLists | `display: none` |
| `harness_poc/tui.py` | CSS: add `#session-picker`, `#model-selector` styles | — |
| `harness_poc/tui.py` | BINDINGS: add `Ctrl+L`, `Ctrl+P`, `Shift+Ctrl+P` | — |
| `harness_poc/core/storage/database.py` | `list_recent_sessions(limit=20)` → `list[dict]` (§G3) | SQL with subquery |
| `harness_poc/core/config.py` | `TuiConfig.models: list[str] = field(default_factory=list)` | — |
| `harness_poc/core/config.py` | Parse `tui.models` in `HarnessConfig.load` | — |
| `tests/repl/test_tui.py` | Tests: streaming Markdown, progressive throttle, `/resume` picker (open/filter/select/empty/no-DB), `/compact` (success/empty/error), model cycling (selector, quick cycle, `/model` command, empty list), overlay exclusivity | — |

---

## Key Dispatch (final, after all phases)

```python
BINDINGS: ClassVar[list] = [
    # Copy
    Binding("super+c", "copy_smart", "Copy", priority=True, show=False),
    Binding("super+y", "copy_last_response", "Copy last response", priority=True, show=False),

    # Submit / Queue
    Binding("ctrl+d", "submit_editor", "Submit", priority=True, show=False),
    Binding("alt+enter", "queue_or_submit", "Queue/Submit", priority=True, show=False),
    Binding("super+enter", "submit_editor", "Submit", priority=True, show=False),

    # Queue
    Binding("alt+up", "restore_queued", "Restore queued", priority=True, show=False),

    # Completion
    Binding("tab", "cycle_completion_forward", "Next completion", priority=True, show=False),
    Binding("shift+tab", "cycle_completion_backward", "Previous completion", priority=True, show=False),
    Binding("enter", "accept_completion_or_newline", "Accept completion", priority=True, show=False),

    # Vim
    Binding("f2", "toggle_vim", "Toggle Vim", priority=True, show=False),

    # Help & Abort
    Binding("escape", "escape", "Abort/Dismiss", priority=False, show=False),
    Binding("question_mark", "toggle_help", "Help", priority=True, show=False),

    # Model cycling (Phase 3)
    Binding("ctrl+l", "model_selector", "Model selector", priority=True, show=False),
    Binding("ctrl+p", "cycle_model_prev", "Previous model", priority=True, show=False),
    Binding("ctrl+shift+p", "cycle_model_next", "Next model", priority=True, show=False),
]
```

---

## Verification

### Automated

```bash
# Full TUI test suite after each phase
uv run pytest tests/repl/test_tui.py tests/repl/test_tui_throttle.py tests/repl/test_tui_vim_chat.py \
    tests/repl/test_tui_vim_core.py tests/repl/test_tui_vim_normal.py tests/repl/test_tui_vim_visual.py -v

# Phase-specific
uv run pytest tests/repl/test_tui.py -k "history or abort or help or escape" -v     # Phase 1
uv run pytest tests/repl/test_tui.py -k "queue or queued or dequeue" -v             # Phase 2
uv run pytest tests/repl/test_tui.py -k "streaming or resume or compact or model" -v # Phase 3
```

Note: The parent spec references `test_tui_vim.py` which does not exist. The actual files are `test_tui_vim_chat.py`, `test_tui_vim_core.py`, `test_tui_vim_normal.py`, `test_tui_vim_visual.py` (INC-2).

### Manual smoke test

(Unchanged from parent spec — 10-step sequence.)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Frozen config prevents model switching | Certain (without fix) | Blocking | Rebuild runtime via `build_runtime(llm=...)`; never mutate config |
| `?` with `priority=True` blocks typing `?` in editor | Certain (without fix) | Medium | Guard in action handler inserts `?` literally when typing |
| Race between command abort and worker finalization | Medium | High | `_pending_command` deferred to `_finalize_response._do()` |
| Markdown incremental updates cause rendering lag | Medium | Low (PoC) | Progressive throttling; Static fallback above 16k chars |
| Executor thread leak on abort | Low | Low | Harmless; thread terminates on LLM call completion |
| `Ctrl+L` conflicts with terminal clear-screen | Medium | Low | `/model` command fallback |
| `_set_activity` from executor thread (`on_tool_event`) | Already exists | Low | Pre-existing bug (CODE-4); not in scope |
| `asyncio.wait_for` polling adds event-loop overhead | Medium | Low | 10 TimeoutErrors/sec; negligible impact |
| Layout jank from Markdown height changes | Medium | Low | Accept as known PoC limitation |
| `call_from_thread` + `call_later` dequeue chain | Low | Medium | `call_later` decouples scheduling context; safe |
