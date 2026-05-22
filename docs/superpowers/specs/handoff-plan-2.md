# Handoff Plan 2: Multi-Skill Chain Agent Tests

**Date:** 2026-05-22
**Parent:** [handoff-tests.md](./handoff-tests.md)
**Status:** All 7 chain tests delivered. Harness extension + 2 validation + 5 scenario tests passing.

---

## What was delivered this session (2026-05-22, session 2)

### 5 new multi-skill chain scenario tests

All tests added to `tests/agent/test_skill_chains.py`. Suite now contains 7 tests (up from 2).

| Test | Skills | What it validates |
|------|--------|-------------------|
| `test_stuck_detection_blocks_repeated_failed_skill` | `read_memory` × 4 | Semantic stuck detection blocks repeated failures, budget exhausts |
| `test_context_window_trims_old_skill_output` | `read_memory` × 12 → `evaluate_goal` | Harness completes with `context_window=5` under load |
| `test_recovers_from_failed_search_by_reading_memory` | `search_documents`(mocked,failed) → `read_memory` → `evaluate_goal` | Model pivots after failure, mixed status assertions |
| `test_skill_not_found_emits_error` | `nonexistent_skill` → `evaluate_goal` | ValueError → SkillCompleted(status="error"), model recovers |
| `test_permission_denied_skill_returns_blocked` | `semble_search`(mocked,blocked) → `evaluate_goal` | Mocked blocked status flows through GoalRunner correctly |

**Note:** SkillNotFound status is `"error"` (not `"failed"` as the original handoff spec suggested). GoalRunner's `except` block (`goal_runner.py:751`) emits `status="error"` for unhandled exceptions.

`SessionHarness.build()` now accepts an optional `skill_overrides` parameter. When the mock LLM calls an overridden skill, `_SkillOverrideProxy` returns a mock `SkillResult` — no real execution, no external service calls. All other skills execute normally against the in-memory database.

**Files modified:**

| File                      | What                                                                   |
| ------------------------- | ---------------------------------------------------------------------- |
| `tests/agent/harness.py`  | `_SkillOverrideProxy` class + `skill_overrides` parameter on `build()` |
| `tests/helpers.py`        | `skill_result(status, content, **artifacts)` factory                   |
| `tests/agent/conftest.py` | Re-exports `skill_result`                                              |

**Usage:**

```python
from tests.helpers import skill_result

harness = SessionHarness.build(
    [
        tool_call_response("search_documents", {"query": "testing architecture"}),
        tool_call_response("read_memory", {"memory_key": "search_results"}),
        evaluate_goal_response(True, "Done.", "Three layers: unit, agent, bench."),
    ],
    skill_overrides={
        "search_documents": skill_result(
            status="success",
            content="Found 2 documents about testing architecture.",
            hit_count=2,
        ),
    },
)
```

### New test file: `tests/agent/test_skill_chains.py`

Two validation tests that prove the harness extension works end-to-end:

| Test                                                  | Skills                                                       | Demonstrates                                               |
| ----------------------------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------- |
| `test_reads_memory_then_evaluates`                    | `read_memory` → `evaluate_goal`                              | Real skill chain, DB pre-seeding, context window data flow |
| `test_mocked_search_then_reads_memory_then_evaluates` | `search_documents`(mocked) → `read_memory` → `evaluate_goal` | Mock + real skill mixing, `skill_overrides` API            |

---

## Handoff pattern (from the file docstring)

```
Each test is a self-contained scenario. To add a new chain test:

1. Decide the skill sequence the mock LLM should follow.
2. If any skills need external services (Vespa, web, subprocess),
   add them to skill_overrides with skill_result().
3. If a real skill needs pre-seeded data, write to
   harness.state.database before harness.run().
4. Use harness.state.session_id for the session key.
5. Assertions verify the chain executed: assert_skill_order()
   for the sequence, assert_skill_completed() for individual
   results, assert_completed() for the outcome.

Available factory imports (from tests.helpers):
  tool_call_response(name, args)   — model calls a skill
  evaluate_goal_response(bool, ...) — model evaluates completion
  text_response(content)           — model emits text, no tool call
  skill_result(status, content, **artifacts) — mock skill result

Remember: evaluate_goal is intercepted by GoalRunner — it emits
GoalEvaluated, not SkillCalled. Do not include it in
assert_skill_order().
```

---

## Tests to add (happy path) ✅ Delivered session 2

### Stuck detection

Model repeats the same failing `read_memory` call 3+ times. GoalRunner blocks subsequent calls → budget exhausted.

```python
def test_stuck_detection_blocks_repeated_failed_skill():
    harness = SessionHarness.build(
        [
            tool_call_response("read_memory", {"memory_key": "missing"}),
            tool_call_response("read_memory", {"memory_key": "missing"}),
            tool_call_response("read_memory", {"memory_key": "missing"}),
            tool_call_response("read_memory", {"memory_key": "missing"}),
        ],
        max_iterations=4,
        stuck_threshold=3,
    )
    harness.run("find data that doesn't exist")
    harness.assert_budget_exhausted()
    # Check that some SkillCompleted events have status="blocked"
```

**Assertions:** `assert_budget_exhausted()`. Check that blocked calls emit `SkillCompleted(status="blocked")`. The 3rd and 4th calls should be blocked (2 failures before `stuck_threshold` triggers at the 3rd).

### Context window trimming

Many skill calls push early output out of the context window. Final answer still references data from the most recent calls.

```python
def test_context_window_trims_old_skill_output():
    harness = SessionHarness.build(
        [
            tool_call_response("read_memory", {"memory_key": f"item_{i}"})
            for i in range(12)
        ]
        + [
            evaluate_goal_response(
                True,
                "Processed all items.",
                "Latest items: item_10 and item_11.",
            ),
        ],
        max_iterations=15,
        context_window=5,  # only last 5 events in context
    )
    # Pre-seed 12 memory keys
    for i in range(12):
        harness.state.database.write_memory(
            harness.state.session_id,
            f"item_{i}",
            f"Data for item {i}",
        )

    harness.run("process all items")
    harness.assert_completed()
    harness.assert_final_answer_contains("item_10")
```

**Assertions:** `assert_completed()`. Final answer references recent items but not early ones. The `context_window=5` means the LLM only sees the last 5 events — early `SkillCompleted` events are excluded from the prompt.

### Error recovery

Mocked external skill fails, model pivots to a different approach, completes.

```python
def test_recovers_from_failed_search_by_reading_memory():
    harness = SessionHarness.build(
        [
            tool_call_response("search_documents", {"query": "architecture"}),
            tool_call_response("read_memory", {"memory_key": "architecture_notes"}),
            evaluate_goal_response(
                True,
                "Search failed but found notes in memory.",
                "Architecture has three layers: unit, agent, bench.",
            ),
        ],
        skill_overrides={
            "search_documents": skill_result(
                status="failed",
                content="Vespa connection refused.",
            ),
        },
    )
    harness.state.database.write_memory(
        harness.state.session_id,
        "architecture_notes",
        "Three layers: unit, agent, bench.",
    )

    harness.run("find architecture information")
    harness.assert_skill_order("search_documents", "read_memory")
    harness.assert_skill_completed("search_documents", status="failed")
    harness.assert_skill_completed("read_memory", status="success")
    harness.assert_completed()
```

**Assertions:** `assert_skill_order()`, `assert_skill_completed()` with mixed statuses, `assert_completed()`.

---

## Tests to add (error path) ✅ Delivered session 2

### SkillNotFound

Model calls a skill name that isn't registered in the system. GoalRunner executes it, SkillRunner raises `ValueError("Unknown skill requested: ...")`, SkillCompleted is emitted with `status="failed"`.

```python
def test_skill_not_found_emits_failed():
    harness = SessionHarness.build([
        tool_call_response("nonexistent_skill", {}),
        evaluate_goal_response(True, "Handled.", "Recovered."),
    ])
    harness.run("test unknown skill")
    harness.assert_skill_completed("nonexistent_skill", status="failed")
    harness.assert_completed()
```

### PermissionDenied

Skill returns `status="blocked"` due to permission restrictions. Model adapts.

```python
def test_permission_denied_skill_returns_blocked():
    harness = SessionHarness.build(
        [
            tool_call_response("semble_search", {"query": "main.py"}),
            evaluate_goal_response(
                True,
                "Semble search blocked — no workspace access.",
                "Cannot search codebase: workspace permission denied.",
            ),
        ],
        skill_overrides={
            "semble_search": skill_result(
                status="blocked",
                content="Permission denied: workspace=read required.",
            ),
        },
    )
    harness.run("search the codebase")
    harness.assert_skill_completed("semble_search", status="blocked")
    harness.assert_completed()
```

---

## Current test counts

| Layer          | Tests                             | Runtime             |
| -------------- | --------------------------------- | ------------------- |
| `tests/unit/`  | 88                                | ~0.2s pure + ~1s DB |
| `tests/agent/` | 12 (5 goal_loop + 7 skill_chains) | ~1.6s               |
| **Total fast** | **100**                           | **~3.4s**           |
| `tests/bench/` | 1 (+ 1 rubric)                    | opt-in, real LLM    |

## How to run

```bash
# All fast tests
uv run pytest tests/unit/ tests/agent/ -v

# Just the new chain tests
uv run pytest tests/agent/test_skill_chains.py -v -s

# Just agent tests
just test-agent
```

## Files changed outside tests/

- `tests/agent/harness.py` — `_SkillOverrideProxy` + `skill_overrides` param
- `tests/helpers.py` — `skill_result()` factory
- `tests/agent/conftest.py` — re-exports `skill_result`
- `tests/agent/test_skill_chains.py` — **new**, 2 tests + handoff pattern

## Related documents

- `docs/superpowers/specs/handoff-tests.md` — main handoff, architecture overview
- `docs/superpowers/specs/2026-05-22-testing-architecture-design.md` — original design
- `docs/superpowers/specs/2026-05-22-testing-architecture-implementation-spec.md` — detailed spec
