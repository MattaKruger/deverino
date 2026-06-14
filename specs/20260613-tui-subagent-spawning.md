---
title: "TUI Sub-Agent Spawning — User-Initiated /spawn, /tasks, /result, /cancel"
date: 2026-06-13
status: draft
kind: spec
---
# TUI Sub-Agent Spawning — User-Initiated /spawn, /tasks, /result, /cancel

## Objective

Let the user spawn sub-agents directly from the TUI chat input via `/spawn`, manage background
tasks via `/tasks` `/result` `/cancel`, and discover available personas via `/agents`. Everything
runs through the existing `ExecutionEngine.spawn_sub_agent()` entry point.

## Background

The TUI (`ChatApp` in `tui.py`) routes all input through `handle_repl_input` in `repl.py`, which
dispatches known commands (e.g. `/workflow`, `/skill`, `/goal`) and falls through to LLM chat for
unrecognized text. Sub-agents are currently only spawnable _indirectly_ — when the LLM calls
`delegate_task`, or when the workflow orchestrator dispatches tasks.

The V2 `ExecutionEngine` already supports:

- `spawn_sub_agent(agent_type, task_payload, mode="foreground|background")` → `dict[str, Any]`
- `status(task_id)` → `"running" | "done" | "cancelled" | "unknown"`
- `result(task_id)` → `dict[str, Any]` (raises `TaskNotCompleteError`, `TaskCancelledError`, `TaskNotFoundError`)
- `cancel(task_id)` → `bool` (raises `TaskNotFoundError`)

The engine is reachable via `app_state.skill_runner.execution_engine`.

## Design Decisions

### 1. New REPL commands, dispatched before chat fallthrough

The following commands are added to `handle_repl_input`, inserted **before** the `handle_chat_input`
fallthrough, matching the pattern of every other REPL command:

| Command | Action |
|---------|--------|
| `/agents` | List available persona names (from `personas/` dir) |
| `/spawn <persona> [bg] <objective>` | Spawn a sub-agent |
| `/tasks` | List background sub-agent task IDs and statuses |
| `/result <task_id>` | Fetch and display a completed task's result |
| `/cancel <task_id>` | Cancel a running background sub-agent |

`/spawn` defaults to **foreground** mode. Add `bg` after the persona name for background:

```
/spawn architect design the auth module              # foreground — blocks, shows result
/spawn architect bg design the auth module           # background — returns task_id immediately
```

Rationale:
- Foreground gives immediate feedback; background is for longer tasks or parallel work.
- The `bg` keyword is a positional flag after persona — it's unambiguous (persona names don't
  contain spaces) and doesn't require a flag parser.
- `/agents` uses the persona files already on disk (`personas/*.md`).

### 2. No `on_text` streaming for Phase 1

The `_HarnessSpawner` does not yet implement `spawn_streaming()` — the `on_text` parameter on
`spawn_sub_agent()` is accepted but silently ignored. Phase 1 therefore does **not** stream
sub-agent output to the TUI in real time. Foreground mode blocks and displays the full result
when done. Streaming is deferred to a follow-up phase once the spawner is wired.

### 3. Foreground blocking behavior

`spawn_sub_agent(mode="foreground")` calls `_handle_delegate_task` synchronously, which blocks
the REPL worker thread until the sub-agent's LLM call completes. During this time:

- The TUI spinner continues (the worker runs on a thread, Textual's event loop is not blocked).
- No other REPL input can be processed on that thread, but the TUI remains responsive.
- This matches the existing `/goal` command behavior.

For very long foreground tasks, the user can interrupt with a future `/cancel` that targets
the foreground task (deferred — see Non-Goals).

### 4. Background task lifecycle

```
/spawn reviewer bg review this PR   →  displays: "Queued reviewer [task_id: a1b2c3d4]"
/tasks                              →  lists all background tasks with status
/result a1b2c3d4                     →  displays result + removes from pool
/cancel a1b2c3d4                     →  cancels + displays confirmation
```

When the pool is full (`max_background_agents`, default 8), `/spawn … bg` returns an error message.

### 5. Completion support

`/spawn <persona>` and `/agents` get tab-completion via the existing `HarnessCompleter`:

| Completion context | Suggests |
|--------------------|----------|
| `/spawn <TAB>` or `/spawn arc<TAB>` | Persona names (`architect`, `code_reviewer`, `data_validator`, `web_researcher`) |
| `/agents<TAB>` | Completes `/agents` (single token) |

Persona names are discovered by listing `personas/*.md` and taking the stem (matching how
`_skill_names` works for skills).

## Requirements

### R1: `/agents` lists personas

- `user_input` in `{"/agents", "agents"}` triggers `handle_agents_command`
- Outputs a table or bulleted list of persona names, with one-line descriptions extracted from
  the first H1 or first paragraph of each `personas/<name>.md`
- If the `personas/` directory is missing or empty, prints "No personas found."

### R2: `/spawn` foreground

- `/spawn <persona> <objective>` parses persona (first word after `/spawn`) and objective
  (everything else).
- Validates persona exists (`personas/<persona>.md` exists). If missing, prints error listing
  available personas.
- If `ExecutionEngine` is `None` (not wired), prints error: "Sub-agent engine not available."
- Calls `engine.spawn_sub_agent(agent_type=persona, task_payload={"objective": objective},
  mode="foreground", session_id=app_state.session_id)`.
- On success, prints a formatted result block: persona name, output_label, summary, raw_output
  (truncated if very long), task_id.
- On failure (spawner exception), prints the error message. `SubAgentCompleted(status="failed")`
  is already guaranteed by the engine's try/finally — the REPL handler just surfaces the
  returned dict.

### R3: `/spawn` background

- `/spawn <persona> bg <objective>` (the literal token `bg` between persona and objective).
- Validates persona and engine availability (same as foreground).
- Calls `engine.spawn_sub_agent(…, mode="background")`.
- Catches `SubAgentPoolFullError` and prints: "Background pool full (N max). Use /cancel
  <task_id> to free a slot."
- On success, prints: "Queued [persona] [task_id: a1b2c3d4] — check /tasks for status."

### R4: `/tasks` lists background tasks

- `/tasks` (no args) triggers `handle_tasks_command`.
- Calls `engine.status(task_id)` for each known task.
- Outputs a table:

  ```
  Background tasks:
    a1b2c3d4  architect   running    "design the auth module"
    e5f6g7h8  reviewer    done       "review this PR"
  ```

- Task statuses come from `engine.status()`. Task descriptions are pulled from
  `engine._results_cache[task_id]["summary"]` or similar.
- If no background tasks: "No background tasks."

**Open question**: the `ExecutionEngine` doesn't currently expose a `list_tasks()` method.
We either add one, or query `_active_tasks` + `_results_cache` directly. Leaning toward adding
`list_tasks() → dict[str, dict[str, str]]` on the engine (returns `{task_id: {status, persona, objective}}`).

### R5: `/result <task_id>` fetches completed result

- `/result <task_id>` calls `engine.result(task_id)`.
- Catches `TaskNotCompleteError`: "Task <id> is still running. Check /tasks for status."
- Catches `TaskCancelledError`: "Task <id> was cancelled."
- Catches `TaskNotFoundError`: "No task found with id <id>."
- On success, displays the result block (same format as foreground spawn output) and notes
  "Task <id> removed from pool."

### R6: `/cancel <task_id>` cancels a running task

- `/cancel <task_id>` calls `engine.cancel(task_id)`.
- Catches `TaskNotFoundError`: "No task found with id <id>."
- On `True` (was running, now cancelled): "Cancelled task <id>."
- On `False` (already done/cancelled): "Task <id> is already done or cancelled."

### R7: Completion support

- `ROOT_COMMANDS` in `repl_completion.py` gains `"/agents"`, `"/spawn"`, `"/tasks"`, `"/result"`,
  `"/cancel"`.
- `/spawn <TAB>` completes persona names (stems of `personas/*.md`).
- Persona names are added to `ReplCommandCatalog` (new field `personas: tuple[str, ...]`).

### R8: Help text updated

- `print_repl_help()` gains entries for `/agents`, `/spawn`, `/tasks`, `/result`, `/cancel`.

### R9: No TUI panel changes (deferred)

- Phase 1 does **not** add a persistent background-task status widget to the TUI layout.
- Users check status via the `/tasks` command.
- A follow-up phase may add a footer bar or side panel showing active background task count.

### R10: Testability

- Unit tests for `handle_spawn_command`, `handle_tasks_command`, `handle_result_command`,
  `handle_cancel_command` in `tests/repl/`.
- Tests inject a mock `ExecutionEngine` (or use the existing `SpawnerSpy` pattern).
- Completion tests in `tests/repl/test_repl_completion.py` for `/spawn` persona completion.
- No real LLM calls in unit tests.

## Non-Goals

- **Real-time streaming of sub-agent output.** Deferred until `_HarnessSpawner` implements
  `spawn_streaming()`.
- **Persistent TUI panel for background tasks.** Deferred; `/tasks` command suffices for Phase 1.
- **Foreground task cancellation.** Foreground mode blocks the worker thread; cancellation
  would need `threading.Event` or similar. Deferred.
- **Sub-agent-to-sub-agent communication.** Sub-agents run independently.
- **`isolate_session` support from TUI.** The flag exists on the engine but has no user-facing
  benefit until session isolation is implemented end-to-end. Defaults to `False`.

## Implementation Phases

### Phase 1: REPL commands + completion (this spec)

**Files to modify:**

| File | Change |
|------|--------|
| `harness_poc/repl.py` | Add `_is_agents_command`, `handle_agents_command`, `_is_spawn_command`, `handle_spawn_command`, `_is_tasks_command`, `handle_tasks_command`, `_is_result_command`, `handle_result_command`, `_is_cancel_command`, `handle_cancel_command`, `_parse_spawn_command`, `print_spawn_result`. Insert dispatch in `handle_repl_input` ordering: agents → spawn → tasks → result → cancel (before chat fallthrough). Update `print_repl_help`. |
| `harness_poc/repl_completion.py` | Add `"/agents"`, `"/spawn"`, `"/tasks"`, `"/result"`, `"/cancel"` to `ROOT_COMMANDS`. Add `_persona_names()` helper. Extend `completions_for_text` for `"spawn"` root to complete persona names. Add `personas` field to `ReplCommandCatalog`. |
| `harness_poc/v2/execution_engine.py` | Add `list_tasks() → dict[str, dict[str, str]]` public method for `/tasks` command. |
| `tests/repl/test_repl_agent_commands.py` | New file: tests for all five commands with mocked `ExecutionEngine`. |
| `tests/repl/test_repl_completion.py` | Extend with persona completion tests. |

**Dispatch insertion point** (in `handle_repl_input`, before `handle_chat_input`):
```python
if _is_agents_command(user_input):
    handle_agents_command(app_state, user_input)
    return
if _is_spawn_command(user_input):
    handle_spawn_command(app_state, user_input)
    return
if _is_tasks_command(user_input):
    handle_tasks_command(app_state)
    return
if _is_result_command(user_input):
    handle_result_command(app_state, user_input)
    return
if _is_cancel_command(user_input):
    handle_cancel_command(app_state, user_input)
    return
```

### Phase 2 (future): TUI background-task status bar

- Add a footer widget to `ChatApp` showing active background task count and status.
- Update on `SubAgentDispatched` / `SubAgentCompleted` events from the event bus.
- Click/select to view details or cancel.

### Phase 3 (future): Streaming sub-agent output

- Once `_HarnessSpawner` implements `spawn_streaming()`, wire `on_text` through to TUI's
  existing `on_text_chunk` streaming infrastructure.
- Show live sub-agent output in the chat pane (collapsible, or in a side panel).

## Review Notes

- N/A (initial draft)
