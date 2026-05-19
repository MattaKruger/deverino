# Textual Chat TUI Design

**Date:** 2026-05-19
**Status:** Approved

## Goal

Replace the `prompt_toolkit` REPL with a Textual-based chat panel that delivers polished markdown rendering, styled tool progress lines, and a clean single-pane chat UX — without touching any business logic.

## Scope

- Single chat panel, no multi-pane layout
- Formatted markdown for assistant responses
- Visually distinct tool progress lines
- Spinner while model is working
- Provider/model/token header bar
- No live streaming of text (spinner → formatted response pattern)

## Architecture

The change is entirely in the I/O layer. All existing logic — `handle_repl_input`, skills, pipelines, state commands, goal runner — is untouched.

### Files changed

| File | Change |
|---|---|
| `harness_poc/tui.py` | New — `ChatApp`, widgets, inline TCSS |
| `harness_poc/repl.py` | `run_repl` becomes `ChatApp(app_state).run()` |
| `harness_poc/console.py` | Add TUI adapter (module-level `_active_app`, patched print functions) |
| `harness_poc/core/pydantic_runtime.py` | Add `on_tool_event` to `AgentDeps`; fix `_emit_tool_progress` |

### Files not changed

Skills, pipelines, goal runner, workflow runner, database, config, all tests.

## Widget Hierarchy

```
ChatApp
├── Label (id="header")         — "provider · model · tokens", updates after each turn
├── VerticalScroll (id="chat")  — fills remaining height, auto-scrolls to bottom
│   └── (mounted per turn)
│       ├── Static              — user message, cyan "You: {text}"
│       ├── Static (0–N)        — tool progress lines, dim "  ⚙ skill: args..."
│       ├── LoadingIndicator    — visible while model runs, removed on completion
│       └── Markdown            — assistant response, replaces LoadingIndicator
└── Input (id="input")          — fixed footer, placeholder "> ", clears on submit
```

Notes:
- Header is a plain `Label`, not Textual's built-in `Header` widget.
- TCSS lives as `DEFAULT_CSS` string in `tui.py` — no separate `.tcss` file.
- Scroll container auto-scrolls to bottom after each new widget is mounted.

## Response Flow

1. User submits input → `Input.Submitted` fires.
2. App mounts a `Static` with the user message, then a `LoadingIndicator`.
3. App starts a `run_worker(thread=True)` that calls `handle_repl_input`.
4. Worker passes an `on_text` callback that buffers LLM text chunks into a list.
5. Worker passes an `on_tool_event` callback that mounts dim `Static` widgets via `app.call_from_thread()`.
6. When `handle_repl_input` returns, worker removes `LoadingIndicator` and mounts `Markdown(buffered_text)`.
7. App updates the header label with latest token count.

## Tool Progress Separation

**Problem:** `_emit_tool_progress` in `pydantic_runtime.py` currently injects tool status into the `stream_text` / `on_text` callback, mixing tool lines with LLM text in the same buffer.

**Fix:** Add `on_tool_event: Callable[[str], None] | None` to `AgentDeps`. `_emit_tool_progress` switches to `on_tool_event`. The `on_text` buffer receives only LLM text.

```python
@dataclass(frozen=True, slots=True)
class AgentDeps:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    stream_text: Callable[[str], None] | None = None     # LLM text buffer
    on_tool_event: Callable[[str], None] | None = None   # tool progress lines
```

## Console Adapter

`console.py` gains a module-level `_active_app: ChatApp | None` reference.

- `set_tui_app(app)` — called on `ChatApp` startup.
- `clear_tui_app()` — called on exit.
- `print_markdown`, `print_error`, `console.print` — check `_active_app`; if set, mount the appropriate widget via `call_from_thread`; otherwise fall through to the existing Rich `Console`.

No callers of these functions need to change.

## Threading Model

Textual runs on an asyncio event loop. All blocking calls (LLM inference, skill execution, DB writes) run in `run_worker(thread=True)`. Widget mutations from the worker go through `app.call_from_thread()`.

## Non-Goals

- Live streaming of text into a widget (deferred — requires debouncing Markdown re-renders)
- Multi-pane layout (side panel for tool calls, etc.)
- Custom bubble-style message widgets
- Mouse interaction beyond scrolling
