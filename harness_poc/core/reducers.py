from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite
import polars as pl

from harness_poc.core.database import BlackboardDatabase

SNAPSHOT_HISTORY_LIMIT = 20


async def derive_session_state(
    db: BlackboardDatabase | Path | str,
    session_id: str,
) -> dict[str, Any]:
    db_path = _database_path(db)

    async with aiosqlite.connect(db_path) as connection:
        connection.row_factory = aiosqlite.Row
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_snapshots (
                session_id TEXT PRIMARY KEY,
                last_offset INTEGER NOT NULL,
                state_payload TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        snapshot = await _fetch_snapshot(connection, session_id)
        last_offset = int(snapshot.get("last_offset", 0))
        state = _initial_state(snapshot.get("state_payload"))

        cursor = await connection.execute(
            """
            SELECT id, event_type, payload, created_at
            FROM state_events
            WHERE scope = 'session'
              AND scope_id = ?
              AND id > ?
            ORDER BY id ASC
            """,
            (session_id, last_offset),
        )
        event_rows = await cursor.fetchall()

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
                [str(status) for status in statuses],
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
            last_offset = max(int(event["id"]) for event in events)

        state["last_offset"] = last_offset
        await connection.execute(
            """
            INSERT INTO session_snapshots (
                session_id,
                last_offset,
                state_payload,
                updated_at
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                last_offset = excluded.last_offset,
                state_payload = excluded.state_payload,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session_id, last_offset, json.dumps(state, sort_keys=True)),
        )
        await connection.commit()

    return state


def _database_path(db: BlackboardDatabase | Path | str) -> Path:
    if isinstance(db, BlackboardDatabase):
        return db.database_path
    return Path(db)


async def _fetch_snapshot(
    connection: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any]:
    cursor = await connection.execute(
        """
        SELECT last_offset, state_payload
        FROM session_snapshots
        WHERE session_id = ?
        """,
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return {}
    return {
        "last_offset": row["last_offset"],
        "state_payload": row["state_payload"],
    }


def _initial_state(payload: object) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = {}
        if isinstance(decoded, dict):
            return decoded

    return {
        "total_tokens": 0,
        "consecutive_skill_failures": 0,
        "recent_message_history": [],
        "stream_paused": False,
    }


def _normalise_event_row(row: aiosqlite.Row) -> dict[str, Any]:
    outer = _decode_object(str(row["payload"]))
    payload_obj = outer.get("payload")
    payload = payload_obj if isinstance(payload_obj, dict) else outer
    event_type = str(outer.get("event_type") or row["event_type"])
    return {
        "id": int(row["id"]),
        "event_type": event_type,
        "created_at": str(row["created_at"]),
        "tokens_used": int(payload.get("tokens_used", 0)),
        "status": str(payload.get("status", "")),
        "skill_name": str(payload.get("skill_name") or payload.get("tool_name") or ""),
        "user_content": str(payload.get("user_content", "")),
        "content": str(payload.get("content") or payload.get("result") or ""),
        "reason": str(payload.get("reason", "")),
        "threshold_breached": str(payload.get("threshold_breached", "")),
    }


def _decode_object(payload: str) -> dict[str, Any]:
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


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
