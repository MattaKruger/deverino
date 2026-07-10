---
title: Code Conventions
mapped_at: 2026-07-11
last_mapped_commit: cf99f7e
focus: quality
---

# Code Conventions

## Sources of Truth

- Repository guidance lives in `AGENTS.md`; executable Python quality policy lives in `pyproject.toml`.
- Common validation commands are centralized in `Justfile` (`just lint`, `just types`, `just check`).
- `tests/GUIDE.md` documents intended test-layer boundaries, though the current tree has additional domain folders.
- Python targets 3.14 and is managed with `uv`; the dashboard targets ES2022 and is managed with `pnpm`.

## Python Style

- Use 4-space indentation, double quotes, and a 100-character line limit.
- Prefer modern Python 3.14 syntax: built-in generics (`list[str]`), `X | None`, and deferred annotations.
- Public functions and methods are typed. Ruff enables `ANN`, while `ty` treats unresolved names, imports,
  and attributes as errors.
- Imports are absolute from `harness_poc`; Ruff's `I` rules enforce ordering. Local imports are reserved for
  dependency registration, optional dependencies, or cycle avoidance and are explicitly suppressed where used.
- Small immutable value objects commonly use `@dataclass(frozen=True, slots=True)`, for example in
  `harness_poc/core/config.py`, `harness_poc/core/runtime/token_accounting.py`, and
  `harness_poc/core/observability/dashboard.py`.
- Use Pydantic models for validated external or persisted envelopes (`harness_poc/core/events/events.py`,
  `harness_poc/core/context_map/schema.py`) and SQLModel for database rows
  (`harness_poc/core/storage/models.py`).
- Pydantic boundary models usually forbid extra fields; immutable event/observation values also use
  `frozen=True` where mutation is not part of the contract.
- Prefer narrow `Protocol` contracts at integration boundaries, as in `ToolGuard`, `ToolDatabase`,
  `SubAgentSpawner`, `ContextMapMaterializer`, and `BlackboardWriter`.
- Names are snake_case for modules, functions, skill directories, and YAML workflows; classes use PascalCase;
  constants use UPPER_SNAKE_CASE. Tests are named `test_*.py`.
- Google-style docstrings are configured, but module/class/function docstrings are not mandatory because this is
  treated as an application rather than a public library.

## Python Quality Gates

- `uv run ruff check .` is the lint gate; the rule set includes correctness, security, annotations, complexity,
  performance, pytest style, import hygiene, and removal of stale commented code/TODOs.
- `uv run ty check` is the static-type gate. Test doubles receive warning-level relaxations for argument,
  override, and attribute diagnostics.
- Ruff complexity ceilings are 15 cyclomatic complexity, 12 branches, 50 statements, 6 returns, and 5 arguments.
- Per-file ignores in `pyproject.toml` document current debt. Do not copy those suppressions into new files unless
  the same tool limitation demonstrably applies.
- Comments should explain non-obvious constraints, not narrate the code. Existing section banners are used to
  divide large runtime, CLI, schema, and test-harness modules.

## TypeScript and Vue Style

- `dashboard-ui/tsconfig.json` enables strict mode, isolated modules, ES2022, bundler resolution, and no emit.
- Use Vue 3 Composition API, Pinia setup stores, `ref`, and explicit exported interfaces from
  `dashboard-ui/src/types/dashboard.ts`.
- Import shared application modules through the `@/` alias; short sibling imports are used within the same layer.
- API functions return typed `Promise<T>` values and share the generic `get<T>` helper in
  `dashboard-ui/src/api/client.ts`.
- Repeated polling behavior belongs in `dashboard-ui/src/stores/composables.ts`; endpoint-specific stores stay
  thin and select a response type, fetcher, and interval.
- Current TypeScript uses single quotes, no semicolons, trailing commas, and two-space indentation. No standalone
  ESLint or formatter configuration is present, so nearby files are the formatting authority.
- Vue components are organized by feature under `components/`, reusable primitives under `components/shared/`,
  route-level screens under `views/`, and network/state logic outside components under `api/` and `stores/`.

## Boundaries

- `harness_poc/core/` owns reusable runtime, event, storage, context-map, retrieval, skill, and tool behavior.
- `harness_poc/api/`, `cli.py`, `repl.py`, and `tui.py` are delivery adapters; they should translate errors and
  format output rather than own domain rules.
- `harness_poc/system_tools/` and `harness_poc/system_skills/` are executable adapters mounted on core contracts;
  project-local equivalents live under `skills/`.
- `harness_poc/v2/` is a parallel experimental orchestration path. Avoid silently coupling reusable core changes
  to v2-only contracts; verify both event paths when touching shared events or storage.
- `dashboard-ui/` consumes FastAPI response contracts. Python response dataclasses and TypeScript interfaces are
  manually mirrored, so any API shape change must update both sides.
- PostgreSQL state is runtime data, not repository source. Credentials and provider keys enter through environment
  variables or local configuration and must not be committed.

## Error Handling

- Validate at trust boundaries and raise specific exceptions (`ValueError`, `FileNotFoundError`,
  `PermissionError`, or domain-specific subclasses) with actionable messages.
- Core parsers and deterministic services raise errors; CLI and API adapters translate them to `typer.Exit`,
  `HTTPException`, structured `SkillResult`, or event status records.
- Long-lived/background work logs failures with `logger.exception` and either emits a failure event or returns a
  typed failed result. Silent broad catches are reserved for best-effort optional behavior.
- Preserve exception causality with `raise ... from exc`. Do not expose raw exception details across untrusted tool
  boundaries; `ToolRunner` returns a generic error while logging the traceback.
- Expected operational failures should be represented in existing result/event envelopes instead of inventing a
  second error channel.

## Configuration and File Conventions

- Runtime configuration is parsed from `harness.yaml` into frozen dataclasses in `harness_poc/core/config.py`.
- Skills use one snake_case directory containing `SKILL.md`, `__init__.py`, and usually `skill.py`.
- Workflow and pipeline definitions use descriptive snake_case YAML names under `workflows/` and `pipelines/`.
- Use `pathlib.Path` for filesystem paths and structured parsers for YAML, JSON, TOML, and model payloads.
