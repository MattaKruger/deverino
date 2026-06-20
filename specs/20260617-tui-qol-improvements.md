---
title: "TUI Quality-of-Life Improvements — Message Queue, Streaming, Session Resume, and Input History"
date: 2026-06-17
status: draft
kind: spec
---
# TUI Quality-of-Life Improvements — Message Queue, Streaming, Session Resume, and Input History

## Objective

Close the biggest quality-of-life gaps between the Deverino Textual TUI and top-tier terminal coding harnesses (notably Pi). Deliver input history, universal abort, keybinding help, a non-blocking message queue, live text streaming, in-TUI session resume, manual compaction, and model cycling — phased by impact-to-effort ratio.

## Background

Our TUI (`ChatApp` in `harness_poc/tui.py`, ~740 lines) is built on Textual and already delivers markdown rendering, Vim modal editing, completion menus, tool-call panels, an activity status bar, and a token counter. However, several UX gaps make it feel sluggish compared to alternatives:

| Gap | Current state | Impact |
|---|---|---|
| **Input history** | No recall of previous prompts | High — re-typing is tedious |
| **No abort key** | Cannot interrupt a running model call | High — feels unresponsive |
| **No keybinding help** | Keys only in source/docs (`?` deferred in 20260613 spec) | Medium — discoverability |
| **Input blocked during streaming** | Input pane is dead while model runs | High — slows conversational flow |
| **No live streaming** | Spinner → full response (deferred as non-goal in original design) | High — context-free wait |
| **CLI-only session resume** | `--resume` / `--resume-last` flags; no in-TUI picker | Medium — break in flow |
| **No model cycling** | Restart with different config to switch models | Medium — friction |
| **No message queue** | Only one message at a time | Medium — can't queue follow-ups |

**Reference specs:**

- `20260613-tui-keybinding-cleanup.md` — keybinding audit; `?` help deferred to Phase 2 (§D5)
- `20260613-tui-subagent-spawning.md` — `/spawn`, `/tasks`, `/result`, `/cancel` commands
- `docs/archive/superpowers/specs/2026-05-19-textual-chat-tui-design.md` — original design; live streaming listed as non-goal

## Design Decisions

### D1: Input history scope

Per-session ring buffer of the last **200** submitted inputs. Stored in memory only — not persisted across TUI restarts. Rationale: Phase 1 scope is to eliminate re-typing within one session. Persisted shell-style history (`~/.deverino_history`) is deferred to a future phase.

- **Up arrow** at the start of the first line → restore the most recent submitted input.
- **Down arrow** at the end of the last line → restore the next-most-recent (or clear back to current draft).
- If the cursor is mid-line, arrow keys behave as normal (no history navigation).
- The current draft text is preserved in the ring so the user can arrow back to it.

### D2: Message queue depth

Maximum **5** queued messages (not submitted — only queued via `Alt+Enter`). When the queue is full, `Alt+Enter` shows a transient warning "Queue full (max 5)". Messages submitted via the normal submit keys while a worker is running are also queued.

- **`Alt+Enter`**: queue the current input text but do not submit (a "follow-up while thinking").
- **`Alt+Up`**: restore the last queued message to the editor (pop from queue, push to editor).
- **Submit keys** (Ctrl+D, Alt+Enter, Super+Enter) when no worker is running: submit immediately. When a worker IS running: queue the text.
- The status bar shows queue depth: `"● streaming · 1.2k tokens (3 queued)"`.

### D3: Streaming approach

Replace the current buffered-Static-then-Markdown pattern with incremental Markdown updates.

**Current flow** (`_chat_worker`, lines 641–728):
1. `on_text_chunk` appends to a `list[str]` buffer.
2. `_flush_to_ui` (debounced at ~30fps) re-renders the buffer into a single `Static` widget.
3. `_finalize_response` removes the `Static`, mounts a `Markdown` widget with the full text.

**New flow**:
1. `on_text_chunk` appends to buffer (unchanged).
2. `_flush_to_ui` mounts/updates a **`Markdown` widget incrementally** instead of a `Static`. The debounce interval remains ~30fps (33ms).
3. `_finalize_response` is a no-op for text — the final Markdown widget is already in place. It only collapses the tool panel and resets activity state.

This reuses the existing `on_text_chunk` callback and `_mount_chat` pattern. The key change is swapping `Static` for `Markdown` in the streaming path, and skipping the final replacement step.

**Why it works**: Textual's `Markdown` widget handles incremental updates via `update()`. The debounced 30fps throttle prevents thrashing. Fenced code blocks that are incomplete during streaming will be rendered as plain text (Textual's Markdown parser is lenient).

### D4: `/resume` picker

Use Textual's `OptionList` widget — the same pattern as the existing completion menu. Not a separate modal; it mounts inline in the chat area or as a pop-over above the input.

**Data source**: `BlackboardDatabase`. Phase 3 adds a `list_recent_sessions(limit=20)` method that queries the `sessions` table joined with `session_messages` to return `(session_id, global_objective, created_at, message_count)`.

**Picker UX**:
- `/resume` opens the picker.
- Each row shows: `[N msgs] objective — 2026-06-15 14:32`
- Type to fuzzy-filter (reuse existing completion filtering logic).
- `Enter` selects, `Escape` dismisses.
- The picker uses the existing `OptionList` widget (`#completion-menu` pattern), mounted above the input in the footer area.

**Behavior on selection**: Load session messages from `session_messages` table, replay them as `Static` messages in the chat pane (user: cyan, agent: green/markdown), update `app_state.session_id` and `app_state.messages`, rebuild the chat history from the loaded messages.

### D5: `/compact` format

Adopt Pi's structured summary format for compatibility:

```
## Compaction Summary

### Goal
[What the user is trying to accomplish]

### Progress
[What has been done so far]

### Key Decisions
[Decisions made and their rationale]

### Next Steps
[What remains to be done]

### Critical Context
[Facts, constraints, or state that must not be lost]
```

The `/compact [instructions]` command:
1. Takes optional free-form instructions after the command (e.g., `/compact focus on the auth module`).
2. Constructs a system prompt that asks the LLM to produce a summary in the above format.
3. The LLM call is made with the chat history + compaction instructions.
4. The result replaces the chat history (the summary becomes the new context).
5. A `Static` marker is mounted: `"--- Context compacted ---"`.

### D6: Escape semantics

**Escape** aborts the current model call but does **not** exit the TUI. Exit stays as `/exit` or `/quit`.

- When `_chat_worker` is running: Escape sets a `threading.Event` that the worker checks. The worker catches the interrupt and calls `_finalize_response` with whatever text has accumulated (marked with a "\[interrupted\]" suffix).
- When no worker is running: Escape is a no-op (or passes through to Vim's NORMAL mode if Vim is enabled and input pane is focused).
- The `Escape` key is added to BINDINGS as a non-priority binding (so Vim's NORMAL-mode Escape still fires first in the input pane).

**Implementation**: Add a `threading.Event` to `ChatApp` (`_abort_event`). In `_chat_worker`, wrap the `run_in_executor` call in a polling loop: every 100ms, check `_abort_event.is_set()`. If set, cancel the executor future and finalize. This avoids needing OS-level thread interruption.

### D7: Model cycling

`Ctrl+L` opens a model selector using the existing `OptionList` pattern. Models are sourced from a new `tui.models` config list in `harness.yaml`. If the list is empty or absent, the selector shows only the current model.

```yaml
tui:
  models:  # optional; defaults to [current llm.model] if absent
    - deepseek/deepseek-v4-flash
    - deepseek/deepseek-v4-pro
    - anthropic/claude-sonnet-4-20250514
```

Each entry is `provider/model`. The selector shows the current model with a `●` marker. Selecting a model updates `app_state.config.llm.provider` and `app_state.config.llm.model` for the next turn. The change does not affect the current running worker — it takes effect on the next submit.

`Ctrl+P` / `Shift+Ctrl+P` cycle backward/forward through the model list without opening the selector (quick toggle).

## Requirements

### R1: Input history recall (Phase 1)

- Given the input editor is focused and cursor is at the start of the first line (row=0, col=0)
- When `Up` is pressed
- Then: the editor text is replaced with the most recent submitted input, and cursor moves to end of text.

- Given a previous input has been recalled via Up
- When `Down` is pressed with cursor at the end of the last line
- Then: the next-most-recent input is recalled (or the original draft is restored if at the newest end).

- Given the cursor is NOT at the start of the first line (or end of the last line for Down)
- When `Up` or `Down` is pressed
- Then: the cursor moves normally (no history recall).

### R2: Escape aborts running worker (Phase 1)

- Given a `_chat_worker` is running (activity phase is "streaming")
- When `Escape` is pressed
- Then: the worker is interrupted, any accumulated text is displayed with an "\[interrupted\]" suffix, and activity resets to "idle".

- Given no worker is running and Vim is off or chat pane focused
- When `Escape` is pressed
- Then: nothing happens (no-op).

- Given Vim is enabled and input pane is in INSERT mode
- When `Escape` is pressed
- Then: Vim switches to NORMAL mode (existing behavior preserved — non-priority binding lets Vim's handler fire first).

### R3: `?` keybinding help panel (Phase 1)

- Given the TUI is running
- When `?` is pressed
- Then: a modal/overlay appears listing all active keybindings, grouped by context (Global, Vim Chat, Vim Input, Completion Menu).

- The help panel shows the key, the action description, and the context where it applies.
- `Escape` or `?` again dismisses the help panel.
- Content is static (hardcoded in the widget, not auto-generated from BINDINGS).
- The help panel respects the Vim enabled/disabled state (shows Vim keys only when Vim is enabled).

### R4: Input decoupled from chat worker (Phase 2)

- Given a `_chat_worker` is running
- When the user types in the input editor
- Then: the editor accepts input (cursor moves, text inserts, Vim modes work). It is never dead.

- Given a `_chat_worker` is running
- When the user presses a submit key (Ctrl+D, Alt+Enter, Super+Enter)
- Then: the text is queued (appended to the message queue). A "Queued" flash appears briefly.

- Given no worker is running and the message queue is non-empty
- When the current worker finishes
- Then: the next queued message is automatically submitted (dequeued and sent to `_submit`).

### R5: `Alt+Enter` queues without submitting (Phase 2)

- Given a worker is running and the input has text
- When `Alt+Enter` is pressed
- Then: the text is added to the message queue, the editor is cleared, and the worker continues. No submit occurs.

- Given no worker is running
- When `Alt+Enter` is pressed
- Then: the text is submitted immediately (existing behavior preserved — no queueing needed).

### R6: `Alt+Up` restores last queued message (Phase 2)

- Given the message queue has at least one queued message
- When `Alt+Up` is pressed
- Then: the most recently queued message is removed from the queue and loaded into the editor (replacing current content). Cursor moves to end of text.

- Given the message queue is empty
- When `Alt+Up` is pressed
- Then: nothing happens (no-op).

### R7: Queue depth in status bar (Phase 2)

- Given N messages are queued (N > 0)
- When the status bar renders
- Then: it shows `"● streaming · 1.2k tokens (N queued)"`.

- Given 0 messages are queued
- When the status bar renders
- Then: it shows the current activity without queue depth (existing behavior).

### R8: Live incremental Markdown streaming (Phase 3)

- Given a `_chat_worker` is running and `on_text_chunk` fires
- When the debounce interval (33ms) elapses
- Then: the chat pane shows a `Markdown` widget with the accumulated text, updated incrementally. No `Static` intermediary.

- Given the worker finishes
- When `_finalize_response` is called
- Then: the final `Markdown` widget remains in place (no replacement). Only the tool panel is collapsed and activity state is reset.

### R9: `/resume` session picker (Phase 3)

- Given the TUI is running with a working database connection
- When `/resume` is entered
- Then: an `OptionList` picker appears showing the 20 most recent sessions with date, message count, and objective.

- Given the picker is open
- When text is typed
- Then: the list filters to matching sessions (fuzzy match on objective and session_id).

- Given a session is selected (Enter)
- Then: the session's messages are loaded and replayed in the chat pane; `app_state.session_id` is updated; a "Resumed session …" marker is mounted.

- Given the database connection is unavailable
- When `/resume` is entered
- Then: "No database connection available." is displayed.

### R10: `/compact [instructions]` (Phase 3)

- Given chat history exists
- When `/compact` (with optional instructions) is entered
- Then: an LLM call is made to summarize the history in the structured format (§D5). The result replaces the chat messages. A "--- Context compacted ---" marker is mounted.

- Given chat history is empty
- When `/compact` is entered
- Then: "Nothing to compact." is displayed.

### R11: Model cycling with `Ctrl+L` (Phase 3)

- Given the TUI is running
- When `Ctrl+L` is pressed
- Then: a model selector `OptionList` appears showing configured models from `harness.yaml` (tui.models). The current model is marked with `●`.

- Given a model is selected
- Then: `app_state.config.llm.provider` and `model` are updated. The header refreshes to show the new model. A "Model: provider/model" confirmation is mounted in chat.

- Given `Ctrl+P` is pressed
- Then: the model cycles to the previous entry in the list (wrapping). The chat shows a confirmation.

- Given `Shift+Ctrl+P` is pressed
- Then: the model cycles to the next entry in the list (wrapping).

### R12: No regressions (all phases)

- All existing TUI/Vim tests pass.
- Vim NORMAL/INSERT mode behavior is unchanged.
- Completion menu, Tab cycling, tool panels, copy bindings all work as before.
- `/exit`, `/quit`, `/spawn`, `/tasks`, and all other REPL commands are unaffected.
- Token counter, header, and status bar update correctly.

## Non-Goals

- **Auto-compaction**: Manual `/compact` only. Automatic compaction when context exceeds budget is deferred.
- **Tree/branching session navigation**: Pi's `/tree` command for branching conversations is deferred.
- **Custom keybinding JSON/YAML config**: All keybindings are hardcoded (same as current).
- **External editor integration**: `Ctrl+G` to open `$EDITOR` is deferred.
- **Kill ring**: `Ctrl+Y` yank / `Alt+Y` yank-pop is deferred.
- **Image paste**: Not applicable to our TUI architecture.
- **Persistent input history across restarts**: History is per-session, in-memory only.
- **Multi-pane layout**: Single chat pane (unchanged from original design).
- **Tool output collapse**: `Ctrl+O` toggles inline (deferred — our ToolPanel already collapses on completion).

## Implementation Plan

### Phase 1: Cheapest Wins (3–5 hours)

| File | Change |
|---|---|
| `harness_poc/tui.py` | Add `_history: list[str]` ring buffer and `_history_index` to `ChatApp.__init__`. Add `_navigate_history(direction)` method. Bind `Up`/`Down` in `VimTextArea._on_key` (or via `on_key` handler) to call history navigation when cursor is at boundary. Add `Escape` binding (non-priority). Add `_abort_event: threading.Event`. In `_chat_worker`, poll `_abort_event` every 100ms and cancel executor future on set. Add `?` binding. Add `HelpPanel` widget (a `VerticalScroll` with static text, toggled by `?`). Add `action_escape`, `action_show_help`, `action_dismiss_help`. |
| `harness_poc/tui.py` (CSS) | Add styles for `#help-panel` (overlay, dock top or fullscreen, z-index). |
| `tests/repl/test_tui.py` | Add tests for: input history navigation (up/down recall, boundary gating), Escape abort (worker interrupted, partial text shown), `?` help panel open/dismiss. |

**Input history implementation detail**: `VimTextArea._on_key` fires before TextArea's native handler. Check `key == "up"` / `key == "down"`, check cursor boundary condition, if true call `self.app._navigate_history()` and stop propagation. Otherwise let the key through to TextArea for normal cursor movement.

**Escape implementation detail**: The `Escape` key is already handled by `InputVimHandler` for Vim mode switching. In `ChatApp.on_key`, when `key == "escape"` and `self._activity.phase != "idle"`, set `self._abort_event`. Vim's Escape handling takes priority when Vim is enabled and input pane is focused (the Vim handler fires in `VimTextArea._on_key` before `ChatApp.on_key`).

**Help panel implementation detail**: A `Static` or `VerticalScroll` widget mounted as a fullscreen overlay. Content is a hardcoded multi-line string organized by context group. The widget has `display: none` by default; `?` toggles visibility. `Escape` when help is visible dismisses it (check in escape handler: if help visible, dismiss; else if worker running, abort).

### Phase 2: Message Queue + Input Decoupling (1–2 days)

| File | Change |
|---|---|
| `harness_poc/tui.py` | Add `_message_queue: list[str]` (max 5) and `_worker_running: bool` to `ChatApp.__init__`. Modify `_submit_editor_text` to check `_worker_running`: if True, queue the text; else submit normally. Modify `_submit` to set `_worker_running = True` before starting worker, and `False` in `_finalize_response`. After `_finalize_response`, if queue is non-empty, pop and call `_submit(next_text)`. Add `Alt+Enter` binding for "queue" action (different from the existing submit `Alt+Enter`). Add `Alt+Up` binding for "restore_queued" action. Update `_render_status_bar` to show queue depth. |
| `harness_poc/tui.py` (BINDINGS) | Replace the existing `Alt+Enter` submit binding with a conditional action: `action_queue_or_submit`. `Alt+Up` → `action_restore_queued`. |
| `tests/repl/test_tui.py` | Add tests for: queuing while worker runs, auto-dequeue after worker finishes, `Alt+Enter` queue, `Alt+Up` restore, queue depth in status bar, queue-full warning, no-queue when worker idle. |

**Key design note**: The existing `Alt+Enter` binding submits. In Phase 2, this binding becomes context-sensitive:
- Worker idle → submit (existing behavior).
- Worker running → queue.
This is implemented as a single action handler `action_queue_or_submit` that checks `_worker_running`.

### Phase 3: Streaming + Session Management (2–3 days)

| File | Change |
|---|---|
| `harness_poc/tui.py` | **Streaming**: In `_chat_worker`, change `_flush_to_ui` to mount/update a `Markdown` widget instead of `Static`. Remove the `Static`-to-`Markdown` replacement in `_finalize_response` (keep only tool panel collapse and activity reset). **`/resume`**: Add `_is_resume_command`, `handle_resume_command`. Mount `OptionList` with session data. On selection, load messages via `db.load_session_messages()`, replay into chat pane. **`/compact`**: Add `_is_compact_command`, `handle_compact_command`. Construct compaction prompt, call LLM, replace `app_state.messages` with summary. **Model cycling**: Add `Ctrl+L`, `Ctrl+P`, `Shift+Ctrl+P` bindings. Add `action_model_selector`, `_cycle_model(direction)`. Read `tui.models` from config. Mount `OptionList` for selection. |
| `harness_poc/core/storage/database.py` | Add `list_recent_sessions(limit: int = 20) -> list[dict]` method: query `sessions` joined with count of `session_messages`, ordered by `created_at DESC`. Returns list of `{session_id, objective, created_at, message_count}`. |
| `harness_poc/core/config.py` | Add `models: list[str] = field(default_factory=list)` to `TuiConfig`. |
| `tests/repl/test_tui.py` | Add tests for: incremental Markdown updates, `/resume` picker open/filter/select, `/resume` with no DB, `/compact` command, model cycling bindings, model selector. |

## Key Dispatch (after all phases)

```python
BINDINGS = [
    # --- Copy ---
    Binding("super+c", "copy_smart", ...),                    # unchanged
    Binding("super+y", "copy_last_response", ...),            # unchanged

    # --- Submit / Queue ---
    Binding("ctrl+d", "submit_editor", ...),                  # Phase 2: queues if worker running
    Binding("alt+enter", "queue_or_submit", ...),             # Phase 2: changed from submit_editor
    Binding("super+enter", "submit_editor", ...),             # Phase 2: queues if worker running

    # --- Queue ---
    Binding("alt+up", "restore_queued", ...),                 # Phase 2: new

    # --- Completion ---
    Binding("tab", "cycle_completion_forward", ...),          # unchanged
    Binding("shift+tab", "cycle_completion_backward", ...),   # unchanged
    Binding("enter", "accept_completion_or_newline", ...),    # unchanged

    # --- Vim ---
    Binding("f2", "toggle_vim", ...),                         # unchanged

    # --- Help & Abort ---
    Binding("escape", "escape", ...),                         # Phase 1: new (non-priority)
    Binding("question_mark", "toggle_help", ...),             # Phase 1: new (non-priority)

    # --- Model cycling (Phase 3) ---
    Binding("ctrl+l", "model_selector", ...),                 # Phase 3: new
    Binding("ctrl+p", "cycle_model_prev", ...),               # Phase 3: new
    Binding("ctrl+shift+p", "cycle_model_next", ...),         # Phase 3: new
]
```

## Verification

### Automated

```bash
# Full TUI test suite after each phase
uv run pytest tests/repl/test_tui.py tests/repl/test_tui_vim.py -v

# Phase-specific
uv run pytest tests/repl/test_tui.py -k "history or abort or help" -v      # Phase 1
uv run pytest tests/repl/test_tui.py -k "queue or queued" -v               # Phase 2
uv run pytest tests/repl/test_tui.py -k "streaming or resume or compact or model" -v  # Phase 3
```

### Manual smoke test

1. Start TUI: `uv run harness-poc`
2. Type "hello", press `Ctrl+D` → submits. Type "world", press Up → restores "hello". Press Down → restores "world". (Phase 1 ✓)
3. Press `?` → help panel appears. Press `Escape` → help dismisses. (Phase 1 ✓)
4. Submit a long-running prompt. While spinner/streaming, type "follow-up question" and press `Alt+Enter` → queued. Status bar shows "(1 queued)". (Phase 2 ✓)
5. Press `Escape` → worker aborts. Queued message auto-submits. (Phase 1+2 ✓)
6. Type `/resume` → session picker appears. Type to filter, select a session → messages load. (Phase 3 ✓)
7. Type `/compact focus on auth` → LLM summarizes, chat replaced with summary. (Phase 3 ✓)
8. Press `Ctrl+L` → model selector appears. Select a model → header updates. (Phase 3 ✓)
9. Press `F2` → Vim on. Press `Escape` in input → NORMAL mode (Vim Escape preserved). Press `Escape` in chat → no-op. (Phase 1 ✓)
10. Press `F2` → Vim off. Press `Ctrl+D` → submits. All existing behavior intact.

## Review Notes

- Initial draft 2026-06-17 based on Pi research, existing codebase analysis, and deferred items from `20260613-tui-keybinding-cleanup.md`.
- Streaming reuses the existing `on_text_chunk` + `_flush_to_ui` infrastructure already debounced at 30fps — the change is swapping `Static` for `Markdown`.
- Message queue piggybacks on the existing submit path; the decoupling is a state check in `_submit_editor_text`.
- `/resume` requires a database query method not yet in `BlackboardDatabase` (`list_recent_sessions`).
- Model cycling requires a config schema addition (`tui.models` list).
- No changes to `repl.py` command dispatch except for `/resume` and `/compact` (following the established `_is_*_command` / `handle_*_command` pattern).
- All changes confined to `tui.py`, `database.py`, `config.py`, and their tests.
