# Textual Chat TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the prompt_toolkit REPL I/O layer with a Textual-based chat panel delivering formatted markdown responses, styled tool progress lines, and a polished single-pane chat UX.

**Architecture:** `ChatApp(App)` in `harness_poc/tui.py` replaces the `PromptSession` loop. A `StreamingContext` dataclass on `AppState` carries replaceable callbacks so the TUI buffers LLM text and routes tool events to separate widgets. All business logic is untouched.

**Tech Stack:** Textual ≥1.0.0 (new), Rich (existing), pytest-asyncio ≥0.24.0 (new dev dep), Python 3.12

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add Textual and pytest-asyncio**

In `pyproject.toml`, update `dependencies` and `[dependency-groups]`, and add `[tool.pytest.ini_options]`:

```toml
dependencies = [
    "openai>=2.37.0",
    "prompt-toolkit>=3.0.52",
    "pydantic-settings>=2.14.1",
    "pyyaml>=6.0.2",
    "tiktoken>=0.7.0",
    "rich>=15.0.0",
    "typer>=0.25.1",
    "pydantic-ai>=1.97.0",
    "logfire[pydantic-ai]>=4.33.0",
    "textual>=1.0.0",
]

[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "ruff>=0.14.0",
    "ty>=0.0.1a22",
    "pytest-asyncio>=0.24.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Sync and verify**

```bash
uv sync
uv run python -c "import textual; print(textual.__version__)"
```

Expected: version string printed, no errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add textual and pytest-asyncio dependencies"
```

---

### Task 2: Add StreamingContext to AppState

**Files:**
- Modify: `harness_poc/app_factory.py`
- Modify: `harness_poc/repl.py`
- Create: `tests/test_streaming_context.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streaming_context.py`:

```python
from __future__ import annotations

from harness_poc.app_factory import StreamingContext


def test_default_on_text_prints(capsys: object) -> None:
    ctx = StreamingContext()
    ctx.on_text("hello")
    captured = capsys.readouterr()  # type: ignore[union-attr]
    assert captured.out == "hello"


def test_default_on_finish_prints_newline(capsys: object) -> None:
    ctx = StreamingContext()
    ctx.on_finish("some content")
    captured = capsys.readouterr()  # type: ignore[union-attr]
    assert captured.out == "\n"


def test_default_on_finish_noop_for_empty(capsys: object) -> None:
    ctx = StreamingContext()
    ctx.on_finish("")
    captured = capsys.readouterr()  # type: ignore[union-attr]
    assert captured.out == ""


def test_on_text_is_replaceable() -> None:
    collected: list[str] = []
    ctx = StreamingContext()
    ctx.on_text = collected.append
    ctx.on_text("a")
    ctx.on_text("b")
    assert collected == ["a", "b"]


def test_on_tool_event_defaults_none() -> None:
    ctx = StreamingContext()
    assert ctx.on_tool_event is None


def test_session_tokens_accumulate() -> None:
    ctx = StreamingContext()
    ctx.session_tokens += 100
    ctx.session_tokens += 200
    assert ctx.session_tokens == 300


def test_reset_callbacks_restores_defaults_and_preserves_tokens(capsys: object) -> None:
    ctx = StreamingContext()
    ctx.session_tokens = 500
    ctx.on_text = lambda _: None  # replace default
    ctx.on_tool_event = lambda _: None
    ctx.on_finish = lambda _: None

    ctx.reset_callbacks()

    # Callbacks restored to defaults
    ctx.on_text("x")
    captured = capsys.readouterr()  # type: ignore[union-attr]
    assert captured.out == "x"
    assert ctx.on_tool_event is None
    # Token count preserved
    assert ctx.session_tokens == 500
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_streaming_context.py -v
```

Expected: `ImportError` — `StreamingContext` does not exist yet.

- [ ] **Step 3: Add StreamingContext and wire AppState**

In `harness_poc/app_factory.py`, add these imports at the top (after existing imports):

```python
from collections.abc import Callable
from dataclasses import dataclass, field
```

Add these module-level functions and `StreamingContext` class before the `AppState` class:

```python
def _default_on_text(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _default_on_finish(content: str) -> None:
    if content:
        print()


@dataclass
class StreamingContext:
    on_text: Callable[[str], None] = field(default_factory=lambda: _default_on_text)
    on_tool_event: Callable[[str], None] | None = None
    on_finish: Callable[[str], None] = field(default_factory=lambda: _default_on_finish)
    session_tokens: int = 0

    def reset_callbacks(self) -> None:
        self.on_text = _default_on_text
        self.on_tool_event = None
        self.on_finish = _default_on_finish
```

Add `streaming: StreamingContext` as the last field of `AppState`:

```python
@dataclass(slots=True)
class AppState:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    pipeline_runner: PipelineRunner
    pydantic_runtime: PydanticAgentRuntime
    pydantic_messages: list[ModelMessage]
    goal_decision_model: Model | None
    messages: list[Message]
    tools: list[dict[str, Any]]
    event_bus: EventBus
    streaming: StreamingContext
```

Add `streaming=StreamingContext()` to the `AppState(...)` constructor call at the end of `build_app_state()`.

- [ ] **Step 4: Update handle_chat_input and handle_goal_command in repl.py**

In `harness_poc/repl.py`, update `_track_tokens` to accumulate into `AppState.streaming`:

```python
def _track_tokens(usage: Usage | None, app_state: AppState) -> None:
    if usage is not None:
        app_state.streaming.session_tokens += usage.get("total_tokens", 0)
```

Remove the now-unused module-level `_session_token_count` and `_session_cache_hit_tokens` variables.

Replace `handle_chat_input`:

```python
def handle_chat_input(app_state: AppState, user_input: str) -> None:
    app_state.messages.append({"role": "user", "content": user_input})

    try:
        response = app_state.pydantic_runtime.stream_text(
            user_input,
            message_history=app_state.pydantic_messages,
            on_text=app_state.streaming.on_text,
        )
        _track_tokens(response.usage, app_state)
        if response.messages:
            app_state.pydantic_messages.extend(response.messages)
            if len(app_state.pydantic_messages) > MAX_PYDANTIC_MESSAGES:
                excess = len(app_state.pydantic_messages) - MAX_PYDANTIC_MESSAGES
                app_state.pydantic_messages = app_state.pydantic_messages[excess:]
        else:
            _append_pydantic_chat_exchange(app_state, user_input, response.content)
        app_state.messages.append({"role": "assistant", "content": response.content})
        app_state.streaming.on_finish(response.content)
    except sqlite3.OperationalError as exc:
        print_error(f"Database operation failed: {exc}")
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print_error(f"Tool execution failed: {exc}")
```

In `handle_goal_command`, change `on_text=_print_stream_chunk` to `on_text=app_state.streaming.on_text`.

Remove the now-unused `_print_stream_chunk` and `_finish_stream_line` functions.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_streaming_context.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
uv run pytest -x
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/app_factory.py harness_poc/repl.py tests/test_streaming_context.py
git commit -m "feat: add StreamingContext to AppState for replaceable streaming callbacks"
```

---

### Task 3: Add on_tool_event to AgentDeps

**Files:**
- Modify: `harness_poc/core/pydantic_runtime.py`
- Create: `tests/test_tool_event_callback.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_event_callback.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from harness_poc.core.pydantic_runtime import AgentDeps, _emit_tool_progress


def _make_ctx(on_tool_event: object = None) -> object:
    deps = AgentDeps(
        session_id="test",
        database=MagicMock(),
        config=MagicMock(),
        skill_runner=MagicMock(),
        on_tool_event=on_tool_event,
    )
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def test_emit_tool_progress_calls_handler() -> None:
    events: list[str] = []
    ctx = _make_ctx(on_tool_event=events.append)
    _emit_tool_progress(ctx, "my_skill: running...")
    assert events == ["my_skill: running..."]


def test_emit_tool_progress_noop_when_no_handler() -> None:
    ctx = _make_ctx(on_tool_event=None)
    _emit_tool_progress(ctx, "my_skill: running...")  # must not raise


def test_agent_deps_on_tool_event_defaults_none() -> None:
    deps = AgentDeps(
        session_id="s",
        database=MagicMock(),
        config=MagicMock(),
        skill_runner=MagicMock(),
    )
    assert deps.on_tool_event is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tool_event_callback.py -v
```

Expected: `TypeError` — `AgentDeps` has no `on_tool_event` field.

- [ ] **Step 3: Add on_tool_event to AgentDeps**

In `harness_poc/core/pydantic_runtime.py`, update `AgentDeps`:

```python
@dataclass(frozen=True, slots=True)
class AgentDeps:
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
    skill_runner: SkillRunner
    stream_text: Callable[[str], None] | None = None
    on_tool_event: Callable[[str], None] | None = None
```

- [ ] **Step 4: Update stream_text and _stream_text_async**

Update `stream_text` method:

```python
def stream_text(
    self,
    prompt: str,
    *,
    message_history: list[ModelMessage] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_tool_event: Callable[[str], None] | None = None,
) -> AgentRunResult:
    logger.debug(
        "Streaming PydanticAI text request",
        extra={
            "session_id": self.deps.session_id,
            "history_length": len(message_history or []),
        },
    )
    return asyncio.run(
        self._stream_text_async(
            prompt,
            message_history=message_history,
            on_text=on_text,
            on_tool_event=on_tool_event,
        ),
    )
```

Update `_stream_text_async` signature and the `deps = replace(...)` line:

```python
async def _stream_text_async(
    self,
    prompt: str,
    *,
    message_history: list[ModelMessage] | None,
    on_text: Callable[[str], None] | None,
    on_tool_event: Callable[[str], None] | None = None,
) -> AgentRunResult:
    max_tool_rounds = 5

    deps = replace(self.deps, stream_text=on_text, on_tool_event=on_tool_event)
    # ... rest of method unchanged
```

- [ ] **Step 5: Fix _emit_tool_progress**

Replace the `_emit_tool_progress` function:

```python
def _emit_tool_progress(ctx: RunContext[AgentDeps], message: str) -> None:
    handler = ctx.deps.on_tool_event
    if handler is not None:
        handler(message)
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_tool_event_callback.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 7: Run full suite**

```bash
uv run pytest -x
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add harness_poc/core/pydantic_runtime.py tests/test_tool_event_callback.py
git commit -m "feat: add on_tool_event to AgentDeps and fix _emit_tool_progress routing"
```

---

### Task 4: Add TUI adapter to console.py and update repl.py callers

**Files:**
- Modify: `harness_poc/console.py`
- Modify: `harness_poc/repl.py`
- Create: `tests/test_console_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_console_adapter.py`:

```python
from __future__ import annotations

import harness_poc.console as cons


def setup_function() -> None:
    cons.clear_tui_handlers()


def teardown_function() -> None:
    cons.clear_tui_handlers()


def test_print_text_uses_rich_when_no_tui() -> None:
    cons.print_text("hello plain")  # must not raise


def test_set_tui_handlers_routes_markdown() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=received.append,
        on_error=lambda _: None,
        on_text=lambda _t, _m: None,
    )
    cons.print_markdown("# hi")
    assert received == ["# hi"]


def test_set_tui_handlers_routes_error() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=lambda _: None,
        on_error=received.append,
        on_text=lambda _t, _m: None,
    )
    cons.print_error("bad")
    assert received == ["bad"]


def test_set_tui_handlers_routes_text() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=lambda _: None,
        on_error=lambda _: None,
        on_text=lambda t, _m: received.append(t),
    )
    cons.print_text("hello")
    assert received == ["hello"]


def test_clear_tui_handlers_reverts_to_rich() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=received.append,
        on_error=lambda _: None,
        on_text=lambda _t, _m: None,
    )
    cons.clear_tui_handlers()
    cons.print_markdown("# hi")
    assert received == []


def test_print_text_markup_false_forwarded() -> None:
    received: list[tuple[str, bool]] = []
    cons.set_tui_handlers(
        on_markdown=lambda _: None,
        on_error=lambda _: None,
        on_text=lambda t, m: received.append((t, m)),
    )
    cons.print_text("[state show]", markup=False)
    assert received == [("[state show]", False)]
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_console_adapter.py -v
```

Expected: `AttributeError` — `set_tui_handlers`, `clear_tui_handlers`, `print_text` do not exist yet.

- [ ] **Step 3: Rewrite console.py**

Replace the entire contents of `harness_poc/console.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.skill_runner import SkillRunner
    from harness_poc.core.workflow_runner import WorkflowRunResult


console = Console()

_tui_on_markdown: Callable[[str], None] | None = None
_tui_on_error: Callable[[str], None] | None = None
_tui_on_text: Callable[[str, bool], None] | None = None


def set_tui_handlers(
    *,
    on_markdown: Callable[[str], None],
    on_error: Callable[[str], None],
    on_text: Callable[[str, bool], None],
) -> None:
    global _tui_on_markdown, _tui_on_error, _tui_on_text  # noqa: PLW0603
    _tui_on_markdown = on_markdown
    _tui_on_error = on_error
    _tui_on_text = on_text


def clear_tui_handlers() -> None:
    global _tui_on_markdown, _tui_on_error, _tui_on_text  # noqa: PLW0603
    _tui_on_markdown = None
    _tui_on_error = None
    _tui_on_text = None


def print_markdown(markdown: str) -> None:
    if _tui_on_markdown is not None:
        _tui_on_markdown(markdown)
    else:
        console.print(Markdown(markdown))


def print_error(message: str) -> None:
    if _tui_on_error is not None:
        _tui_on_error(message)
    else:
        console.print(f"[red]{message}[/red]")


def print_text(text: str, *, markup: bool = True) -> None:
    if _tui_on_text is not None:
        _tui_on_text(text, markup)
    else:
        console.print(text, markup=markup)


def print_skill_table(skill_files: list[Path], skill_runner: SkillRunner) -> None:
    if not skill_files:
        print_text("No skills found.")
        return

    table = Table(title="Skills")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("Description")

    for skill_file in skill_files:
        skill = skill_runner.parse_skill_document(skill_file)
        metadata = skill["metadata"]
        source = (
            "system"
            if skill_file.is_relative_to(skill_runner.config.paths.system_skills)
            else "project"
        )
        table.add_row(metadata["name"], source, metadata["description"])

    console.print(table)


def print_workflow_result(result: WorkflowRunResult) -> None:
    print_text(
        f"Workflow [cyan]{result.workflow_name}[/cyan] completed with status: "
        f"[green]{result.status}[/green]"
    )
    if result.outputs:
        table = Table(title="Workflow States")
        table.add_column("State", style="cyan", no_wrap=True)
        table.add_column("Skill", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        for output in result.outputs:
            table.add_row(output.state_name, output.skill_name, output.result.status)
        console.print(table)
    print_text(result.final_content)
```

- [ ] **Step 4: Replace console.print calls in repl.py**

Update the import in `harness_poc/repl.py`:

```python
from harness_poc.console import console, print_error, print_markdown, print_skill_table, print_text
```

Then replace every `console.print(...)` call with `print_text(...)`. The full mapping:

`run_repl` startup block:
```python
print_text(f"Started session: [cyan]{app_state.session_id}[/cyan]")
print_text("Type 'exit' or 'quit' to stop.")
print_text("Run an explicit workflow with: workflow research_task <objective>")
print_text("Run a pipeline with: pipeline <name> [key=value ...]")
print_text("Run an autonomous goal loop with: /goal <objective>")
print_text("Manage STATE with: state show | state note <text> | state propose")
print_text("Manage skills with: skill list | skill create <name> <description>")
print_text("Type '/' and press Tab to discover slash commands.")
```

`print_repl_help`:
```python
def print_repl_help() -> None:
    print_text(
        """REPL commands:
  /goal <objective>
  /workflow <name> <objective>
  /workflows
  /pipeline <name> [key=value ...]
  /pipelines
  /state show [project|session|all]
  /state note <text>
  /state consolidate [preview|propose|approve]
  /skill list
  /skill show <name>
  /skills
  /help
  /exit

Non-slash forms still work: goal, workflow, state, skill, exit, quit.""",
        markup=False,
    )
```

`run_workflow`:
```python
print_text(summary)
```

`list_pipelines`:
```python
print_text("[dim]No pipelines found.[/dim]")
print_text(f"  {name}")
```

`run_pipeline`:
```python
print_text(
    f"\n[{status_color}]Pipeline '{pipeline_name}': {result.status}[/{status_color}]"
    f" ({result.duration_s:.1f}s)\n"
)
print_text(f"  [{node_color}]{node_id}: {node_result.status}[/{node_color}]")
```

`list_workflows`:
```python
print_text("No workflows found.")
print_text(f"- {workflow_file.stem}")
```

`handle_state_command`:
```python
print_text(f"Unknown state command: {command}")
```

`append_session_state`:
```python
print_text(f"Added session state {section}: {argument}")
```

`propose_state`:
```python
print_text(f"Created state proposal: [cyan]{proposal.proposal_id}[/cyan]")
```

`approve_state`:
```python
print_text(f"Approved state proposal: {proposal_id}")
```

`reject_state`:
```python
print_text(f"Rejected state proposal: {proposal_id}")
```

`consolidate_state` — replace the bare `console.print`:
```python
print_text(result.content)
```

`print_state_help`:
```python
def print_state_help() -> None:
    print_text(
        """State commands:
  state show [project|session]
  state note <text>
  state decision <text>
  state next <text>
  state question <text>
  state changelog <entry>
  state propose
  state approve [proposal_id]
  state reject <proposal_id>
  state consolidate [preview|propose|approve]""",
        markup=False,
    )
```

`execute_named_skill`:
```python
print_text(result.content)
```

`create_skill`:
```python
print_text(f"Created skill: [cyan]{scaffolded.skill_name}[/cyan]")
print_text(f"- {path.relative_to(app_state.config.project_root)}")
```

`print_skill_help`:
```python
def print_skill_help() -> None:
    print_text(
        """Skill commands:
  skill list
  skill show <name>
  skill create <name> <description>
  skill <name> [args|key=value|json-object]""",
        markup=False,
    )
```

`handle_skill_command`:
```python
print_text(f"Unknown skill command: {command}")
```

`handle_goal_command`:
```python
print_text("[cyan]Starting autonomous goal loop...[/cyan]")
print_text(f"Goal: [bold]{objective}[/bold]")
print_text("")
```

`_print_goal_result`:
```python
print_text("")
print_text(f"[{color}]Status: {result.status}[/{color}]")
print_text(f"Iterations: {result.iterations}")
print_text(f"Total tokens: {result.total_tokens}")
print_text("")
print_text("")
print_text("[dim]--- Event Log ---[/dim]")
print_text(f"[dim]{i}. [{event_type}] {tool}{extra}[/dim]")
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_console_adapter.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
uv run pytest -x
```

Expected: all tests pass.

- [ ] **Step 7: Lint**

```bash
uv run ruff check harness_poc/console.py harness_poc/repl.py
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add harness_poc/console.py harness_poc/repl.py tests/test_console_adapter.py
git commit -m "feat: add TUI adapter to console and replace console.print with print_text in repl"
```

---

### Task 5: Create harness_poc/tui.py

**Files:**
- Create: `harness_poc/tui.py`
- Create: `tests/test_tui.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from harness_poc.app_factory import StreamingContext
from harness_poc.tui import ChatApp


def _make_app_state() -> object:
    state = MagicMock()
    state.config.llm.provider = "test-provider"
    state.config.llm.model = "test-model"
    state.streaming = StreamingContext()
    return state


async def test_chat_app_composes() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        assert pilot.app.query_one("#header")
        assert pilot.app.query_one("#chat")
        assert pilot.app.query_one("#input")


async def test_chat_app_exit_on_quit() -> None:
    app = ChatApp(_make_app_state())
    async with app.run_test() as pilot:
        await pilot.press("q", "u", "i", "t", "enter")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tui.py -v
```

Expected: `ImportError` — `harness_poc.tui` does not exist.

- [ ] **Step 3: Create harness_poc/tui.py**

Create `harness_poc/tui.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, LoadingIndicator, Markdown, Static

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
        from harness_poc.console import set_tui_handlers

        set_tui_handlers(
            on_markdown=self._tui_print_markdown,
            on_error=self._tui_print_error,
            on_text=self._tui_print_text,
        )
        self._update_header()
        self.query_one(Input).focus()

    def on_unmount(self) -> None:
        from harness_poc.console import clear_tui_handlers

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
        from harness_poc.repl import handle_repl_input

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

    def _tui_print_text(self, text: str, markup: bool = True) -> None:
        def _mount() -> None:
            chat = self.query_one("#chat", VerticalScroll)
            chat.mount(Static(text, markup=markup))
            chat.scroll_end(animate=False)

        self.call_from_thread(_mount)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tui.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -x
```

Expected: all tests pass.

- [ ] **Step 6: Lint**

```bash
uv run ruff check harness_poc/tui.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/tui.py tests/test_tui.py
git commit -m "feat: add ChatApp Textual TUI with markdown rendering and tool progress"
```

---

### Task 6: Wire run_repl to ChatApp

**Files:**
- Modify: `harness_poc/repl.py`

- [ ] **Step 1: Replace run_repl**

In `harness_poc/repl.py`, replace the `run_repl` function body:

```python
def run_repl(app_state: AppState) -> None:
    from harness_poc.tui import ChatApp

    ChatApp(app_state).run()
```

Remove these now-unused items from `repl.py`:
- `from prompt_toolkit import PromptSession`
- `from prompt_toolkit.formatted_text import FormattedText`
- `from prompt_toolkit.history import FileHistory`
- `from harness_poc.repl_completion import HarnessCompleter`
- The `_build_prompt_bar` function
- The `TOKEN_MILLION` and `TOKEN_THOUSAND` constants (token formatting moved to `tui.py`)

Keep: `_track_tokens`, `_format_tokens` — `_track_tokens` is called in `handle_chat_input`; `_format_tokens` is kept for now (can be removed later, it's no longer called from repl but removing it is a separate cleanup).

- [ ] **Step 2: Lint**

```bash
uv run ruff check harness_poc/repl.py
```

Fix any unused import or variable warnings reported.

- [ ] **Step 3: Run full suite**

```bash
uv run pytest -x
```

Expected: all tests pass.

- [ ] **Step 4: Smoke test the TUI**

```bash
uv run harness-poc
```

Expected: Textual app launches in alternate screen mode. You see a one-line header with provider and model, an empty chat area, and an input at the bottom. Type a message — the `You:` line appears immediately, a spinner shows while the model works, and the response renders as formatted markdown. Tool calls (if any) appear as dim `⚙` lines above the response.

- [ ] **Step 5: Commit**

```bash
git add harness_poc/repl.py
git commit -m "feat: wire run_repl to ChatApp — Textual TUI replaces prompt_toolkit REPL"
```
