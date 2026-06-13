# GoalRunner Implementation Plan

## Resolved design decisions

1. **Budget**: iteration count (default 50) + optional wall-clock seconds. Token-based budgeting rejected — no tokenizer dependency.
2. **Context window**: sliding window over last N `state_events` (default 20). The system prompt carries the goal; recent events are formatted inline. Older events drop out naturally. No summarization in v1.
3. **evaluate_goal callable any time**: yes. Agent can call it on iteration 1 if it already knows the answer.
4. **Hard circuit breaker**: `max_iterations` (default 50). Independent of stuck detection.
5. **Loop state lifetime**: session-scoped only. Loop dies with the REPL/CLI process.

---

## Phase 1 — Database: event types + retrieval (30 min)

### 1a. Add public event recording methods to `BlackboardDatabase`

The `_insert_state_event` helper is already private. Add two public methods:

```python
def record_llm_action(
    self, session_id: str, tool_name: str, arguments: dict[str, Any]
) -> None: ...

def record_tool_observation(
    self, session_id: str, tool_name: str, status: str, content: str
) -> None: ...
```

Both delegate to `_insert_state_event` with `scope="session"`, `scope_id=session_id`, event_type `llm_action` / `tool_observation`, and a JSON payload.

### 1b. Add event retrieval method

```python
def get_recent_events(
    self, session_id: str, limit: int = 20
) -> list[StateEvent]: ...
```

Queries: `SELECT * FROM state_events WHERE scope = 'session' AND scope_id = ? AND event_type IN ('llm_action', 'tool_observation') ORDER BY id DESC LIMIT ?` then reverses to chronological order.

_No schema migration needed._ `event_type` is TEXT — new values are just data.

### 1c. Test

`tests/test_goal_runner.py` — test recording + retrieval roundtrip.

---

## Phase 2 — evaluate_goal system skill (15 min)

### 2a. Create skill directory + files

`harness_poc/system_skills/evaluate_goal/`

**SKILL.md**:

```yaml
---
name: evaluate_goal
description: Evaluate whether the current goal is complete. Call with is_complete=true to stop the loop.
version: "1.0"
parameters:
  type: object
  properties:
    is_complete:
      type: boolean
      description: True if the goal has been fully achieved, False otherwise.
    reasoning:
      type: string
      description: Concise explanation of the current state and next steps if incomplete.
  required:
    - is_complete
    - reasoning
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: none
  workspace: none
---
# Skill: Evaluate Goal

## Purpose
Explicit exit mechanism for the autonomous goal loop. The GoalRunner intercepts this skill call — it never executes as a normal skill.

## Behavior
- If `is_complete` is true: GoalRunner breaks the loop and returns the reasoning to the user.
- If `is_complete` is false: GoalRunner appends the reasoning as a tool_observation and forces the loop to continue.

## Expected Output
Returns a `SkillResult` — but only if called outside the GoalRunner context.
```

**skill.py** — minimal stub:

```python
def execute(ctx, arguments):
    return SkillResult(
        status="success",
        content=f"Goal evaluation: complete={arguments['is_complete']}. {arguments['reasoning']}",
        artifacts={"is_complete": arguments["is_complete"], "reasoning": arguments["reasoning"]},
    )
```

The skill exists so it's discovered + registered as an OpenAI tool. The GoalRunner intercepts before `SkillRunner.execute_skill` is called.

### 2b. Test

Verify skill discovery and parameter schema. Verify stub execute returns expected result.

---

## Phase 3 — GoalRunner core class (90 min)

### 3a. File: `harness_poc/core/goal_runner.py`

```python
from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.app_factory import AppState
    from harness_poc.core.database import StateEvent

@dataclass
class GoalRunResult:
    status: str                    # "completed" | "budget_exhausted" | "error"
    content: str                   # final summary for the user
    iterations: int
    events: list[dict[str, Any]]   # summary of all llm_action/tool_observation events

@dataclass
class GoalRunner:
    max_iterations: int = 50
    max_seconds: float | None = None
    context_window: int = 20       # number of recent events in context
    stuck_threshold: int = 3       # block on 4th identical consecutive action

    # Internal state (per run)
    _stuck_hashes: deque[str] = field(default_factory=lambda: deque(maxlen=3))

    def run(self, goal: str, app_state: AppState) -> GoalRunResult:
        """Execute the autonomous ReAct loop for the given goal."""
        start_time = time.monotonic()
        self._stuck_hashes.clear()
        events: list[dict[str, Any]] = []

        for iteration in range(1, self.max_iterations + 1):
            # --- Budget check ---
            if self.max_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.max_seconds:
                    return GoalRunResult(
                        status="budget_exhausted",
                        content=f"Time budget ({self.max_seconds}s) exhausted after {iteration - 1} iterations.",
                        iterations=iteration - 1,
                        events=events,
                    )

            # --- Build context window ---
            recent_events = app_state.database.get_recent_events(
                app_state.session_id, limit=self.context_window
            )

            # --- Build messages for LLM ---
            messages = self._build_messages(goal, recent_events)

            # --- LLM decision ---
            response = app_state.llm_client.chat(
                messages=messages, tools=app_state.tools
            )

            if response.kind == "text":
                # LLM didn't call a tool — record as observation and continue
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="_llm_text",
                    status="success",
                    content=response.content,
                )
                events.append({
                    "type": "tool_observation",
                    "tool": "_llm_text",
                    "content": response.content[:200],
                })
                continue

            # --- Tool call path ---
            tool_name = response.tool_call["name"]
            arguments = response.tool_call["arguments"]

            # --- Record llm_action ---
            app_state.database.record_llm_action(
                session_id=app_state.session_id,
                tool_name=tool_name,
                arguments=arguments,
            )
            events.append({
                "type": "llm_action",
                "tool": tool_name,
                "arguments": arguments,
            })

            # --- Stuck detection ---
            action_hash = self._hash_action(tool_name, arguments)
            if self._is_stuck(action_hash):
                # Inject synthetic error observation, skip execution
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    status="blocked",
                    content=(
                        "STUCK DETECTION: You have attempted the same action "
                        f"({tool_name}) with identical arguments {self.stuck_threshold}+ times. "
                        "The action was blocked. Step back and try a different approach."
                    ),
                )
                events.append({
                    "type": "tool_observation",
                    "tool": tool_name,
                    "status": "blocked",
                    "content": "Stuck detection triggered.",
                })
                continue

            self._stuck_hashes.append(action_hash)

            # --- Intercept evaluate_goal ---
            if tool_name == "evaluate_goal":
                is_complete = arguments.get("is_complete", False)
                reasoning = arguments.get("reasoning", "")

                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="evaluate_goal",
                    status="success",
                    content=f"is_complete={is_complete}, reasoning={reasoning}",
                )

                if is_complete:
                    return GoalRunResult(
                        status="completed",
                        content=reasoning or "Goal completed.",
                        iterations=iteration,
                        events=events,
                    )
                # Not complete — inject reasoning as observation, continue loop
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name="_evaluate_goal_feedback",
                    status="success",
                    content=f"Goal not yet complete. Agent reasoning: {reasoning}",
                )
                events.append({
                    "type": "tool_observation",
                    "tool": "evaluate_goal",
                    "content": f"Not complete: {reasoning[:200]}",
                })
                continue

            # --- Execute normal skill ---
            try:
                result = app_state.skill_runner.execute_skill(
                    tool_name=tool_name,
                    arguments=arguments,
                    session_id=app_state.session_id,
                )
                # Record observation
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    status=result.status,
                    content=result.content,
                )
                events.append({
                    "type": "tool_observation",
                    "tool": tool_name,
                    "status": result.status,
                    "content": result.content[:200],
                })
            except Exception as exc:
                error_msg = f"Skill execution failed: {exc}"
                app_state.database.record_tool_observation(
                    session_id=app_state.session_id,
                    tool_name=tool_name,
                    status="error",
                    content=error_msg,
                )
                events.append({
                    "type": "tool_observation",
                    "tool": tool_name,
                    "status": "error",
                    "content": error_msg,
                })

        # --- Budget exhausted (iterations) ---
        return GoalRunResult(
            status="budget_exhausted",
            content=f"Iteration budget ({self.max_iterations}) exhausted. Goal may be incomplete.",
            iterations=self.max_iterations,
            events=events,
        )

    def _build_messages(
        self, goal: str, recent_events: list[StateEvent]
    ) -> list[dict[str, str]]:
        """Build the message list for the LLM: system prompt + event history."""
        system_prompt = self._goal_system_prompt(goal)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Format recent events as user/assistant messages
        for event in recent_events:
            payload = json.loads(event.payload) if isinstance(event.payload, str) else event.payload
            if event.event_type == "llm_action":
                tool_name = payload.get("tool_name", "unknown")
                args = payload.get("arguments", {})
                messages.append({
                    "role": "assistant",
                    "content": f"[Action] Called {tool_name}({json.dumps(args)})",
                })
            elif event.event_type == "tool_observation":
                tool_name = payload.get("tool_name", "unknown")
                content = payload.get("content", "")
                messages.append({
                    "role": "user",
                    "content": f"[Observation from {tool_name}]\n{content}",
                })

        # Final prompt to drive the next action
        messages.append({
            "role": "user",
            "content": (
                "Continue working toward the goal. Take the next concrete action. "
                "If you believe the goal is fully achieved, call evaluate_goal with is_complete=true. "
                "If you are stuck or need clarification, call evaluate_goal with is_complete=false and explain why."
            ),
        })

        return messages

    def _goal_system_prompt(self, goal: str) -> str:
        return (
            "You are an autonomous agent operating in a ReAct (Reason + Act) loop. "
            "Your sole objective is to achieve the following goal.\n\n"
            f"## Goal\n{goal}\n\n"
            "## Instructions\n"
            "- Work step by step. Call tools to take actions.\n"
            "- After each tool result, decide on your next action.\n"
            "- When the goal is fully achieved, call `evaluate_goal` with `is_complete: true` "
            "and explain what was accomplished.\n"
            "- If you are stuck or cannot proceed, call `evaluate_goal` with `is_complete: false` "
            "and explain what's blocking you.\n"
            "- Do not repeat the same action with identical arguments — the system will block repeated patterns.\n"
            "- Be concise. Focus on actions, not conversation.\n"
        )

    def _hash_action(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Deterministic hash of a (tool_name, arguments) pair."""
        canonical = json.dumps({"tool": tool_name, "args": arguments}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _is_stuck(self, action_hash: str) -> bool:
        """True if this action_hash matches all of the last stuck_threshold hashes."""
        if len(self._stuck_hashes) < self.stuck_threshold:
            return False
        return all(h == action_hash for h in self._stuck_hashes)
```

### 3b. Design notes

- **Context window**: The `_build_messages` method formats events into user/assistant pairs. The `continue` prompt at the end drives the LLM forward. This avoids the unbounded growth of the REPL's `app_state.messages`.
- **Text-only LLM responses**: If the LLM returns text instead of a tool call, we record it as an observation and loop. The `continue` prompt should nudge it back toward tool use. If it keeps returning text without calling `evaluate_goal`, the iteration budget will eventually trip.
- **evaluate_goal interception**: The GoalRunner checks `tool_name == "evaluate_goal"` _before_ calling `SkillRunner.execute_skill`. The skill itself is never invoked during a goal run — it exists purely for tool registration. If someone calls it directly via `/skill evaluate_goal`, the stub executes normally.
- **Stuck detection**: Uses SHA-256 of the canonical JSON. Only blocks when the _exact_ same (tool, args) appears 4 times consecutively. Different args to the same tool = different hash = allowed.

---

## Phase 4 — CLI + REPL integration (30 min)

### 4a. REPL: `/goal <objective>`

In `harness_poc/repl.py`, add to `handle_repl_input`:

```python
if user_input.startswith(("/goal ", "goal ")):
    handle_goal_command(app_state, user_input)
    return
```

New function:

```python
def handle_goal_command(app_state: AppState, user_input: str) -> None:
    objective = user_input.removeprefix("/").removeprefix("goal").strip()
    if not objective:
        console.print("Usage: /goal <objective>")
        return

    console.print(f"[cyan]Starting autonomous goal loop...[/cyan]")
    console.print(f"Goal: {objective}")

    runner = GoalRunner()
    try:
        result = runner.run(goal=objective, app_state=app_state)
    except Exception as exc:
        print_error(f"Goal loop failed: {exc}")
        return

    _print_goal_result(result)
```

Also update `print_repl_help()` and `handle_repl_input` to include `/goal`.

### 4b. CLI: `harness-poc goal <objective>`

In `harness_poc/cli.py`:

```python
@app.command()
def goal(
    objective: Annotated[str, typer.Argument(help="The goal to pursue autonomously.")],
    max_iterations: Annotated[
        int, typer.Option("--max-iterations", "-n", help="Max loop iterations (default 50).")
    ] = 50,
    max_seconds: Annotated[
        float | None, typer.Option("--max-seconds", "-t", help="Max wall-clock seconds.")
    ] = None,
) -> None:
    """Run an autonomous goal execution loop."""
    app_state = _new_app_state()
    runner = GoalRunner(max_iterations=max_iterations, max_seconds=max_seconds)
    try:
        result = runner.run(goal=objective, app_state=app_state)
    except Exception as exc:
        print_error(f"Goal loop failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(_format_goal_result(result))
```

### 4c. Output formatting

```python
def _format_goal_result(result: GoalRunResult) -> str:
    status_style = {"completed": "green", "budget_exhausted": "yellow", "error": "red"}
    color = status_style.get(result.status, "white")

    parts = [
        f"[{color}]Status: {result.status}[/{color}]",
        f"Iterations: {result.iterations}",
        "",
        result.content,
        "",
        "[dim]--- Event Log ---[/dim]",
    ]
    for i, event in enumerate(result.events, 1):
        event_type = event["type"]
        tool = event.get("tool", "?")
        parts.append(f"[dim]{i}. [{event_type}] {tool}[/dim]")
    return "\n".join(parts)
```

---

## Phase 5 — Tests (45 min)

### 5a. Database tests (`tests/test_goal_runner.py`)

```python
def test_record_and_retrieve_llm_actions():
    db = BlackboardDatabase(":memory:")
    db.create_tables()
    sid = db.start_session("test")

    db.record_llm_action(sid, "read_memory", {"memory_key": "x"})
    db.record_tool_observation(sid, "read_memory", "success", "result content")

    events = db.get_recent_events(sid, limit=10)
    assert len(events) == 2
    assert events[0].event_type == "llm_action"
    assert events[1].event_type == "tool_observation"
```

### 5b. GoalRunner tests (mock LLM)

Use the existing mock mode (no API key) to test the loop:

```python
def test_goal_runner_completes_on_evaluate_goal_true():
    # Set up app_state with mock LLM
    # The mock returns evaluate_goal(is_complete=true) on first iteration
    # Assert result.status == "completed", iterations == 1

def test_goal_runner_exhausts_iteration_budget():
    # Mock returns text responses forever (no tool calls)
    # max_iterations=3
    # Assert result.status == "budget_exhausted", iterations == 3

def test_stuck_detection_blocks_fourth_identical_action():
    # Mock returns the same tool_call 4 times
    # Assert 4th one is blocked, stuck detection injects observation

def test_goal_runner_handles_skill_execution_error():
    # Mock returns a tool_call to a skill that raises
    # Assert error is recorded as tool_observation, loop continues
```

The mock LLM needs to be steerable for these tests. Current `_mock_chat` uses keyword matching — we may need to add a `_mock_override` mechanism or inject a callable. Simplest approach: add a `mock_response: Callable | None = None` param to `LLMClient.__init__` that, when set, bypasses `_mock_chat` and returns whatever the callable produces.

### 5c. CLI test

```python
def test_goal_cli_command():
    result = runner.invoke(app, ["goal", "test objective", "--max-iterations", "1"])
    assert result.exit_code == 0
    assert "Status:" in result.output
```

### 5d. REPL test

Similar to existing `test_repl_skill_execution.py` — add test for `/goal` parsing and basic execution.

---

## Phase 6 — Lint + type check + run existing tests (15 min)

```bash
uv run ruff check .
uv run ty check
uv run pytest
```

Fix any regressions. The existing CI tests (`test_cli.py`, `test_repl_completion.py`, `test_repl_skill_execution.py`, `test_consolidate_state.py`, `test_spec_writer.py`) must continue to pass.

---

## Files changed

| File | Action |
|---|---|
| `harness_poc/core/database.py` | Add `record_llm_action`, `record_tool_observation`, `get_recent_events` |
| `harness_poc/core/goal_runner.py` | **New** — GoalRunner class + GoalRunResult |
| `harness_poc/system_skills/evaluate_goal/SKILL.md` | **New** — evaluate_goal skill doc |
| `harness_poc/system_skills/evaluate_goal/__init__.py` | **New** — init |
| `harness_poc/system_skills/evaluate_goal/skill.py` | **New** — stub execute |
| `harness_poc/cli.py` | Add `goal` command |
| `harness_poc/repl.py` | Add `/goal` handling + help text |
| `harness_poc/app_factory.py` | Expose `GoalRunner` (if needed) |
| `tests/test_goal_runner.py` | **New** — full test suite |

## Edge cases handled

1. **Empty goal**: CLI/REPL validate before starting loop.
2. **LLM returns text, not tool call**: Recorded as observation, loop continues. Budget prevents infinite spins.
3. **Skill execution raises**: Caught, recorded as error observation, loop continues.
4. **Context window overflow**: Sliding window of N events. Oldest drop out. No summarization needed.
5. **Repeated identical actions**: Stuck detection blocks 4th attempt, injects error.
6. **evaluate_goal with is_complete=false**: Reasoning injected as observation, loop continues.
7. **Time budget exhaustion**: Checked at top of each iteration.
8. **Iteration budget exhaustion**: for-loop naturally terminates, returns budget_exhausted.
9. **Database errors during recording**: Propagate as exceptions — the catch in `run()` records them and continues, or if catastrophic, the REPL/CLI handler catches and reports.
10. **Concurrent goal runs**: Each run gets a fresh `GoalRunner` instance with cleared stuck hashes. Session-scoped events prevent cross-run pollution.
