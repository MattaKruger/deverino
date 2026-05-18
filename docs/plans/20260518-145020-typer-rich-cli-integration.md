# Typer/Rich CLI Integration Plan

Created: 2026-05-18 14:50:20 Europe/Brussels

## Goal

Integrate Typer and Rich into the existing harness CLI without disrupting the current interactive proof-of-concept loop.

The desired result is a clearer command surface, richer terminal output, better command help, and testable CLI entrypoints while preserving the existing state, workflow, skill, and chat behavior.

## Current CLI Shape

The current entrypoint is `harness_poc.main:main`, exposed as the `harness-poc` script in `pyproject.toml`.

`harness_poc/main.py` currently:

- Builds one `AppState` with config, SQLite blackboard, skill runner, workflow runner, LLM client, messages, and discovered tools.
- Starts an interactive REPL immediately.
- Parses commands manually from raw input strings.
- Handles these command families:
  - `workflow <name> <objective>`
  - `state show|note|decision|next|question|changelog|propose|approve|reject`
  - `skill list|show|create`
  - otherwise chat input to the LLM/tool loop
- Uses direct `print()` and `input()` throughout.

This is small and understandable, but it makes command behavior harder to test, discover, extend, and format consistently.

## Library Fit

Typer is a good fit for the outer CLI because it provides typed commands, subcommands, options, arguments, prompts, confirmation helpers, Rich-powered help output, and `CliRunner` testing.

Rich is a good fit for presentation because the app already prints markdown-like state, command summaries, skill lists, streamed model output, and operational status messages. Rich can improve these without changing core behavior.

Use Typer for command routing. Use Rich for output rendering. Do not move core workflow, state, or skill behavior into Typer callback bodies.

## Proposed Command Model

Keep `harness-poc` usable with no arguments by launching the current REPL for backward compatibility.

Add explicit commands:

```text
harness-poc repl
harness-poc workflow run <name> <objective>
harness-poc state show [project|session|all]
harness-poc state note <text>
harness-poc state decision <text>
harness-poc state next <text>
harness-poc state question <text>
harness-poc state changelog <entry>
harness-poc state propose
harness-poc state approve [proposal-id]
harness-poc state reject <proposal-id>
harness-poc skill list
harness-poc skill show <name>
harness-poc skill create <name> <description>
```

Optional later commands:

```text
harness-poc chat <message>
harness-poc workflow list
harness-poc config show
harness-poc session start --objective <text>
```

## Proposed Module Structure

Split CLI routing from application behavior:

```text
harness_poc/
  main.py              # script-compatible shim; imports cli.app
  cli.py               # Typer app, command groups, global options
  console.py           # Rich Console factory and render helpers
  repl.py              # interactive loop, still line-oriented
  core/
    ...
```

Keep `_build_app_state()` either in `main.py` temporarily or move it to a small `app_factory.py` module once command tests need it.

Recommended final structure:

```text
harness_poc/
  app_factory.py       # build_app_state()
  cli.py               # Typer commands
  console.py           # Rich output helpers
  repl.py              # REPL loop using shared command handlers
  main.py              # def main(): app()
```

## Implementation Plan

### Phase 1: Dependencies and Entry Point

Add runtime dependencies:

```toml
dependencies = [
    "openai>=2.37.0",
    "pydantic-settings>=2.14.1",
    "pyyaml>=6.0.2",
    "rich>=13.0.0",
    "typer>=0.21.1",
]
```

Then run `uv lock` or `uv sync` so `uv.lock` reflects the new dependencies.

Update `harness_poc/main.py` so `main()` delegates to the Typer app. Preserve the direct `python harness_poc/main.py` path.

### Phase 2: Extract Reusable Handlers

Separate command logic from string parsing:

- Keep existing handler internals for workflow, state, skill, and chat.
- Add function-level handlers that accept parsed values rather than raw command strings.
- Make the REPL call those handlers after its own line parsing.
- Make Typer commands call the same handlers directly.

This keeps the first behavior change small: Typer becomes a new front door, not a rewrite of the application.

### Phase 3: Add Typer Command Groups

Create:

```python
app = typer.Typer(
    name="harness-poc",
    help="Interactive LLM harness proof of concept.",
    rich_markup_mode="rich",
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
)

state_app = typer.Typer(help="Manage durable project and session state.")
skill_app = typer.Typer(help="Manage executable skills.")
workflow_app = typer.Typer(help="Run deterministic workflow YAML files.")
```

Use `@app.callback(invoke_without_command=True)` to launch `repl` when no subcommand is provided. This preserves `harness-poc` behavior.

Use type annotations and `typing.Annotated` for arguments/options so command help is self-documenting.

### Phase 4: Introduce Rich Rendering

Start with safe output improvements:

- Use `Console.print()` instead of raw `print()` for non-streaming output.
- Render state markdown with `rich.markdown.Markdown`.
- Render skill lists with `rich.table.Table`.
- Render workflow summaries as a short status line plus table of state outputs.
- Use `console.status()` around slow startup/workflow operations only when output is not already streaming.
- Use `console.print_exception(show_locals=False)` only behind a debug/verbose option.

Avoid using Rich formatting inside model-stream chunks at first. Keep streamed LLM text plain so token streaming remains predictable.

### Phase 5: Preserve REPL Ergonomics

The REPL should remain line-oriented:

```text
> state show project
> workflow research_task compare approaches
> skill list
> hello model
```

Use Rich for startup banners, help text, state rendering, and errors, but keep the prompt itself simple unless adopting a real prompt library later.

Do not require users to type Typer-style subcommands inside the REPL. The REPL is the conversational shell; Typer is the outer process CLI.

### Phase 6: Testing

Add CLI tests with Typer's `CliRunner`.

Recommended test coverage:

- `harness-poc --help` exits 0 and includes state/skill/workflow groups.
- `harness-poc state show project` renders the project state.
- `harness-poc skill list` includes system and project skills.
- `harness-poc skill show read_memory` renders the skill document.
- `harness-poc workflow run missing objective` produces a clear usage error.
- No-argument invocation is tested with monkeypatched REPL entrypoint so it does not block.

For Rich output tests, either:

- Create a test console with `Console(file=StringIO(), force_terminal=False, width=120)`, or
- Assert on Typer result output after avoiding style-dependent exact formatting.

## Design Constraints

- Preserve existing command strings inside the REPL.
- Preserve current `harness-poc` default behavior by launching the REPL when no arguments are provided.
- Keep state mutations in existing database methods, not in CLI presentation code.
- Keep workflow execution in `WorkflowRunner`.
- Keep skill execution in `SkillRunner`.
- Avoid making Rich styling part of behavioral assertions.
- Do not introduce async CLI behavior in this pass.

## Risks and Mitigations

### Risk: Typer no-args behavior conflicts with REPL startup

Mitigation: use an app callback with `invoke_without_command=True`, inspect `ctx.invoked_subcommand`, and call `repl()` only when no subcommand was invoked.

### Risk: Duplicate command parsing between REPL and Typer

Mitigation: extract handler functions that accept structured arguments. Keep REPL parsing as compatibility glue only.

### Risk: Rich output makes tests brittle

Mitigation: centralize Rich rendering in `console.py`, inject or construct deterministic consoles in tests, and assert semantic text instead of ANSI styling.

### Risk: Exceptions become noisier

Mitigation: keep current friendly error messages by default. Enable rich tracebacks only with `--debug` or `--verbose`.

### Risk: Chat streaming becomes garbled

Mitigation: leave `_print_stream_chunk()` plain initially, or route it through `console.out(..., end="")` only after verifying streaming behavior.

## Suggested First Patch

The first implementation patch should be deliberately narrow:

1. Add `typer` and `rich` dependencies.
2. Create `harness_poc/cli.py`, `harness_poc/console.py`, and `harness_poc/repl.py`.
3. Move `_run_repl()` to `repl.py` with minimal changes.
4. Add Typer `state show`, `skill list`, and `workflow run` commands.
5. Keep all old parsing helpers until equivalent Typer commands are covered.
6. Add basic `CliRunner` tests for help, state show, and skill list.
7. Run `uv run ruff check .`, `uv run ty check`, and targeted tests.

## Acceptance Criteria

- `uv run harness-poc` still opens the interactive REPL.
- `uv run harness-poc repl` opens the interactive REPL.
- `uv run harness-poc state show project` prints the same project state content as the current REPL command.
- `uv run harness-poc skill list` lists all discovered system and project skills.
- `uv run harness-poc workflow run research_task "<objective>"` executes the same workflow as `workflow research_task <objective>` in the REPL.
- Startup/config/database errors still produce concise user-facing messages.
- Ruff and ty pass.
