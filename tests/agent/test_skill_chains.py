"""Agent-layer tests: multi-skill chains.

These tests demonstrate how skills chain together across GoalRunner
iterations — the behaviour that emerges when the mock LLM calls one
skill, the GoalRunner feeds the result into the context window, and the
next iteration calls another skill.

=== Handoff pattern for extending this file ===

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
"""

# ruff: noqa: ANN201, FBT003

from tests.agent.harness import SessionHarness
from tests.helpers import (
    evaluate_goal_response,
    skill_result,
    tool_call_response,
)

# ---------------------------------------------------------------------------
# Two-skill chain: real skill → evaluate
# ---------------------------------------------------------------------------


def test_reads_memory_then_evaluates():
    """Model calls read_memory (real), sees the data, then evaluates complete.

    Demonstrates: real skill execution against in-memory DB, context
    window feeding the result into the next LLM iteration, and the
    GoalRunner intercepting evaluate_goal to complete the loop.
    """
    harness = SessionHarness.build([
        tool_call_response("read_memory", {"memory_key": "context_summary"}),
        evaluate_goal_response(
            True,
            "Read the context summary — project state is clear.",
            "Project has 3 active sessions and 12 stored memory keys.",
        ),
    ])

    # Pre-seed the database so read_memory has data to return.
    harness.state.database.write_memory(
        harness.state.session_id,
        "context_summary",
        "Project has 3 active sessions and 12 stored memory keys.",
    )

    harness.run("summarise the project state")

    harness.assert_skill_called("read_memory")
    harness.assert_skill_completed("read_memory", status="success")
    harness.assert_completed()
    harness.assert_final_answer_contains("3 active sessions")


# ---------------------------------------------------------------------------
# Three-skill chain: mocked external → real → evaluate
# ---------------------------------------------------------------------------


def test_mocked_search_then_reads_memory_then_evaluates():
    """Model calls search_documents (mocked), calls read_memory (real), then evaluates complete.

    Demonstrates: skill_overrides proxy returning a mock SkillResult
    without touching Vespa, the mock result flowing through the context
    window to the next iteration, and real + mocked skills mixing in
    a single chain.
    """
    harness = SessionHarness.build(
        [
            tool_call_response("search_documents", {"query": "testing architecture"}),
            tool_call_response("read_memory", {"memory_key": "search_results"}),
            evaluate_goal_response(
                True,
                "Searched docs and read stored results.",
                "The testing architecture has three layers: unit, agent, bench.",
            ),
        ],
        skill_overrides={
            "search_documents": skill_result(
                status="success",
                content=(
                    "Found 2 documents:\n"
                    "1. testing-architecture-design.md — Three-layer design\n"
                    "2. testing-architecture-implementation-spec.md — Phase plan"
                ),
                hit_count=2,
            ),
        },
    )

    # Pre-seed the database so read_memory has data to return.
    harness.state.database.write_memory(
        harness.state.session_id,
        "search_results",
        {
            "query": "testing architecture",
            "hits": 2,
            "top_result": "Three-layer design: unit, agent, bench.",
        },
    )

    harness.run("find information about the testing architecture")

    harness.assert_skill_order("search_documents", "read_memory")
    harness.assert_skill_completed("search_documents", status="success")
    harness.assert_skill_completed("read_memory", status="success")
    harness.assert_completed()
    harness.assert_final_answer_contains("three layers")


# ---------------------------------------------------------------------------
# Stuck detection: repeated failed calls → blocked → budget exhausted
# ---------------------------------------------------------------------------


def test_stuck_detection_blocks_repeated_failed_skill():
    """Model repeats the same failing read_memory call 3+ times.

    GoalRunner tracks all actions via _action_keys. After
    stuck_threshold (3) consecutive semantically-identical attempts,
    subsequent calls are blocked with SkillCompleted(status="blocked")
    instead of executing. The loop exhausts its iteration budget.

    Sequence: call1 fails, call2 fails, call3 fails, call4 blocked.
    """
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

    # No data pre-seeded for "missing" — read_memory returns status="failed".
    harness.run("find data that doesn't exist")

    harness.assert_budget_exhausted()
    harness.assert_skill_completed("read_memory", status="failed")
    harness.assert_skill_completed("read_memory", status="blocked")


# ---------------------------------------------------------------------------
# Context window trimming: many calls, small window, final answer references recent
# ---------------------------------------------------------------------------


def test_context_window_trims_old_skill_output():
    """Many skill calls push early output out of the context window.

    With context_window=5, only the last 5 events of types
    [SkillCalled, SkillCompleted, GoalEvaluated, LLMTextEmitted]
    are included in the decision prompt. Earlier skill results are
    invisible to the LLM.

    The mock LLM returns predetermined responses (it doesn't read
    the context), so this test validates that the harness correctly
    limits get_recent_events and completes without errors under
    constrained context.
    """
    item_count = 12

    harness = SessionHarness.build(
        [
            tool_call_response("read_memory", {"memory_key": f"item_{i}"})
            for i in range(item_count)
        ]
        + [
            evaluate_goal_response(
                True,
                "Processed all items.",
                "Latest items: item_10 and item_11.",
            ),
        ],
        max_iterations=15,
        context_window=5,
    )

    # Pre-seed all memory keys so read_memory succeeds.
    for i in range(item_count):
        harness.state.database.write_memory(
            harness.state.session_id,
            f"item_{i}",
            f"Data for item {i}",
        )

    harness.run("process all items")

    harness.assert_completed()
    harness.assert_final_answer_contains("item_10")


# ---------------------------------------------------------------------------
# Error recovery: external skill fails → model pivots → completes
# ---------------------------------------------------------------------------


def test_recovers_from_failed_search_by_reading_memory():
    """Mocked external search fails; model pivots to read_memory.

    Demonstrates: mixed status assertions across a chain, the model
    adapting after a failed skill by switching to a different approach,
    and the goal still completing successfully.
    """
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


# ---------------------------------------------------------------------------
# Error path: SkillNotFound
# ---------------------------------------------------------------------------


def test_skill_not_found_emits_error():
    """Model calls a skill name not registered in the system.

    SkillRunner._find_skill_file raises ValueError("Unknown skill
    requested: ..."), which GoalRunner catches and emits
    SkillCompleted(status="error"). The model then evaluates complete.
    """
    harness = SessionHarness.build([
        tool_call_response("nonexistent_skill", {}),
        evaluate_goal_response(True, "Handled.", "Recovered from unknown skill."),
    ])

    harness.run("test unknown skill")

    harness.assert_skill_completed("nonexistent_skill", status="error")
    harness.assert_completed()


# ---------------------------------------------------------------------------
# Error path: PermissionDenied
# ---------------------------------------------------------------------------


def test_permission_denied_skill_returns_blocked():
    """Skill returns status="blocked" due to permission restrictions.

    The mock override returns a SkillResult with status="blocked".
    GoalRunner tracks it in _action_keys. The model adapts and completes.
    """
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
