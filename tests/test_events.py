from __future__ import annotations

from harness_poc.core.events import (
    EVENT_REGISTRY,
    AgentStarted,
    GoalEvaluated,
    SkillCalled,
    SkillCompleted,
)


def test_event_type_property_matches_class_name() -> None:
    event = SkillCalled(session_id="s1", tool_name="foo", arguments={})
    assert event.event_type == "SkillCalled"


def test_base_event_auto_generates_unique_ids() -> None:
    e1 = AgentStarted(session_id="s1", goal="g")
    e2 = AgentStarted(session_id="s1", goal="g")
    assert e1.event_id != e2.event_id


def test_event_registry_covers_all_concrete_types() -> None:
    expected = {
        "AgentStarted", "SkillCalled", "SkillCompleted", "GoalEvaluated",
        "LLMTextEmitted", "SubAgentDispatched", "SubAgentCompleted",
    }
    assert set(EVENT_REGISTRY.keys()) == expected


def test_skill_completed_round_trips_via_model_dump() -> None:
    event = SkillCompleted(
        session_id="s1",
        tool_name="read_memory",
        status="success",
        content="data",
        artifacts={"k": "v"},
    )
    d = event.model_dump()
    restored = SkillCompleted.model_validate(d)
    assert restored.tool_name == "read_memory"
    assert restored.artifacts == {"k": "v"}
    assert restored.event_id == event.event_id


def test_goal_evaluated_default_final_answer_is_empty() -> None:
    event = GoalEvaluated(session_id="s1", is_complete=True, reasoning="done")
    assert event.final_answer == ""
