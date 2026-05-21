from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class BaseEvent(BaseModel):
    id: int | None = None
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
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


EVENT_REGISTRY: dict[str, type[BaseEvent]] = {
    cls.__name__: cls  # type: ignore[misc]
    for cls in [
        AgentStarted,
        SkillCalled,
        SkillRequested,
        SkillCompleted,
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
    ]
}
