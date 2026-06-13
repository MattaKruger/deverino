# Docs Index

## Active

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `architecture/v2-architecture.md` | 2026-06-13 | design | V2 module architecture — module map, dependency graph, contracts, request lifecycle, old-harness touchpoints, and intent-vs-reality gaps |
| `plans/2026-06-13-eventbus-unification.md` | 2026-06-13 | plan | V2 EventBus unification — real adapter, pipeline-as-subscriber, ReAct subscribers, multi-mode runtime (4 phases) |

---

## Archive (pre-v2 — all historical)

Everything below this line documents the proof-of-concept phase. Status is `historical` for all
entries. The structure preserves the original directory layout for path stability.

### `archive/plans/` — Original implementation plans (May 2026)

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/plans/20260518-145020-typer-rich-cli-integration.md` | 2026-05-18 | plan | Typer/Rich CLI migration — command model, module structure, phases |
| `archive/plans/20260518-172417-spec-writer-skill.md` | 2026-05-18 | plan | Spec writer executable skill design |
| `archive/plans/20260518-210320-pydanticai-migration.md` | 2026-05-18 | plan | Migration from raw OpenAI client to PydanticAI runtime |
| `archive/plans/20260518-goal-runner-implementation.md` | 2026-05-18 | plan | Autonomous goal execution loop (ReAct-style) |
| `archive/plans/20260519-auto-invokable-skills.md` | 2026-05-19 | plan | Auto-invokable skill registration and gating |
| `archive/plans/20260519-skill-permission-enforcement.md` | 2026-05-19 | plan | Skill permission model (workspace, blackboard, network) |
| `archive/plans/20260520-test-suite-refactor-and-prompt-testing.md` | 2026-05-20 | plan | Test suite reorganization and LLM prompt testing |
| `archive/plans/20260520-token-delta-accounting.md` | 2026-05-20 | plan | Token usage tracking and billing delta accounting |
| `archive/plans/20260521-plan-mode-vespa-embedding-v2.md` | 2026-05-21 | plan | Vespa embedding integration v2 |
| `archive/plans/20260521-plan-mode-vespa-embedding.md` | 2026-05-21 | plan | Vespa embedding integration v1 |
| `archive/plans/20260522-hot-reload-and-session-restore.md` | 2026-05-22 | plan | Hot-reload watcher and session restore from event log |
| `archive/plans/20260523-195500-acdl-agent-inspectable-spec.md` | 2026-05-23 | plan | ACDL as agent-inspectable specification format |
| `archive/plans/20260523-acdl-agent-tooling.md` | 2026-05-23 | plan | ACDL tooling for agent-driven spec workflows |
| `archive/plans/20260523-sprint-contract-delegate-task-impl.md` | 2026-05-23 | plan | Delegate-task sprint contract implementation |
| `archive/plans/20260523-sprint-contract-delegate-task.md` | 2026-05-23 | plan | Delegate-task sprint contract design |

### `archive/superpowers/plans/` — Claude-generated implementation plans (May–Jul 2026)

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/superpowers/plans/2026-05-18-event-driven-agents.md` | 2026-05-18 | plan | Event-driven agent runtime: workers, event bus, ReAct loop |
| `archive/superpowers/plans/2026-05-18-spec-writer-gather-mode.md` | 2026-05-18 | plan | Spec writer gather-mode for aggregating context |
| `archive/superpowers/plans/2026-05-19-pipeline-runner.md` | 2026-05-19 | plan | Declarative DAG pipeline runner |
| `archive/superpowers/plans/2026-05-19-streaming-hardening.md` | 2026-05-19 | plan | LLM streaming reliability hardening |
| `archive/superpowers/plans/2026-05-19-textual-chat-tui.md` | 2026-05-19 | plan | Textual-based chat TUI |
| `archive/superpowers/plans/2026-05-20-vespa-document-retrieval.md` | 2026-05-20 | plan | Vespa document retrieval — indexing, search, skills |
| `archive/superpowers/plans/2026-05-22-docling-pdf-pipeline.md` | 2026-05-22 | plan | Docling PDF conversion pipeline |
| `archive/superpowers/plans/2026-05-23-core-module-restructure.md` | 2026-05-23 | plan | Core module reorganization |
| `archive/superpowers/plans/2026-05-23-deterministic-cartographer.md` | 2026-05-23 | plan | Deterministic cartographer stress testing |
| `archive/superpowers/plans/2026-05-24-auto-observe-post-turn-hook.md` | 2026-05-24 | plan | Auto-observe post-turn hook (part 1) |
| `archive/superpowers/plans/2026-05-24-auto-observe-post-turn-hook-part-2.md` | 2026-05-24 | plan | Auto-observe post-turn hook (part 2) |
| `archive/superpowers/plans/2026-05-24-multi-corpus-gap-closure.md` | 2026-05-24 | plan | Multi-corpus context map gap closure |
| `archive/superpowers/plans/2026-05-24-observe-missing-types-fix.md` | 2026-05-24 | plan | Observe tool — missing entity type fixes |
| `archive/superpowers/plans/2026-05-24-readme-refresh.md` | 2026-05-24 | plan | README refresh |
| `archive/superpowers/plans/2026-05-24-track-b-testing-and-feedback-loop.md` | 2026-05-24 | plan | Track B testing and feedback loop |
| `archive/superpowers/plans/2026-05-25-dashboard-session-timeline-context-map-explorer.md` | 2026-05-25 | plan | Dashboard with session timeline and context map explorer |
| `archive/superpowers/plans/2026-07-25-multi-corpus-context-map-unblock.md` | 2026-07-25 | plan | Multi-corpus context map unblock |
| `archive/superpowers/plans/bench-progress.md` | — | plan | Benchmark progress tracking |
| `archive/superpowers/plans/next-phases.md` | — | plan | Next development phases |
| `archive/superpowers/plans/plan-2-build-execution.md` | — | plan | Build execution plan (phase 2) |
| `archive/superpowers/plans/plan.md` | — | plan | High-level project plan |

### `archive/superpowers/specs/` — Claude-generated design specs (May–Jul 2026)

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/superpowers/specs/2026-05-18-event-driven-agents-design.md` | 2026-05-18 | design | Event-driven agent architecture design |
| `archive/superpowers/specs/2026-05-19-agent-token-history-control-design.md` | 2026-05-19 | design | Agent token history and control design |
| `archive/superpowers/specs/2026-05-19-multi-provider-llm-design.md` | 2026-05-19 | design | Multi-provider LLM abstraction (DeepSeek, OpenAI, Anthropic) |
| `archive/superpowers/specs/2026-05-19-pipeline-runner-design.md` | 2026-05-19 | design | Pipeline runner DAG design |
| `archive/superpowers/specs/2026-05-19-textual-chat-tui-design.md` | 2026-05-19 | design | Textual chat TUI design |
| `archive/superpowers/specs/2026-05-20-context-map-implementation-spec.md` | 2026-05-20 | design | Context map implementation specification |
| `archive/superpowers/specs/2026-05-20-event-sourced-context-map-design.md` | 2026-05-20 | design | Event-sourced context map architecture |
| `archive/superpowers/specs/2026-05-20-vespa-document-retrieval-design.md` | 2026-05-20 | design | Vespa document retrieval design |
| `archive/superpowers/specs/2026-05-21-textual-vim-layer-design.md` | 2026-05-21 | design | Textual TUI vim keybinding layer |
| `archive/superpowers/specs/2026-05-22-docling-pdf-pipeline-spec.md` | 2026-05-22 | design | Docling PDF pipeline specification |
| `archive/superpowers/specs/2026-05-22-hot-reload-and-session-restore-spec.md` | 2026-05-22 | design | Hot-reload and session restore specification |
| `archive/superpowers/specs/2026-05-22-testing-architecture-design.md` | 2026-05-22 | design | Testing architecture design |
| `archive/superpowers/specs/2026-05-22-testing-architecture-implementation-spec.md` | 2026-05-22 | design | Testing architecture implementation spec |
| `archive/superpowers/specs/2026-05-22-testing-architecture-phases-7-10.md` | 2026-05-22 | design | Testing architecture phases 7–10 |
| `archive/superpowers/specs/2026-05-23-create-rubrics-usage.md` | 2026-05-23 | guide | Create-rubrics skill usage guide |
| `archive/superpowers/specs/2026-05-23-deterministic-cartographer-design.md` | 2026-05-23 | design | Deterministic cartographer design |
| `archive/superpowers/specs/2026-05-24-cartographer-wiring-implications.md` | 2026-05-24 | design | Cartographer wiring implications |
| `archive/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md` | 2026-05-24 | design | Deterministic cartographer deferred features |
| `archive/superpowers/specs/2026-05-25-component-extraction-format.md` | 2026-05-25 | design | Component extraction format for v2 rewrite |
| `archive/superpowers/specs/2026-05-25-dashboard-session-timeline-context-map-explorer-design.md` | 2026-05-25 | design | Dashboard with session timeline and context map explorer |
| `archive/superpowers/specs/2026-05-25-obsolete-architecture-section-budget.md` | 2026-05-25 | design | Obsolete architecture section budget analysis |
| `archive/superpowers/specs/2026-07-23-context-map-freeze-derivation-ids.md` | 2026-07-23 | design | Context map freeze — derivation ID tracking |
| `archive/superpowers/specs/20260518-154737-autonomous-goal-execution-loop-react.md` | 2026-05-18 | design | Autonomous goal execution loop (ReAct) design |
| `archive/superpowers/specs/deverino-v2-architecture.md` | — | design | Deverino v2 architecture overview |
| `archive/superpowers/specs/handoff-plan-2.md` | — | plan | Handoff notes for plan phase 2 |
| `archive/superpowers/specs/handoff-tests.md` | — | plan | Handoff notes for test architecture |

### `archive/superpowers/` — Handoff tracker

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/superpowers/HANDOFF.md` | 2026-05-20 | plan | Vespa document retrieval task tracker with commit references and remaining tasks |

### `archive/refactors/` — Deferred refactor items

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/refactors/2026-05-24-multi-corpus-deferred-refactors.md` | 2026-05-24 | inventory | Deferred refactors from multi-corpus gap closure review (6 items) |

### `archive/rewrite/` — v2 rewrite inventory

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/rewrite/COMPONENTS.md` | — | inventory | Component extraction inventory for v2 rewrite (partially filled) |

### `archive/soul/` — SOUL capability contract notes

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/soul/soul-capability-contract-notes.md` | — | design | Notes on rewriting SOUL.md as a capability contract with verified context and source pointers |

### `archive/testing-scenarios/` — Testing scenario documents

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/testing-scenarios/acdl-agent-tooling.md` | — | guide | ACDL agent tooling testing scenario |
| `archive/testing-scenarios/acdl-self-reasoning.md` | — | guide | ACDL self-reasoning testing scenario |
| `archive/testing-scenarios/demonstration-guide.md` | — | guide | Demonstration guide |
| `archive/testing-scenarios/stress-report-test.md` | 2026-07-25 | investigation | Context map materializer stress test — deliberation cascade detection |

### Root-level archive files

| Document | Date | Kind | Description |
|----------|------|------|-------------|
| `archive/bug-investigation-list-corpora.md` | — | investigation | Bug investigation: `list_corpora` missing `database` argument — root cause + handoff-ready implementation spec |
| `archive/context_map_findings.md` | 2025-07-17 | investigation | Context map eviction findings — budget enforcement, distiller merging, eviction behavior |
| `archive/skills.md` | — | guide | Brief note on skill cancellation patterns (`ctx.cancelled`) |
| `archive/test-migration-2.md` | — | plan | Test migration plan part 2 — deduplication, fixture extraction, domain directory layout |
