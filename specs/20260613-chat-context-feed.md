---
title: "Chat Context Feed — bridging sub-agent findings into main chat history"
date: 2026-06-13
status: draft
kind: spec
---
# Chat Context Feed — bridging sub-agent findings into main chat history

## Objective

Let the user spawn a sub-agent (e.g. architect) from pipeline mode, then switch
back to chat mode and have the chat LLM see the sub-agent's findings in its
history — without manual copy-paste. A `/feed` command and a `--feed` flag on
`/spawn` bridge sub-agent results from the blackboard into
`app_state.pydantic_messages`.

## Background

When `/spawn architect design auth` completes, the V2 handler writes a
`DelegatedTaskOutput` to the blackboard under the task's UUID key (step 6 of
`_handle_delegate_task`):

```python
blackboard.write(task_id=raw.task_id, output=output, session_id=session_id)
# → db.write_memory(session_id, task_id, output)
```

The chat agent's history lives in `app_state.pydantic_messages: list[ModelMessage]`.
When the user switches from pipeline → chat mode, the chat history is unchanged —
the sub-agent's findings are on disk but invisible to the LLM.

## Design

### 1. `/feed <task_id>` command

Reads the `DelegatedTaskOutput` from blackboard memory and appends a synthetic
assistant message to `app_state.pydantic_messages`:

```
[assistant] Architect findings (task abc123):
  Recommendation: use OAuth2 with PKCE for the auth module
  Approaches: ...
```

After feeding, the chat LLM sees the findings in its history on the next turn.

**Implementation:**
- Read from `app_state.database.read_memory(session_id, task_id)` — returns the
  `DelegatedTaskOutput` dict
- Format as markdown using the existing `_format_raw_output` helper
- Append as a `ModelRequest(parts=[TextPart(content=formatted)])` with
  `role="assistant"` (or `role="user"` prefixed with a context label)
- Prints confirmation: "Fed architect findings (task abc123) to chat."

**Error cases:**
- Task not found → "No result found for task <id>."
- Already fed → idempotent (re-feeding the same task overwrites or is a no-op)
- Chat mode required → if in pipeline/react mode, switch first or warn

### 2. `--feed` flag on `/spawn`

```
/spawn architect --feed design the auth module
```

Spawns the sub-agent (foreground), displays the result, then automatically calls
the `/feed` equivalent on the completed task_id.

```
/spawn architect bg --feed design auth
```

Spawns in background, returns task_id. User later runs `/feed <task_id>` to
inject when ready.

**Implementation:**
- After `_print_spawn_result`, call the feed logic on `result["task_id"]`
- For background mode, print a reminder: "Use /feed <task_id> to inject findings
  into chat when ready."

### 3. Chat-mode `/feed` requirement

`/feed` only modifies `pydantic_messages`, which is the chat agent's history. It
SHOULD work regardless of current mode, but the practical use case is to feed
findings before switching to chat mode, or after switching. If `pydantic_messages`
isn't available (edge case), print an error.

## Non-Goals

- **Auto-feed on mode switch.** Deferred — the user explicitly chooses when to
  feed findings. An auto-detect prompt ("Feed architect findings to chat?") is
  a follow-up.
- **Feeding from the legacy `delegate_task` skill path.** Only the V2 engine path
  (used by `/spawn`) writes to blackboard with the standard `DelegatedTaskOutput`
  format. The skill path uses a different `DelegatedTaskOutput` pydantic model
  and a different storage key (`memory_key`). Out of scope for Phase 1.
- **Deduplication.** Re-feeding the same task_id appends again. A `fed_tasks`
  set on `AppState` could prevent this — deferred.
- **Streaming feed.** The feed is instant — it's reading from already-persisted
  blackboard memory.

## Requirements

### R1: `/feed <task_id>` injects sub-agent result into chat history

- `user_input` starting with `/feed ` or `feed ` triggers `handle_feed_command`
- Reads `output` from `app_state.database.read_memory(app_state.session_id, task_id)`
- If the value is a `DelegatedTaskOutput` dict with `summary` and `raw_output`:
  - Formats the output as a markdown string using the existing `_format_raw_output`
  - Wraps in a context header: `"Sub-agent findings (task {task_id}):\n\n{formatted}"`
- Appends to `app_state.pydantic_messages` as a synthetic user message:
  ```python
  ModelRequest(parts=[TextPart(content=formatted)])
  ```
  Using `role="user"` ensures the LLM treats it as context, not its own output.
- Prints confirmation: `"Fed [persona] findings (task {task_id}) to chat."`
- If no result found for task_id: `"No result found for task {task_id}."`
- If result exists but isn't a `DelegatedTaskOutput`: `"Task {task_id} has no feed-able output."`
- Raises no exceptions — all errors are printed.

### R2: `/spawn --feed` flag

- `/spawn <persona> --feed <objective>` parses `--feed` token anywhere after persona
- Same parsing rules as `bg` token: positional flag after persona, unambiguous
- After `_print_spawn_result`, calls the feed logic on `result["task_id"]`
- For background mode (`bg`): the `--feed` flag is accepted but prints a reminder
  to use `/feed <task_id>` manually after completion (since background spawn
  returns immediately, the result isn't available yet)
- For foreground mode: feed happens automatically after spawn completes

### R3: Help text updated

- `print_repl_help()` gains `/feed <task_id>` entry
- `/spawn` usage updated to show `[--feed]` flag

### R4: Completion support

- `/feed <TAB>` completes nothing (task_ids are UUIDs — not completable)
- `/spawn` completion unchanged (`--feed` is positional, not a completion target)

### R5: Testability

- Unit tests for `handle_feed_command` in `tests/repl/test_repl_agent_commands.py`
- Mock `app_state.database.read_memory()` to return canned `DelegatedTaskOutput`
- Verify `app_state.pydantic_messages` is appended correctly
- Verify error paths (missing task, malformed output)

## Implementation Phases

### Phase 1: `/feed` command + `--feed` flag (this spec)

**Files to modify:**

| File | Change |
|------|--------|
| `harness_poc/repl.py` | `_is_feed_command`, `_parse_feed_command`, `handle_feed_command`, `_feed_task_to_chat`. Modify `_parse_spawn_command` to support `--feed` flag. Modify `handle_spawn_command` to auto-feed on `--feed`. Update `print_repl_help`. |
| `tests/repl/test_repl_agent_commands.py` | Add `TestHandleFeedCommand` class with positive + error path tests. Add `--feed` integration test. |

### Phase 2 (future): Auto-detect on mode switch

- When switching pipeline→chat, scan recent `DelegateTaskCompleted` events
- Offer to feed any un-fed findings

### Phase 3 (future): Deduplication

- Track `fed_tasks: set[str]` on `AppState` to prevent double-feeding
