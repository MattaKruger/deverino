"""Unit tests for the event model layer — the communication fabric.

Every event in the system flows through these types. Tests validate
auto-population, backward-compatibility fields, and registry integrity.
"""

# ruff: noqa: ANN201

from harness_poc.core.events import (
    EVENT_REGISTRY,
    AgentInputAdded,
    AgentStarted,
    AgentTurnRecorded,
    BaseEvent,
    ContextWarmed,
    DelegateTaskCompleted,
    ExecutionCompleted,
    GateCompleted,
    GateFailed,
    GatePassed,
    GoalEvaluated,
    LLMActionEmitted,
    LLMTextEmitted,
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
    ProbeCompleted,
    ProbeFailed,
    SkillCalled,
    SkillCancelled,
    SkillCompleted,
    SkillRequested,
    SpecCommitted,
    StreamPaused,
    SubAgentCompleted,
    SubAgentDispatched,
    WorkflowStarted,
)

# ---------------------------------------------------------------------------
# BaseEvent — auto-population
# ---------------------------------------------------------------------------


def test_event_type_name_is_populated():
    """Each event auto-populates type_name from its class name."""
    event = AgentStarted(session_id="s1", goal="test")
    assert event.type_name == "AgentStarted"
    assert event.event_type == "AgentStarted"


def test_type_name_preserved_when_explicitly_set():
    """An explicit type_name value is not overwritten."""
    event = BaseEvent(session_id="s1", type_name="CustomType")
    assert event.type_name == "CustomType"


def test_event_id_is_unique():
    """Each event gets a unique UUID by default."""
    a = AgentStarted(session_id="s1", goal="g")
    b = AgentStarted(session_id="s1", goal="g")
    assert a.event_id != b.event_id


def test_event_id_can_be_set_explicitly():
    """The event_id can be overridden (useful for deterministic tests)."""
    event = AgentStarted(session_id="s1", goal="g", event_id="known-id")
    assert event.event_id == "known-id"


# ---------------------------------------------------------------------------
# SkillCompleted — backward-compatibility fields
# ---------------------------------------------------------------------------


def test_skill_completed_populates_tool_name_from_skill_name():
    """When only skill_name is set, tool_name mirrors it."""
    event = SkillCompleted(
        session_id="s1", status="success", skill_name="read_memory", content="ok"
    )
    assert event.tool_name == "read_memory"
    assert event.skill_name == "read_memory"


def test_skill_completed_populates_skill_name_from_tool_name():
    """When only tool_name is set, skill_name mirrors it."""
    event = SkillCompleted(
        session_id="s1", status="success", tool_name="read_memory", content="ok"
    )
    assert event.tool_name == "read_memory"
    assert event.skill_name == "read_memory"


def test_skill_completed_populates_content_from_result():
    """When result is set but content is empty, content mirrors result."""
    event = SkillCompleted(
        session_id="s1", status="success", tool_name="read", result="output data"
    )
    assert event.content == "output data"
    assert event.result == "output data"


def test_skill_completed_populates_result_from_content():
    """When content is set but result is empty, result mirrors content."""
    event = SkillCompleted(
        session_id="s1", status="success", tool_name="read", content="output data"
    )
    assert event.result == "output data"
    assert event.content == "output data"


def test_skill_completed_explicit_fields_are_not_overwritten():
    """When both content and result are set, neither is overwritten."""
    event = SkillCompleted(
        session_id="s1",
        status="success",
        tool_name="read",
        content="content version",
        result="result version",
    )
    assert event.content == "content version"
    assert event.result == "result version"


# ---------------------------------------------------------------------------
# LLMActionEmitted — token field auto-population
# ---------------------------------------------------------------------------


def test_llm_action_emitted_populates_token_fields():
    """new_tokens and billable_tokens fall back to tokens_used when not set."""
    event = LLMActionEmitted(
        session_id="s1", tokens_used=150, model="test-model"
    )
    assert event.new_tokens == 150
    assert event.billable_tokens == 150
    assert event.tokens_used == 150


def test_llm_action_emitted_respects_explicit_token_fields():
    """Explicit new_tokens / billable_tokens are not overwritten."""
    event = LLMActionEmitted(
        session_id="s1",
        tokens_used=150,
        model="test-model",
        new_tokens=200,
        billable_tokens=300,
    )
    assert event.new_tokens == 200
    assert event.billable_tokens == 300


# ---------------------------------------------------------------------------
# EVENT_REGISTRY — completeness and integrity
# ---------------------------------------------------------------------------


def test_event_registry_contains_all_public_events():
    """Every public event class should be present in EVENT_REGISTRY.

    This guarantees that event_store.reconstruct() and any dispatch
    that relies on the registry can resolve every event type.
    """
    expected = {
        "AgentStarted",
        "SkillCalled",
        "SkillRequested",
        "SkillCompleted",
        "SkillCancelled",
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
        "WorkflowStarted",
        "ProbeCompleted",
        "ExecutionCompleted",
        "GateCompleted",
        "ProbeFailed",
        "ContextWarmed",
        "GatePassed",
        "GateFailed",
        "SpecCommitted",
        "DelegateTaskCompleted",
    }
    assert set(EVENT_REGISTRY.keys()) == expected


def test_event_registry_values_match_class_names():
    """Registry values are the actual event classes, keyed by __name__."""
    assert EVENT_REGISTRY["AgentStarted"] is AgentStarted
    assert EVENT_REGISTRY["SkillCalled"] is SkillCalled
    assert EVENT_REGISTRY["SkillCompleted"] is SkillCompleted
    assert EVENT_REGISTRY["GoalEvaluated"] is GoalEvaluated
    assert EVENT_REGISTRY["LLMTextEmitted"] is LLMTextEmitted
    assert EVENT_REGISTRY["StreamPaused"] is StreamPaused
    assert EVENT_REGISTRY["PipelineStarted"] is PipelineStarted
    assert EVENT_REGISTRY["SubAgentDispatched"] is SubAgentDispatched


# ---------------------------------------------------------------------------
# Event construction — required fields
# ---------------------------------------------------------------------------


def test_each_event_type_can_be_constructed_with_minimal_args():
    """Every event type constructs successfully with only required fields.

    This catches Pydantic validation errors from missing fields or
    incorrect types in the event schema.
    """
    events: list[BaseEvent] = [
        AgentStarted(session_id="s1", goal="test"),
        SkillCalled(session_id="s1", tool_name="read_memory", arguments={}),
        SkillRequested(session_id="s1", skill_name="read_memory", arguments={}),
        SkillCompleted(session_id="s1", status="success", content="ok"),
        SkillCancelled(session_id="s1", call_id="c1", skill_name="read", reason="test"),
        AgentInputAdded(session_id="s1", user_content="hello"),
        LLMActionEmitted(session_id="s1", tokens_used=100, model="gpt-4"),
        StreamPaused(session_id="s1", reason="test"),
        GoalEvaluated(session_id="s1", is_complete=True, reasoning="done"),
        LLMTextEmitted(session_id="s1", content="thinking..."),
        AgentTurnRecorded(session_id="s1", messages_blob=[], ordinal=1),
        SubAgentDispatched(
            session_id="s1", sub_session_id="s2", persona="helper", objective="test"
        ),
        SubAgentCompleted(session_id="s1", sub_session_id="s2", status="success", content="ok"),
        PipelineStarted(session_id="s1", pipeline_name="test", node_count=3),
        PipelineNodeStarted(session_id="s1", node_id="n1", node_type="skill"),
        PipelineNodeCompleted(
            session_id="s1", node_id="n1", status="completed", output_preview="ok"
        ),
        PipelineCompleted(
            session_id="s1",
            pipeline_name="test",
            status="completed",
            duration_s=1.5,
        ),
        WorkflowStarted(session_id="s1", workflow_id="wf1"),
        ProbeCompleted(session_id="s1"),
        ExecutionCompleted(session_id="s1"),
        GateCompleted(session_id="s1"),
        ProbeFailed(session_id="s1"),
        ContextWarmed(session_id="s1"),
        GatePassed(session_id="s1"),
        GateFailed(session_id="s1"),
        SpecCommitted(session_id="s1"),
        DelegateTaskCompleted(session_id="s1"),
    ]
    assert len(events) == len(EVENT_REGISTRY), (
        f"Constructed {len(events)} events, registry has {len(EVENT_REGISTRY)}"
    )
