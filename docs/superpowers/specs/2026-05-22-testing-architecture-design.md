# Testing Architecture Design — Deverino Agentic Harness

**Date:** 2026-05-22  
**Status:** Approved, pending implementation plan

---

## Context

The existing test suite (441 tests, ~9k lines) was written by multiple agents across providers with no shared architecture. The result is blurred unit/integration boundaries, `build_app_state()` overused in "unit" tests, `RecordingEventBus` underused, no test markers, and no benchmark layer.

Deverino is meta-programming: it is a harness that reasons about and orchestrates other programs. This makes the testing problem qualitatively different from standard application testing. A test framework for an agentic harness must be able to:

1. Assert what the agent **did** (skill/tool call sequence)
2. Assert what the agent **produced** (outcome quality)
3. Compare **model behaviour** across runs (benchmarks)

**Guiding principle: clarity over complexity.** Every test must be readable as a specification. If a test requires reading the test infrastructure to understand what it is asserting, the infrastructure is wrong.

---

## Architecture

Three test namespaces with hard boundaries:

```
tests/
  unit/           # Pure logic. No DB, no AppState, no real LLM.
  agent/          # Full GoalRunner sessions. Mock LLM. Event trace assertions.
  bench/          # Real LLM. Rubric-scored. CI-gated separately.
  conftest.py     # Shared fixtures: db_engine, tmp_path only
  helpers.py      # RecordingEventBus + TraceAssertions
```

### What belongs where

| Layer | Fixture cost | LLM | DB | Use for |
|-------|-------------|-----|----|---------|
| `unit/` | Zero | No | In-memory only | Pure functions, data models, skill logic, event types, routing |
| `agent/` | Low | Mock (FunctionModel) | In-memory | Loop behaviour, skill sequencing, context window, stuck detection |
| `bench/` | High | Real | Real (Postgres) | Model quality scoring, regression between model versions |

---

## Layer 1: Unit Tests

**Rule:** If a test imports `build_app_state` or `AppState`, it does not belong in `unit/`.

Unit tests wire components manually with the minimum needed. The existing `db_engine` fixture (truncating Postgres) is replaced by an in-memory SQLite engine for tests that need DB at all.

```python
# tests/unit/core/test_event_bus.py  ← already close to this
def test_bad_handler_does_not_stop_other_handlers():
    bus = EventBus(EventStore(sqlite_engine))
    ...
```

**Coverage targets:**
- `core/events.py` — all event types, `EVENT_REGISTRY`
- `core/event_bus.py` — publish, subscribe, bad handler isolation
- `core/event_store.py` — persist and retrieve events
- `core/pipeline_runner.py` — `build_waves()` DAG logic
- `core/goal_runner.py` — `count_tokens`, `_semantic_key`, stuck detection logic
- `core/message_history.py` — token estimation
- `core/document_index.py` — indexing logic with `FakeVespaClient`
- `core/vespa_client.py` — query building, hit normalisation
- `skills/*` — each skill executed through `SkillRunner` with in-memory DB

---

## Layer 2: Agent Tests (`SessionHarness`)

The centrepiece of the new framework. `SessionHarness` is the single controlled surface for testing full agent sessions.

### SessionHarness

```python
# tests/agent/harness.py

@dataclass
class SessionHarness:
    state: AppState           # RecordingEventBus + in-memory DB
    runner: GoalRunner
    result: GoalRunResult | None = None

    def run(self, goal: str, *, max_iterations: int = 10) -> GoalRunResult:
        self.result = self.runner.run(goal, self.state)
        return self.result

    # --- Skill assertions ---
    def assert_skill_called(self, name: str) -> None:
        """Assert the skill was called at least once."""

    def assert_skill_not_called(self, name: str) -> None:
        """Assert the skill was never called."""

    def assert_skill_order(self, *names: str) -> None:
        """Assert skills were called in this relative order."""

    def assert_skill_completed(self, name: str, *, status: str = "success") -> None:
        """Assert the skill completed with the given status."""

    # --- Outcome assertions ---
    def assert_completed(self) -> None:
        """Assert the goal reached status='completed'."""

    def assert_budget_exhausted(self) -> None:

    def assert_final_answer_contains(self, *fragments: str) -> None:
        """Hard gate: final answer must contain all fragments (deterministic)."""

    # --- Introspection ---
    def skill_calls(self) -> list[SkillCalled]: ...
    def skill_results(self, name: str) -> list[SkillCompleted]: ...
    def final_answer(self) -> str: ...
    def all_events(self) -> list[BaseEvent]: ...
```

### Fixture

```python
# tests/agent/conftest.py

@pytest.fixture
def session(mock_responses: list[LLMResponse]) -> SessionHarness:
    return SessionHarness.build(mock_responses)
```

### Example test

```python
def test_reads_memory_before_evaluating(session):
    session.run("summarise the project state")
    session.assert_skill_order("read_memory", "evaluate_goal")
    session.assert_completed()
```

This reads as a specification. No infrastructure knowledge required.

---

## Layer 3: Benchmarks

### Rubric format

Each benchmark has a companion `.md` rubric file. This is the source of truth — not inline Python strings.

```
tests/bench/rubrics/
  summarise-blackboard-database.md
  index-a-pdf-document.md
  web-search-and-synthesise.md
```

**Rubric file format:**

```markdown
# Rubric: summarise-blackboard-database

## Goal
Summarise what BlackboardDatabase does and how it is structured.

## Hard assertions (deterministic, no token cost)
- must_contain: "session"
- must_contain: "SQLite"
- must_contain: "state_proposals"
- must_not_contain: "I don't know"
- min_words: 50

## Skill sequence (ordered)
- read_memory
- evaluate_goal

## LLM judge (soft score)
threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score the following answer 0.0–1.0 on whether it accurately
  describes the BlackboardDatabase's purpose, its key tables,
  and its relationship to session state management.
  
  Answer: {answer}
```

### Scoring pipeline

```
run goal → GoalRunResult
  → hard assertions (fail fast, no token cost)
  → LLM judge (only if hard assertions pass)
  → emit score + pass/fail
```

Hard assertions are free and run first. The LLM judge only fires when structural shape is confirmed. This keeps benchmark costs predictable.

### Benchmark test shape

```python
# tests/bench/test_goal_quality.py

@pytest.mark.benchmark
def test_summarise_blackboard_database(live_session, rubric):
    result = live_session.run(rubric.goal)
    rubric.assert_hard_gates(result.content)        # deterministic
    score = rubric.judge(result.content)            # LLM judge
    assert score >= rubric.threshold
```

`live_session` uses a real model from `BENCHMARK_MODEL` env var, enabling cross-model comparison:

```bash
BENCHMARK_MODEL=claude-haiku-4-5-20251001 pytest tests/bench/ --run-benchmarks
BENCHMARK_MODEL=claude-sonnet-4-6 pytest tests/bench/ --run-benchmarks
```

---

## Migration Approach: Clean Break

The existing 441 tests are frozen in place. No migration pass upfront.

**Rule:** New features are TDD'd into the new structure from day one. Old tests are deleted when you touch that area and rewrite the test properly. This avoids a migration project that blocks feature work.

**Order of operations:**
1. Build `tests/agent/harness.py` — the `SessionHarness` fixture
2. Write 3–5 agent tests to validate the API design
3. Build `tests/bench/` scaffolding — rubric loader, hard assertion runner, LLM judge
4. Write first rubric file + benchmark test
5. From here: all new tests go into `unit/` or `agent/`; old tests are cleaned up on contact

---

## CI Strategy

```yaml
# Fast path — every push
pytest tests/unit/ tests/agent/

# Integration — on PR
pytest tests/ -m integration   # needs Postgres + Vespa

# Benchmark — nightly, separate job
BENCHMARK_MODEL=claude-haiku-4-5-20251001 pytest tests/bench/ --run-benchmarks
```

`bench/` tests are skipped by default:

```python
# tests/bench/conftest.py
def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-benchmarks", default=False):
        for item in items:
            if "bench" in str(item.fspath):
                item.add_marker(pytest.mark.skip(reason="--run-benchmarks not set"))
```

---

## What Gets Deleted (on contact)

| File | Replacement |
|------|-------------|
| `tests/smoke_test_skills.py` | `tests/unit/skills/test_*.py` run by pytest |
| AppState setup in ~29 test files | `SessionHarness` fixture in `agent/` |
| `tests/test_vespa_integration.py` | Marked `@pytest.mark.integration`, stays but gated |
| Duplicate loop behaviour tests across files | Single `tests/agent/test_goal_loop.py` |

---

## Non-goals

- **Not** a full migration sprint — old tests stay frozen until touched
- **Not** golden-file / event-replay testing (revisit when behaviour is stable)
- **Not** mocking the DB at the unit layer — use SQLite in-memory instead
