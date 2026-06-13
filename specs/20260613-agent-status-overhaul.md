---
title: "Agent Status Output Overhaul"
date: 2026-06-13
status: draft
kind: spec
---
# Agent Status Output Overhaul

Replace the decorative spinner and ad-hoc tool overlays with a real-time
informational status system. The agent should tell the user what it's doing,
not recite kaomoji and jokes.

## Current State (audit 2026-06-13)

### Components

| Component | Location | Widget | What it shows |
|---|---|---|---|
| Header | Top | `Static` | `provider · model · 12.3k` |
| Streaming text | Chat | `Static` → `Markdown` | LLM text output, throttled to ~30fps |
| Tool events | Chat | `Static` (overlaid) | `⚙ skill_view: scanning docs...` |
| Console output | Chat | `Static` (appended) | REPL command results, errors |
| Spinner | Footer | `Static` | Rotating kaomoji + joke phrases + dots |
| Vim status | Footer | `Static` | `vim off` / `NORMAL input` / etc. |
| Prompt | Footer | `VimTextArea` | User input |

### Problems

1. **Spinner is pure decoration.** Rotates kaomoji (`(งツ)ว`, `¯\_(ツ)_/¯`) and phrases (`"cooking"`, `"sending it"`) on an 0.4s timer. Zero connection to actual agent activity. The user cannot tell if the agent is generating text, running a tool, waiting on I/O, or stuck in a loop.

2. **Spinner stops too early.** Line 610: spinner stops on the *first* text chunk. During extended tool-only phases (no text output for seconds), the spinner is gone and the user sees a dead `"Agent:"` label.

3. **Spinner blocks mode info.** The spinner occupies prime footer real estate with nonsense while actual state (mode, pool capacity, circuit breaker) is invisible.

4. **Tool events have no container.** Lines 633-652 mount bare `Static` widgets into chat. No border, no background, no color coding. Indistinguishable from chat messages.

5. **Tool events leak.** The tool-event widget is never cleaned up. On the next message it scrolls off but stays in the widget tree. Over a session, garbage accumulates with no benefit.

6. **Tool event list grows unbounded.** `tool_lines` (line 629) never trimmed. Each event triggers a full widget re-render even if off-screen.

7. **`call_from_thread` boilerplate duplicated 5 times.** Every UI mutation (`_tui_print_text`, `_tui_print_error`, `_tui_print_markdown`, `on_text_chunk`, `on_tool_event`) wraps in the same `call_from_thread` + `was_at_end` + scroll-end pattern. ~15 lines of identical scaffolding per call site.

8. **Streaming buffer may lose tail bytes.** The 30fps throttle leaves bytes in the buffer between the last flush and `on_finish`. Line 669-670 tries to catch them, but `on_finish` is a no-op (line 656) — the flush relies on the worker's finally-path, which races with the thread.

9. **No phase visibility during blocking operations.** `/spawn` foreground, `/goal`, and workflow execution run synchronously on a thread — the TUI has no spinner or progress indicator during these blocks.

10. **Footer is underused.** Two `Static` widgets (spinner + vim-status) show one line of actual information (vim mode) and one line of noise. Space for a richer single-line status bar.

## Design

### D1: Replace spinner with activity line

The spinner `Static` becomes an **activity line** that shows what the agent is actually doing.

States:

| State | Display |
|---|---|
| Idle | (empty) |
| Streaming text | `● streaming...`  — dim, pulsing |
| Running tool | `● tool: skill_view` — with tool name |
| Waiting (tool returned, model thinking) | `● thinking...` |
| Background pool active | `● 3 agents running` |
| Error | `● error — see chat` — red |

Implementation: replace `_start_spinner`/`_stop_spinner` with `_set_activity(state, detail=None)`. The activity line is a single `Static` widget updated via a 0.5s refresh timer that reads current state from a shared `ActivityState` dataclass.

```python
@dataclass
class ActivityState:
    phase: Literal["idle", "streaming", "tool", "thinking", "blocked"]
    detail: str = ""  # tool name, agent count, error message
    token_count: int = 0
    started_at: float = 0.0  # for elapsed time
```

The activity line shows: `● {phase_detail}  ·  {elapsed}s  ·  {tokens}`

### D2: Tool panel with lifecycle

Tool events get a **collapsible panel** in the chat area with:

- A **border** (dim dashed line) to visually separate from chat messages
- **Status icons**: ✓ (success), ✗ (error), … (running)
- **Collapse**: shows last 5 events. Older events collapsed to `[+ 3 earlier]` toggle
- **Cleanup**: when the response completes, the panel collapses to a one-line summary:  
  `✓ 5 tools ran (skill_view, file_tools ×2, read_memory, execute_python)  ·  2.3s`
- **Auto-cleanup**: the summary is removed when the next user message mounts

The tool panel replaces the current bare `Static` mount. It's a container widget (`ToolPanel`) that owns its own lifecycle:

```python
class ToolPanel(Static):
    events: list[ToolEvent]     # bounded to 20 max
    collapsed: bool = False
    def add(self, message: str, status: str = "running") -> None: ...
    def finish(self) -> str: ...  # returns summary line, removes widget
    def dismiss(self) -> None: ...
```

### D3: Extract `_call_from_thread` mounting helper

All chat-area mounts go through a single helper:

```python
def _mount_chat(self, widget: Widget, *, scroll: bool = True) -> None:
    def _do() -> None:
        chat = self.query_one("#chat", VerticalScroll)
        was_at_end = _is_chat_at_scroll_end(chat) if scroll else False
        chat.mount(widget)
        if scroll:
            _scroll_chat_end_if_following(chat, was_at_end=was_at_end)
    self.call_from_thread(_do)
```

Replace all 5 duplicates with this single call.

### D4: Merge footer into single status bar

The two `Static` widgets (spinner, vim-status) merge into one **status bar** at the bottom of the footer, above the prompt:

```
NORMAL input │ pipeline │ pool: 2/8 │ ● streaming... · 12.3s · 4.2k
```

Sections (left-aligned, `│` separated):

| Section | Source | Always visible? |
|---|---|---|
| Vim mode + pane | `_vim` | Yes |
| Active mode | `app_state.active_mode` | Yes |
| Pool status | `execution_engine._active_tasks` | When > 0 |
| Activity | `ActivityState` | When active |
| Elapsed + tokens | `ActivityState` | When active |

Implementation: single `Static` widget `#status-bar`. Updated via `_render_status_bar()` called from:
- `_set_activity()` (activity changes)
- `_update_vim_status()` (vim mode changes)
- `_update_header()` (token count changes)
- On mode switch, pool change

### D5: Fix streaming lifecycle

**Problem**: spinner stops on first text chunk, leaving dead air during tool-only phases.

**Fix**: spinner (now activity line) stays visible until `on_finish`. The activity line shows `● streaming...` during text, `● tool: {name}` during tool calls, `● thinking...` between tool and next text.

**Problem**: tail bytes lost between throttle and finish.

**Fix**: `on_finish` (currently no-op, line 656) becomes the final flush trigger:

```python
self._app_state.streaming.on_finish = lambda _: self.call_from_thread(
    lambda: _finalize_response(buffer, state, tool_panel)
)
```

Where `_finalize_response` flushes the buffer, replaces the `Static` with `Markdown`, collapses the tool panel to summary, and clears the activity line.

### D6: Status bar during blocking operations

Blocking operations (`/spawn` foreground, `/goal`, workflow run) set the activity line to `● running...` before dispatching the thread, and clear it when the result returns. This gives the user visible feedback that work is happening.

```python
# Before dispatch
self._set_activity("blocked", detail=persona)
# After result
self._set_activity("idle")
```

## Requirements

### R1: Activity line replaces spinner

- When agent starts processing: activity line shows `● streaming...`
- When tool runs: activity line shows `● tool: skill_view` (actual tool name)
- When tool returns, model thinking: `● thinking...`
- When idle: activity line is empty
- No kaomoji, no joke phrases, no rotating dots
- Elapsed time and token count shown when active

### R2: Activity line stays visible until finish

- Activity line does NOT disappear on first text chunk
- Activity line persists through tool→text→tool→text cycles
- Activity line clears only when the full agent response is complete (on_finish)

### R3: Tool panel with container and lifecycle

- Tool events appear in a visually distinct panel (bordered, separated from chat)
- Panel shows last 5 events with status icons (✓ running, ✓ success, ✗ error)
- Older events collapsed: `[+ 3 earlier]` (not expandable in Phase 1 — cosmetic only)
- When response finishes: panel collapses to summary line `✓ 5 tools ran ...`
- When next user message is submitted: summary line is removed
- Tool event list bounded to 20 entries; oldest dropped

### R4: Single `_mount_chat` helper

- All chat-area widget mounts use `_mount_chat(widget)` 
- Removes 5 duplicate `call_from_thread` + scroll-preserve patterns
- Call sites: `_tui_print_text`, `_tui_print_error`, `_tui_print_markdown`, `on_text_chunk` flush, `on_tool_event`

### R5: Merged status bar

- Single footer line replaces two `Static` widgets (`#spinner`, `#vim-status`)
- Shows: vim mode+pane, active mode, pool status, activity, elapsed+tokens
- Sections separated by `│`
- Updated atomically via `_render_status_bar()`

### R6: Streaming buffer final flush

- `on_finish` callback triggers final buffer flush and Markdown conversion
- No bytes lost between the last throttle tick and worker thread completion
- `_finalize_response()` handles flush, Markdown mount, tool panel collapse, activity clear

### R7: Activity during blocking operations

- `/spawn` foreground sets activity to `● running: {persona}` before dispatch
- `/goal` sets activity to `● goal: {objective_truncated}`
- Blocking workflow steps show `● running workflow...`
- Activity clears when operation completes

### R8: No regression

- All 78 TUI/Vim tests still pass
- Streaming output visually unchanged (same throttle rate, same Markdown rendering)
- Vim mode switching and status unaffected
- Completion menu unaffected
- Copy, submit, toggle Vim all work

## Non-Goals

- Per-character animation or smooth transitions (Phase 1: static updates)
- Expandable tool panel history (collapsed summary only)
- Network latency or model-tier indicators in status bar
- Changing the 30fps throttle rate
- Per-message timestamps (requires schema changes)
- Multi-line status bar or split-pane footer
- Animated spinner as fallback (removed entirely)

## Implementation Plan

### Phase 1: Core overhaul

Flat order (no sub-phases — changes are interdependent):

| # | File | Change |
|---|---|---|
| 1 | `tui.py` | Define `ActivityState` dataclass, `_set_activity()`, `_render_status_bar()` |
| 2 | `tui.py` | Replace `_start_spinner`/`_stop_spinner` calls with `_set_activity()` |
| 3 | `tui.py` | Add `_mount_chat(widget)` helper; migrate 5 call sites |
| 4 | `tui.py` | Replace `#spinner` + `#vim-status` `Static`s with single `#status-bar` in `compose()` |
| 5 | `tui.py` | Define `ToolPanel` widget class with `add()`, `finish()`, `dismiss()` |
| 6 | `tui.py` | Replace `on_tool_event` bare `Static` mount with `ToolPanel` |
| 7 | `tui.py` | Wire `on_finish` to `_finalize_response()` (flush buffer, convert to Markdown, collapse tool panel) |
| 8 | `tui.py` | Add `_set_activity("blocked", ...)` before blocking operations in `/spawn`, `/goal` |
| 9 | `harness_poc/repl.py` | Remove `print_text("[dim]Spawning...[/dim]")` — replaced by activity line |
| 10 | `tests/repl/test_tui.py` | Update spinner tests to activity line tests |
| 11 | `tests/repl/test_tui.py` | Add tests: activity transitions, tool panel lifecycle, status bar sections |

### Phase 2: Polish

| # | File | Change |
|---|---|---|
| 12 | `tui.py` | Color-code tool panel events by status |
| 13 | `tui.py` | Add elapsed time to activity line |
| 14 | `tui.py` | Wire circuit breaker state into status bar |
| 15 | `tui.py` | CSS: ToolPanel border/background styling |

## CSS Changes

```css
#status-bar {
    height: 1;
    color: $text-muted;
    padding: 0 1;
}

ToolPanel {
    border: dashed $surface-lighten-1;
    padding: 0 1;
    margin: 1 0;
    color: $text-muted;
}

ToolPanel.success {
    color: $success;
}

ToolPanel.error {
    color: $error;
}
```

## Verification

### Automated

```bash
# All existing TUI tests pass
uv run pytest tests/repl/test_tui.py tests/repl/test_tui_vim.py -v

# New activity/tool panel tests
uv run pytest tests/repl/test_tui.py -k "activity or tool_panel or status_bar" -v
```

### Manual smoke

1. Start TUI, submit a simple prompt
2. Activity line shows `● streaming...` then `● tool: ...` then `● streaming...` then clears
3. Tool events appear in bordered panel
4. When response finishes: tool panel collapses to summary, activity clears
5. Status bar shows `INSERT input │ chat │ ● streaming... · 2.3s · 1.2k`
6. Submit `/spawn researcher find bugs` — activity shows `● running: researcher` during execution
7. Press F2: status bar shows `NORMAL input │ chat`
8. Submit another prompt: previous tool panel summary is cleared, new one appears

## Review Notes

- Draft 2026-06-13 based on audit of spinner, tool events, footer, and streaming lifecycle
- All changes confined to `tui.py`, `repl.py` (minor), and `test_tui.py`
- No schema changes, no API changes, no LLM pipeline changes
- Removes `_SPINNER_ICONS`, `_SPINNER_PHRASES`, `_format_spinner_status`
