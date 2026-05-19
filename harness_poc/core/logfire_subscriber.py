from __future__ import annotations

from typing import TYPE_CHECKING

import logfire

from harness_poc.core.events import (
    AgentStarted,
    GoalEvaluated,
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
    SkillCalled,
    SkillCompleted,
)

if TYPE_CHECKING:
    from harness_poc.core.event_bus import EventBus


def configure_logfire(*, include_content: bool = False) -> None:
    logfire.configure()
    logfire.instrument_pydantic_ai(include_content=include_content)


def wire_logfire(event_bus: EventBus) -> None:
    """Subscribe Logfire handlers to the EventBus. Call configure_logfire() first."""
    event_bus.subscribe(PipelineStarted, _on_pipeline_started)
    event_bus.subscribe(PipelineNodeStarted, _on_node_started)
    event_bus.subscribe(PipelineNodeCompleted, _on_node_completed)
    event_bus.subscribe(PipelineCompleted, _on_pipeline_completed)
    event_bus.subscribe(AgentStarted, _on_agent_started)
    event_bus.subscribe(SkillCalled, _on_skill_called)
    event_bus.subscribe(SkillCompleted, _on_skill_completed)
    event_bus.subscribe(GoalEvaluated, _on_goal_evaluated)


def _on_pipeline_started(event: PipelineStarted) -> None:
    logfire.info(
        "pipeline started",
        pipeline_name=event.pipeline_name,
        node_count=event.node_count,
        session_id=event.session_id,
    )


def _on_node_started(event: PipelineNodeStarted) -> None:
    logfire.info(
        "pipeline node started",
        node_id=event.node_id,
        node_type=event.node_type,
        session_id=event.session_id,
    )


def _on_node_completed(event: PipelineNodeCompleted) -> None:
    logfire.info(
        "pipeline node completed",
        node_id=event.node_id,
        status=event.status,
        output_preview=event.output_preview,
        session_id=event.session_id,
    )


def _on_pipeline_completed(event: PipelineCompleted) -> None:
    logfire.info(
        "pipeline completed",
        pipeline_name=event.pipeline_name,
        status=event.status,
        duration_s=event.duration_s,
        session_id=event.session_id,
    )


def _on_agent_started(event: AgentStarted) -> None:
    logfire.info(
        "agent started",
        goal=event.goal,
        session_id=event.session_id,
    )


def _on_skill_called(event: SkillCalled) -> None:
    logfire.info(
        "skill called",
        tool_name=event.tool_name,
        session_id=event.session_id,
    )


def _on_skill_completed(event: SkillCompleted) -> None:
    logfire.info(
        "skill completed",
        tool_name=event.tool_name,
        status=event.status,
        session_id=event.session_id,
    )


def _on_goal_evaluated(event: GoalEvaluated) -> None:
    logfire.info(
        "goal evaluated",
        is_complete=event.is_complete,
        reasoning=event.reasoning[:200],
        session_id=event.session_id,
    )
