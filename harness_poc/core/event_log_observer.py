from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

if TYPE_CHECKING:
    from sqlalchemy import Engine

from harness_poc.core.models import DbStateEvent


@dataclass(frozen=True, slots=True)
class EventLogRow:
    id: int
    session_id: str
    event_type: str
    created_at: str
    payload: dict[str, Any]


def fetch_event_log_rows(
    engine: Engine,
    *,
    after_id: int = 0,
    session_id: str | None = None,
    event_types: list[str] | None = None,
    limit: int | None = None,
) -> list[EventLogRow]:
    if limit is not None and limit < 1:
        msg = "limit must be greater than zero"
        raise ValueError(msg)

    with Session(engine) as session:
        stmt = select(DbStateEvent).where(DbStateEvent.id > after_id)  # type: ignore[operator]
        if session_id:
            stmt = stmt.where(DbStateEvent.scope_id == session_id)
        if event_types:
            stmt = stmt.where(DbStateEvent.event_type.in_(event_types))
        stmt = stmt.order_by(DbStateEvent.id.asc())  # type: ignore[arg-type]
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = session.exec(stmt).all()

    return [_to_event_log_row(row) for row in rows]


def fetch_latest_event_log_rows(
    engine: Engine,
    *,
    session_id: str | None = None,
    event_types: list[str] | None = None,
    limit: int = 50,
) -> list[EventLogRow]:
    if limit < 1:
        msg = "limit must be greater than zero"
        raise ValueError(msg)

    with Session(engine) as session:
        stmt = select(DbStateEvent)
        if session_id:
            stmt = stmt.where(DbStateEvent.scope_id == session_id)
        if event_types:
            stmt = stmt.where(DbStateEvent.event_type.in_(event_types))
        stmt = stmt.order_by(DbStateEvent.id.desc()).limit(limit)  # type: ignore[arg-type]
        rows = session.exec(stmt).all()

    return [_to_event_log_row(row) for row in reversed(rows)]


def render_event_log_row(
    row: EventLogRow,
    *,
    include_payload: bool = True,
    json_output: bool = False,
) -> str:
    if json_output:
        return json.dumps(_row_to_dict(row, include_payload=True), sort_keys=True)

    summary = _event_summary(row).strip()
    line = f"{row.id:06d} {row.created_at} {row.session_id} {row.event_type}"
    if not include_payload:
        summary_suffix = f" {summary}" if summary else ""
        return f"{line}{summary_suffix}"

    payload = json.dumps(row.payload, ensure_ascii=False, indent=2, sort_keys=True)
    payload_lines = "\n".join(f"    {pl}" for pl in payload.splitlines())
    header_lines = [
        f"{row.id:06d} {row.event_type}",
        f"  created_at: {row.created_at}",
        f"  session_id: {row.session_id}",
    ]
    if summary:
        header_lines.append(f"  summary: {summary}")
    return "\n".join([*header_lines, "  payload:", payload_lines])


def _to_event_log_row(row: DbStateEvent) -> EventLogRow:
    outer = row.payload  # already a dict from JSON/JSONB column
    inner = outer.get("payload")
    payload_dict = inner if isinstance(inner, dict) else outer
    return EventLogRow(
        id=row.id or 0,
        session_id=row.scope_id,
        event_type=row.event_type,
        created_at=str(row.created_at),
        payload=payload_dict,
    )


def _event_summary(row: EventLogRow) -> str:
    payload = row.payload
    if row.event_type == "AgentInputAdded":
        return _format_fields(user_content=_truncate(str(payload.get("user_content", ""))))
    if row.event_type in {"SkillCalled", "SkillRequested", "SkillCompleted"}:
        skill_name = payload.get("skill_name") or payload.get("tool_name") or ""
        status = str(payload.get("status", ""))
        return _format_fields(skill=str(skill_name), status=status)
    if row.event_type == "LLMActionEmitted":
        return _format_fields(
            model=str(payload.get("model", "")),
            tokens=str(payload.get("tokens_used", "")),
        )
    if row.event_type == "LLMTextEmitted":
        return _format_fields(content=_truncate(str(payload.get("content", ""))))
    if row.event_type == "StreamPaused":
        return _format_fields(
            reason=str(payload.get("reason", "")),
            threshold=str(payload.get("threshold_breached", "")),
        )
    return ""


def _format_fields(**fields: str) -> str:
    parts = [f"{key}={value}" for key, value in fields.items() if value]
    return f" {' '.join(parts)}" if parts else ""


def _truncate(value: str, max_length: int = 80) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3]}..."


def _row_to_dict(row: EventLogRow, *, include_payload: bool) -> dict[str, Any]:
    output: dict[str, Any] = {
        "id": row.id,
        "session_id": row.session_id,
        "event_type": row.event_type,
        "created_at": row.created_at,
    }
    if include_payload:
        output["payload"] = row.payload
    return output
