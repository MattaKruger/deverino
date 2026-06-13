# Hot Reload & Session Restore

> **Goal:** Eliminate the dev-loop friction of restarting the harness on code change. Edits to skills and most of `harness_poc/core/*` should be picked up without killing the TUI; full cold restarts must restore the prior conversation.

## Motivation

The harness currently has three friction points during active development:

1. **Cold-restart latency.** `build_app_state` does Vespa health check (3s timeout), auto-index, skill discovery, agent construction, and DB schema setup synchronously before the TUI mounts.
2. **Lost conversation history.** `pydantic_messages` lives only in `AppState`; on exit it is gone. Postgres has `state_events` but not the full pydantic-ai `ModelMessage` graph needed to resume.
3. **No way to pick up code edits short of full restart.** Editing a skill, system prompt, or processor requires killing the process.

This plan addresses all three by:

- Making conversation history event-sourced.
- Splitting `AppState` into reload boundaries.
- Adding a file watcher → reload coordinator that swaps the reloadable layer in place.

## Non-goals

- In-process reload of `app_factory.py`, `database.py`, `events.py`, `models.py`, or the TUI/REPL itself. These remain restart-only; a `/restart` banner is shown.
- Mid-flight resume of `GoalRunner` or `PipelineRunner` state — reload is **refused** while an active run is in progress.
- Hot reload of dependency upgrades (`uv sync` changes). Out of scope.

## Architecture

### Three-tier `AppState`

`AppState` is split into Identity, LongLived, and Runtime layers based on what survives a reload.

```python
@dataclass(frozen=True)
class Identity:
    """Frozen across reloads. Defines session identity."""
    session_id: str
    database: BlackboardDatabase
    event_bus: EventBus
    event_store: EventStore

@dataclass
class LongLived:
    """Tasks that survive reload via in-place reference swap."""
    materializer: MaterializerRunner   # exposes swap_runtime(runtime)
    supervisor: ProcessorSupervisor    # exposes restart(runtime)

@dataclass
class Runtime:
    """Fully replaceable on reload."""
    config: HarnessConfig
    skill_runner: SkillRunner
    tool_runner: ToolRunner
    pydantic_runtime: PydanticAgentRuntime
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    pipeline_runner: PipelineRunner
    tools: list[dict[str, Any]]
    skill_catalog: SkillCatalog

@dataclass
class AppState:
    identity: Identity
    long_lived: LongLived
    runtime: Runtime                                # reassigned atomically on reload
    pydantic_messages: list[ModelMessage]           # backed by AgentTurnRecorded
    messages: list[Message]
    streaming: StreamingContext
    active_run: ActiveRunHandle | None = None       # gates reload
```

### Reload tiers

| Tier | Trigger | Action | Disruption |
|---|---|---|---|
| 1 — skills | `skills/**`, `harness_poc/system_skills/**` | Re-run `discover_skills`, rebuild agent tool list, hot-swap into `pydantic_runtime` | None — next chat sees new tools |
| 2 — runtime | Most of `harness_poc/core/**`, `harness_poc/system_tools/**`, `system_prompts/**`, non-identity keys in `harness.yaml` | `sys.modules` surgery + `build_runtime_layer` + supervisor restart + materializer reference swap | ~100ms, in-flight skills cancelled |
| 3 — identity | `app_factory.py`, `main.py`, `cli.py`, `tui.py`, `repl.py`, `database.py`, `db_engine.py`, `event_bus.py`, `event_store.py`, `events.py`, `models.py`; `database_url`/`project_id` in `harness.yaml` | Refuse reload, emit `ReloadRefused`, TUI shows `/restart` banner | User initiates restart |

### Reload protocol

When `ReloadCoordinator` consumes `RuntimeReloadRequested`:

1. **Gate.** If `state.active_run is not None`, emit `ReloadRefused(reason="active_run", kind=..., name=...)`. Store the request; retry on `ActiveRunEnded`. TUI shows "reload deferred" toast.
2. **Classify.** Watcher payload → tier 1 / 2 / 3.
3. **Tier 3 → refuse.** Emit `ReloadRefused(reason="identity_change", paths=...)`. TUI shows `/restart` banner.
4. **Tier 2 → drain.**
   - For each in-flight `(call_id, skill_name)` in `supervisor.in_flight()`:
     - Set the cancellation token.
     - Emit `SkillCancelled(call_id, skill_name, reason="reload")`.
     - Inject a synthetic `ToolReturnPart` into `pydantic_messages` (content: `"cancelled by reload"`) and persist via `AgentTurnRecorded`. This keeps pydantic-ai's tool-call/result invariant intact post-reload.
   - `await supervisor.stop()` — cancels `llm_worker`, `tool_worker`, `circuit_breaker` tasks.
   - Materializer is NOT stopped. If it was awaiting `execute_skill`, that await resolves with a `SkillCancelled` result; its existing exception handling treats it as a poll failure.
5. **Rebuild.**
   - Drop tier-2 modules from `sys.modules` (explicit allow-list — see step 8).
   - Re-import.
   - `new_runtime = build_runtime_layer(identity)`.
   - `state.runtime = new_runtime` (atomic reassignment).
   - `state.long_lived.materializer.swap_runtime(new_runtime)`.
   - `await supervisor.start(new_runtime, identity)`.
6. **Tier 1 → simpler path.**
   - No drain needed (no module replacement).
   - `state.runtime.skill_runner.rediscover_skills()` (new method).
   - Rebuild tool list, replace `state.runtime.tools`.
   - Call `pydantic_runtime.swap_tools(new_tools)` (new method).
7. **Emit.** `RuntimeReloaded(tier=..., duration_ms=..., paths=...)`. TUI banner updates.

### Active-run gate

`GoalRunner.run` and `PipelineRunner.run` are wrapped with:

```python
@asynccontextmanager
async def active_run(state: AppState, kind: Literal["goal", "pipeline", "chat"], name: str):
    state.active_run = ActiveRunHandle(kind=kind, name=name, started_at=...)
    state.identity.event_bus.publish(ActiveRunStarted(...))
    try:
        yield
    finally:
        state.active_run = None
        state.identity.event_bus.publish(ActiveRunEnded(...))
```

`handle_chat_input` is also wrapped (decision: a streaming chat turn counts as an active run — reload only fires on a quiescent bus). `ReloadCoordinator` subscribes to `ActiveRunEnded` and retries the most recent queued reload.

### Session restore

Add `AgentTurnRecorded` event:

```python
@dataclass
class AgentTurnRecorded(BaseEvent):
    messages_blob: list[dict[str, Any]]   # ModelMessagesTypeAdapter.dump_python(new_messages)
```

Persistence point: `repl.py:248` (after `pydantic_messages.extend(sanitize_new_messages(...))`).

Storage: write a new SQL table `session_messages` for fast point-in-time replay (avoids scanning the full `state_events` log). Schema:

```python
class DbSessionMessage(SQLModel, table=True):
    __tablename__ = "session_messages"
    session_id: str = Field(primary_key=True, foreign_key="sessions.session_id")
    ordinal: int = Field(primary_key=True)
    messages_blob: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    created_at: str
```

Restore path in `build_app_state(session_id=None)`:

- `session_id is None` → `database.start_session(...)`, empty `pydantic_messages`.
- `session_id` given → verify session exists; load all `DbSessionMessage` rows ordered by `ordinal`, run through `ModelMessagesTypeAdapter.validate_python()`, concatenate into `pydantic_messages`. Also rebuild `messages` from the same source for REPL display.

CLI: `harness-poc --resume <session_id>`, `harness-poc --resume-last`. Same flags supported on `tui` subcommand.

### TUI integration

- New `_reload_banner` Static widget below `#header`. Shows last reload tier + timestamp, or "deferred (goal active)", or "/restart needed (tui.py changed)".
- Subscribes to `RuntimeReloadRequested`, `RuntimeReloaded`, `ReloadRefused`, `ActiveRunStarted`, `ActiveRunEnded`.
- New commands:
  - `/reload` — manually fire `RuntimeReloadRequested(paths=[], manual=True)`.
  - `/restart` — clean exit + supervisor relaunch (only path for tier-3 changes; surfaces a brief "restarting…" then re-opens with `--resume <current_session_id>`).
- On restore (`--resume`): replay `pydantic_messages` into `_chat_messages` so the user sees prior conversation. Walk `ModelRequest.parts` for `UserPromptPart` → `"You: …"`; `ModelResponse.parts` for `TextPart` → `"Agent: …"`; tool calls render as `.tool-line` muted entries.

### `sys.modules` allow-list

Explicit list of tier-2 modules to drop and re-import:

```python
TIER_2_MODULES = (
    "harness_poc.core.skill_runner",
    "harness_poc.core.skill_catalog",
    "harness_poc.core.skill_context",
    "harness_poc.core.skill_preprocessing",
    "harness_poc.core.skill_scaffolder",
    "harness_poc.core.tool_runner",
    "harness_poc.core.tool_context",
    "harness_poc.core.tool_result",
    "harness_poc.core.pydantic_runtime",
    "harness_poc.core.workflow_runner",
    "harness_poc.core.pipeline_runner",
    "harness_poc.core.goal_runner",
    "harness_poc.core.message_history",
    "harness_poc.core.reducers",
    "harness_poc.core.permissions",
    "harness_poc.core.processors.llm_worker",
    "harness_poc.core.processors.tool_worker",
    "harness_poc.core.processors.circuit_breaker",
)
```

Plus all submodules of `harness_poc.system_skills` and `harness_poc.system_tools` (resolved at reload time via prefix match). Tier 1 reload only touches the user-facing `skills/` dir (loaded by path, not by import) and the system skill modules listed above.

## Implementation order

### Step 1 — Session restore foundation (1d)

- Add `AgentTurnRecorded` event in `events.py`, register in `EVENT_REGISTRY`.
- Add `DbSessionMessage` model in `models.py`.
- Add `database.append_session_messages(session_id, blob)` and `database.load_session_messages(session_id) -> list[ModelMessage]`.
- Update `repl.py:handle_chat_input` to emit `AgentTurnRecorded` and call `append_session_messages` after each turn.
- Update `build_app_state` to accept `session_id: str | None = None`; load history if given.
- Add `--resume <id>` and `--resume-last` flags to the typer app (`harness-poc` and `harness-poc tui`).
- Add `database.get_last_session_id() -> str | None`.

**Verification:** Run `harness-poc tui`, have a 3-turn conversation, exit, run `harness-poc tui --resume-last`, see prior conversation in chat scroll, send a 4th turn that references turn 2 — agent answers coherently.

### Step 2 — `AppState` topology refactor (0.5d)

- Introduce `Identity`, `LongLived`, `Runtime` dataclasses.
- Split `build_app_state` into `build_identity(session_id)`, `build_runtime_layer(identity)`, `build_long_lived(identity, runtime)`.
- Update all consumers (REPL, TUI, CLI, processors, tests) to access `state.identity.session_id` etc.
- No behavior change — pure refactor.

**Verification:** All existing tests pass. `uv run pytest` clean.

### Step 3 — `ProcessorSupervisor` + `MaterializerRunner.swap_runtime` (0.5d)

- New `harness_poc/core/processor_supervisor.py`:
  - `start(runtime, identity)` — launches `run_circuit_breaker`, `run_llm_worker`, `run_skill_worker` as named tasks.
  - `stop()` — cancels tasks, awaits with timeout.
  - `restart(runtime, identity)` — `stop` then `start`.
  - `in_flight() -> list[(call_id, skill_name)]` — queries tool worker's active calls.
- Refactor `main.py:run_async_main` to use the supervisor instead of inline `asyncio.gather`.
- Add `MaterializerRunner.swap_runtime(runtime: Runtime)` — atomically reassigns `_skill_runner` and `_config`. `_no_change_count` preserved. Loop reads `self._skill_runner` per iteration, so next poll uses the new runtime.

**Verification:** Manual: start TUI, observe materializer polling continues across `supervisor.restart()` (add a temporary log line). Automated: unit test on `swap_runtime` that asserts `_no_change_count` survives.

### Step 4 — Skill cancellation (1d, load-bearing)

- New event `SkillCancelled(call_id, skill_name, reason)`.
- Add `CancellationToken` plumbing through `tool_runner` and `SkillContext`. Each in-flight skill call gets a token. `SkillContext.cancelled` becomes a property the skill can check.
- Long-running skills (`container_exec`, `execute_python`, `web_search`) wrapped with `asyncio.wait_for` keyed to the token; cooperative skills check `ctx.cancelled` at safe points.
- On cancellation, `tool_runner` returns a `SkillResult(status="cancelled", content="cancelled by reload")` AND the worker injects a synthetic `ToolReturnPart` into `pydantic_messages` matching the outstanding tool_call_id.
- Persist the synthetic turn via `AgentTurnRecorded` so post-restore history is consistent.

**Verification (critical):** Test scenario — start a 10-second `execute_python` skill (`time.sleep(10)`), fire `supervisor.restart` mid-call, assert:
1. `SkillCancelled` event emitted.
2. `pydantic_messages` ends with a valid request-response pair (no dangling tool call).
3. Post-reload, next `agent.run` succeeds (pydantic-ai's history validation passes).
4. Session restore from this point in a fresh process also succeeds.

### Step 5 — Active-run gate (0.5d)

- New events `ActiveRunStarted`, `ActiveRunEnded`, `ReloadRefused`, `RuntimeReloadRequested`, `RuntimeReloaded`. Register in `EVENT_REGISTRY`.
- New dataclass `ActiveRunHandle(kind, name, started_at)`.
- `@asynccontextmanager active_run(state, kind, name)` helper.
- Wrap `GoalRunner.run`, `PipelineRunner.run`, and `handle_chat_input` with `active_run`.
- Deferred-reload queue inside `ReloadCoordinator`: stores last refused request, retries on `ActiveRunEnded`.

**Verification:** Start a long goal, fire `/reload` during goal, assert `ReloadRefused` event + TUI shows deferred toast, wait for goal to finish, assert `RuntimeReloaded` fires automatically.

### Step 6 — Watcher + `ReloadCoordinator` + tier classification + `sys.modules` surgery (1d)

- Add `watchfiles` dependency.
- New `harness_poc/core/reload_coordinator.py`:
  - `async def watch_files(state, paths)` — `watchfiles.awatch`, emits `RuntimeReloadRequested(paths=...)`.
  - `async def run_reload_coordinator(state)` — processor consuming `RuntimeReloadRequested`, runs the 7-step protocol above.
  - `classify(paths) -> Literal["tier_1", "tier_2", "tier_3"]` with `harness.yaml` key inspection (parse YAML, diff with last-known-good copy).
- Launch watcher + coordinator from `ProcessorSupervisor.start()`. They are NOT torn down on reload (they're managed by `LongLived`, not `Runtime`).
- Implement `_drop_and_reimport(modules)` helper with the allow-list above. Tier-1 path skips this.
- Implement `pydantic_runtime.swap_tools(new_tools)` for tier-1 path.
- Implement `skill_runner.rediscover_skills()` for tier-1 path.

**Verification:**
1. Edit a project skill (`skills/web_search/skill.py`), add a log line, observe `RuntimeReloaded(tier=1)` within ~1s, invoke the skill, log line appears.
2. Edit `core/processors/llm_worker.py`, add a log line, observe `RuntimeReloaded(tier=2)`, send a chat turn, log line appears.
3. Edit `tui.py`, observe `ReloadRefused(reason="identity_change")`, banner appears.

### Step 7 — TUI integration (0.5d)

- Add `_reload_banner` Static widget to `ChatApp.compose`.
- Subscribe to reload events in `on_mount`.
- Implement `/reload` and `/restart` commands.
- On `--resume`, replay loaded `pydantic_messages` into `_chat_messages` for visual restore.

**Verification:** End-to-end manual: launch TUI with `--resume-last`, see prior conversation, edit a skill, see banner update, edit `tui.py`, see `/restart` hint, run `/restart`, session restored, prior conversation still visible.

## Risks & open questions

- **`sys.modules` surgery has known sharp edges.** Lingering references in caller frames keep old classes alive; `isinstance` checks across the boundary fail; pydantic model registries may end up with duplicate names. Mitigation: keep the allow-list narrow, exhaustive test in step 6 that exercises a full chat turn post-reload.
- **`harness.yaml` reload classification** assumes structured diffing. Tier-3 keys: `database_url`, `project_id`, `paths.*`. Everything else → tier 2. Document this in the config docstring.
- **`MaterializerRunner` reference swap is not atomic across attributes.** If a reload lands between `self._skill_runner = ...` and `self._config = ...`, a poll cycle could mix versions. Fix: introduce a single `self._runtime: Runtime` reference; the materializer reads `self._runtime.skill_runner` per access.
- **Restore + tool calls.** If a session's last persisted turn ended mid-tool-call (process killed between request and synthetic-cancel injection), restore will yield invalid history. Mitigation: on restore, validate the last message; if it's a `ModelRequest` with a `ToolCallPart` and no matching `ToolReturnPart`, inject `"interrupted by process exit"` synthetic return before handing to pydantic-ai.
- **Tier-2 reload during streaming.** The active-run gate covers this — a streaming chat turn is an active run, so reload defers.

## Verification checklist (acceptance)

- [ ] `harness-poc --resume-last` restores conversation across process exit.
- [ ] Editing a project skill triggers tier-1 reload within ~1s, no chat disruption.
- [ ] Editing `core/processors/llm_worker.py` triggers tier-2 reload, mid-flight skill (if any) is cancelled with valid post-reload history.
- [ ] Editing `tui.py` triggers `ReloadRefused`, banner instructs `/restart`.
- [ ] `/reload` during an active goal emits `ReloadRefused`, runs after goal ends.
- [ ] Materializer's `_no_change_count` survives tier-2 reload.
- [ ] All existing tests pass.
- [ ] New tests: session restore round-trip, skill cancellation history integrity, tier classification, deferred-reload queue.

## Estimated effort

~5 dev-days. Step 4 (skill cancellation) is the load-bearing piece; the rest is mostly mechanical refactor on top of the existing event-driven architecture.
