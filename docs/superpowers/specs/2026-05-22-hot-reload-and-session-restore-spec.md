# Hot Reload & Session Restore: Implementation Spec

**Date:** 2026-05-22
**Status:** ready-for-implementation
**Plan ref:** `docs/plans/20260522-hot-reload-and-session-restore.md`
**Target:** Codex / autonomous implementation agent

---

## Overview

Implement hot reload and session restore in seven phases. Each phase is independently
deployable and ships with verification criteria. Phase 1 (session restore) is the
minimum viable slice and unlocks the rest. Phase 4 (skill cancellation) is
load-bearing — without it tier-2 reload corrupts agent history.

This spec is prescriptive. Follow the file paths, class names, and method signatures
exactly. Where behaviour is underspecified, prefer the simplest correct
implementation.

---

## Repo conventions (read before writing any code)

- Python 3.14. `from __future__ import annotations` at top of every file.
- Ruff: `line-length = 100`, double quotes, `S101` ignored under `tests/`.
- No comments unless the WHY is non-obvious.
- Events extend `BaseEvent` (pydantic `BaseModel`); add to `EVENT_REGISTRY`.
- DB models extend `SQLModel, table=True`; use `_StateJSON` for portable JSON.
- All timestamps: `datetime.now(tz=UTC).isoformat(timespec="seconds")`.
- Async work: pydantic-ai is sync-wrapped via `asyncio.to_thread`; processors are async.
- Tests use SQLite via `BlackboardDatabase.from_url("sqlite:///...")`.

---

## Phase 1 — Session restore foundation

**Goal:** Conversation history survives process restart. `--resume-last` works.
No reload behaviour yet.

### 1.1 Add `AgentTurnRecorded` event

**File: `harness_poc/core/events.py`**

Append after `LLMTextEmitted`:

```python
class AgentTurnRecorded(BaseEvent):
    messages_blob: list[dict[str, Any]] = Field(default_factory=list)
    ordinal: int = 0
```

Add `AgentTurnRecorded` to `EVENT_REGISTRY`.

### 1.2 Add `session_messages` table

**File: `harness_poc/core/models.py`**

Append after `DbSessionSnapshot`:

```python
class DbSessionMessage(SQLModel, table=True):
    __tablename__ = "session_messages"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "idx_session_messages_session_ordinal",
            "session_id",
            "ordinal",
        ),
    )

    session_id: str = Field(primary_key=True, foreign_key="sessions.session_id")
    ordinal: int = Field(primary_key=True)
    messages_blob: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    created_at: str
```

### 1.3 Database accessors

**File: `harness_poc/core/database.py`**

Add to `BlackboardDatabase`:

```python
def append_session_messages(
    self,
    session_id: str,
    messages_blob: list[dict[str, Any]],
) -> int:
    with Session(self._engine) as session:
        next_ordinal = (
            session.exec(
                select(DbSessionMessage.ordinal)
                .where(DbSessionMessage.session_id == session_id)
                .order_by(col(DbSessionMessage.ordinal).desc())
                .limit(1)
            ).first()
            or 0
        ) + 1
        session.add(
            DbSessionMessage(
                session_id=session_id,
                ordinal=next_ordinal,
                messages_blob=messages_blob,
                created_at=self._utc_now(),
            )
        )
        session.commit()
        return next_ordinal

def load_session_messflashages(self, session_id: str) -> list[dict[str, Any]]:
    with Session(self._engine) as session:
        rows = session.exec(
            select(DbSessionMessage)
            .where(DbSessionMessage.session_id == session_id)
            .order_by(col(DbSessionMessage.ordinal))
        ).all()
    blob: list[dict[str, Any]] = []
    for row in rows:
        blob.extend(row.messages_blob)
    return blob

def get_last_session_id(self) -> str | None:
    with Session(self._engine) as session:
        return session.exec(
            select(DbSession.session_id)
            .order_by(col(DbSession.created_at).desc())
            .limit(1)
        ).first()

def session_exists(self, session_id: str) -> bool:
    with Session(self._engine) as session:
        return session.get(DbSession, session_id) is not None
```

Import `DbSessionMessage` from `harness_poc.core.models`.

### 1.4 Persist turns after chat input

**File: `harness_poc/repl.py`**

In `handle_chat_input`, after the existing `app_state.pydantic_messages.extend(...)`
block (around `repl.py:248`), add:

```python
from pydantic_ai.messages import ModelMessagesTypeAdapter  # at top of file

# ...inside handle_chat_input, after sanitize_new_messages:
new_messages = (
    sanitize_new_messages(
        response.messages,
        tool_result_max_chars=app_state.config.runtime.tool_result_max_chars,
    )
    if response.messages
    else fallback_messages
)
blob = ModelMessagesTypeAdapter.dump_python(new_messages, mode="json")
ordinal = app_state.database.append_session_messages(
    app_state.session_id,
    blob,
)
app_state.event_bus.publish(
    AgentTurnRecorded(
        session_id=app_state.session_id,
        messages_blob=blob,
        ordinal=ordinal,
    )
)
```

Refactor the existing `if response.messages: ... else: ...` to assign to
`new_messages` first, then extend `pydantic_messages` from `new_messages`. Keep
the bounding/pruning logic intact.

Import `AgentTurnRecorded` from `harness_poc.core.events`.

### 1.5 Restore on startup

**File: `harness_poc/app_factory.py`**

Change the signature of `build_app_state`:

```python
def build_app_state(session_id: str | None = None) -> AppState:
    config = HarnessConfig.load()
    configure_logging(config.project_root)

    engine = create_db_engine(config.runtime.database_url)
    database = BlackboardDatabase(engine)
    database.create_tables()
    event_store = EventStore(engine)

    if session_id is not None:
        if not database.session_exists(session_id):
            raise ValueError(f"Session {session_id} not found")
        effective_session_id = session_id
    else:
        effective_session_id = database.start_session(
            "Interactive proof of concept session."
        )
    # ...rest unchanged, replacing session_id with effective_session_id
```

After constructing `messages` and `tools` (around `app_factory.py:240`), insert:

```python
from pydantic_ai.messages import ModelMessagesTypeAdapter  # at top of file

restored_messages: list[ModelMessage] = []
if session_id is not None:
    blob = database.load_session_messages(effective_session_id)
    if blob:
        restored_messages = ModelMessagesTypeAdapter.validate_python(blob)
        restored_messages = _ensure_history_consistent(restored_messages)
```

Pass `pydantic_messages=restored_messages` to the `AppState(...)` constructor at
the bottom (replacing the existing `pydantic_messages=[]`).

Add helper at module level:

```python
def _ensure_history_consistent(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Repair history if the last turn ended mid-tool-call.

    A process killed between a ModelResponse with ToolCallPart and the matching
    ToolReturnPart leaves pydantic-ai's history invalid. Inject a synthetic
    return so the next agent.run succeeds.
    """
    from pydantic_ai.messages import (  # noqa: PLC0415
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    if not messages:
        return messages
    last = messages[-1]
    if not isinstance(last, ModelResponse):
        return messages
    pending: list[ToolCallPart] = [
        p for p in last.parts if isinstance(p, ToolCallPart)
    ]
    if not pending:
        return messages
    repair = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=call.tool_name,
                content="interrupted by process exit",
                tool_call_id=call.tool_call_id,
            )
            for call in pending
        ]
    )
    return [*messages, repair]
```

### 1.6 CLI flags

**File: `harness_poc/cli.py`**

Add typer options to the root callback and the `tui` subcommand:

```python
@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    resume: Annotated[str | None, typer.Option("--resume", help="Resume session by id")] = None,
    resume_last: Annotated[bool, typer.Option("--resume-last", help="Resume most recent session")] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        ctx.obj = _ResumeOptions(resume=resume, resume_last=resume_last)
        return
    _launch_repl(resume=resume, resume_last=resume_last)


@dataclass(frozen=True, slots=True)
class _ResumeOptions:
    resume: str | None
    resume_last: bool


def _resolve_session_id(opts: _ResumeOptions | None) -> str | None:
    if opts is None:
        return None
    if opts.resume:
        return opts.resume
    if opts.resume_last:
        from harness_poc.core.config import HarnessConfig  # noqa: PLC0415
        from harness_poc.core.database import BlackboardDatabase  # noqa: PLC0415
        config = HarnessConfig.load()
        db = BlackboardDatabase.from_url(config.runtime.database_url)
        last = db.get_last_session_id()
        if last is None:
            print_error("No prior sessions found.")
            raise typer.Exit(code=1)
        return last
    return None
```

Update `_launch_repl` and the `tui` command to call
`build_app_state(session_id=_resolve_session_id(...))`.

### 1.7 Verification

1. `uv run pytest tests/test_app_factory.py` — add a test that builds twice
   with the same `session_id`, runs a chat turn between, and asserts the second
   build's `pydantic_messages` matches what was persisted.
2. Manual: `uv run harness-poc tui`, send 3 turns, exit, run
   `uv run harness-poc tui --resume-last`, verify chat scroll shows prior
   conversation and the next turn references turn 2 coherently.

---

## Phase 2 — `AppState` topology refactor

**Goal:** Split `AppState` into Identity / LongLived / Runtime layers. No
behaviour change.

### 2.1 New dataclasses

**File: `harness_poc/app_factory.py`**

Replace the `AppState` definition with:

```python
@dataclass(frozen=True, slots=True)
class Identity:
    session_id: str
    database: BlackboardDatabase
    event_bus: EventBus
    event_store: EventStore
    config_project_root: Path
    config_project_id: str


@dataclass(slots=True)
class Runtime:
    config: HarnessConfig
    skill_runner: SkillRunner
    tool_runner: ToolRunner
    pydantic_runtime: PydanticAgentRuntime
    skill_scaffolder: SkillScaffolder
    workflow_runner: WorkflowRunner
    pipeline_runner: PipelineRunner
    tools: list[dict[str, Any]]
    skill_catalog: SkillCatalog


@dataclass(slots=True)
class LongLived:
    materializer: MaterializerRunner
    supervisor: ProcessorSupervisor


@dataclass(slots=True)
class ActiveRunHandle:
    kind: str  # "goal" | "pipeline" | "chat"
    name: str
    started_at: str


@dataclass(slots=True)
class AppState:
    identity: Identity
    runtime: Runtime
    long_lived: LongLived
    pydantic_messages: list[ModelMessage]
    goal_decision_model: Model | None
    messages: list[Message]
    streaming: StreamingContext
    active_run: ActiveRunHandle | None = None

    @property
    def session_id(self) -> str:
        return self.identity.session_id

    @property
    def database(self) -> BlackboardDatabase:
        return self.identity.database

    @property
    def event_bus(self) -> EventBus:
        return self.identity.event_bus

    @property
    def config(self) -> HarnessConfig:
        return self.runtime.config

    @property
    def skill_runner(self) -> SkillRunner:
        return self.runtime.skill_runner

    @property
    def tool_runner(self) -> ToolRunner:
        return self.runtime.tool_runner

    @property
    def pydantic_runtime(self) -> PydanticAgentRuntime:
        return self.runtime.pydantic_runtime

    @property
    def workflow_runner(self) -> WorkflowRunner:
        return self.runtime.workflow_runner

    @property
    def pipeline_runner(self) -> PipelineRunner:
        return self.runtime.pipeline_runner

    @property
    def materializer_runner(self) -> MaterializerRunner:
        return self.long_lived.materializer
```

The property shims keep all existing call sites
(`app_state.session_id`, `app_state.config`, etc.) working without edits.

### 2.2 Split `build_app_state`

```python
def build_identity(
    config: HarnessConfig,
    session_id: str | None,
) -> Identity:
    engine = create_db_engine(config.runtime.database_url)
    database = BlackboardDatabase(engine)
    database.create_tables()
    event_store = EventStore(engine)
    event_bus = EventBus(event_store)
    effective_session_id = _resolve_or_create_session(database, session_id)
    return Identity(
        session_id=effective_session_id,
        database=database,
        event_bus=event_bus,
        event_store=event_store,
        config_project_root=config.project_root,
        config_project_id=config.project_id,
    )


def build_runtime_layer(identity: Identity, config: HarnessConfig) -> Runtime:
    """Build the reloadable layer. Re-callable on hot reload."""
    skill_runner = SkillRunner(database=identity.database, config=config)
    db_proxy = BlackboardAccessProxy(identity.database, _permissive_for_tools())
    tool_runner = ToolRunner(
        config=config,
        skill_runner=skill_runner,
        database=db_proxy,
        runtime_config=config.runtime,
    )
    workflow_runner = WorkflowRunner(skill_runner)
    pipeline_runner = PipelineRunner(config.paths.pipelines)

    system_prompt = config.paths.soul.read_text(encoding="utf-8")
    project_state = identity.database.ensure_project_state()
    session_state = identity.database.ensure_session_state(identity.session_id)
    state_context = build_state_context(project_state, session_state)
    corpus_key = f"{identity.config_project_id}:default"
    context_map = identity.database.get_context_map(corpus_key)
    context_map_block = (
        f"--- Context Map ---\n{json.dumps(context_map, indent=2)}\n---"
        if context_map
        else ""
    )
    full_system_prompt = "\n\n".join(
        filter(None, [system_prompt, state_context, context_map_block or None])
    )

    knowledge_dirs = [config.paths.project_skills]
    if config.paths.system_skills.exists():
        knowledge_dirs.append(config.paths.system_skills)
    init_knowledge_context(
        knowledge_dirs,
        project_root=config.project_root,
        scratch_base=None,
        session_id=identity.session_id,
    )
    skill_catalog = build_skill_catalog(knowledge_dirs)
    tools = skill_runner.discover_skills()

    return Runtime(
        config=config,
        skill_runner=skill_runner,
        tool_runner=tool_runner,
        pydantic_runtime=build_runtime(
            session_id=identity.session_id,
            database=identity.database,
            config=config,
            skill_runner=skill_runner,
            tool_runner=tool_runner,
            system_prompt=full_system_prompt,
            llm=config.llm,
            enable_tools=True,
            blocked_skills=_TUI_BLOCKED_SKILLS,
            skill_catalog=skill_catalog,
        ),
        skill_scaffolder=SkillScaffolder(config),
        workflow_runner=workflow_runner,
        pipeline_runner=pipeline_runner,
        tools=tools,
        skill_catalog=skill_catalog,
    )


def build_app_state(session_id: str | None = None) -> AppState:
    config = HarnessConfig.load()
    configure_logging(config.project_root)
    identity = build_identity(config, session_id)
    runtime = build_runtime_layer(identity, config)
    materializer = MaterializerRunner(
        db=identity.database,
        skill_runner=runtime.skill_runner,
        config=config,
        session_id=identity.session_id,
        poll_interval=config.runtime.materializer_poll_interval,
    )
    supervisor = ProcessorSupervisor(identity=identity)
    long_lived = LongLived(materializer=materializer, supervisor=supervisor)

    if config.observability.logfire_enabled:
        from harness_poc.core.logfire_subscriber import (  # noqa: PLC0415
            configure_logfire,
            wire_logfire,
        )
        configure_logfire(include_content=config.observability.logfire_include_content)
        wire_logfire(identity.event_bus)

    return _build_app_state_with(
        identity=identity,
        runtime=runtime,
        long_lived=long_lived,
        config=config,
        session_id_was_resumed=session_id is not None,
    )
```

Move `messages` / `pydantic_messages` / `restore` construction into
`_build_app_state_with` for clarity.

### 2.3 Verification

`uv run pytest` clean. No new tests required — the refactor is structural.

---

## Phase 3 — `ProcessorSupervisor` + materializer reference swap

**Goal:** Processors become restartable. Materializer survives swap.

### 3.1 `ProcessorSupervisor`

**File: `harness_poc/core/processor_supervisor.py`** (new):

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from harness_poc.core.processors.circuit_breaker import run_circuit_breaker
from harness_poc.core.processors.llm_worker import run_llm_worker
from harness_poc.core.processors.tool_worker import run_skill_worker

if TYPE_CHECKING:
    from harness_poc.app_factory import Identity, Runtime

logger = logging.getLogger(__name__)

_STOP_TIMEOUT_S = 5.0


class ProcessorSupervisor:
    def __init__(self, identity: Identity) -> None:
        self._identity = identity
        self._tasks: list[asyncio.Task[None]] = []
        self._in_flight_calls: dict[str, str] = {}  # call_id -> skill_name

    async def start(self, runtime: Runtime) -> None:
        if self._tasks:
            raise RuntimeError("Supervisor already started")
        bus = self._identity.event_bus
        session_id = self._identity.session_id
        db = self._identity.database

        self._tasks = [
            asyncio.create_task(
                run_circuit_breaker(
                    bus,
                    session_id,
                    max_retries=runtime.config.runtime.max_retries,
                    max_tokens=runtime.config.runtime.max_tokens,
                ),
                name="circuit_breaker",
            ),
            asyncio.create_task(
                run_llm_worker(
                    bus,
                    session_id,
                    db,
                    runtime.config,
                    runtime.skill_runner,
                ),
                name="llm_worker",
            ),
            asyncio.create_task(
                run_skill_worker(
                    bus,
                    session_id,
                    runtime.skill_runner,
                    on_call_started=self._record_call_started,
                    on_call_ended=self._record_call_ended,
                ),
                name="tool_worker",
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await asyncio.wait_for(task, timeout=_STOP_TIMEOUT_S)
            except (TimeoutError, asyncio.CancelledError):
                logger.warning("Processor %s did not exit cleanly", task.get_name())
        self._tasks = []

    async def restart(self, runtime: Runtime) -> None:
        await self.stop()
        await self.start(runtime)

    def in_flight(self) -> list[tuple[str, str]]:
        return list(self._in_flight_calls.items())

    def _record_call_started(self, call_id: str, skill_name: str) -> None:
        self._in_flight_calls[call_id] = skill_name

    def _record_call_ended(self, call_id: str) -> None:
        self._in_flight_calls.pop(call_id, None)
```

### 3.2 Wire tool worker callbacks

**File: `harness_poc/core/processors/tool_worker.py`**

Add optional `on_call_started` / `on_call_ended` callbacks to `run_skill_worker`.
Invoke at the start and end of each skill dispatch. Existing behaviour
unchanged when callbacks are `None`.

### 3.3 `MaterializerRunner.swap_runtime`

**File: `harness_poc/core/materializer_runner.py`**

Replace separate `_skill_runner` / `_config` attributes with a single mutable
`_runtime` reference:

```python
class MaterializerRunner:
    def __init__(
        self,
        db: BlackboardDatabase,
        skill_runner: SkillRunner,
        config: HarnessConfig,
        session_id: str,
        poll_interval: float = 30.0,
    ) -> None:
        self._db = db
        self._session_id = session_id
        self._poll_interval = poll_interval
        self._no_change_count: dict[str, int] = {}
        self._skill_runner = skill_runner
        self._config = config

    def swap_runtime(self, runtime: Runtime) -> None:
        """Atomically replace runtime references. _no_change_count preserved."""
        self._skill_runner = runtime.skill_runner
        self._config = runtime.config
```

(Two-attribute swap is acceptable here — Python attribute assignment cannot be
preempted by another asyncio coroutine, and only the loop reads these fields.)

### 3.4 `main.py` adoption

**File: `harness_poc/main.py`**

```python
async def run_async_main(session_id: str | None = None) -> None:
    app_state = build_app_state(session_id=session_id)
    await app_state.long_lived.supervisor.start(app_state.runtime)
    materializer_task = asyncio.create_task(
        app_state.long_lived.materializer.run_forever(),
        name="materializer",
    )
    try:
        await materializer_task
    finally:
        await app_state.long_lived.supervisor.stop()
```

### 3.5 Verification

- Unit test: build `AppState`, capture materializer's `_no_change_count`, set
  one entry to `5`, call `supervisor.restart(new_runtime)`, assert
  `_no_change_count` still has `5`.
- Manual: launch TUI, observe processors run normally. No behaviour change yet.

---

## Phase 4 — Skill cancellation (load-bearing)

**Goal:** In-flight skills can be cancelled cleanly with a synthetic tool
return that keeps pydantic-ai history valid.

### 4.1 `SkillCancelled` event

**File: `harness_poc/core/events.py`**

```python
class SkillCancelled(BaseEvent):
    call_id: str
    skill_name: str
    reason: str  # "reload" | "user_interrupt"
```

Register in `EVENT_REGISTRY`.

### 4.2 Cancellation token

**File: `harness_poc/core/skill_context.py`**

Add to `SkillContext`:

```python
@dataclass(slots=True)
class CancellationToken:
    _cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str) -> None:
        self._cancelled = True
        self.reason = reason

    @property
    def cancelled(self) -> bool:
        return self._cancelled


# inside SkillContext dataclass:
cancellation: CancellationToken = field(default_factory=CancellationToken)

@property
def cancelled(self) -> bool:
    return self.cancellation.cancelled
```

### 4.3 Tool runner integration

**File: `harness_poc/core/tool_runner.py`**

Track active tokens by `call_id`:

```python
class ToolRunner:
    def __init__(self, ...) -> None:
        # existing init...
        self._active_tokens: dict[str, CancellationToken] = {}

    def cancel_call(self, call_id: str, reason: str) -> None:
        token = self._active_tokens.get(call_id)
        if token is not None:
            token.cancel(reason)
```

In the dispatch path, register the token under `call_id` before invoking the
skill and pop it afterwards. Long-running system tools
(`container_exec`, `execute_python`, `web_search`) wrap their blocking call:

```python
async def _execute_with_token(
    self,
    fn: Callable[..., SkillResult],
    token: CancellationToken,
    timeout_s: float,
    *args: Any,
    **kwargs: Any,
) -> SkillResult:
    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    while not task.done():
        if token.cancelled:
            task.cancel()
            return SkillResult(
                status="cancelled",
                content=f"cancelled: {token.reason}",
                artifacts={},
            )
        await asyncio.sleep(0.05)
    return await task
```

Cooperative skills check `ctx.cancelled` at safe points. Document in
`docs/skills.md`.

### 4.4 Synthetic tool return injection

**File: `harness_poc/core/processors/tool_worker.py`**

When the worker receives a cancelled `SkillResult`, emit `SkillCancelled` AND
inject a synthetic `ToolReturnPart` into `pydantic_messages`. The injection
happens via a new helper on `PydanticAgentRuntime`:

**File: `harness_poc/core/pydantic_runtime.py`**

```python
def inject_synthetic_tool_return(
    self,
    messages: list[ModelMessage],
    call_id: str,
    tool_name: str,
    content: str,
) -> list[ModelMessage]:
    from pydantic_ai.messages import ModelRequest, ToolReturnPart  # noqa: PLC0415

    return [
        *messages,
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name=tool_name,
                    content=content,
                    tool_call_id=call_id,
                )
            ]
        ),
    ]
```

The reload coordinator (Phase 6) is responsible for calling this for each
cancelled in-flight call, appending the result to `AppState.pydantic_messages`,
and persisting via `database.append_session_messages`.

### 4.5 Verification (critical)

Create `tests/test_skill_cancellation.py`:

```python
async def test_cancellation_preserves_history(app_state: AppState) -> None:
    # Start a 10s skill in background
    call_id = "test-call-1"
    task = asyncio.create_task(
        app_state.tool_runner.execute(
            skill_name="execute_python",
            call_id=call_id,
            args={"code": "import time; time.sleep(10)"},
        )
    )
    await asyncio.sleep(0.2)

    app_state.tool_runner.cancel_call(call_id, reason="reload")
    result = await task

    assert result.status == "cancelled"

    # Simulate worker injection
    app_state.pydantic_messages = app_state.pydantic_runtime.inject_synthetic_tool_return(
        app_state.pydantic_messages,
        call_id=call_id,
        tool_name="execute_python",
        content="cancelled: reload",
    )

    # History must be valid for next agent.run
    response = app_state.pydantic_runtime.run_text(
        "What just happened?",
        message_history=app_state.pydantic_messages,
    )
    assert response.content  # no validation error
```

---

## Phase 5 — Active-run gate

**Goal:** Reload is refused while a goal, pipeline, or chat turn is active.

### 5.1 New events

**File: `harness_poc/core/events.py`**

```python
class ActiveRunStarted(BaseEvent):
    kind: str  # "goal" | "pipeline" | "chat"
    name: str


class ActiveRunEnded(BaseEvent):
    kind: str
    name: str
    status: str  # "completed" | "failed"


class RuntimeReloadRequested(BaseEvent):
    paths: list[str] = Field(default_factory=list)
    manual: bool = False


class RuntimeReloaded(BaseEvent):
    tier: str  # "tier_1" | "tier_2"
    duration_ms: int
    paths: list[str] = Field(default_factory=list)


class ReloadRefused(BaseEvent):
    reason: str  # "active_run" | "identity_change"
    detail: str = ""
    paths: list[str] = Field(default_factory=list)
```

Register all five in `EVENT_REGISTRY`.

### 5.2 `active_run` context manager

**File: `harness_poc/core/active_run.py`** (new):

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from harness_poc.core.events import ActiveRunEnded, ActiveRunStarted

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from harness_poc.app_factory import ActiveRunHandle, AppState


RunKind = Literal["goal", "pipeline", "chat"]


@asynccontextmanager
async def active_run(state: AppState, kind: RunKind, name: str) -> AsyncIterator[None]:
    from harness_poc.app_factory import ActiveRunHandle  # noqa: PLC0415

    started_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    state.active_run = ActiveRunHandle(kind=kind, name=name, started_at=started_at)
    await state.event_bus.publish_async(
        ActiveRunStarted(session_id=state.session_id, kind=kind, name=name)
    )
    status = "completed"
    try:
        yield
    except BaseException:
        status = "failed"
        raise
    finally:
        state.active_run = None
        await state.event_bus.publish_async(
            ActiveRunEnded(session_id=state.session_id, kind=kind, name=name, status=status)
        )
```

### 5.3 Wrap entry points

- `GoalRunner.run` (`core/goal_runner.py`) — wrap body with `async with active_run(state, "goal", objective):`.
- `PipelineRunner.run` (`core/pipeline_runner.py`) — wrap with `kind="pipeline"`.
- `handle_chat_input` (`repl.py`) — wrap with `kind="chat", name="turn"`. Note
  this is currently sync; either make it async-aware or use a sync mirror that
  publishes events directly.

For the sync `handle_chat_input` case, use a sync helper:

```python
def begin_active_run(state: AppState, kind: str, name: str) -> None:
    state.active_run = ActiveRunHandle(kind=kind, name=name, started_at=_utc_now())
    state.event_bus.publish(ActiveRunStarted(session_id=state.session_id, kind=kind, name=name))


def end_active_run(state: AppState, status: str = "completed") -> None:
    if state.active_run is None:
        return
    handle = state.active_run
    state.active_run = None
    state.event_bus.publish(
        ActiveRunEnded(
            session_id=state.session_id, kind=handle.kind, name=handle.name, status=status
        )
    )
```

### 5.4 Verification

Test that emits `RuntimeReloadRequested` mid-goal asserts no `RuntimeReloaded`
fires until `ActiveRunEnded`.

---

## Phase 6 — Watcher + `ReloadCoordinator` + `sys.modules` surgery

**Goal:** Filesystem changes drive reload.

### 6.1 Dependency

Add `watchfiles = "^0.24"` to `pyproject.toml` `[project.dependencies]`.

### 6.2 Path classification

**File: `harness_poc/core/reload_classifier.py`** (new):

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

ReloadTier = Literal["tier_1", "tier_2", "tier_3"]

TIER_3_IDENTITY = frozenset({
    "harness_poc/app_factory.py",
    "harness_poc/main.py",
    "harness_poc/cli.py",
    "harness_poc/tui.py",
    "harness_poc/repl.py",
    "harness_poc/core/database.py",
    "harness_poc/core/db_engine.py",
    "harness_poc/core/event_bus.py",
    "harness_poc/core/event_store.py",
    "harness_poc/core/events.py",
    "harness_poc/core/models.py",
})

TIER_1_PREFIXES = (
    "skills/",
    "harness_poc/system_skills/",
)

TIER_3_CONFIG_KEYS = frozenset({
    "runtime.database_url",
    "project.id",
    "paths.soul",
    "paths.project_skills",
    "paths.system_skills",
    "paths.pipelines",
})


def classify(paths: list[str], project_root: Path) -> ReloadTier:
    rels = [_to_rel(p, project_root) for p in paths]
    if any(r in TIER_3_IDENTITY for r in rels):
        return "tier_3"
    if any(r.startswith(p) for r in rels for p in TIER_1_PREFIXES):
        if not any(_is_tier_2(r) for r in rels):
            return "tier_1"
    if any(r == "harness.yaml" for r in rels):
        # caller resolves which keys changed via diff_yaml_keys
        return "tier_2"  # default; caller may override to tier_3
    return "tier_2"


def _to_rel(path: str, project_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(project_root))
    except ValueError:
        return path


def _is_tier_2(rel: str) -> bool:
    return rel.startswith("harness_poc/") and not rel.startswith(
        ("harness_poc/system_skills/",)
    )


def diff_yaml_keys(old: dict, new: dict, prefix: str = "") -> set[str]:
    """Return the dotted paths whose values changed between two configs."""
    changed: set[str] = set()
    keys = set(old.keys()) | set(new.keys())
    for key in keys:
        dotted = f"{prefix}.{key}" if prefix else key
        old_v = old.get(key)
        new_v = new.get(key)
        if isinstance(old_v, dict) and isinstance(new_v, dict):
            changed |= diff_yaml_keys(old_v, new_v, dotted)
        elif old_v != new_v:
            changed.add(dotted)
    return changed
```

### 6.3 `ReloadCoordinator`

**File: `harness_poc/core/reload_coordinator.py`** (new):

```python
from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import time
from typing import TYPE_CHECKING

from watchfiles import awatch

from harness_poc.core.events import (
    ActiveRunEnded,
    ReloadRefused,
    RuntimeReloaded,
    RuntimeReloadRequested,
    SkillCancelled,
)
from harness_poc.core.reload_classifier import classify

if TYPE_CHECKING:
    from harness_poc.app_factory import AppState

logger = logging.getLogger(__name__)

TIER_2_MODULES: tuple[str, ...] = (
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

TIER_2_PREFIXES: tuple[str, ...] = (
    "harness_poc.system_tools.",
    "harness_poc.system_skills.",
)


async def watch_files(state: AppState, debounce_ms: int = 300) -> None:
    root = state.identity.config_project_root
    async for changes in awatch(root, debounce=debounce_ms):
        paths = [str(path) for _change, path in changes]
        await state.event_bus.publish_async(
            RuntimeReloadRequested(session_id=state.session_id, paths=paths)
        )


async def run_reload_coordinator(state: AppState) -> None:
    pending: RuntimeReloadRequested | None = None
    async for event in state.event_bus.subscribe_session(state.session_id):
        if isinstance(event, ActiveRunEnded) and pending is not None:
            queued, pending = pending, None
            await _handle_request(state, queued)
            continue
        if not isinstance(event, RuntimeReloadRequested):
            continue
        if state.active_run is not None:
            pending = event
            await state.event_bus.publish_async(
                ReloadRefused(
                    session_id=state.session_id,
                    reason="active_run",
                    detail=f"{state.active_run.kind}:{state.active_run.name}",
                    paths=event.paths,
                )
            )
            continue
        await _handle_request(state, event)


async def _handle_request(state: AppState, event: RuntimeReloadRequested) -> None:
    tier = classify(event.paths, state.identity.config_project_root)
    if tier == "tier_3":
        await state.event_bus.publish_async(
            ReloadRefused(
                session_id=state.session_id,
                reason="identity_change",
                paths=event.paths,
            )
        )
        return
    started = time.perf_counter()
    if tier == "tier_1":
        await _reload_tier_1(state)
    else:
        await _reload_tier_2(state)
    duration_ms = int((time.perf_counter() - started) * 1000)
    await state.event_bus.publish_async(
        RuntimeReloaded(
            session_id=state.session_id,
            tier=tier,
            duration_ms=duration_ms,
            paths=event.paths,
        )
    )


async def _reload_tier_1(state: AppState) -> None:
    new_tools = state.runtime.skill_runner.rediscover_skills()
    state.runtime.tools = new_tools
    state.runtime.pydantic_runtime.swap_tools(new_tools)


async def _reload_tier_2(state: AppState) -> None:
    await _drain_in_flight(state)
    _drop_modules()
    from harness_poc.app_factory import build_runtime_layer  # noqa: PLC0415
    from harness_poc.core.config import HarnessConfig  # noqa: PLC0415

    fresh_config = HarnessConfig.load()
    new_runtime = build_runtime_layer(state.identity, fresh_config)
    state.runtime = new_runtime
    state.long_lived.materializer.swap_runtime(new_runtime)
    await state.long_lived.supervisor.restart(new_runtime)


async def _drain_in_flight(state: AppState) -> None:
    in_flight = state.long_lived.supervisor.in_flight()
    for call_id, skill_name in in_flight:
        state.runtime.tool_runner.cancel_call(call_id, reason="reload")
        await state.event_bus.publish_async(
            SkillCancelled(
                session_id=state.session_id,
                call_id=call_id,
                skill_name=skill_name,
                reason="reload",
            )
        )
        state.pydantic_messages = state.runtime.pydantic_runtime.inject_synthetic_tool_return(
            state.pydantic_messages,
            call_id=call_id,
            tool_name=skill_name,
            content="cancelled: reload",
        )
        from pydantic_ai.messages import ModelMessagesTypeAdapter  # noqa: PLC0415
        blob = ModelMessagesTypeAdapter.dump_python(
            state.pydantic_messages[-1:], mode="json"
        )
        state.identity.database.append_session_messages(state.session_id, blob)


def _drop_modules() -> None:
    targets = set(TIER_2_MODULES)
    for name in list(sys.modules.keys()):
        if name in targets or name.startswith(TIER_2_PREFIXES):
            sys.modules.pop(name, None)
```

### 6.4 Skill rediscovery + tool swap

**File: `harness_poc/core/skill_runner.py`**

Add to `SkillRunner`:

```python
def rediscover_skills(self) -> list[ToolSchema]:
    """Re-scan skill directories and update cached tools."""
    self._discovery_cache = None  # if cache exists
    return self.discover_skills()
```

**File: `harness_poc/core/pydantic_runtime.py`**

Add to `PydanticAgentRuntime`:

```python
def swap_tools(self, tools: list[dict[str, Any]]) -> None:
    """Replace the agent's tool registry without rebuilding the agent."""
    # Implementation depends on pydantic-ai internals; rebuild the agent if
    # in-place tool swap is unsupported.
    self._tools = tools
    self._agent = self._build_agent_with_tools(tools)
```

### 6.5 Launch watcher and coordinator

**File: `harness_poc/main.py`**

```python
async def run_async_main(session_id: str | None = None) -> None:
    app_state = build_app_state(session_id=session_id)
    await app_state.long_lived.supervisor.start(app_state.runtime)

    tasks = [
        asyncio.create_task(
            app_state.long_lived.materializer.run_forever(), name="materializer"
        ),
    ]
    if app_state.config.runtime.hot_reload_enabled:
        from harness_poc.core.reload_coordinator import (  # noqa: PLC0415
            run_reload_coordinator,
            watch_files,
        )
        tasks.append(asyncio.create_task(watch_files(app_state), name="watch_files"))
        tasks.append(
            asyncio.create_task(run_reload_coordinator(app_state), name="reload_coordinator")
        )

    try:
        await asyncio.gather(*tasks)
    finally:
        await app_state.long_lived.supervisor.stop()
```

Add `hot_reload_enabled: bool = False` to `RuntimeConfig` in `core/config.py`,
defaulting to `False` in `harness.yaml`. Dev users set
`runtime.hot_reload_enabled: true`.

### 6.6 Verification

1. Set `hot_reload_enabled: true` in `harness.yaml`.
2. Launch TUI. Edit `skills/web_search/skill.py` (add a log). Send a chat turn
   that uses the skill. Assert log appears (tier 1).
3. Edit `harness_poc/core/processors/llm_worker.py`. Send a chat turn. Assert
   `RuntimeReloaded(tier="tier_2")` event in `state_events` table.
4. Edit `harness_poc/tui.py`. Assert `ReloadRefused(reason="identity_change")`
   event present.
5. Start a `/goal` run. Edit a skill mid-goal. Assert `ReloadRefused`. Wait
   for goal to end. Assert `RuntimeReloaded` fires automatically.

---

## Phase 7 — TUI integration

**Goal:** Visible reload status and manual triggers.

### 7.1 Banner widget

**File: `harness_poc/tui.py`**

Add `_reload_banner` to `ChatApp.compose`:

```python
def compose(self) -> ComposeResult:
    yield Static("", id="header")
    yield Static("", id="reload-banner")
    yield VerticalScroll(id="chat")
    # ...rest unchanged
```

CSS:

```css
#reload-banner {
    height: 1;
    color: $warning;
    padding: 0 1;
}
```

### 7.2 Subscribe to reload events

In `on_mount`:

```python
self._reload_subscription = asyncio.create_task(
    self._consume_reload_events(), name="tui_reload_subscriber"
)


async def _consume_reload_events(self) -> None:
    from harness_poc.core.events import (  # noqa: PLC0415
        ActiveRunEnded,
        ActiveRunStarted,
        ReloadRefused,
        RuntimeReloaded,
        RuntimeReloadRequested,
    )
    async for event in self._app_state.event_bus.subscribe_session(
        self._app_state.session_id
    ):
        banner = self.query_one("#reload-banner", Static)
        if isinstance(event, RuntimeReloadRequested):
            banner.update("[yellow]reloading…[/yellow]")
        elif isinstance(event, RuntimeReloaded):
            banner.update(f"[green]✓ reloaded {event.tier} ({event.duration_ms}ms)[/green]")
        elif isinstance(event, ReloadRefused) and event.reason == "identity_change":
            banner.update("[red]identity changed — type /restart[/red]")
        elif isinstance(event, ReloadRefused) and event.reason == "active_run":
            banner.update(f"[dim]reload deferred ({event.detail})[/dim]")
        elif isinstance(event, ActiveRunEnded):
            pass
        elif isinstance(event, ActiveRunStarted):
            pass
```

### 7.3 `/reload` and `/restart` commands

In `_handle_command` (or REPL dispatcher), match `/reload`:

```python
if user_input.strip() == "/reload":
    self._app_state.event_bus.publish(
        RuntimeReloadRequested(session_id=self._app_state.session_id, manual=True)
    )
    return
if user_input.strip() == "/restart":
    self._app_state.event_bus.publish(
        AgentInputAdded(session_id=self._app_state.session_id, user_content="[restart]")
    )
    self.exit()
    return
```

The `--resume <current_session_id>` flag is auto-appended by an outer
supervisor script (`Justfile` recipe `dev`):

```bash
dev:
    @while true; do \
        SESSION_ID=$$(uv run harness-poc state last-session-id 2>/dev/null || echo ""); \
        if [ -n "$$SESSION_ID" ]; then \
            uv run harness-poc tui --resume "$$SESSION_ID"; \
        else \
            uv run harness-poc tui; \
        fi; \
        echo "restarting in 1s..."; sleep 1; \
    done
```

### 7.4 Replay on resume

In `ChatApp.on_mount`, if `self._app_state.pydantic_messages` is non-empty,
populate `_chat_messages`:

```python
from pydantic_ai.messages import (  # noqa: PLC0415
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

for msg in self._app_state.pydantic_messages:
    if isinstance(msg, ModelRequest):
        for part in msg.parts:
            if isinstance(part, UserPromptPart):
                self._chat_messages.append(f"You: {part.content}")
    elif isinstance(msg, ModelResponse):
        for part in msg.parts:
            if isinstance(part, TextPart):
                self._chat_messages.append(f"Agent: {part.content}")
            elif isinstance(part, ToolCallPart):
                self._chat_messages.append(f"  [tool] {part.tool_name}")

self._render_chat_history()  # add helper if needed
```

### 7.5 Verification

End-to-end manual run:

1. `uv run harness-poc tui --resume-last`.
2. Verify prior conversation appears in chat scroll.
3. Edit a skill — banner shows `✓ reloaded tier_1`.
4. Edit `tui.py` — banner shows `identity changed — type /restart`.
5. Run `/restart` (via `just dev`) — session restored, banner clears.

---

## Acceptance checklist

- [ ] `harness-poc --resume-last` restores conversation across process exit.
- [ ] `harness-poc --resume <id>` restores a specific session.
- [ ] Mid-tool-call session restore repairs the dangling tool call.
- [ ] `AgentTurnRecorded` is persisted on every chat turn.
- [ ] Editing a project skill triggers tier-1 reload within ~1s.
- [ ] Editing `core/processors/llm_worker.py` triggers tier-2 reload.
- [ ] Mid-flight skills cancelled on tier-2 reload emit `SkillCancelled` and
      produce valid post-reload pydantic-ai history.
- [ ] Editing `tui.py` triggers `ReloadRefused(reason="identity_change")`.
- [ ] `/reload` during an active goal emits `ReloadRefused(reason="active_run")`
      and runs automatically once the goal ends.
- [ ] Materializer's `_no_change_count` survives tier-2 reload.
- [ ] `hot_reload_enabled: false` (default) preserves existing behaviour.
- [ ] All existing tests pass.
- [ ] New tests in `tests/test_skill_cancellation.py`,
      `tests/test_session_restore.py`, `tests/test_reload_coordinator.py`,
      `tests/test_reload_classifier.py`.

---

## Estimated effort

~5 dev-days. Phase 4 (skill cancellation) is the load-bearing piece; the rest
is mostly mechanical refactor on top of the existing event-driven architecture.
