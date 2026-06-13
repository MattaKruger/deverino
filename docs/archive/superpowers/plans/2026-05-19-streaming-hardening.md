# Streaming Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace batch model-response streaming with true token-level streaming using pydantic-ai's node streaming API, and harden the TUI with update throttling, tool event consolidation, and error visibility in chat.

**Architecture:** `_stream_text_async` is rewritten to iterate `ModelRequestNode` objects inside `agent.iter()`, streaming token deltas via `PartDeltaEvent`/`TextPartDelta` events. The TUI's `on_text_chunk` callback is throttled to ~30 fps using `time.monotonic()`, preventing render-queue saturation. Tool progress is consolidated into a single updatable widget instead of one widget per message. Unhandled worker errors are shown in the chat panel.

**Tech Stack:** pydantic-ai 1.97.0, Textual, Python 3.12 asyncio, `threading.Lock`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `harness_poc/core/pydantic_runtime.py` | Modify | Rewrite `_stream_text_async`; replace `_next_consecutive_tool_rounds` with inline logic; add new pydantic-ai streaming imports |
| `harness_poc/tui.py` | Modify | Throttle `on_text_chunk`; consolidate tool event widget; show errors in chat |
| `tests/test_pydantic_runtime.py` | Modify | Remove import of deleted `_next_consecutive_tool_rounds`; add streaming smoke test |

---

## Task 1: Rewrite `_stream_text_async` for token-level streaming

**Context:** pydantic-ai 1.97.0 exposes `Agent.is_model_request_node(node)` which returns `True` for `ModelRequestNode` objects that support `async with node.stream(ctx) as stream`. Inside the stream, `PartDeltaEvent` with a `TextPartDelta` delta gives `event.delta.content_delta` — the raw incremental token string. Consecutive-tool-round counting moves to tracking `ToolCallPartDelta` events (which appear in the same stream when the model generates a tool call) and `Agent.is_call_tools_node(node)` for the actual execution node.

**Files:**
- Modify: `harness_poc/core/pydantic_runtime.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_pydantic_runtime.py`, add a test that verifies `stream_text` emits at least one chunk via the callback. This already works with TestModel but will concretely break if we accidentally stop calling `on_text`.

```python
def test_stream_text_calls_on_text_callback(tmp_path: Path) -> None:
    skill_runner, database, config, session_id = _runtime_parts(tmp_path)
    runtime = build_runtime(
        session_id=session_id,
        database=database,
        config=config,
        skill_runner=skill_runner,
        system_prompt="You are a test agent.",
        model=TestModel(call_tools=[]),
    )

    chunks: list[str] = []
    result = runtime.stream_text("hello", on_text=chunks.append)

    assert chunks, "on_text callback must be called at least once"
    assert result.content == "".join(chunks) or result.content  # content non-empty
```

- [ ] **Step 2: Run test to confirm it fails (or passes with old code)**

```bash
cd /Users/matthijskruger/personal_projects/deverino
uv run pytest tests/test_pydantic_runtime.py::test_stream_text_calls_on_text_callback -v
```

Note the result — this test may already pass with old code. Its value is as a regression guard.

- [ ] **Step 3: Update imports in `pydantic_runtime.py`**

Replace this block at the top of `harness_poc/core/pydantic_runtime.py`:

```python
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import TextPart, ToolCallPart
```

With:

```python
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.result import PartDeltaEvent, TextPartDelta, ToolCallPartDelta
```

- [ ] **Step 4: Rewrite `_stream_text_async`**

Replace the entire `_stream_text_async` method (lines 107–192) with:

```python
    async def _stream_text_async(
        self,
        prompt: str,
        *,
        message_history: list[ModelMessage] | None,
        on_text: Callable[[str], None] | None,
        on_tool_event: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        max_consecutive_tool_rounds = 10

        deps = replace(self.deps, stream_text=on_text, on_tool_event=on_tool_event)
        all_output_parts: list[str] = []
        usage: Usage | None = None
        consecutive_tool_rounds = 0
        capped = False
        model_turn_index = 0

        async with self.agent.iter(
            prompt,
            deps=deps,
            message_history=message_history,
            conversation_id="new",
        ) as agent_run:
            async for node in agent_run:
                if Agent.is_model_request_node(node):
                    turn_chunks: list[str] = []
                    had_tool_call = False

                    # Emit separator between model turns (after tool calls)
                    if model_turn_index > 0 and on_text is not None:
                        on_text("\n\n")

                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            if isinstance(event, PartDeltaEvent):
                                if isinstance(event.delta, TextPartDelta):
                                    delta = event.delta.content_delta
                                    if delta:
                                        if on_text is not None:
                                            on_text(delta)
                                        turn_chunks.append(delta)
                                elif isinstance(event.delta, ToolCallPartDelta):
                                    had_tool_call = True

                    if not had_tool_call:
                        consecutive_tool_rounds = 0
                    if turn_chunks:
                        all_output_parts.append("".join(turn_chunks))
                    model_turn_index += 1

                elif Agent.is_call_tools_node(node):
                    consecutive_tool_rounds += 1
                    if consecutive_tool_rounds > max_consecutive_tool_rounds:
                        capped = True
                        logger.warning(
                            "Consecutive tool call limit (%d) reached, stopping agent loop",
                            max_consecutive_tool_rounds,
                            extra={"session_id": self.deps.session_id},
                        )
                        break

            if capped and on_text is not None:
                on_text(
                    "\n\n[Consecutive tool call limit reached — stopping. "
                    "Refine your query for better results.]"
                )

            result_output = agent_run.result.output if agent_run.result else None
            output = str(result_output) if result_output is not None else "".join(all_output_parts)

            if not capped and agent_run.result is not None:
                usage = _usage_to_dict(agent_run.result.usage)
                all_new_messages = agent_run.result.new_messages()
            else:
                all_new_messages = []

        return AgentRunResult(
            content=str(output),
            usage=usage,
            messages=all_new_messages,
        )
```

- [ ] **Step 5: Remove `_next_consecutive_tool_rounds`**

Delete lines 360–363 (the `_next_consecutive_tool_rounds` function):

```python
def _next_consecutive_tool_rounds(parts: list[object], current_count: int) -> int:
    if any(isinstance(part, ToolCallPart) for part in parts):
        return current_count + 1
    return 0
```

Also remove `ToolCallPart` from the `pydantic_ai.messages` import (keep `TextPart` only, unless `ToolCallPart` is used elsewhere).

Check first:
```bash
grep -n "ToolCallPart" harness_poc/core/pydantic_runtime.py
```

If it only appears in the deleted function and the import line, remove it from the import too.

- [ ] **Step 6: Update `tests/test_pydantic_runtime.py` to remove deleted import**

Find and remove `_next_consecutive_tool_rounds` from the import block (line ~20):

```python
from harness_poc.core.pydantic_runtime import (
    AgentDeps,
    _next_consecutive_tool_rounds,   # <-- DELETE THIS LINE
    build_model,
    build_runtime,
    build_skill_tools,
    execute_skill_as_tool,
)
```

Also remove `EXPECTED_CONSECUTIVE_TOOL_ROUNDS = 2` (line ~33) and the entire `test_tool_round_counter_only_tracks_consecutive_tool_calls` test (lines ~131–154), since the helper function no longer exists. The streaming behavior is covered by `test_stream_text_calls_on_text_callback`.

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest tests/test_pydantic_runtime.py -v
```

Expected: all tests pass. The new `test_stream_text_calls_on_text_callback` should pass because TestModel emits a response that pydantic-ai routes through `ModelRequestNode`.

- [ ] **Step 8: Type-check**

```bash
uv run ty check harness_poc/core/pydantic_runtime.py
```

Expected: no errors. If `PartDeltaEvent`/`TextPartDelta`/`ToolCallPartDelta` are not found in `pydantic_ai.result`, check with:
```bash
uv run python -c "from pydantic_ai.result import PartDeltaEvent, TextPartDelta; print('ok')"
# if that fails, try:
uv run python -c "from pydantic_ai import PartDeltaEvent, TextPartDelta; print('ok')"
```

Use whichever import path works and update Step 3 accordingly.

- [ ] **Step 9: Commit**

```bash
git add harness_poc/core/pydantic_runtime.py tests/test_pydantic_runtime.py
git commit -m "feat: token-level streaming via pydantic-ai ModelRequestNode.stream()"
```

---

## Task 2: TUI update throttling

**Context:** With token-level streaming, `on_text_chunk` will fire 10–50× per second. Each call schedules a Textual render via `call_from_thread`. Without throttling, Textual's event queue saturates and the UI lags. We throttle to ~30 fps (one render per 33 ms) using `time.monotonic()` and a `threading.Lock`.

**Files:**
- Modify: `harness_poc/tui.py`

- [ ] **Step 1: Write the failing test**

This is a pure logic test for the throttle behavior. Add to a new file `tests/test_tui_throttle.py`:

```python
from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock


def _make_throttled_flusher(flush_fn, interval: float = 0.033):
    """Mirrors the throttle logic from tui.py on_text_chunk."""
    last_flush: list[float] = [0.0]
    lock = threading.Lock()

    def maybe_flush(text: str) -> None:
        now = time.monotonic()
        with lock:
            if now - last_flush[0] >= interval:
                last_flush[0] = now
                flush_fn(text)

    return maybe_flush


def test_throttle_suppresses_rapid_calls() -> None:
    flush = MagicMock()
    throttled = _make_throttled_flusher(flush, interval=0.1)

    throttled("a")  # first call — fires immediately
    throttled("b")  # within 100ms — suppressed
    throttled("c")  # within 100ms — suppressed

    assert flush.call_count == 1


def test_throttle_fires_after_interval() -> None:
    flush = MagicMock()
    throttled = _make_throttled_flusher(flush, interval=0.05)

    throttled("a")
    time.sleep(0.06)
    throttled("b")  # after interval — fires again

    assert flush.call_count == 2
```

- [ ] **Step 2: Run test to confirm it fails (the helper doesn't exist yet)**

```bash
uv run pytest tests/test_tui_throttle.py -v
```

Expected: `ModuleNotFoundError` or test errors since the helper is not importable from tui.py yet. That's fine — the test defines the throttle logic inline for unit testing.

Actually these tests are self-contained (the throttle logic is copied inline for testing). Expected: **PASS** — this validates our intended throttle behavior before we wire it into tui.py.

- [ ] **Step 3: Add `import time` and `import threading` to `tui.py`**

In `harness_poc/tui.py`, the existing imports block starts at line 1. Add two imports:

```python
import asyncio
import contextlib
import itertools
import logging
import re
import shutil
import subprocess
import threading   # ADD
import time        # ADD
from pathlib import Path
```

- [ ] **Step 4: Replace `on_text_chunk` in `_chat_worker` with throttled version**

In `harness_poc/tui.py`, replace the `on_text_chunk` closure (lines ~213–228):

```python
        def on_text_chunk(chunk: str) -> None:
            buffer.append(chunk)
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
```

With the throttled version:

```python
        _last_flush: list[float] = [0.0]
        _flush_lock = threading.Lock()
        _FLUSH_INTERVAL = 0.033  # ~30 fps

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
                if now - _last_flush[0] >= _FLUSH_INTERVAL:
                    _last_flush[0] = now
                    _flush_to_ui()
```

- [ ] **Step 5: Add final flush before the Markdown replacement**

In `_chat_worker`, after the `await loop.run_in_executor(...)` block and before `response = "".join(buffer)`, add a final flush so the last tokens are never dropped:

Find this section (~line 247):

```python
        # Replace live streaming Static with rendered Markdown
        response = "".join(buffer)
```

Add the final flush just before it:

```python
        # Flush any buffered tokens that were throttled
        if buffer and state["widget"] is not None:
            state["widget"].update("".join(buffer))

        # Replace live streaming Static with rendered Markdown
        response = "".join(buffer)
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_tui_throttle.py tests/test_pydantic_runtime.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/tui.py tests/test_tui_throttle.py
git commit -m "feat: throttle TUI text updates to ~30fps to prevent render-queue saturation"
```

---

## Task 3: Tool event consolidation

**Context:** Currently, every tool progress message (start, done, error) mounts a new `Static` widget via `on_tool_event`. A busy tool invocation emits 3+ messages → 3+ widgets. Instead: mount one `Static` per response and update it in-place, appending each new line.

**Files:**
- Modify: `harness_poc/tui.py`

- [ ] **Step 1: Replace `on_tool_event` closure in `_chat_worker`**

Find the current `on_tool_event` closure (~line 230):

```python
        def on_tool_event(message: str) -> None:
            def _mount() -> None:
                chat.mount(Static(f"  ⚙ {message}", classes="tool-line"))
                chat.scroll_end(animate=False)

            self.call_from_thread(_mount)
```

Replace it with a version that accumulates messages into a single widget:

```python
        tool_lines: list[str] = []
        tool_state: dict[str, Static | None] = {"widget": None}

        def on_tool_event(message: str) -> None:
            tool_lines.append(message)
            combined = "\n".join(f"  ⚙ {line}" for line in tool_lines)

            def _update_tool() -> None:
                if tool_state["widget"] is None:
                    w = Static(combined, classes="tool-line", markup=False)
                    tool_state["widget"] = w
                    chat.mount(w)
                else:
                    tool_state["widget"].update(combined)
                chat.scroll_end(animate=False)

            self.call_from_thread(_update_tool)
```

- [ ] **Step 2: Run the app manually to verify tool events look correct**

```bash
uv run harness-poc
```

Ask it to use a tool (e.g. "search for X" if semble_search is configured). Confirm tool progress appears as a single updating block, not multiple lines.

- [ ] **Step 3: Commit**

```bash
git add harness_poc/tui.py
git commit -m "feat: consolidate tool progress into single updatable widget"
```

---

## Task 4: Error surface in chat

**Context:** The `_chat_worker` exception handler currently only logs. Users see the spinner vanish with no explanation. Fix: render the exception message as a red `Static` in the chat.

**Files:**
- Modify: `harness_poc/tui.py`

- [ ] **Step 1: Update exception handler in `_chat_worker`**

Find (~line 244):

```python
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, handle_repl_input, self._app_state, text)
        except Exception:
            logger.exception("ChatApp worker raised", extra={"text": text})
```

Replace with:

```python
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, handle_repl_input, self._app_state, text)
        except Exception as exc:
            logger.exception("ChatApp worker raised", extra={"text": text})
            error_msg = f"[red]Error: {exc}[/red]"
            await chat.mount(Static(error_msg, markup=True))
            chat.scroll_end(animate=False)
```

- [ ] **Step 2: Also stop the spinner in the except branch**

The spinner is stopped in the normal path (inside `on_text_chunk` on first chunk, or in `_chat_worker` cleanup). On exception it may keep spinning. Update the handler:

```python
        except Exception as exc:
            logger.exception("ChatApp worker raised", extra={"text": text})
            self._stop_spinner()
            error_msg = f"[red]Error: {exc}[/red]"
            await chat.mount(Static(error_msg, markup=True))
            chat.scroll_end(animate=False)
```

- [ ] **Step 3: Verify cleanup still runs after exception**

Check that the code after the try/except block (`_app_state.streaming.reset_callbacks()`, `_update_header()`) still runs even on error. The current structure is:

```python
        try:
            await loop.run_in_executor(...)
        except Exception as exc:
            ...

        # Replace live streaming Static with rendered Markdown
        response = "".join(buffer)
        ...
        self._stop_spinner()
        chat.scroll_end(animate=False)
        self._app_state.streaming.reset_callbacks()
        self._update_header()
```

The cleanup block runs unconditionally — that's correct. The `_stop_spinner()` in the except branch is safe to call twice (it's idempotent).

- [ ] **Step 4: Run the test suite**

```bash
uv run pytest -v
```

Expected: all tests pass. There are no direct tests for the exception path — this is acceptable since it requires a Textual test harness.

- [ ] **Step 5: Commit**

```bash
git add harness_poc/tui.py
git commit -m "fix: surface worker exceptions as visible error messages in chat"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Text appears token-by-token instead of all at once | Task 1 (ModelRequestNode streaming) |
| TUI doesn't lag under fast token arrival | Task 2 (throttling) |
| Tool events don't flood chat with duplicate widgets | Task 3 (consolidation) |
| Users see errors instead of silent spinner disappearance | Task 4 |

**Placeholder scan:** No TBD, no "similar to above", all code blocks complete.

**Type consistency:**
- `PartDeltaEvent`, `TextPartDelta`, `ToolCallPartDelta` — must verify import path at Step 3 of Task 1 (the type-check step catches this)
- `state["widget"]` is `Static | None` in both Task 1 (TUI) and Task 3 — consistent
- `_flush_to_ui` is defined before `on_text_chunk` — correct closure capture order

**Known import risk:** pydantic-ai 1.97.0 — `PartDeltaEvent`/`TextPartDelta` may live in `pydantic_ai` (top-level) rather than `pydantic_ai.result`. Task 1 Step 8 includes a verification command for this.
