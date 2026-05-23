from __future__ import annotations

from harness_poc.core.events import (
    EVENT_REGISTRY,
    AgentInputAdded,
    AgentStarted,
    GoalEvaluated,
    LLMActionEmitted,
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
    SkillCalled,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
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
        "AgentStarted",
        "SkillCalled",
        "SkillRequested",
        "SkillCancelled",
        "SkillCompleted",
        "AgentInputAdded",
        "LLMActionEmitted",
        "StreamPaused",
        "GoalEvaluated",
        "LLMTextEmitted",
        "AgentTurnRecorded",
        "SubAgentDispatched",
        "SubAgentCompleted",
        "PipelineStarted",
        "PipelineNodeStarted",
        "PipelineNodeCompleted",
        "PipelineCompleted",
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


def test_async_runtime_events_roundtrip() -> None:
    expected_tokens = 10
    input_event = AgentInputAdded(session_id="s1", user_content="hello")
    skill_event = SkillRequested(
        session_id="s1",
        skill_name="read_memory",
        arguments={"key": "x"},
    )
    action_event = LLMActionEmitted(
        session_id="s1",
        tokens_used=expected_tokens,
        model="test",
    )
    paused_event = StreamPaused(
        session_id="s1",
        reason="budget_exhausted",
        threshold_breached="10",
    )

    restored_input = AgentInputAdded.model_validate(input_event.model_dump())
    restored_skill = SkillRequested.model_validate(skill_event.model_dump())
    restored_action = LLMActionEmitted.model_validate(action_event.model_dump())
    restored_pause = StreamPaused.model_validate(paused_event.model_dump())

    assert restored_input.type_name == "AgentInputAdded"
    assert restored_skill.skill_name == "read_memory"
    assert restored_action.tokens_used == expected_tokens
    assert restored_action.new_tokens == expected_tokens
    assert restored_action.billable_tokens == expected_tokens
    assert restored_pause.reason == "budget_exhausted"


def test_llm_action_preserves_explicit_token_breakdown() -> None:
    new_tokens = 7
    input_tokens = 100
    output_tokens = 12
    billable_tokens = 112
    event = LLMActionEmitted(
        session_id="s1",
        model="test",
        tokens_used=new_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=billable_tokens,
        new_tokens=new_tokens,
    )

    restored = LLMActionEmitted.model_validate(event.model_dump())

    assert restored.tokens_used == new_tokens
    assert restored.new_tokens == new_tokens
    assert restored.billable_tokens == billable_tokens
    assert restored.input_tokens == input_tokens
    assert restored.output_tokens == output_tokens


def test_pipeline_started_roundtrip() -> None:
    event = PipelineStarted(session_id="s1", pipeline_name="my-pipe", node_count=3)
    assert event.event_type == "PipelineStarted"
    restored = PipelineStarted.model_validate(event.model_dump())
    assert restored.pipeline_name == "my-pipe"
    assert restored.node_count == 3


def test_pipeline_node_started_roundtrip() -> None:
    event = PipelineNodeStarted(session_id="s1", node_id="web_research", node_type="agent")
    assert event.event_type == "PipelineNodeStarted"
    restored = PipelineNodeStarted.model_validate(event.model_dump())
    assert restored.node_id == "web_research"
    assert restored.node_type == "agent"


def test_pipeline_node_completed_roundtrip() -> None:
    event = PipelineNodeCompleted(
        session_id="s1", node_id="web_research", status="completed", output_preview="done"
    )
    restored = PipelineNodeCompleted.model_validate(event.model_dump())
    assert restored.status == "completed"


def test_pipeline_completed_roundtrip() -> None:
    event = PipelineCompleted(
        session_id="s1", pipeline_name="my-pipe", status="completed", duration_s=1.5
    )
    restored = PipelineCompleted.model_validate(event.model_dump())
    assert restored.duration_s == 1.5


def test_pipeline_events_in_registry() -> None:
    pipeline_event_names = (
        "PipelineStarted",
        "PipelineNodeStarted",
        "PipelineNodeCompleted",
        "PipelineCompleted",
    )
    for name in pipeline_event_names:
        assert name in EVENT_REGISTRY
