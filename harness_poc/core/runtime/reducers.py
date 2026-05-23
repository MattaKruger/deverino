from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import polars as pl
from sqlmodel import Session, col, select

from harness_poc.core.storage import DbSessionSnapshot, DbStateEvent

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from harness_poc.core.storage import BlackboardDatabase

SNAPSHOT_HISTORY_LIMIT = 20


async def derive_session_state(
    db: BlackboardDatabase | Engine,
    session_id: str,
) -> dict[str, Any]:
    engine = db.engine if hasattr(db, "engine") else db  # type: ignore[union-attr]
    return await asyncio.to_thread(_derive_session_state_sync, engine, session_id)


def _derive_session_state_sync(engine: Engine, session_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        snapshot_row = session.get(DbSessionSnapshot, session_id)
        last_offset = int(snapshot_row.last_offset) if snapshot_row else 0
        state = _initial_state(snapshot_row.state_payload if snapshot_row else None)

        event_rows = session.exec(
            select(DbStateEvent)
            .where(DbStateEvent.scope == "session")
            .where(DbStateEvent.scope_id == session_id)
            .where(col(DbStateEvent.id) > last_offset)
            .order_by(col(DbStateEvent.id).asc())
        ).all()

        if event_rows:
            events = [_normalise_event_row(row) for row in event_rows]
            frame = pl.DataFrame(events)
            token_delta = int(frame["tokens_used"].sum())
            statuses = (
                frame.filter(pl.col("event_type") == "SkillCompleted")
                .select("status")
                .to_series()
                .to_list()
            )
            state["total_tokens"] = int(state.get("total_tokens", 0)) + token_delta
            state["consecutive_skill_failures"] = _apply_skill_statuses(
                int(state.get("consecutive_skill_failures", 0)),
                [str(s) for s in statuses],
            )
            state["recent_message_history"] = _recent_history(
                [*state.get("recent_message_history", []), *events],
            )
            paused_events = frame.filter(pl.col("event_type") == "StreamPaused")
            if not paused_events.is_empty():
                latest_pause = paused_events.tail(1).to_dicts()[0]
                state["stream_paused"] = True
                state["pause_reason"] = latest_pause.get("reason", "")
                state["pause_threshold"] = latest_pause.get("threshold_breached", "")
            last_offset = max(int(e["id"]) for e in events)

        state["last_offset"] = last_offset

        now_str = _utc_now()
        existing = session.get(DbSessionSnapshot, session_id)
        if existing is None:
            session.add(
                DbSessionSnapshot(
                    session_id=session_id,
                    last_offset=last_offset,
                    state_payload=state,
                    updated_at=now_str,
                )
            )
        else:
            existing.last_offset = last_offset
            existing.state_payload = state
            existing.updated_at = now_str
        session.commit()

    return state


def _normalise_event_row(row: DbStateEvent) -> dict[str, Any]:
    outer = row.payload  # already a dict from JSONB/JSON column
    payload_obj = outer.get("payload")
    payload = payload_obj if isinstance(payload_obj, dict) else outer
    event_type = str(outer.get("event_type") or row.event_type)
    return {
        "id": row.id or 0,
        "event_type": event_type,
        "created_at": str(row.created_at),
        "tokens_used": int(payload.get("tokens_used", 0)),
        "billable_tokens": int(payload.get("billable_tokens", 0)),
        "input_tokens": int(payload.get("input_tokens", 0)),
        "output_tokens": int(payload.get("output_tokens", 0)),
        "new_tokens": int(payload.get("new_tokens", payload.get("tokens_used", 0))),
        "status": str(payload.get("status", "")),
        "skill_name": str(payload.get("skill_name") or payload.get("tool_name") or ""),
        "user_content": str(payload.get("user_content", "")),
        "content": str(payload.get("content") or payload.get("result") or ""),
        "reason": str(payload.get("reason", "")),
        "threshold_breached": str(payload.get("threshold_breached", "")),
    }


def _initial_state(payload: object) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()}
    return {
        "total_tokens": 0,
        "consecutive_skill_failures": 0,
        "recent_message_history": [],
        "stream_paused": False,
    }


def _apply_skill_statuses(initial_failures: int, statuses: list[str]) -> int:
    failures = initial_failures
    for status in statuses:
        if status == "failed":
            failures += 1
        elif status == "success":
            failures = 0
    return failures


def _recent_history(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return events[-SNAPSHOT_HISTORY_LIMIT:]


def _utc_now() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(tz=UTC).isoformat(timespec="seconds")
