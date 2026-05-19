from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def event_type(self) -> str:
        return self.__class__.__name__


class AgentStarted(BaseEvent):
    goal: str


class SkillCalled(BaseEvent):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SkillCompleted(BaseEvent):
    tool_name: str
    status: str
    content: str
    artifacts: dict[str, Any] = Field(default_factory=dict)


class GoalEvaluated(BaseEvent):
    is_complete: bool
    reasoning: str
    final_answer: str = ""


class LLMTextEmitted(BaseEvent):
    content: str


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
        SkillCompleted,
        GoalEvaluated,
        LLMTextEmitted,
        SubAgentDispatched,
        SubAgentCompleted,
        PipelineStarted,
        PipelineNodeStarted,
        PipelineNodeCompleted,
        PipelineCompleted,
    ]
}
