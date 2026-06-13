# Test Suite Refactor and Prompt Testing Implementation Spec

Created: 2026-05-20 Europe/Brussels

## Goal

Refactor the existing pytest suite so it is easier to extend, faster to run in focused
slices, and explicit about prompt behavior. The migration should reduce repeated setup,
group related assertions into readable test classes, and add prompt-contract coverage for
the harness's LLM-facing instructions.

This is a test-only migration. It should not change runtime behavior.

## Background

The current suite is broad and useful, but most tests are flat module-level functions.
Several modules repeat the same setup for:

- `HarnessConfig`
- `BlackboardDatabase`
- session creation
- `SkillRunner`
- fake app state objects
- fake PydanticAI run contexts
- mocked goal-decision model responses

This makes test changes noisy and raises the cost of adding coverage for prompts, runtime
adapters, or new skills.

The largest current files are:

- `tests/test_spec_writer.py`
- `tests/test_goal_runner.py`
- `tests/test_pipeline_runner.py`
- `tests/test_container_skills.py`
- `tests/test_semble_search.py`
- `tests/test_pydantic_runtime.py`

The most important missing coverage is prompt-contract testing around:

- `GoalRunner._goal_system_prompt`
- `GoalRunner._build_decision_prompt`
- `GoalRunner._build_messages`
- `pydantic_runtime._with_tool_policy`
- application-level prompt assembly in `build_app_state`
- persona and subagent prompt loading for `delegate_task`

## Non-Goals

- Do not rewrite runtime code as part of this migration.
- Do not replace pytest with another test framework.
- Do not convert tests to `unittest.TestCase`.
- Do not add live model calls.
- Do not add brittle full-prompt snapshot testing as the primary assertion style.
- Do not modify skill behavior to make tests easier.
- Do not require all tests to be class-based. Use classes where they improve grouping.

## Design Principles

1. Fixtures own setup; tests own behavior.
2. Test classes group scenarios, not mutable state.
3. Prompt tests assert contracts, not incidental formatting.
4. Integration tests stay deterministic and API-key-free.
5. Existing test coverage should be migrated gradually with small, reviewable changes.
6. The first pass should improve structure without hiding important setup behind opaque
   helper layers.

## Target Test Layout

Introduce a package layout under `tests/` that mirrors behavior areas:

```text
tests/
  conftest.py
  factories.py
  fakes.py
  helpers.py
  assertions/
    __init__.py
    prompts.py
  cli/
    test_cli_commands.py
    test_goal_cli.py
  core/
    test_events.py
    test_event_bus.py
    test_event_store.py
    test_event_log_observer.py
    test_message_history.py
    test_permissions.py
    test_pydantic_runtime.py
    test_streaming_context.py
    test_tool_event_callback.py
  goal/
    test_goal_runner_loop.py
    test_goal_runner_budgets.py
    test_goal_runner_events.py
    test_goal_runner_prompts.py
  prompts/
    test_primary_agent_prompt.py
    test_goal_prompts.py
    test_delegate_task_prompts.py
    test_prompt_assets.py
  repl/
    test_repl_chat.py
    test_repl_completion.py
    test_repl_direct_invocation.py
    test_repl_skill_execution.py
  skills/
    test_consolidate_state.py
    test_container_skills.py
    test_delegate_task.py
    test_evaluate_goal.py
    test_execute_python.py
    test_read_memory.py
    test_reflect_on_result.py
    test_review_work.py
    test_semble_search.py
    test_spec_writer_draft.py
    test_spec_writer_gather.py
    test_spec_writer_parsing.py
    test_summarize_memory.py
    test_web_search.py
  workflows/
    test_pipeline_runner.py
  tui/
    test_console_adapter.py
    test_tui.py
    test_tui_throttle.py
```

This target layout can be reached incrementally. Moving all files in one commit is not
required and is likely to create avoidable review noise.

## Shared Fixtures

Extend `tests/conftest.py` with fixtures that encode the existing setup pattern.

### `repo_root`

```python
@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
```

Use this instead of `Path.cwd()` inside tests. This avoids failures when tests are run
from a different working directory.

### `test_config`

Build a `HarnessConfig` using the existing repo assets and the active test database URL.

Inputs:

- `repo_root`
- `db_engine`
- optional `tmp_path` for tests that need `project_root` isolation

Recommended shape:

```python
@pytest.fixture
def test_config(repo_root: Path, db_engine: Engine) -> HarnessConfig:
    return make_test_config(repo_root=repo_root, engine=db_engine, project_root=repo_root)
```

Also add a factory for isolated project roots:

```python
@pytest.fixture
def config_factory(repo_root: Path, db_engine: Engine) -> Callable[..., HarnessConfig]:
    def _make(*, project_root: Path | None = None) -> HarnessConfig:
        ...
    return _make
```

The factory should preserve current paths:

- `harness_poc/system_prompts/SOUL.md`
- `harness_poc/system_tools`
- `harness_poc/system_skills`
- `skills`
- `workflows`
- `pipelines`
- `personas`

### `database`

```python
@pytest.fixture
def database(db_engine: Engine) -> BlackboardDatabase:
    return BlackboardDatabase(db_engine)
```

### `session_id`

```python
@pytest.fixture
def session_id(database: BlackboardDatabase) -> str:
    return database.start_session("test")
```

Tests that need a more specific session title can create their own session explicitly.

### `skill_runner`

```python
@pytest.fixture
def skill_runner(database: BlackboardDatabase, test_config: HarnessConfig) -> SkillRunner:
    return SkillRunner(database=database, config=test_config)
```

### `skill_harness`

Many skill tests need the tuple `(runner, session_id, database)`. Use a small dataclass
instead of tuple unpacking:

```python
@dataclass(frozen=True, slots=True)
class SkillHarness:
    runner: SkillRunner
    session_id: str
    database: BlackboardDatabase
    config: HarnessConfig
```

Fixture:

```python
@pytest.fixture
def skill_harness(
    skill_runner: SkillRunner,
    session_id: str,
    database: BlackboardDatabase,
    test_config: HarnessConfig,
) -> SkillHarness:
    return SkillHarness(
        runner=skill_runner,
        session_id=session_id,
        database=database,
        config=test_config,
    )
```

### `runtime_parts`

Replace local `_runtime_parts` helpers in Pydantic runtime tests with:

```python
@dataclass(frozen=True, slots=True)
class RuntimeParts:
    skill_runner: SkillRunner
    database: BlackboardDatabase
    config: HarnessConfig
    session_id: str
```

### `cli_runner`

```python
@pytest.fixture(scope="session")
def cli_runner() -> CliRunner:
    return CliRunner()
```

Avoid module-level `runner = CliRunner()` declarations.

### `recording_event_bus`

Move the existing `RecordingEventBus` into `tests/fakes.py` or expose it through a fixture.
Keep `tests/helpers.py` for assertion helpers rather than fake object definitions.

## Factories and Fakes

Create `tests/factories.py` for data factories and `tests/fakes.py` for fake runtime
objects.

### `tests/factories.py`

Include:

- `make_test_config`
- `make_llm_config`
- `make_goal_action_response`
- `make_evaluate_goal_response`
- `make_tool_call_response`
- `make_model_request`
- `make_model_response`
- event factories for `AgentStarted`, `LLMTextEmitted`, `SkillCompleted`

### `tests/fakes.py`

Include:

- `RecordingEventBus`
- fake app state for REPL/direct invocation tests
- fake run context for `execute_skill_as_tool`
- fake skill runner for adapter tests
- fake goal model / PydanticAI `FunctionModel` wrapper

Rules:

- Fake objects should implement only the attributes used by the test.
- Prefer typed dataclasses for simple fakes.
- Keep behavior explicit; do not build a second application framework in tests.

## Test Class Conventions

Use pytest classes to group related scenarios. Do not use `setup_method` unless there is
a strong reason.

Recommended style:

```python
class TestReadMemorySkill:
    def test_lists_keys_when_no_key_provided(self, skill_harness: SkillHarness) -> None:
        ...

    def test_returns_failed_when_key_missing(self, skill_harness: SkillHarness) -> None:
        ...
```

Class names should describe the component or behavior group:

- `TestGoalRunnerCompletion`
- `TestGoalRunnerBudgets`
- `TestGoalRunnerPromptContracts`
- `TestSkillToolAdapter`
- `TestSpecWriterDraftMode`
- `TestSpecWriterGatherFlow`
- `TestReplDirectInvocation`

Avoid classes such as `TestUtils` or `TestMisc`.

## Prompt Testing Strategy

Prompt tests should be semantic contract tests. They should prevent regressions in
LLM-facing behavioral instructions without failing on harmless prose changes.

### Prompt Assertion Helpers

Create `tests/assertions/prompts.py`.

Suggested helpers:

```python
def normalize_prompt(prompt: str) -> str:
    return "\n".join(line.rstrip() for line in prompt.strip().splitlines())


def assert_prompt_has_sections(prompt: str, sections: Iterable[str]) -> None:
    normalized = normalize_prompt(prompt)
    for section in sections:
        assert section in normalized


def assert_prompt_mentions_all(prompt: str, required: Iterable[str]) -> None:
    normalized = normalize_prompt(prompt).lower()
    for text in required:
        assert text.lower() in normalized


def assert_prompt_excludes(prompt: str, forbidden: Iterable[str]) -> None:
    normalized = normalize_prompt(prompt).lower()
    for text in forbidden:
        assert text.lower() not in normalized
```

Use exact assertions only for clauses where wording is behaviorally significant.

### Goal Prompt Tests

Add `tests/goal/test_goal_runner_prompts.py` or `tests/prompts/test_goal_prompts.py`.

Coverage:

1. `_goal_system_prompt` includes the goal verbatim.
2. `_goal_system_prompt` requires `evaluate_goal` for completion.
3. `_goal_system_prompt` requires a complete `final_answer`.
4. `_goal_system_prompt` covers blocked/incomplete progress.
5. `_build_messages` returns a system message first and a continuation user prompt last.
6. `_build_messages` converts recent events into prompt messages.
7. `_build_decision_prompt` includes available tools as JSON.
8. `_build_decision_prompt` includes required structured output fields:
   - `tool_name`
   - `arguments`
   - `content`
9. `_build_decision_prompt` tells the model not to call tools directly.
10. `_build_decision_prompt` summarizes older events when event count exceeds the raw
    event retention threshold.
11. `_build_decision_prompt` preserves the latest raw events.
12. `_build_decision_prompt` tells generation goals to include artifacts in
    `arguments.final_answer`.

Example:

```python
class TestGoalSystemPrompt:
    def test_requires_final_answer_for_completion(self) -> None:
        prompt = GoalRunner._goal_system_prompt("write a commit message")

        assert_prompt_mentions_all(
            prompt,
            [
                "evaluate_goal",
                "is_complete: true",
                "final_answer",
                "only text the user will see",
            ],
        )
```

### Primary Agent Tool Policy Tests

Add `tests/prompts/test_primary_agent_prompt.py`.

Coverage:

1. `_with_tool_policy` preserves the original system prompt.
2. The policy includes a `Tool Result Policy` section.
3. Successful tool calls return content directly.
4. Failed tool calls are prefixed with `[failed]`.
5. Human-in-loop JSON must be surfaced unchanged.
6. Failed tools must not be retried.
7. `semble_search` and `web_search` retry budgets are described.
8. Duplicate tool calls are forbidden.

If direct testing of `_with_tool_policy` is considered too private, add a public helper
such as `build_system_prompt_with_tool_policy`. Do not contort tests around private
access if a small public prompt builder improves design.

### Application Prompt Assembly Tests

Add tests for `build_app_state` prompt assembly after shared fixtures exist.

Coverage:

1. `AppState.messages[0]` is a system message.
2. The system content includes `SOUL.md`.
3. The system content includes project/session state context.
4. `pydantic_runtime` receives the same base state context plus tool policy.
5. Blocked skills for the TUI runtime remain excluded from auto-invokable tools.

If `build_app_state` is too heavy for prompt assembly tests, extract a pure helper:

```python
def build_primary_system_prompt(
    *,
    soul: str,
    project_state: ProjectState,
    session_state: SessionState,
) -> str:
    ...
```

Then test that helper directly and keep one integration smoke test for `build_app_state`.

### Persona and Delegation Prompt Tests

Add `tests/prompts/test_delegate_task_prompts.py`.

Coverage:

1. `_build_subagent_prompt` includes objective and context.
2. Empty context is handled deterministically.
3. `SkillContext.read_subagent_template` loads underscore and hyphen variants where
   supported.
4. Delegate task passes the persona template as the subagent system prompt.
5. Delegate task does not silently substitute an unrelated persona when the requested
   template is missing.

### Prompt Asset Tests

Add `tests/prompts/test_prompt_assets.py`.

Coverage:

1. `harness_poc/system_prompts/SOUL.md` exists and is non-empty.
2. Required persona files exist and are non-empty:
   - `personas/code_reviewer.md`
   - `personas/data_validator.md`
   - `personas/web_researcher.md`
3. Prompt assets do not contain unresolved template placeholders such as `{{...}}`
   unless explicitly allowed.
4. Prompt assets do not accidentally mention test-only model names or fixtures.

## Migration Phases

### Phase 1: Foundation Fixtures

Create:

- `tests/factories.py`
- `tests/fakes.py`
- `tests/assertions/__init__.py`
- `tests/assertions/prompts.py`

Update `tests/conftest.py` with:

- `repo_root`
- `test_config`
- `config_factory`
- `database`
- `session_id`
- `skill_runner`
- `skill_harness`
- `runtime_parts`
- `cli_runner`

Acceptance criteria:

- Existing tests still pass.
- No test files are moved in this phase.
- At least one existing skill test uses `skill_harness`.

Recommended first migrated file:

- `tests/test_read_memory.py`

### Phase 2: Low-Risk Skill Test Migration

Migrate simple skill tests to shared fixtures and class groups:

- `tests/test_read_memory.py`
- `tests/test_consolidate_state.py`
- `tests/test_evaluate_goal.py`
- `tests/test_review_work.py`
- `tests/test_reflect_on_result.py`
- `tests/test_summarize_memory.py`
- `tests/test_web_search.py`

Acceptance criteria:

- Local `_test_config` and `_runner` helpers are removed from migrated files.
- Tests use `SkillHarness` or specific fixtures.
- Each migrated module has class names matching the behavior under test.
- No runtime code is changed.

### Phase 3: Pydantic Runtime Test Migration

Migrate `tests/test_pydantic_runtime.py`.

Class groups:

- `TestModelFactory`
- `TestSkillToolSchema`
- `TestSkillToolExecution`
- `TestToolBudgets`
- `TestRuntimeExecution`

Move fake context and fake runner into `tests/fakes.py`.

Acceptance criteria:

- `_runtime_parts`, `_fake_run_context`, and `_FakeSkillRunner` no longer live in the
  test module.
- Tool policy prompt tests are introduced.
- Existing runtime execution tests still use `TestModel` and do not require API keys.

### Phase 4: Goal Runner Test Split

Split `tests/test_goal_runner.py` by behavior.

Proposed mapping:

- skill registration and evaluate goal execution:
  `tests/skills/test_evaluate_goal.py`
- loop completion and failure behavior:
  `tests/goal/test_goal_runner_loop.py`
- budget and stuck detection:
  `tests/goal/test_goal_runner_budgets.py`
- event formatting / message conversion:
  `tests/goal/test_goal_runner_events.py`
- CLI goal command:
  `tests/cli/test_goal_cli.py`
- prompt construction:
  `tests/goal/test_goal_runner_prompts.py`

Move factories:

- `_mock_response_factory`
- `_evaluate_goal_response`
- `_tool_call_response`
- `_mock_goal_model`
- `_response_to_goal_action`

Acceptance criteria:

- No behavior is lost from the original file.
- Goal prompt-contract tests exist before or during the split.
- CLI tests use the shared `cli_runner`.
- Goal loop tests use fake models, not live LLM calls.

### Phase 5: Spec Writer Test Split

Split `tests/test_spec_writer.py`.

Proposed mapping:

- `tests/skills/test_spec_writer_draft.py`
  - questions mode
  - missing intent
  - draft writes markdown and memory
  - refine uses previous draft
  - draft without gather key behavior
- `tests/skills/test_spec_writer_gather.py`
  - gather state persistence
  - phase transitions
  - full gather flow
  - XML context output
- `tests/skills/test_spec_writer_parsing.py`
  - component parsing
  - question construction
  - title/slug helpers
  - deterministic markdown helper behavior

Class groups:

- `TestSpecWriterDraftMode`
- `TestSpecWriterRefineMode`
- `TestGatherStatePersistence`
- `TestGatherFlow`
- `TestComponentParsing`
- `TestQuestionGeneration`
- `TestXmlContext`

Acceptance criteria:

- The original 500+ line module is removed or reduced to a compatibility import-free
  shell during the transition.
- Shared fixtures replace local `_runner` and `_test_config`.
- Assertions stay behavior-oriented, not full markdown snapshots.

### Phase 6: Remaining Area Migration

Migrate the remaining files opportunistically:

- `tests/test_container_skills.py`
- `tests/test_execute_python.py`
- `tests/test_semble_search.py`
- `tests/test_delegate_task.py`
- `tests/test_repl_chat.py`
- `tests/test_repl_direct_invocation.py`
- `tests/test_pipeline_runner.py`
- TUI and console tests

Do not force class grouping where the file is already small and clear.

Acceptance criteria:

- Repeated config/database setup is gone.
- Fake subprocess/process objects are centralized only when reused.
- Tests remain readable without jumping through many helper layers.

### Phase 7: Marks and Test Selection

Add pytest markers in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
  "unit: pure tests without database or subprocess side effects",
  "integration: database-backed or multi-component tests",
  "cli: Typer CLI invocation tests",
  "prompt: prompt contract and prompt asset tests",
  "tui: Textual UI tests",
]
```

Apply markers conservatively:

- Prompt tests: `@pytest.mark.prompt`
- Pure helper/parser tests: `@pytest.mark.unit`
- DB-backed skill tests: `@pytest.mark.integration`
- Typer invocation tests: `@pytest.mark.cli`
- Textual app tests: `@pytest.mark.tui`

Document focused commands:

```bash
uv run pytest -m unit
uv run pytest -m prompt
uv run pytest tests/skills/test_read_memory.py
uv run pytest tests/goal
```

Acceptance criteria:

- `uv run pytest -m prompt` runs prompt tests only.
- `uv run pytest -m unit` excludes DB-backed tests.
- Unknown marker warnings do not appear.

## Detailed Task Breakdown

### Task 1: Add Test Support Modules

Files:

- `tests/factories.py`
- `tests/fakes.py`
- `tests/assertions/__init__.py`
- `tests/assertions/prompts.py`
- `tests/conftest.py`

Implementation notes:

- Keep new helper APIs small.
- Add type annotations for every helper.
- Do not import application modules at module import time if doing so triggers expensive
  app startup.
- Avoid circular imports between fixtures and factories.

Validation:

```bash
uv run pytest tests/test_read_memory.py
uv run ruff check tests
uv run ty check
```

### Task 2: Migrate Read Memory Skill Tests

File:

- `tests/test_read_memory.py`

Expected result:

```python
class TestReadMemorySkill:
    def test_lists_keys_when_no_key_provided(self, skill_harness: SkillHarness) -> None:
        ...
```

Remove:

- local `_runner`
- local `_test_config`

Validation:

```bash
uv run pytest tests/test_read_memory.py
```

### Task 3: Add First Prompt Tests

Files:

- `tests/prompts/test_goal_prompts.py`
- `tests/prompts/test_primary_agent_prompt.py`

Coverage minimum:

- goal prompt includes `final_answer` requirements
- decision prompt includes tool schema and required output fields
- tool policy forbids retrying failed tools
- tool policy handles human-in-loop results

Validation:

```bash
uv run pytest -m prompt
```

If markers are not added yet, use:

```bash
uv run pytest tests/prompts
```

### Task 4: Migrate Pydantic Runtime Tests

File:

- `tests/test_pydantic_runtime.py`

Expected class groups:

- `TestModelFactory`
- `TestSkillToolAdapter`
- `TestRuntimeExecution`

Validation:

```bash
uv run pytest tests/test_pydantic_runtime.py tests/prompts/test_primary_agent_prompt.py
```

### Task 5: Split Goal Runner Tests

Files:

- `tests/goal/test_goal_runner_loop.py`
- `tests/goal/test_goal_runner_budgets.py`
- `tests/goal/test_goal_runner_events.py`
- `tests/goal/test_goal_runner_prompts.py`
- `tests/cli/test_goal_cli.py`

Validation:

```bash
uv run pytest tests/goal tests/cli/test_goal_cli.py
```

### Task 6: Split Spec Writer Tests

Files:

- `tests/skills/test_spec_writer_draft.py`
- `tests/skills/test_spec_writer_gather.py`
- `tests/skills/test_spec_writer_parsing.py`

Validation:

```bash
uv run pytest tests/skills/test_spec_writer_*.py
```

### Task 7: Apply Markers and Documentation

Files:

- `pyproject.toml`
- optionally `docs/plans/20260520-test-suite-refactor-and-prompt-testing.md`

Validation:

```bash
uv run pytest -m prompt
uv run pytest -m unit
uv run pytest
uv run ruff check .
uv run ty check
```

## Acceptance Criteria

The migration is complete when:

1. Shared config/database/skill-runner setup lives in fixtures or factories.
2. No migrated skill test file defines its own full `HarnessConfig` builder.
3. `test_goal_runner.py` and `test_spec_writer.py` are split into focused modules.
4. Prompt-contract tests cover goal prompts, primary agent tool policy, prompt assets,
   and delegation prompts.
5. Prompt tests run without API keys and without live model calls.
6. Test classes group major behavior areas.
7. Pytest markers support focused unit, integration, CLI, TUI, and prompt runs.
8. The full suite passes.
9. `uv run ruff check .` passes.
10. `uv run ty check` passes or any remaining type failures are documented as unrelated
    pre-existing issues.

## Risks and Mitigations

### Risk: Fixture Abstractions Hide Important Setup

Mitigation:

- Use typed dataclasses such as `SkillHarness` and `RuntimeParts`.
- Keep fixture names concrete.
- Avoid deeply nested fixture dependencies.

### Risk: File Moves Create Review Noise

Mitigation:

- Extract fixtures first.
- Migrate one behavior area per commit.
- Avoid rewriting assertions while moving files unless needed.

### Risk: Prompt Tests Become Brittle

Mitigation:

- Assert required sections and behavior-critical clauses.
- Normalize whitespace.
- Avoid full prompt snapshots except for very small, stable prompts.

### Risk: Prompt Tests Lock In Poor Wording

Mitigation:

- Phrase assertions around behavioral guarantees.
- Keep exact string assertions limited to contract-critical phrases.

### Risk: DB-Backed Tests Are Marked as Unit

Mitigation:

- Treat any test using `db_engine`, `database`, `SkillRunner`, `build_app_state`, or
  subprocess fakes as integration unless it is purely validating a parser/helper.

### Risk: Existing Dirty Worktree Complicates Migration

Mitigation:

- Before implementation, check `git status --short`.
- Do not revert unrelated changes.
- Keep test-only changes scoped to `tests/`, `pyproject.toml`, and docs unless a small
  prompt-builder extraction is required.

## Suggested Commit Plan

1. `Add shared test fixtures and fakes`
2. `Migrate simple skill tests to shared harness fixtures`
3. `Add prompt contract tests`
4. `Refactor Pydantic runtime tests`
5. `Split goal runner tests by behavior`
6. `Split spec writer tests by behavior`
7. `Add pytest markers for focused test runs`

## Open Questions

1. Should the suite keep backward-compatible root-level test modules during the
   migration, or should files be moved directly into subpackages?
2. Should prompt helpers that are currently private, such as `_with_tool_policy`, remain
   private and be tested directly, or should they be promoted to public prompt-builder
   functions?
3. Should DB-backed tests remain the default local test path, or should the default
   command favor `-m "not integration"` once markers exist?
4. Should prompt asset tests enforce placeholder rules globally, or only for selected
   prompt assets?

## Recommended First Slice

Implement Phase 1 plus the `read_memory` migration and the first prompt tests.

That slice proves:

- shared fixtures are usable,
- test classes improve readability,
- prompt tests can run without model calls,
- the migration path works without disturbing high-risk goal/spec-writer tests.

