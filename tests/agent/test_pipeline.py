"""Agent-layer tests: multi-skill chains, memory flow, and error recovery.

Extends the agent test suite with scenarios that exercise the SessionHarness
infrastructure beyond simple one-skill loops.
"""

# ruff: noqa: FBT003

from tests.agent.harness import SessionHarness
from tests.helpers import (
    evaluate_goal_response,
    skill_result,
    text_response,
    tool_call_response,
)


def test_reads_memory_then_writes_back():
    """Model reads, processes, then writes back to memory."""
    harness = SessionHarness.build(
        [
            tool_call_response("read_memory", {"memory_key": "counter"}),
            tool_call_response("write_memory", {"memory_key": "counter", "payload": "2"}),
            evaluate_goal_response(True, "Incremented.", "Counter is now 2."),
        ]
    )

    harness.state.database.write_memory(harness.state.session_id, "counter", "1")

    harness.run("increment the counter")
    harness.assert_skill_order("read_memory", "write_memory")
    harness.assert_completed()


def test_multi_step_analysis_chain():
    """Model chains: read → observe → reflect → evaluate."""
    harness = SessionHarness.build(
        [
            tool_call_response("read_memory", {"memory_key": "project_state"}),
            tool_call_response("observe", {"observation": "3 sessions, 12 memory keys"}),
            tool_call_response("reflect_on_result", {"result": "analysis complete"}),
            evaluate_goal_response(True, "Analysis done.", "3 active sessions."),
        ]
    )

    harness.state.database.write_memory(
        harness.state.session_id,
        "project_state",
        "Sessions: 3, Memory keys: 12, Skills: 5",
    )

    harness.run("analyze the project state")
    harness.assert_skill_order("read_memory", "observe", "reflect_on_result")
    harness.assert_completed()
    harness.assert_final_answer_contains("3 active sessions")


def test_recovers_from_failed_search():
    """Model recovers from search failure by falling back to memory."""
    harness = SessionHarness.build(
        [
            tool_call_response("search_documents", {"query": "architecture"}),
            tool_call_response("read_memory", {"memory_key": "architecture_notes"}),
            evaluate_goal_response(True, "Found in memory.", "Three-layer architecture."),
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
        "Three-layer architecture: unit, agent, bench.",
    )

    harness.run("find architecture docs")
    harness.assert_skill_called("search_documents")
    harness.assert_skill_called("read_memory")
    harness.assert_completed()


def test_iteration_budget_with_thought_chain():
    """Long chain of thought → tool → thought exhausts iteration budget."""
    harness = SessionHarness.build(
        [
            text_response("Let me analyze..."),
            tool_call_response("read_memory", {"memory_key": "state"}),
            text_response("Interesting findings..."),
            tool_call_response("consolidate_state", {}),
            text_response("Almost done..."),
            tool_call_response("read_memory", {"memory_key": "other"}),
        ],
        max_iterations=4,
    )

    harness.state.database.write_memory(harness.state.session_id, "state", "data")
    harness.state.database.write_memory(harness.state.session_id, "other", "more data")

    harness.run("deep analysis")
    harness.assert_budget_exhausted()
    # Should have executed 4 iterations (text+tool pairs count as 2 each? No — each response
    # is one iteration, so 6 responses but max_iterations=4 means only 4 run)
    assert len(harness.skill_calls) <= 4


def test_skill_override_preserves_real_skill_behavior():
    """Only overridden skills are mocked; non-overridden skills run real."""
    harness = SessionHarness.build(
        [
            tool_call_response("write_memory", {"memory_key": "notes", "payload": "hello"}),
            tool_call_response("read_memory", {"memory_key": "notes"}),
            evaluate_goal_response(True, "Verified.", "Stored and retrieved."),
        ],
        skill_overrides={
            "write_memory": skill_result(
                status="success",
                content="Written.",
                artifacts={"memory_key": "notes"},
            ),
        },
    )

    harness.run("store and verify")
    harness.assert_skill_order("write_memory", "read_memory")
    harness.assert_completed()
