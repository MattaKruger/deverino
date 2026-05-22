# Testing Architecture — Implementation Spec

**Date:** 2026-05-22
**Parent:** [2026-05-22-testing-architecture-design.md](./2026-05-22-testing-architecture-design.md)
**Status:** Draft

---

## 1. Overview

This document specifies the exact implementation steps, file structure, class APIs, and
migration mechanics for the three-layer testing architecture. It assumes the design doc
has been read and does not restate motivations.

---

## 2. File Structure After Implementation

```
tests/
  __init__.py                       # (existing, unchanged)
  conftest.py                       # MODIFIED — add in-memory engine fixture
  helpers.py                        # MODIFIED — add TraceAssertions class

  unit/                             # NEW
    __init__.py
    conftest.py                     # No-op (no shared fixtures needed at unit layer)
    core/
      __init__.py
      test_events.py                # (migrated on-contact from tests/test_events.py)
      test_event_bus.py             # (migrated on-contact)
      test_event_store.py           # (migrated on-contact)
      test_goal_runner.py           # Pure-logic tests only (token counting, stuck detection)
      test_message_history.py       # (migrated on-contact)
      test_pipeline_runner.py       # (migrated on-contact)
    skills/
      __init__.py
      test_read_memory.py           # SkillRunner + in-memory DB, no AppState
      test_evaluate_goal.py         # (migrated on-contact)

  agent/                            # NEW
    __init__.py
    harness.py                      # SessionHarness + internal TraceAssertions delegation
    conftest.py                     # session fixture
    test_goal_loop.py               # ReAct loop integration tests
    test_read_memory_session.py     # End-to-end mock session tests

  bench/                            # NEW
    __init__.py
    conftest.py                     # live_session fixture, benchmark skip logic
    rubric_loader.py                # Rubric parser + validator
    llm_judge.py                    # LLM judge client
    rubrics/
      summarise-blackboard-database.md
    test_goal_quality.py            # Benchmark tests

  # --- Existing files (frozen until on-contact migration) ---
  test_goal_runner.py               # (contains unit + agent tests — split on-contact)
  test_event_bus.py                 # (contains unit tests — move on-contact)
  test_event_store.py               # (ditto)
  test_events.py                    # (ditto)
  ...all other existing test files...
```

---

## 3. Phase 1: Shared In-Memory DB Construction

### 3.1 Problem

`build_app_state()` → `HarnessConfig.load()` → `BlackboardDatabase.from_url(config.runtime.database_url)`
→ `create_db_engine(postgres_url)`. Tests need in-memory SQLite, but we must not fork the
construction logic.

### 3.2 Solution

Add an optional `database_url` parameter to `build_identity()` and `build_app_state()`.
When provided, it overrides `config.runtime.database_url`. The SQLModel `_StateJSON` type
already handles Postgres vs SQLite (`JSON().with_variant(JSONB(), "postgresql")`), so
SQLite in-memory works without model changes.

### 3.3 Changes

**`harness_poc/app_factory.py`:**

```python
# build_identity() — add optional database_url parameter
def build_identity(
    config: HarnessConfig,
    session_id: str | None = None,
    *,
    database_url: str | None = None,      # NEW
) -> Identity:
    effective_url = database_url or config.runtime.database_url
    database = BlackboardDatabase.from_url(effective_url)
    event_store = EventStore(database.engine)
    event_bus = EventBus(event_store)
    # ... rest unchanged


# build_app_state() — plumb the parameter through
def build_app_state(
    session_id: str | None = None,
    *,
    database_url: str | None = None,       # NEW
) -> AppState:
    config = HarnessConfig.load()
    configure_logging(config.project_root)
    identity = build_identity(config, session_id, database_url=database_url)
    runtime = build_runtime_layer(identity, config)
    long_lived = build_long_lived(identity, runtime)
    # ... rest unchanged
```

**`tests/conftest.py` — add in-memory engine fixture:**

```python
import pytest
from sqlalchemy import Engine, create_engine
from sqlmodel import SQLModel

@pytest.fixture
def in_memory_engine() -> Engine:
    """In-memory SQLite engine with full schema. Use for unit + agent tests."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine
```

The existing `db_engine` fixture (truncating Postgres) remains for integration tests
behind `@pytest.mark.integration`.

---

## 4. Phase 2: TraceAssertions

### 4.1 Purpose

A reusable assertion engine over event traces. `SessionHarness` composes it;
tests can also use it directly for lower-level assertions.

### 4.2 Location

`tests/helpers.py` — appended below the existing `RecordingEventBus` class.

### 4.3 API

```python
@dataclass
class TraceAssertions:
    """Assertion engine over a list of BaseEvent."""
    events: list[BaseEvent]

    # --- Skill presence ---

    def skill_called(self, name: str) -> bool:
        """True if any SkillCalled event matches the skill name."""

    def skill_completed(self, name: str, *, status: str | None = None) -> bool:
        """True if any SkillCompleted event matches name + optional status."""

    @property
    def skill_calls(self) -> list[SkillCalled]:
        """All SkillCalled events in order."""

    @property
    def skill_results(self) -> list[SkillCompleted]:
        """All SkillCompleted events in order."""

    # --- Order assertions ---

    def assert_skill_called(self, name: str) -> None:
        """Raise AssertionError if skill was never called."""

    def assert_skill_not_called(self, name: str) -> None:
        """Raise AssertionError if skill was called."""

    def assert_skill_order(self, *names: str) -> None:
        """Assert skill calls appear in this relative order (not necessarily adjacent)."""

    def assert_skill_completed(self, name: str, *, status: str = "success") -> None:
        """Assert skill completed with given status."""

    # --- Event introspection ---

    def events_of_type(self, event_type: type[E]) -> list[E]:
        """All events matching the given type."""

    @property
    def all_events(self) -> list[BaseEvent]:
        """All recorded events."""

    # --- Goal result assertions ---

    def assert_completed(self, result: GoalRunResult) -> None:
        """Assert result.status == 'completed'."""

    def assert_budget_exhausted(self, result: GoalRunResult) -> None:
        """Assert result.status == 'budget_exhausted'."""

    def assert_final_answer_contains(self, result: GoalRunResult, *fragments: str) -> None:
        """Assert result.content contains all fragments (case-insensitive)."""
```

### 4.4 Implementation Notes

- `assert_skill_order` uses a positional iterator: for each expected name, find the next
  occurrence after the previous match. This allows non-adjacent ordering (e.g.,
  `read_memory → ... → evaluate_goal`).
- All assertion methods raise `AssertionError` with descriptive messages showing the
  received event trace (skill names + statuses) for debugging.
- `skill_calls` and `skill_results` are computed properties that filter `self.events`.

### 4.5 Extending RecordingEventBus

The existing `RecordingEventBus` needs one addition: a `get_all_events` method that
returns all events (not filtered by session or limit). This is needed by
`SessionHarness` to feed the full trace into `TraceAssertions`.

```python
class RecordingEventBus:
    # ... existing methods ...

    def get_all_events(
        self,
        session_id: str,
        event_types: list[type[BaseEvent]] | None = None,
    ) -> list[BaseEvent]:
        """Return all events for a session, optionally filtered by type."""
        filtered = [e for e in self.events if e.session_id == session_id]
        if event_types is not None:
            names = {t.__name__ for t in event_types}
            filtered = [e for e in filtered if type(e).__name__ in names]
        return filtered
```

---

## 5. Phase 3: SessionHarness

### 5.1 Purpose

The single controlled surface for testing full agent sessions. Combines an in-memory
`AppState` (SQLite + `RecordingEventBus`) with a `FunctionModel`-backed `GoalRunner`.

### 5.2 Location

`tests/agent/harness.py`

### 5.3 API

```python
@dataclass
class SessionHarness:
    """Controlled test surface for mock-LLM GoalRunner sessions.

    Usage:
        harness = SessionHarness.build([
            _tool_call_response("read_memory", {"memory_key": "test"}),
            _evaluate_goal_response(True, "Done."),
        ])
        harness.run("summarise the project state")
        harness.assert_skill_order("read_memory", "evaluate_goal")
        harness.assert_completed()
    """

    state: AppState
    runner: GoalRunner
    result: GoalRunResult | None = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        mock_responses: list[LLMResponse],
        *,
        max_iterations: int = 10,
        stuck_threshold: int = 3,
        context_window: int = 20,
    ) -> SessionHarness:
        """Construct a harness with a FunctionModel-backed GoalRunner.

        Args:
            mock_responses: Sequence of LLMResponse objects the mock
                model will return, in order. The last response repeats.
            max_iterations: GoalRunner iteration limit.
            stuck_threshold: Semantic stuck detection sensitivity.
            context_window: Number of recent events in LLM context.
        """
        # 1. Build AppState with in-memory SQLite + RecordingEventBus
        # 2. Wire a FunctionModel that consumes mock_responses
        # 3. Construct GoalRunner with the mock model
        # 4. Return SessionHarness(state, runner)
        ...

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, goal: str) -> GoalRunResult:
        """Execute the goal loop and store the result."""
        self.result = self.runner.run(goal, self.state)
        return self.result

    # ------------------------------------------------------------------
    # Skill assertions (delegated to TraceAssertions)
    # ------------------------------------------------------------------

    def assert_skill_called(self, name: str) -> None: ...
    def assert_skill_not_called(self, name: str) -> None: ...
    def assert_skill_order(self, *names: str) -> None: ...
    def assert_skill_completed(self, name: str, *, status: str = "success") -> None: ...

    # ------------------------------------------------------------------
    # Outcome assertions
    # ------------------------------------------------------------------

    def assert_completed(self) -> None: ...
    def assert_budget_exhausted(self) -> None: ...
    def assert_final_answer_contains(self, *fragments: str) -> None: ...

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def skill_calls(self) -> list[SkillCalled]: ...
    @property
    def skill_results(self) -> list[SkillCompleted]: ...
    @property
    def final_answer(self) -> str: ...
    @property
    def all_events(self) -> list[BaseEvent]: ...

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_result(self) -> GoalRunResult:
        """Raise if run() hasn't been called yet."""
        if self.result is None:
            raise RuntimeError("SessionHarness.run() must be called before assertions")
        return self.result

    @property
    def _trace(self) -> TraceAssertions:
        """Lazily-built TraceAssertions over the full event trace."""
        # Rebuild each time in case events were added
        return TraceAssertions(self.state.event_bus.events)
```

### 5.4 Internal Construction Details

`SessionHarness.build()` must:

1. **Create in-memory engine + BlackboardDatabase:**
   ```python
   engine = create_engine("sqlite:///:memory:")
   SQLModel.metadata.create_all(engine)
   database = BlackboardDatabase(engine)
   ```

2. **Create RecordingEventBus:**
   ```python
   event_bus = RecordingEventBus()
   ```

3. **Create minimal config:**
   The `HarnessConfig` loaded from `harness.yaml` may reference external services
   (Vespa URLs, container images). For tests, we need a config that:
   - Has valid `paths` pointing to the real project root (so `SkillRunner` can find
     system/project skills on disk)
   - Has `retrieval.enabled = False` or mock Vespa (no real network calls)
   We create a helper `_test_config()` that loads the real config but safe-defaults
   networking fields.

4. **Construct SkillRunner:**
   ```python
   from harness_poc.core.skill_runner import SkillRunner
   skill_runner = SkillRunner(database=database, config=config)
   ```

5. **Construct GoalRunner with FunctionModel:**
   The mock model adapter follows the existing pattern from `test_goal_runner.py`:
   ```python
   def _mock_goal_model(responses: list[LLMResponse]) -> FunctionModel:
       respond = _mock_response_factory(responses)
       def _model_fn(messages, info):
           response = respond([], None)
           action = _response_to_goal_action(response)
           return ModelResponse(parts=[TextPart(json.dumps(action))])
       return FunctionModel(_model_fn)
   ```

6. **Assemble AppState:**
   Construct `Identity`, `Runtime`, `LongLived` manually (not via `build_app_state`)
   since we need `RecordingEventBus` instead of `EventBus`:
   ```python
   identity = Identity(
       session_id=str(uuid.uuid4()),
       database=database,
       event_bus=event_bus,
       agent_name="test-agent",
   )
   runtime = Runtime(
       config=config,
       skill_runner=skill_runner,
       tool_runner=ToolRunner(...),
       tools=skill_runner.discover_skills(),
       # ... other fields
   )
   state = AppState(
       identity=identity,
       runtime=runtime,
       long_lived=LongLived(...),
       pydantic_messages=[],
       goal_decision_model=mock_model,
       messages=[],
       streaming=StreamingContext(),
   )
   ```

   **Alternative:** Use `build_app_state(database_url="sqlite:///:memory:")` and
   post-construction swap `state.identity.event_bus` for a `RecordingEventBus`.
   This is simpler but mutates a frozen-ish object.

   **Decision:** Manual construction is preferred because:
   - `RecordingEventBus` is not a drop-in for `EventBus` (different constructor signature)
   - We want explicit control over every component
   - The harness construction is test infrastructure, not production code — duplication
     of wiring logic is acceptable here

### 5.5 Skill Extraction from Events

`skill_calls` and `skill_results` delegate to `TraceAssertions`, which filters
`self.events`:

```python
@property
def skill_calls(self) -> list[SkillCalled]:
    return [e for e in self.events if isinstance(e, SkillCalled)]

@property
def skill_results(self) -> list[SkillCompleted]:
    return [e for e in self.events if isinstance(e, SkillCompleted)]
```

---

## 6. Phase 4: Agent Test Fixtures

### 6.1 Location

`tests/agent/conftest.py`

### 6.2 Fixtures

```python
import pytest
from tests.agent.harness import SessionHarness
from harness_poc.core.llm_client import LLMResponse

@pytest.fixture
def session() -> SessionHarness:
    """Empty harness — tests provide mock_responses inline."""
    # Return an unbuilt harness; tests call SessionHarness.build() themselves
    # This fixture exists so tests can import 'session' without boilerplate
    return None  # sentinel — tests call build() directly

# Convenience response factories — re-exported for test ergonomics
from tests.agent.harness import (
    _tool_call_response,
    _evaluate_goal_response,
    _text_response,
)
```

**Decision:** No `session` fixture that auto-builds. The `mock_responses` list is the
essence of each test — it's the scenario definition. Forcing it through a fixture would
obscure the test's intent. Tests call `SessionHarness.build([...])` directly, making the
mock sequence visible in the test body.

### 6.3 Response Factory Helpers

Re-exported from `tests/agent/harness.py` for convenience:

```python
def _tool_call_response(name: str, arguments: dict[str, Any]) -> LLMResponse:
    """Shorthand for a tool-call mock response."""
    return LLMResponse(kind="tool_call", content="", tool_call={"name": name, "arguments": arguments})

def _evaluate_goal_response(
    is_complete: bool, reasoning: str = "", final_answer: str = ""
) -> LLMResponse:
    """Shorthand for an evaluate_goal mock response."""
    args: dict[str, Any] = {"is_complete": is_complete, "reasoning": reasoning}
    if final_answer:
        args["final_answer"] = final_answer
    return LLMResponse(kind="tool_call", content="", tool_call={"name": "evaluate_goal", "arguments": args})

def _text_response(content: str) -> LLMResponse:
    """Shorthand for a plain-text mock response (no tool call)."""
    return LLMResponse(kind="text", content=content)
```

### 6.4 Example Agent Test

```python
# tests/agent/test_goal_loop.py

def test_reads_memory_before_evaluating():
    harness = SessionHarness.build([
        _tool_call_response("read_memory", {"memory_key": "project_summary"}),
        _evaluate_goal_response(True, "Memory read complete.", "Project state: ..."),
    ])
    harness.run("summarise the project state")
    harness.assert_skill_order("read_memory", "evaluate_goal")
    harness.assert_completed()
```

---

## 7. Phase 5: Rubric System

### 7.1 Concept

A rubric is a portable, human-readable `.md` specification of expected agent behavior.
It defines:

- **Hard gates** (deterministic, no LLM cost): must-include strings, must-not-include
  strings, minimum word count, expected skill sequence
- **Soft gates** (LLM judge): a quality threshold judged by a cheap model

The same rubric can validate:
- A **mock session** (agent tests) — hard gates only
- A **live session** (benchmarks) — hard gates + LLM judge

### 7.2 Rubric File Format

```markdown
# Rubric: <slug-name>

## Goal

<the exact goal string to pass to the agent>

## Hard Assertions

- must_contain: "<fragment>"
- must_not_contain: "<fragment>"
- min_words: <int>
- skill_sequence: [skill_a, skill_b, ...]

## LLM Judge

threshold: <float 0.0-1.0>
model: <model-id>
prompt: |
  <scoring prompt with {answer} placeholder>
```

### 7.3 Rubric Loader

**Location:** `tests/bench/rubric_loader.py`

```python
@dataclass(frozen=True, slots=True)
class Rubric:
    slug: str
    goal: str
    must_contain: list[str]
    must_not_contain: list[str]
    min_words: int | None
    skill_sequence: list[str] | None
    judge_threshold: float | None
    judge_model: str | None
    judge_prompt: str | None

    @classmethod
    def from_markdown(cls, path: Path) -> Rubric:
        """Parse a rubric .md file."""

    def assert_hard_gates(self, result: GoalRunResult, harness: SessionHarness | None = None) -> None:
        """Run all hard assertions.

        - must_contain / must_not_contain: check result.content
        - min_words: split result.content and count
        - skill_sequence: requires harness for event trace; skipped if harness is None
        """

    def judge(self, answer: str) -> float | None:
        """Run the LLM judge. Returns None if no judge is configured."""
```

### 7.4 Rubric → Session Comparison

The user's framing: **session = absolute truth, rubric = what-if scenario.**

A session produces concrete events + output. The rubric describes what SHOULD have
happened. Comparison answers: "Did the session satisfy the rubric?"

```
┌──────────┐       ┌──────────────┐       ┌──────────────────┐
│  Rubric  │──────▶│   Validate   │◀──────│  Session Result  │
│  (.md)   │       │  hard gates  │       │  (GoalRunResult  │
│          │       │  + LLM judge │       │   + event trace) │
└──────────┘       └──────────────┘       └──────────────────┘
```

### 7.5 Usage Patterns

**Pattern A: Mock session + rubric (agent tests)**

```python
def test_summarise_project_state_matches_rubric():
    rubric = Rubric.from_markdown(Path("tests/bench/rubrics/summarise-project.md"))
    harness = SessionHarness.build([
        _tool_call_response("read_memory", {"memory_key": "project_state"}),
        _evaluate_goal_response(True, "Done.", "Project state includes SQLite sessions..."),
    ])
    harness.run(rubric.goal)
    rubric.assert_hard_gates(harness.result, harness)
```

**Pattern B: Live session + rubric (benchmarks)**

```python
@pytest.mark.benchmark
def test_summarise_project_state_benchmark(live_session, rubric):
    result = live_session.run(rubric.goal)
    rubric.assert_hard_gates(result)
    score = rubric.judge(result.content)
    assert score >= rubric.judge_threshold
```

### 7.6 Example Rubric File

```markdown
# Rubric: summarise-blackboard-database

## Goal

Summarise what BlackboardDatabase does and how it is structured.

## Hard Assertions

- must_contain: "session"
- must_contain: "SQLite"
- must_contain: "state_proposals"
- must_not_contain: "I don't know"
- min_words: 50
- skill_sequence: [read_memory, evaluate_goal]

## LLM Judge

threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score the following answer 0.0–1.0 on whether it accurately
  describes the BlackboardDatabase's purpose, its key tables,
  and its relationship to session state management.

  Answer: {answer}
```

---

## 8. Phase 6: Benchmark Scaffolding

### 8.1 Location

`tests/bench/conftest.py`

### 8.2 Fixtures

```python
import os
import pytest
from pathlib import Path
from harness_poc.app_factory import build_app_state, AppState
from harness_poc.core.goal_runner import GoalRunner, GoalRunResult

BENCHMARK_MODEL = os.getenv("BENCHMARK_MODEL", "claude-haiku-4-5-20251001")
RUBRICS_DIR = Path(__file__).parent / "rubrics"


@pytest.fixture
def live_session() -> GoalRunner:
    """GoalRunner wired to a real LLM (BENCHMARK_MODEL env var)."""
    # Use build_app_state with real Postgres (no database_url override)
    state = build_app_state()
    # Override the decision model with BENCHMARK_MODEL
    state.goal_decision_model = _resolve_model(BENCHMARK_MODEL)
    # Return a wrapper or the runner directly
    return _LiveSession(state)


@pytest.fixture
def rubric(request) -> Rubric:
    """Load a rubric by convention: test name → rubric slug."""
    # e.g., test_summarise_blackboard_database → summarise-blackboard-database.md
    ...


def pytest_addoption(parser):
    parser.addoption(
        "--run-benchmarks",
        action="store_true",
        default=False,
        help="Run benchmark tests (skipped by default)",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-benchmarks", default=False):
        skip_bench = pytest.mark.skip(reason="--run-benchmarks not set")
        for item in items:
            if "bench" in str(item.fspath):
                item.add_marker(skip_bench)
```

### 8.3 LiveSession Wrapper

```python
@dataclass
class _LiveSession:
    """Thin wrapper so benchmark tests can call run() like SessionHarness."""
    state: AppState

    def run(self, goal: str) -> GoalRunResult:
        runner = GoalRunner(max_iterations=30, max_tokens=20_000)
        return runner.run(goal, self.state)
```

### 8.4 LLM Judge

**Location:** `tests/bench/llm_judge.py`

```python
def llm_judge(prompt: str, answer: str, model_id: str) -> float:
    """Score an answer 0.0–1.0 using a cheap judge model.

    The judge model should be deterministic (temperature=0) and cheap
    (haiku). The prompt template must contain {answer} as a placeholder.
    """
    filled = prompt.format(answer=answer)
    # Call the judge model via the existing LLM client infrastructure
    # Parse the numeric score from the response
    ...
```

### 8.5 Benchmark Marker

```python
# In pyproject.toml or pytest.ini:
# [tool.pytest.ini_options]
# markers = [
#     "benchmark: Real-LLM quality benchmark (skipped by default)",
#     "integration: Requires Postgres and Vespa",
# ]
```

---

## 9. Phase 7: CI Strategy

### 9.1 pytest Markers

| Marker        | Meaning                                | CI Gate          |
| ------------- | -------------------------------------- | ---------------- |
| (none)        | Unit or agent test                     | Every push       |
| `integration` | Requires Postgres + Vespa              | PR               |
| `benchmark`   | Real LLM, skipped by default           | Nightly (opt-in) |

### 9.2 CI Workflow

```yaml
# Fast path — every push
fast:
  script: pytest tests/unit/ tests/agent/

# Integration — on PR
integration:
  script: pytest tests/ -m integration

# Benchmark — nightly, separate job
benchmark:
  script: BENCHMARK_MODEL=claude-haiku-4-5-20251001 pytest tests/bench/ --run-benchmarks
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### 9.3 Marker Registration

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: Requires Postgres and Vespa",
    "benchmark: Real-LLM quality benchmark (skipped by default)",
]
```

---

## 10. Phase 8: Unit Tests Structure

### 10.1 Rule

If a test imports `AppState` or `build_app_state`, it does not belong in `unit/`.

### 10.2 Coverage Targets (from design doc)

| Module                  | Test file                             | DB needed? |
| ----------------------- | ------------------------------------- | ---------- |
| `core/events.py`        | `tests/unit/core/test_events.py`      | No         |
| `core/event_bus.py`     | `tests/unit/core/test_event_bus.py`   | No(*)      |
| `core/event_store.py`   | `tests/unit/core/test_event_store.py` | SQLite     |
| `core/goal_runner.py`   | `tests/unit/core/test_goal_runner.py` | No         |
| `core/message_history.py` | `tests/unit/core/test_message_history.py` | No    |
| `core/pipeline_runner.py` | `tests/unit/core/test_pipeline_runner.py` | No    |
| `core/document_index.py`  | `tests/unit/core/test_document_index.py` | No (**)  |
| `core/vespa_client.py`    | `tests/unit/core/test_vespa_client.py` | No (**)   |
| `skills/*`              | `tests/unit/skills/test_*.py`         | SQLite     |

- **(*)** `EventBus` tests with `RecordingEventBus` (no DB); `EventStore`-backed
  tests go to `test_event_store.py` or integration layer.
- **(**)** Uses `FakeVespaClient` — no network.

### 10.3 Unit Test Example

```python
# tests/unit/core/test_event_bus.py

def test_bad_handler_does_not_stop_other_handlers():
    bus = EventBus(EventStore(in_memory_engine))
    results: list[str] = []

    def bad_handler(_event):
        raise RuntimeError("boom")

    def good_handler(event):
        results.append(event.tool_name)

    bus.subscribe(SkillCalled, bad_handler)
    bus.subscribe(SkillCalled, good_handler)
    bus.publish(SkillCalled(session_id="s1", tool_name="foo", arguments={}))
    assert results == ["foo"]
```

---

## 11. Migration: On-Contact Replacement

### 11.1 Principle

Existing 441 tests are frozen. When you touch a file that has tests in the old structure,
you delete the old test and rewrite it in the new structure. No bulk migration.

### 11.2 On-Contact Replacements

| Old file                          | New location                             |
| --------------------------------- | ---------------------------------------- |
| `tests/test_events.py`            | `tests/unit/core/test_events.py`         |
| `tests/test_event_bus.py`         | `tests/unit/core/test_event_bus.py`      |
| `tests/test_event_store.py`       | `tests/unit/core/test_event_store.py`    |
| `tests/test_goal_runner.py` (unit portions) | `tests/unit/core/test_goal_runner.py` |
| `tests/test_goal_runner.py` (loop portions) | `tests/agent/test_goal_loop.py`     |
| `tests/test_message_history.py`   | `tests/unit/core/test_message_history.py`|
| `tests/smoke_test_skills.py`      | `tests/unit/skills/test_read_memory.py` etc. |
| `tests/test_vespa_integration.py` | `@pytest.mark.integration` (keep in place, add marker) |

### 11.3 What To Do When Touching an Old Test File

1. Identify which layer the test belongs in (unit / agent / integration)
2. Write the replacement test in the new structure
3. Run the new test to confirm it passes
4. Delete the old test
5. If removing the last test in a file, delete the file

---

## 12. Implementation Order

| # | Phase                          | Files Created/Modified                     | Dependencies |
|---| ------------------------------ | ------------------------------------------ | ------------ |
| 1 | In-memory DB plumbing          | `app_factory.py`, `tests/conftest.py`      | None         |
| 2 | TraceAssertions                | `tests/helpers.py`                         | 1            |
| 3 | SessionHarness                 | `tests/agent/harness.py`                   | 1, 2         |
| 4 | Response factories + fixtures  | `tests/agent/conftest.py`                  | 3            |
| 5 | 3–5 validation agent tests     | `tests/agent/test_goal_loop.py`            | 3, 4         |
| 6 | Rubric loader                  | `tests/bench/rubric_loader.py`             | None         |
| 7 | LLM judge                      | `tests/bench/llm_judge.py`                 | None         |
| 8 | Benchmark fixtures             | `tests/bench/conftest.py`                  | 6, 7         |
| 9 | First rubric file + test       | `tests/bench/rubrics/*.md`, `tests/bench/test_goal_quality.py` | 6, 7, 8 |
| 10 | CI config                      | `pyproject.toml`, CI workflow              | 5, 9         |

Each phase can be validated independently:
- **Phase 1:** `pytest tests/unit/` runs with in-memory SQLite
- **Phase 5:** `pytest tests/agent/` exercises `SessionHarness`
- **Phase 9:** `pytest tests/bench/ --run-benchmarks` runs against a real LLM

---

## 13. Design Decisions Summary

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| DB in agent tests | In-memory SQLite via `database_url` param | No Postgres drift; shared construction path |
| SessionHarness construction | Manual component wiring (not `build_app_state`) | Need `RecordingEventBus`; explicit control |
| `session` fixture | No auto-build fixture; tests call `SessionHarness.build()` inline | Mock sequence is the test's essence |
| TraceAssertions location | `tests/helpers.py`; composed by `SessionHarness` | Reusable; harness owns delegation |
| Rubric validation | Rubric applies to any session result (mock or live) | Same spec validates both agent tests and benchmarks |
| Rubric hard gate: skill_sequence | Requires `SessionHarness` event trace; skipped when only `GoalRunResult` available | Mock sessions have traces; benchmarks may not |
| LLM judge model | Configurable per rubric; default cheap (haiku) | Keeps benchmark costs predictable |

---

## 14. Open Questions & Future Work

1. **Sub-agent testing:** The design doc mentions "subagent outcome" in rubrics. The
   current `SessionHarness` only wraps a single `GoalRunner`. Sub-agent dispatch
   (`delegate_task`) creates a nested `GoalRunner` — the harness may need extension to
   mock sub-agent responses.

2. **Event replay / golden-file testing:** Listed as a non-goal in the design doc.
   Revisit when agent behaviour stabilizes.

3. **Parallel benchmark runs:** When comparing models (e.g., haiku vs sonnet), benchmarks
   should be runnable in parallel. The `live_session` fixture creates a real Postgres
   session — concurrent runs need unique session IDs or isolated DBs.

4. **Rubric auto-discovery:** Currently tests explicitly pass rubric paths. A
   `pytest_generate_tests` hook could auto-parameterize benchmark tests over all rubrics
   in the `rubrics/` directory.

5. **`message_history.py` token estimation unit tests:** These are pure functions —
   prime candidates for the first `tests/unit/` migration.
