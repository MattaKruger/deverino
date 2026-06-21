# Spec: Agent-Accessible Project State

**Date**: 2026-06-21
**Status**: draft

## Context

The harness has a 4-table state system (`project_state`, `session_state`, `state_proposals`, `state_events`) with a promotion workflow: session state accumulates notes/decisions, `consolidate_state` proposes them for promotion, and the user approves into durable project state. The CLI and REPL expose 10 commands each for managing state.

However, state is only injected into the system prompt once at session start (`app_factory.py:408-436`). After that point the agent **cannot read or write state at runtime**. The only state-mutating tool available to the agent is `consolidate_state` (which bundles everything from session state into a proposal). The agent has no way to take notes, record decisions, flag open questions, or check past constraints while working.

This means the state system — one of the earliest ideas in the project — is a write-only append log from the user's perspective. The agent never touches it autonomously.

## Problem

1. **No runtime read access.** State is a frozen snapshot at session start. If the agent causes state changes (via `consolidate_state` or if the user runs a CLI state command mid-session), the agent sees stale data.
2. **No runtime write access.** The agent can't record "I discovered that the API uses v2 auth now" without the user manually typing `/state note "API uses v2 auth"`. This defeats the purpose of an autonomous agent.
3. **GoalRunner is state-blind.** Goals run without project state context. The agent can't reference past decisions, constraints, or open questions when pursuing a goal.
4. **State is invisible.** The `state_events` audit trail exists but nothing surfaces it. No `state events` command, no dashboard view.
5. **No auto-consolidation.** After a session, nothing prompts the user to consolidate findings into project state. Session state is ephemeral and lost if not manually proposed.
6. **Flat text only.** `StatePayload` has 7 text-list fields. No key-value facts, no metadata (source session, confidence), no priorities. The agent can't store structured data like `{"api_version": "v2"}`.

## Proposed Solution

Three built-in tools that close the read/write gap, plus integration points that make state flow through the system end-to-end.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         AGENT TOOLS                              │
│                                                                  │
│  read_project_state()     "What do we know about auth?"          │
│  append_session_state()   "Note: API uses v2 auth"               │
│  set_project_fact()       "api_version = v2"                     │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                         INTEGRATION                              │
│                                                                  │
│  GoalRunner ── injects state into goal prompt                    │
│  Workflows  ── read_state / write_state YAML hooks               │
│  Session end ── auto-consolidation prompt                        │
│  Dashboard  ── state changelog view                              │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                         STORAGE                                  │
│                                                                  │
│  project_state     ◄── approved facts                            │
│  session_state     ◄── agent-scratched notes                     │
│  state_proposals   ◄── pending promotions                        │
│  state_events      ◄── audit trail (new: surfaced)               │
└──────────────────────────────────────────────────────────────────┘
```

### Files

| File | Change |
|---|---|
| `harness_poc/system_tools/read_project_state.py` | **New** — built-in tool for reading project state |
| `harness_poc/system_tools/append_session_state.py` | **New** — built-in tool for appending to session state |
| `harness_poc/system_tools/set_project_fact.py` | **New** — built-in tool for key-value facts |
| `harness_poc/core/storage/state.py` | Add `facts: dict[str, str]` to `StatePayload` |
| `harness_poc/core/storage/models.py` | Migrate: add `facts` column (JSONB, default `{}`) |
| `harness_poc/core/storage/database.py` | Add `get_state_events()`, `set_project_fact()`, `get_project_fact()` |
| `harness_poc/core/runtime/goal_runner.py` | Inject project state into goal system prompt |
| `harness_poc/core/execution/workflow_runner.py` | Add `read_state`/`write_state` YAML hooks |
| `harness_poc/repl.py` | Add `state events` command; auto-consolidation prompt on session close |
| `harness_poc/dashboard_*.py` | Add state changelog to dashboard |

### API

#### `read_project_state`

```
Tool: read_project_state
Args:  { section?: "notes"|"decisions"|"next_actions"|"open_questions"|
                "constraints"|"changelog"|"summary"|"facts"|"all" }
Return: Markdown rendering of the requested section(s), or the full
        project state if section is omitted or "all".

Behavior:
- Reads directly from the project_state table (always current).
- If section is specified, returns only that section's content.
- "facts" returns key-value pairs as a bullet list.
- Empty sections return "No entries.".
```

#### `append_session_state`

```
Tool: append_session_state
Args:  { section: "notes"|"decisions"|"next_actions"|
                 "open_questions"|"changelog",
         text: string }
Return: Confirmation with the updated section content.

Behavior:
- Appends text to the named section in session_state.
- Writes a state_event (scope="session", event_type="append_{section}").
- Sets the session_state.dirty flag.
- The agent can call this autonomously during task execution.
```

#### `set_project_fact` (Phase 2)

```
Tool: set_project_fact
Args:  { key: string, value: string }
Return: Confirmation.

Behavior:
- Sets a key-value pair in project_state.facts.
- Overwrites if key already exists.
- Writes a state_event (event_type="fact_set").
- No proposal workflow needed — facts are low-risk structured data.
- The agent can call this autonomously.
```

### Integration Points

#### GoalRunner state injection (Phase 1)

When the user runs `@goal "implement feature X"`, the GoalRunner's system prompt includes a `## Project State` block with:
- Active constraints (to avoid repeating past mistakes)
- Relevant decisions (to maintain consistency)
- Open questions (to prioritize investigation)

This is a prompt-only change — no new tools, no storage changes.

```python
# goal_runner.py — _goal_system_prompt()
state = database.ensure_project_state()
state_block = _format_state_for_goal(state, goal)
system_prompt = f"{goal_prompt}\n\n{state_block}"
```

#### Workflow state hooks (Phase 2)

Add optional YAML keys to workflow steps:

```yaml
steps:
  - name: analyze
    skill: code_analysis
    read_state: constraints    # inject constraints into skill context
    write_state: decisions     # append skill result to session decisions
```

#### Session-end auto-consolidation (Phase 2)

When a session ends (user types `/exit` or the REPL closes):
1. Check if `session_state.dirty` is true
2. If so, run `consolidate_state` in preview mode
3. Print a prompt: "This session produced 3 notes, 1 decision. Propose for project state? [y/N]"
4. On 'y', auto-propose and print the proposal ID for later approval

#### Dashboard state view (Phase 3)

Add a "State" tab to the dashboard showing:
- Current project state sections
- State changelog (recent `state_events`)
- Pending proposals

### Data Model Change

Add one field to `StatePayload`:

```python
@dataclass(frozen=True, slots=True)
class StatePayload:
    summary: str = ""
    notes: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)  # NEW
```

`facts` renders as a key-value table in markdown. The `append_payload` merge does a shallow dict update (last writer wins). The `is_empty` check includes `not self.facts`.

### Migration

The `facts` field defaults to `{}`. Existing `state_payload` JSON blobs in the database are missing this key. The deserialization path in `StatePayload.from_dict()` already handles missing keys via `dataclass` defaults. No migration script needed — old rows are read-compatible. The first write with a fact adds the key to the JSON blob.

---

## Implementation Phases

### Phase 1 — Agent agency (today)

| # | Task | Files | Lines |
|---|---|---|---|
| 1.1 | Add `read_project_state` built-in tool | `system_tools/read_project_state.py` | ~40 |
| 1.2 | Add `append_session_state` built-in tool | `system_tools/append_session_state.py` | ~50 |
| 1.3 | Register both tools in `build_builtin_tools()` | `pydantic_runtime.py` | ~4 |
| 1.4 | Inject project state into GoalRunner prompt | `goal_runner.py` | ~20 |
| 1.5 | Add `read_project_state` to REPL blocked list if needed | `app_factory.py` | ~2 |
| 1.6 | Smoke test: agent calls `read_project_state` + `append_session_state` in a session | `tests/` | ~40 |

**Total Phase 1: ~156 lines, 2 new files**

### Phase 2 — Data model + integration (next)

| # | Task | Files | Lines |
|---|---|---|---|
| 2.1 | Add `facts: dict[str, str]` to `StatePayload` | `state.py` | ~10 |
| 2.2 | Add `set_project_fact` built-in tool | `system_tools/set_project_fact.py` | ~40 |
| 2.3 | Add `get_project_fact` / `set_project_fact` to `BlackboardDatabase` | `database.py` | ~20 |
| 2.4 | Add `read_state` / `write_state` to workflow YAML schema | `workflow_runner.py` | ~30 |
| 2.5 | Session-end auto-consolidation prompt | `repl.py` | ~30 |
| 2.6 | Add `state events` REPL/CLI command | `repl.py`, `cli.py`, `database.py` | ~40 |

### Phase 3 — Visibility (later)

| # | Task |
|---|---|
| 3.1 | Dashboard state changelog view |
| 3.2 | Pending proposals widget on overview |
| 3.3 | State search via `search_documents` (index project state in Vespa) |

---

## Risks & Open Questions

1. **State spam.** An LLM that autonomously calls `append_session_state` could flood session state with noise. Mitigation: suggest a `max_session_state_entries` config (default 50), after which the tool returns a soft error.

2. **Fact overwrites.** `set_project_fact` overwrites without confirmation. For critical facts (e.g., `deployment_target`), this could be destructive. Mitigation: `state_events` audit trail captures every write; `state events` command can show the history of a specific key.

3. **GoalRunner token budget.** Injecting full project state into every goal prompt could consume significant context window. Mitigation: only inject `constraints` + `decisions` (the two most actionable sections), and only if non-empty.

4. **Session state vs blackboard memory.** The agent already has `read_memory` / `write_memory` for key-value storage in `shared_memory`. Session state is a separate, structured concept. Should they be unified? **Decision: keep separate.** Memory is runtime scratchpad; state is curated institutional knowledge with a promotion workflow.
