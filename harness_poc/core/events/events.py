from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class BaseEvent(BaseModel):
    id: int | None = None
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    type_name: str = ""

    @model_validator(mode="after")
    def _populate_type_name(self) -> BaseEvent:
        if not self.type_name:
            self.type_name = self.__class__.__name__
        return self

    @property
    def event_type(self) -> str:
        return self.__class__.__name__


class AgentStarted(BaseEvent):
    goal: str


class SkillCalled(BaseEvent):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SkillRequested(BaseEvent):
    skill_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SkillCompleted(BaseEvent):
    tool_name: str = ""
    status: str
    content: str = ""
    artifacts: dict[str, Any] = Field(default_factory=dict)
    skill_name: str = ""
    result: str = ""

    @model_validator(mode="after")
    def _populate_compat_fields(self) -> SkillCompleted:
        if not self.tool_name and self.skill_name:
            self.tool_name = self.skill_name
        if not self.skill_name and self.tool_name:
            self.skill_name = self.tool_name
        if not self.content and self.result:
            self.content = self.result
        if not self.result and self.content:
            self.result = self.content
        return self


class SkillCancelled(BaseEvent):
    call_id: str
    skill_name: str
    reason: str


class AgentInputAdded(BaseEvent):
    user_content: str


class LLMActionEmitted(BaseEvent):
    tokens_used: int
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    billable_tokens: int = 0
    new_tokens: int = 0

    @model_validator(mode="after")
    def _populate_token_fields(self) -> LLMActionEmitted:
        if not self.new_tokens:
            self.new_tokens = self.tokens_used
        if not self.billable_tokens:
            self.billable_tokens = self.tokens_used
        return self


class StreamPaused(BaseEvent):
    reason: str
    threshold_breached: str = ""


class GoalEvaluated(BaseEvent):
    is_complete: bool
    reasoning: str
    final_answer: str = ""


class LLMTextEmitted(BaseEvent):
    content: str


class AgentTurnRecorded(BaseEvent):
    messages_blob: list[dict[str, Any]] = Field(default_factory=list)
    ordinal: int = 0


class SubAgentDispatched(BaseEvent):
    sub_session_id: str
    persona: str
    objective: str


class SubAgentCompleted(BaseEvent):
    sub_session_id: str
    status: str
    content: str


class PipelineStarted(BaseEvent):
    pipeline_name: str
    node_count: int


class PipelineNodeStarted(BaseEvent):
    node_id: str
    node_type: str  # "skill" | "agent"


class PipelineNodeCompleted(BaseEvent):
    node_id: str
    status: str  # "completed" | "failed" | "skipped"
    output_preview: str


class PipelineCompleted(BaseEvent):
    pipeline_name: str
    status: str  # "completed" | "failed"
    duration_s: float


# ---------------------------------------------------------------------------
# V2 pipeline mode events (unified — replaces v2/events.py string constants)
# ---------------------------------------------------------------------------


class WorkflowStarted(BaseEvent):
    """Published by the orchestrator to kick off a pipeline run."""

    workflow_id: str
    goal: str = ""
    persona_id: str = ""
    probe_code: str | None = None
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    workspace_path: str | None = None


class ProbeCompleted(BaseEvent):
    """Published by PipelineStepRunner after the probe step."""

    workflow_id: str = ""
    probe_id: str | None = None
    success: bool = True
    exit_code: int = 0
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    workspace_path: str | None = None


class ExecutionCompleted(BaseEvent):
    """Published by PipelineStepRunner after the execution step."""

    workflow_id: str = ""
    execution_id: str | None = None
    sub_agents: list[dict[str, Any]] = Field(default_factory=list)
    all_passed: bool = True
    workspace_path: str | None = None


class GateCompleted(BaseEvent):
    """Published by PipelineStepRunner after the gate step."""

    workflow_id: str = ""
    gate_id: str | None = None
    passed: bool = True
    test_count: int = 0


class ProbeFailed(BaseEvent):
    """Published by ContextEngine when a probe discovers constraints."""

    team_member: str = "orchestrator"
    execution_error: dict[str, Any] = Field(default_factory=dict)
    extracted_constraints: list[dict[str, Any]] = Field(default_factory=list)


class ContextWarmed(BaseEvent):
    """Published by ContextEngine after warming context from a failure."""

    team_member: str = "orchestrator"
    constraint_count: int = 0
    probe_event_id: str = ""


class GatePassed(BaseEvent):
    """Published by ExecutionEngine when the deterministic gate passes."""

    team_member: str = "execution_engine"
    passed: bool = True
    detail: str = ""
    project_id: str = ""


class GateFailed(BaseEvent):
    """Published by ExecutionEngine when the deterministic gate fails."""

    team_member: str = "execution_engine"
    passed: bool = False
    detail: str = ""
    project_id: str = ""


class SpecCommitted(BaseEvent):
    """Published by WorkflowOrchestrator after spec execution completes."""

    team_member: str = "orchestrator"
    execution_id: str = ""
    task_count: int = 0
    failure_count: int = 0
    all_passed: bool = False


class DelegateTaskCompleted(BaseEvent):
    """Published by the delegate_task handler on completion."""

    task_id: str = ""
    output_label: str = ""
    summary: str = ""


EVENT_REGISTRY: dict[str, type[BaseEvent]] = {
    cls.__name__: cls  # type: ignore[misc]
    for cls in [
        AgentStarted,
        SkillCalled,
        SkillRequested,
        SkillCompleted,
        SkillCancelled,
        AgentInputAdded,
        LLMActionEmitted,
        StreamPaused,
        GoalEvaluated,
        LLMTextEmitted,
        AgentTurnRecorded,
        SubAgentDispatched,
        SubAgentCompleted,
        PipelineStarted,
        PipelineNodeStarted,
        PipelineNodeCompleted,
        PipelineCompleted,
        WorkflowStarted,
        ProbeCompleted,
        ExecutionCompleted,
        GateCompleted,
        ProbeFailed,
        ContextWarmed,
        GatePassed,
        GateFailed,
        SpecCommitted,
        DelegateTaskCompleted,
    ]
}
