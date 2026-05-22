"""Fixtures for agent-layer tests (mock-LLM GoalRunner sessions)."""

# Response factory shorthands — re-exported for test ergonomics so tests can write:
#   from tests.agent.conftest import tool_call_response, evaluate_goal_response
from tests.agent.harness import (  # noqa: F401
    evaluate_goal_response,
    text_response,
    tool_call_response,
)
