# Testing Guide

Three layers. Each has one job. Each runs independently.

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│   unit   │     │  agent   │     │  bench   │
│          │     │          │     │          │
│ pure fn  │     │ mock LLM │     │  Postgres│
│ + SQLite │     │ + SQLite │     │  + LLM   │
└──────────┘     └──────────┘     └──────────┘
     │                │                │
     ▼                ▼                ▼
  functions       goal loop         quality
  & parsing       behaviour         scoring
```

| Layer | Runs | What it validates |
|-------|------|-------------------|
| `tests/unit/` | `just test-unit` | Pure functions, parsing, events, database operations |
| `tests/agent/` | `just test-agent` | GoalRunner loop behaviour with a mock LLM |
| `tests/bench/` | `just test-bench` | Agent output quality against rubrics with a real LLM |

All fast tests in one go:

```bash
uv run pytest tests/unit/ tests/agent/
```

## Layer rules

| If a test imports... | It belongs in |
|---------------------|---------------|
| Nothing from `harness_poc` (pure function) | `unit/` |
| `BlackboardDatabase` or `in_memory_engine` fixture | `unit/` |
| `SessionHarness` | `agent/` |
| `AppState` or `build_app_state` | `agent/` or `bench/` |
| Real `build_model()` with API keys | `bench/` |

## Unit tests (`tests/unit/`)

Test one thing. No harness, no real LLM, no Postgres. In-memory SQLite for
database-dependent tests.

**Example — testing a database operation:**

```python
# tests/unit/test_database_core.py

def test_write_and_read_memory_string(in_memory_engine):
    """Write a string, read it back. Session isolation works."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("test")

    db.write_memory(sid, "greeting", "hello")
    result = db.read_memory(sid, "greeting")

    assert result == "hello"
```

**Example — testing a pure function:**

```python
# tests/unit/test_events.py

def test_skill_completed_populates_tool_name_from_skill_name():
    """When only skill_name is set, tool_name is auto-populated."""
    event = SkillCompleted(
        session_id="s1",
        skill_name="read_memory",
        status="success",
        content="done",
    )
    assert event.tool_name == "read_memory"
```

No fixtures needed for pure functions. Use `in_memory_engine` fixture
(defined in `tests/conftest.py`) for database tests.

## Agent tests (`tests/agent/`)

Test the GoalRunner loop. A mock LLM returns predetermined responses — no API
calls. Skills execute against an in-memory database. The test defines a
sequence of LLM actions and asserts what the loop did with them.

**Core concept:** `SessionHarness.build([response, response, ...])` — each
element is what the mock LLM returns for one iteration of the goal loop.

Three factory functions produce mock responses:

```python
from tests.helpers import (
    tool_call_response,        # model calls a skill
    evaluate_goal_response,    # model says the goal is complete (or not)
    text_response,             # model emits text without calling a tool
    skill_result,              # mock what a skill returns (for skill_overrides)
)
```

**Example — the simplest agent test:**

```python
# tests/agent/test_goal_loop.py

def test_completes_on_direct_evaluate_goal():
    """Model immediately evaluates the goal as complete."""
    harness = SessionHarness.build([
        evaluate_goal_response(True, "Nothing to do.", "All good."),
    ])

    harness.run("check status")

    harness.assert_completed()
    harness.assert_final_answer_contains("All good")
```

**Example — a two-skill chain with data dependency:**

```python
def test_reads_memory_then_evaluates():
    """Model reads from the blackboard, then evaluates complete."""
    harness = SessionHarness.build([
        tool_call_response("read_memory", {"memory_key": "context_summary"}),
        evaluate_goal_response(True, "Read complete.", "Project has 3 sessions."),
    ])

    # Pre-seed data the real skill will read.
    harness.state.database.write_memory(
        harness.state.session_id,
        "context_summary",
        "Project has 3 active sessions and 12 stored memory keys.",
    )

    harness.run("summarise the project state")

    harness.assert_skill_called("read_memory")
    harness.assert_skill_completed("read_memory", status="success")
    harness.assert_completed()
```

**Mocking external skills:**

Skills that need external services (Vespa, web, subprocess) can be overridden
with `skill_result()`. The mock result is returned instead of executing the
real skill.

```python
def test_recovers_from_failed_search_by_reading_memory():
    harness = SessionHarness.build(
        [
            tool_call_response("search_documents", {"query": "architecture"}),
            tool_call_response("read_memory", {"memory_key": "architecture_notes"}),
            evaluate_goal_response(True, "Found in memory.", "Three layers."),
        ],
        skill_overrides={
            "search_documents": skill_result(
                status="failed",
                content="Vespa connection refused.",
            ),
        },
    )
    # Pre-seed data, run, assert...
```

**Available assertions:**

| Method | What it checks |
|--------|---------------|
| `assert_completed()` | GoalRunResult.status == "completed" |
| `assert_budget_exhausted()` | GoalRunResult.status == "budget_exhausted" |
| `assert_skill_called(name)` | A SkillCalled event exists for this skill |
| `assert_skill_not_called(name)` | No SkillCalled event exists for this skill |
| `assert_skill_completed(name, status=)` | A SkillCompleted event exists with this status |
| `assert_skill_order("a", "b", ...)` | Skills were called in this relative order |
| `assert_final_answer_contains(fragment)` | Result content contains this text (case-insensitive) |

**Important:** `evaluate_goal` is intercepted by GoalRunner — it emits a
`GoalEvaluated` event, not a `SkillCalled` event. Do not include it in
`assert_skill_order()` or in a rubric's `skill_sequence`.

## Benchmark tests (`tests/bench/`)

Test agent output quality with a real LLM. Opt-in via `--run-benchmarks`.
Each benchmark is paired with a rubric — a `.md` file that defines hard gates
(free, deterministic) and an LLM judge (token cost).

**Running benchmarks:**

```bash
just test-bench                           # default: haiku
just test-bench claude-sonnet-4-6         # cross-model comparison
```

**Rubric format (`tests/bench/rubrics/<slug>.md`):**

```markdown
# Rubric: summarise-blackboard-database

## Goal

Summarise what BlackboardDatabase does and how it is structured.

## Hard Assertions

- must_contain: "session"
- must_contain: "SQLite"
- must_not_contain: "I don't know"
- min_words: 50
- skill_sequence: [read_memory]

## LLM Judge

threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score 0.0-1.0: does the answer accurately describe
  the BlackboardDatabase's purpose and structure?

  Answer: {answer}
```

**Hard gates** run first — they're free and fail-fast. **LLM judge** only
fires if hard gates pass — saves tokens on clearly wrong answers.

**Benchmark test structure:**

```python
@pytest.mark.benchmark
def test_summarise_blackboard_database(live_session, rubric):
    result = live_session.run(rubric.goal)
    rubric.assert_hard_gates(result, events=live_session.events)
    score = rubric.judge(result.content, config=live_session.state.config.llm)
    assert score >= rubric.judge_threshold
```

The `live_session` fixture wires a real LLM via `BENCHMARK_MODEL` env var.
The `rubric` fixture loads the `.md` file by convention:
`test_summarise_blackboard_database` → `summarise-blackboard-database.md`.

## Writing a new test

**Unit test** — create `tests/unit/test_<thing>.py`:

1. Add `# ruff: noqa: ANN201, FBT003` at the top
2. Use `in_memory_engine` fixture if you need a database
3. No imports from `harness_poc.app_factory` — that's an agent/bench concern

**Agent test** — add to `tests/agent/test_skill_chains.py` (or create a new file):

1. Import `SessionHarness` from `tests.agent.harness`
2. Import factories from `tests.helpers`
3. Build a mock response sequence — each element is one loop iteration
4. Pre-seed data with `harness.state.database.write_memory()` if real skills need it
5. Override external skills with `skill_overrides` if they'd need real services
6. `harness.run(goal)` then assert

**Benchmark test** — create `tests/bench/test_<thing>.py` and a matching rubric.
Use the `create_rubrics` skill to generate the rubric from a description
rather than writing it by hand:

```text
/skill create_rubrics description="..." goal="..."
/skill create_rubrics confirm=true slug="my-slug"
```

Then create the test function using `live_session` and `rubric` fixtures,
add `@pytest.mark.benchmark`, and run with `--run-benchmarks`.

See `docs/superpowers/specs/2026-05-23-create-rubrics-usage.md` for the full
`create_rubrics` guide.

## Design decisions

| Decision | Why |
|----------|-----|
| In-memory SQLite for agent tests | No Postgres drift. Same construction path via `database_url`. |
| Manual `SessionHarness.build()` — no auto-fixture | The mock response sequence IS the test. It belongs inline. |
| `RecordingEventBus` instead of real `EventBus` | No persistence, no subscribers. Tests read events directly. |
| `skill_overrides` dict on `SessionHarness.build()` | Mock only the skills that need external services. Real skills still execute. |
| Rubrics as `.md` files | Readable as documentation. Parseable as structured data. Same file validates both mock and live sessions. |
| LLM judge uses a cheap model (haiku) | Scoring doesn't need reasoning depth. Keeps benchmark costs predictable. |
| `--run-benchmarks` opt-in flag | Prevents accidental token spend during normal test runs. |


## Mock Conventions

| Pattern | Use case | Example |
|---------|----------|---------|
| `monkeypatch.setattr` | Attribute/syspath/environment patching | `monkeypatch.setattr("module.func", mock_fn)` |
| `unittest.mock.patch` | Print capture in REPL tests (context manager auto-cleanup) | `with patch("harness_poc.repl.print_text") as p:` |
| Custom mock classes | Domain object substitution in handler tests | `MockEngine`, `MockDatabase` |
| `MagicMock` | Only when the caller checks `.assert_called_with()`; never when return value matters | `mock_db.write_memory = MagicMock()` |

- Prefer `monkeypatch.setattr` for simple attribute replacement — it's pytest-native and doesn't leave stale patches.
- Use `unittest.mock.patch()` only for REPL/handler tests that capture `print_text`/`print_error` output — the context manager ensures cleanup.
- Custom mock classes (`MockEngine`, `MockDatabase`) should live in the test file that uses them.
- When a test needs a real PostgreSQL database (not SQLite), use the `db_engine` fixture — it connects to the test container on port 5433.