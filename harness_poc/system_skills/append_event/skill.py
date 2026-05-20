from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.context_map_events import EVENT_REGISTRY
from harness_poc.core.skill_context import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skill_context import SkillContext


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    event_type = str(arguments.get("event_type") or "").strip()
    corpus_key = str(arguments.get("corpus_key") or "").strip()
    payload = arguments.get("payload")

    if not event_type:
        return SkillResult(
            status="failed",
            content="Missing required argument: event_type",
            artifacts={},
        )
    if not corpus_key:
        return SkillResult(
            status="failed",
            content="Missing required argument: corpus_key",
            artifacts={},
        )
    if not isinstance(payload, dict):
        return SkillResult(status="failed", content="payload must be a JSON object", artifacts={})

    cls = EVENT_REGISTRY.get(event_type)
    if cls is None:
        return SkillResult(
            status="failed",
            content=f"Unknown event_type: {event_type!r}. Valid types: {sorted(EVENT_REGISTRY)}",
            artifacts={},
        )

    try:
        event = cls.model_validate(
            {
                **payload,
                "event_type": event_type,
                "corpus_key": corpus_key,
                "session_id": ctx.session_id,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return SkillResult(status="failed", content=f"Invalid payload: {exc}", artifacts={})

    ctx.database.append_context_map_event(event)

    return SkillResult(
        status="success",
        content=f"Event {event.event_id} ({event_type}) appended to {corpus_key}.",
        artifacts={"event_id": event.event_id, "corpus_key": corpus_key},
    )
