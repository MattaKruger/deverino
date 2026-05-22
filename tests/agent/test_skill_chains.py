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

=== Tests to add (happy path) ===

- Stuck detection: model repeats same read_memory call 3+ times,
  GoalRunner blocks it → budget exhausted
- Context window: model calls read_memory many times, earlier
  skill output gets truncated, final answer still references it
- Error recovery: search_documents(mocked, status="failed") →
  model calls read_memory instead → evaluates complete

=== Tests to add (error path) ===

- SkillNotFound: model calls a skill that doesn't exist
- PermissionDenied: skill returns status="blocked"
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
    """Model calls search_documents (mocked), sees the result, calls
    read_memory (real), then evaluates complete.

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
    # In a real session, the model would write search results to memory
    # before reading them back; here we simulate that.
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
