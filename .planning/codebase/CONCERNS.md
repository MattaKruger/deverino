---
title: Codebase Concerns
mapped_at: 2026-07-11
last_mapped_commit: cf99f7e
focus: concerns
---

# Codebase Concerns

This map separates defects observed in the current checkout from risks that depend on deployment or load. It covers the whole repository, with extra detail on extracting the reusable context backbone described in `docs/superpowers/specs/2026-07-11-context-backbone-refactor-discovery.md`.

## Immediate Breakage

### Observed

- **The full pytest suite does not collect.** `harness_poc/v2/subscribers/llm_worker.py:24-32` imports `MapEntryReferenced` from `harness_poc.core.events.events`, but that class lives in `harness_poc/core/events/context_map_events.py:138`. `./.venv/bin/pytest -q` stops at `tests/pressure/test_parser.py` with this import error, so the repository currently has no full-suite regression signal.
- **Project-state indexing is unreachable.** `DocumentIndexer.index_project_state` is indented inside the module helper `_under_ignore_prefix` after that helper returns (`harness_poc/core/retrieval/document_index.py:544-623`). `harness_poc/cli.py:510` calls it as an instance method, which will raise `AttributeError`. Ruff also reports the nested block's undefined `DocumentChunk` and `compute_content_hash` names.
- **Static quality gates are red.** `./.venv/bin/ruff check harness_poc skills tests` reports 193 errors; `./.venv/bin/ty check` reports 408 diagnostics. These totals include style debt, but also undefined names, incompatible protocols, and unreachable/misplaced code, so they cannot be treated as cosmetic-only baselines.
- **Configuration contains ignored keys.** `harness.yaml:34` still declares `runtime.materializer_token_budget`, although `RuntimeConfig` does not load it (`harness_poc/core/config.py:34-50,191-213`). `harness.yaml:48-49` declares `compiler.be_enabled` and `compiler.rc_enabled`, but `CompilerConfig` and its loader only accept `enabled`, `model`, and `provider` (`harness_poc/core/config.py:124-133,265-270`). PyYAML mapping access silently leaves these settings ineffective.

## Context Backbone Extraction

### Observed

- **Two incompatible event domains exist.** Runtime events inherit `BaseEvent` and derive PascalCase `event_type` values (`harness_poc/core/events/events.py:10-25`); context events inherit a separate `ContextMapEvent` and use snake-case literal types (`harness_poc/core/events/context_map_events.py:10-21`). They persist to `state_events` and `context_map_events` respectively (`harness_poc/core/storage/models.py:66-74,128-144`). Extraction needs an envelope/adapter boundary rather than moving either hierarchy wholesale.
- **Distilled observations are transient.** `skills/context-map-materializer/skill.py:121-162` passes LLM output directly to the cartographer and persists only the resulting map plus processed flags. There is no immutable observation record. A rebuild from raw events therefore requires another model call and cannot guarantee the same projection.
- **A batch can acknowledge events it never decoded.** `_events_from_rows` stops when its character budget is reached and skips malformed rows (`skills/context-map-materializer/skill.py:334-358`), but every successful branch marks every row in the original `pending` batch processed (`skills/context-map-materializer/skill.py:87-92,139-144,195-200`). Oversized trailing events and malformed events can be permanently discarded without reaching the distiller.
- **Current projection writes are last-writer-wins.** `write_map_and_mark_processed` reads the view, increments `version`, overwrites `map_json`, and marks event rows in one transaction, but accepts no `expected_version` (`harness_poc/core/storage/database.py:746-789`). Concurrent materializers can compute from the same old view and the later commit can erase the earlier projection.
- **Cycle allocation is not the atomic operation its docstring claims.** `get_and_bump_cycle` performs `session.get`, Python increment, and commit (`harness_poc/core/storage/database.py:791-808`); it does not use `SELECT FOR UPDATE`, a version predicate, or the documented `INSERT ... ON CONFLICT`. Concurrent workers can lose increments or collide on first insert.
- **Derived projection events share the raw input queue.** The materializer appends `MapEntryInserted` and `MapEntryEvicted` events before committing the map (`skills/context-map-materializer/skill.py:164-200`). Those newly appended rows are not in the original `pending` IDs and remain pending for a later distillation cycle. A failed map commit also leaves those derived events persisted without the projection that produced them.
- **The materializer is coupled to the host skill runtime.** It is implemented as a project skill, builds the configured LLM internally, reads concrete `HarnessConfig`, and calls concrete database methods (`skills/context-map-materializer/skill.py:20-38,43-72`). The reusable kernel should not retain `SkillContext`, `SkillRunner`, or provider construction.
- **Scope naming is already embedded in host terminology.** Storage and APIs use `corpus_key`, while v2 materialized maps use `project_id` (`harness_poc/core/storage/models.py:128-171`). The extraction must migrate both to the agreed opaque `scope_key` contract without pretending they are currently identical.
- **The existing `version` column is insufficient provenance.** `DbContextMap` has a numeric version and schema version, but no policy revision or consumed-observation set (`harness_poc/core/storage/models.py:146-158`). Reproducing why a view changed currently requires correlating multiple tables and inferred timing.

### Refactor Hazards

- Preserve the atomic part that does exist: map replacement and marking the supplied event IDs processed occur in one database transaction (`harness_poc/core/storage/database.py:762-789`). Splitting repositories without a unit-of-work boundary would introduce a new partial-commit failure.
- Preserve historical deserialization. `MapEntryPromoted` is deprecated but intentionally retained in the registry for old rows (`harness_poc/core/events/context_map_events.py:113-127`). Removing old event classes during cleanup would make retained evidence unreadable.
- Do not equate `EventBus` with the backbone. The bus persists `BaseEvent` to session-scoped `state_events` before live dispatch (`harness_poc/core/events/event_bus.py:28-42`, `event_store.py:29-54`), while context materialization reads a different store. Coupling Component A to this bus would import session and runtime assumptions that the target spec excludes.
- Do not move CopT optimization into the first kernel cut. The pgvector schema and Sentence Transformers/NumPy gates are optional optimization paths (`skills/context-map-materializer/skill.py:75-160,229-317`; `harness_poc/core/storage/database.py:845-1010`). Correct append, observation persistence, replay, and optimistic commit need to work without them first.

## Event Runtime and Lifecycle

### Observed

- **Durable persistence does not imply durable delivery.** `EventBus.publish` commits first and then dispatches in-process; handler exceptions are logged and swallowed (`harness_poc/core/events/event_bus.py:28-42,88-92`). Subscribers have no offset, retry, dead-letter state, or replay-on-start contract.
- **Async delivery is explicitly lossy.** Each subscriber queue is capped at 500 and drops events on overflow (`harness_poc/core/events/event_bus.py:54-65,79-86`). This is acceptable for a local POC only if consumers do not rely on every live notification.
- **Session filtering happens after global fan-out.** Every event is enqueued into every async subscriber queue, then discarded by nonmatching session consumers (`harness_poc/core/events/event_bus.py:54-62,79-82`). Work and queue pressure grow with total subscribers times total events, not events for one session.
- **Known lifecycle gaps are encoded as expected failures.** Tests under `tests/pressure/test_lifecycle_guarantees.py`, `test_session_isolation.py`, `test_event_ordering.py`, and `test_task_spec.py` document missing dispatch/completion events, missing `sub_session_id`, and callback forwarding regressions. They are not protecting the desired behavior while marked `xfail`.
- **Parser compatibility gaps are also expected failures.** `tests/pressure/test_parser.py` documents unsupported XML `invoke` and `tool_call` forms. This matters if models can emit those formats outside native structured tool calling.
- **Runtime construction has parallel paths.** `harness_poc/app_factory.py` composes the default event-driven ReAct runtime while `harness_poc/v2/wiring.py`, `harness_poc/v2/context_engine.py`, and `harness_poc/v2/workflow_orchestrator.py` retain separate pipeline/react composition. Comments in v2 subscribers still describe using the “v1 EventBus.” Ownership is unclear even where implementations are shared.

### Hypotheses to Verify

- If event handlers perform non-idempotent work, persistence-before-dispatch plus swallowed failures can leave the event log claiming an operation occurred while its materialized side effect did not. Verify each subscriber's replay/idempotency behavior before extracting a generic delivery contract.
- If many sessions run concurrently, global fan-out and per-session filtering will become a measurable CPU and queue-memory bottleneck. The current POC has no load evidence establishing the threshold.

## Security and Trust Boundaries

### Observed

- **The FastAPI application has no authentication or authorization middleware.** It exposes session listing, raw history, session creation/deletion, cancellation, chat, state, event, context-map, and compilation endpoints (`harness_poc/api/chat.py`, `harness_poc/api/routes.py`). The CLI defaults to `127.0.0.1`, but accepts an arbitrary `--host` (`harness_poc/cli.py:916-942`).
- **CORS is unrestricted.** `harness_poc/api/__init__.py:18-24` configures `allow_origins=["*"]`, all methods, all headers, and credentials. Localhost binding reduces network reach, but does not prevent a browser page from making cross-origin calls to the local service.
- **Web chat bypasses the guard pipeline used by the TUI.** `harness_poc/api/chat.py:145-156` constructs `ToolRunner` without guards, which defaults to an empty `GuardPipeline` (`harness_poc/core/tools/tool_runner.py:73`; `harness_poc/core/tools/guards.py:582-603`). In contrast, `harness_poc/app_factory.py:391-411` mounts path, size, type, idempotency, content, and query guards.
- **The web chat blackboard proxy is explicitly read/write.** `harness_poc/api/chat.py:146-150` grants both blackboard and workspace `read_write`; this is broader than a read-only dashboard description.
- **Path guards are deny-list based, not project confinement.** `PathGuard` rejects relative paths and selected sensitive prefixes but never requires a resolved absolute path to be under `project_root` (`harness_poc/core/tools/guards.py:99-157`). File tools apply a similar deny list (`harness_poc/system_tools/file_tools.py:82-120`). An absolute path outside the project and outside listed prefixes can pass.
- **Container execution is the stronger boundary.** `execute_python` runs generated code in a session container and documents `/workspace` as read-only (`harness_poc/system_tools/execute_python.py:26-89`). Extraction should preserve this distinction instead of treating Python execution and host file tools as equally isolated.

### Conditional Risk

- Binding the dashboard to a non-loopback interface, reverse-proxying it, or exposing it through a tunnel would make unauthenticated state mutation and model/tool execution remotely reachable. This is a deployment-dependent risk; the checked-in CLI default remains loopback-only.
- Prompt and event payloads may contain proprietary code or user content. Logfire defaults to enabled in `harness.yaml:40-42`, although `logfire_include_content` is false. Verify provider instrumentation behavior before using the harness on sensitive repositories.

## Performance and Operations

### Observed

- **Startup composes many expensive optional systems.** `harness_poc/app_factory.py` initializes PostgreSQL, retrieval, model runtime, skill discovery, background compilation, context materialization, processors, and optional v2 runtime. Failures are frequently degraded through broad exception handling; there are 96 `except Exception` sites across `harness_poc/` and `skills/`.
- **Core files are oversized ownership hubs.** `harness_poc/cli.py` is about 1,900 lines, `repl.py` 1,700, `core/observability/dashboard.py` 1,500, `tui.py` 1,400, `system_tools/file_tools.py` 1,400, and `app_factory.py` 770. Changes to runtime wiring or persistence routinely cross these hubs.
- **The runtime depends on multiple local services.** The default `harness.yaml` requires PostgreSQL, Vespa, a container image/runtime, a model provider, and optional Logfire. Unit tests support SQLite, but production configuration and CopT behavior are PostgreSQL-specific.
- **Background materialization is polling-based.** `MaterializerRunner` scans pending scopes every 30 seconds by default, serially materializes each scope, and retries failed scopes on later polls (`harness_poc/core/execution/materializer_runner.py:17-67`). Slow LLM calls in one scope delay subsequent scopes in that runner.
- **Materialization cost is nondeterministic and partly hidden.** Each batch can embed raw events, call an LLM with retries and a 120-second timeout, embed observations, and update pgvector (`skills/context-map-materializer/skill.py`; `harness.yaml:77-86`). Metrics do not form part of the kernel contract.
- **The full test command depends on optional infrastructure after collection is fixed.** PostgreSQL tests use a dedicated service; Vespa and real-model benchmarks are opt-in. The current collection error masks the later pass/fail/skip profile.

### Hypotheses to Verify

- Broad fallback behavior may make startup appear successful with a `TestModel`, disabled retrieval, or failed compiler preload when the intended live integration is unavailable. Audit user-visible health reporting before treating degraded startup as operational readiness.
- The context-map polling loop is probably adequate for one local process. Multiple app processes would create concurrent materializers and trigger the confirmed last-writer-wins risks above.

## Data and Schema Evolution

### Observed

- Schema evolution is handled by `create_all` plus imperative `_ensure_*` methods in `BlackboardDatabase.create_tables` (`harness_poc/core/storage/database.py:50-58`), not a versioned migration framework. This supports the POC but makes downgrade, ordered rollout, and audit of schema changes difficult.
- Timestamps are stored inconsistently: many tables use ISO strings while `DbStateProposal.resolved_at` uses `DateTime` (`harness_poc/core/storage/models.py`). Correct ordering depends on consistent UTC formatting rather than database timestamp semantics.
- Session message ordinals are allocated with read-max-plus-one (`harness_poc/core/storage/database.py:101-126`). Concurrent appends to one session can choose the same composite primary key.
- `EventStore` has a stable UUID `event_id` in the serialized payload, but `DbStateEvent` has only an integer primary key and no unique column for that UUID (`harness_poc/core/events/events.py:10-14`; `harness_poc/core/storage/models.py:66-74`). Retried producer writes are not idempotent at the storage boundary.
- Unknown or malformed stored runtime events are skipped during reads (`harness_poc/core/events/event_store.py:79-94`). This preserves availability but silently creates incomplete replays unless callers inspect warnings.

## Recommended Order of Work

1. Restore the verification baseline: fix the v2 import and misplaced `index_project_state`, then make pytest collect and classify remaining failures.
2. For Component A, add immutable observation persistence and fix batch acknowledgement before changing package boundaries.
3. Add optimistic `expected_version` commits and a concurrency test for one scope; do not rely on the current cycle counter as a lock.
4. Define one typed producer envelope/adapter and bridge both existing event hierarchies into it; keep the host `EventBus` outside the kernel.
5. Mount the existing guard pipeline in web chat and document loopback-only operation until authentication is deliberately designed.
6. Remove ignored configuration keys and retire duplicate runtime paths only after callers and pressure-test expectations identify the surviving path.

## Verification Snapshot

- Mapped against commit `cf99f7e` with an already-dirty worktree; this document does not classify unrelated uncommitted files as repository defects.
- `./.venv/bin/pytest -q`: failed during collection on the `MapEntryReferenced` import.
- `./.venv/bin/ruff check harness_poc skills tests`: 193 errors.
- `./.venv/bin/ty check`: 408 diagnostics.
- Vespa integration and real-model benchmarks were not run; claims about their runtime behavior are code-derived and marked accordingly.
