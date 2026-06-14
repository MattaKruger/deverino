# Test Structure Cleanup — Implementation Spec (v3)

## Summary

Relocate 3 misplaced root-level tests, split 2 monolith files, and add
conftest docstrings. No test logic changes — pure file reorganization.

## Phase 1: Relocate root-level tests

| From | To |
|------|-----|
| `tests/test_copt_gate.py` | `tests/context_map/test_copt_gate.py` |
| `tests/test_acdl_parser.py` | `tests/unit/test_acdl_parser.py` |
| `tests/test_auto_observe_hook.py` | `tests/repl/test_auto_observe_hook.py` |

Zero external import references — safe moves.

## Phase 2a: Split `test_subagent_system.py` (834L → 7 files + conftest)

**Extract to `tests/pressure/conftest.py` (new):**
- `SpawnerSpy` dataclass (lines 61-79)
- `EventBusSpy` dataclass (lines 81-98)
- `BlackboardSpy` dataclass (lines 100-106)
- `_make_result()` helper (lines 48-59)
- 4 pytest fixtures: `spawner`, `event_bus`, `blackboard`, `engine` (lines 112-139)

**New files (one per concern):**

| File | Contents | Tests |
|------|----------|-------|
| `test_event_ordering.py` | `TestEventOrdering` | 3 |
| `test_lifecycle_guarantees.py` | `TestFinallyGuarantee` + `TestBackgroundPool` + `TestSpawnSubAgentReturn` | 13 |
| `test_session_isolation.py` | `TestSessionIsolation` | 2 |
| `test_event_schema.py` | `TestEventSchema` | 4 |
| `test_error_paths.py` | `TestErrorPaths` | 6 |
| `test_task_spec.py` | `TestTaskSpec` | 2 |
| `test_context_map_lifecycle.py` | `TestContextMapLifecycleEvents` + `TestCorpusKeyAutoGeneration` | 7 |

Delete `tests/pressure/test_subagent_system.py`.

## Phase 2b: Split `test_tui_vim.py` (636L → 4 files + conftest)

**Extract to `tests/repl/conftest.py` (new):**
- `FakeEditor` class (lines 22-118)
- `FakeChat` class (lines 484-531)

**New files (by functional area):**

| File | Contents | Tests |
|------|----------|-------|
| `test_tui_vim_core.py` | core state + counts + operator sections | 17 |
| `test_tui_vim_normal.py` | normal + insert sections | 15 |
| `test_tui_vim_visual.py` | visual section | 7 |
| `test_tui_vim_chat.py` | chat handler section | 13 |

Delete `tests/repl/test_tui_vim.py`.

## Phase 3: Conftest docstrings

- `tests/conftest.py`: `"""Shared fixtures: db_engine (PostgreSQL), in_memory_engine (SQLite), test_config, session_runner."""`
- `tests/agent/conftest.py`: `"""Re-exports mock LLM factories from tests.helpers for agent-layer tests."""`
- `tests/bench/conftest.py`: `"""Benchmark opt-in toggle (--run-benchmarks) and live_session/rubric fixtures."""`

## Design Decisions

- Don't refactor test bodies — move code verbatim
- Keep test doubles local to their test directory
- Group by concern, not by line count
- `TestBackgroundPool` + `TestFinallyGuarantee` + `TestSpawnSubAgentReturn` grouped as "lifecycle guarantees"
- `TestContextMapLifecycleEvents` + `TestCorpusKeyAutoGeneration` grouped as "context map lifecycle"

## Verification

```bash
uv run pytest tests/ -x -q  # full suite passes
find tests -name "test_*.py" ! -exec grep -q "def test_\|async def test_" {} \; -print  # no zombie files
```
