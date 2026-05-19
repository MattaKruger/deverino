from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EventLogRow:
    id: int
    session_id: str
    event_type: str
    created_at: str
    payload: dict[str, Any]


def fetch_event_log_rows(
    database_path: Path | str,
    *,
    after_id: int = 0,
    session_id: str | None = None,
    event_types: list[str] | None = None,
    limit: int | None = None,
) -> list[EventLogRow]:
    if limit is not None and limit < 1:
        msg = "limit must be greater than zero"
        raise ValueError(msg)

    db_path = Path(database_path)
    if not db_path.exists():
        return []

    clauses = ["id > ?"]
    parameters: list[object] = [after_id]
    if session_id:
        clauses.append("scope_id = ?")
        parameters.append(session_id)
    if event_types:
        placeholders = ",".join("?" for _ in event_types)
        clauses.append(f"event_type IN ({placeholders})")
        parameters.extend(event_types)

    limit_clause = ""
    if limit is not None:
        limit_clause = " LIMIT ?"
        parameters.append(limit)

    query = f"""
        SELECT id, scope_id, event_type, payload, created_at
        FROM state_events
        WHERE {" AND ".join(clauses)}
        ORDER BY id ASC
        {limit_clause}
        """  # noqa: S608

    try:
        with sqlite3.connect(db_path, timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, parameters).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: state_events" in str(exc):
            return []
        raise

    return [_decode_row(row) for row in rows]


def fetch_latest_event_log_rows(
    database_path: Path | str,
    *,
    session_id: str | None = None,
    event_types: list[str] | None = None,
    limit: int = 50,
) -> list[EventLogRow]:
    if limit < 1:
        msg = "limit must be greater than zero"
        raise ValueError(msg)

    db_path = Path(database_path)
    if not db_path.exists():
        return []

    clauses: list[str] = []
    parameters: list[object] = []
    if session_id:
        clauses.append("scope_id = ?")
        parameters.append(session_id)
    if event_types:
        placeholders = ",".join("?" for _ in event_types)
        clauses.append(f"event_type IN ({placeholders})")
        parameters.extend(event_types)

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit)
    query = f"""
        SELECT id, scope_id, event_type, payload, created_at
        FROM state_events
        {where_clause}
        ORDER BY id DESC
        LIMIT ?
        """  # noqa: S608

    try:
        with sqlite3.connect(db_path, timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, parameters).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: state_events" in str(exc):
            return []
        raise

    return [_decode_row(row) for row in reversed(rows)]


def render_event_log_row(
    row: EventLogRow,
    *,
    include_payload: bool = True,
    json_output: bool = False,
) -> str:
    if json_output:
        return json.dumps(
            _row_to_dict(row, include_payload=True), sort_keys=True
        )

    summary = _event_summary(row).strip()
    line = f"{row.id:06d} {row.created_at} {row.session_id} {row.event_type}"
    if not include_payload:
        summary_suffix = f" {summary}" if summary else ""
        return f"{line}{summary_suffix}"

    payload = json.dumps(
        row.payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    payload_lines = "\n".join(
        f"    {payload_line}" for payload_line in payload.splitlines()
    )
    header_lines = [
        f"{row.id:06d} {row.event_type}",
        f"  created_at: {row.created_at}",
        f"  session_id: {row.session_id}",
    ]
    if summary:
        header_lines.append(f"  summary: {summary}")
    return "\n".join([*header_lines, "  payload:", payload_lines])


def _decode_row(row: sqlite3.Row) -> EventLogRow:
    outer = _decode_json_object(str(row["payload"]))
    payload = outer.get("payload")
    payload_dict = payload if isinstance(payload, dict) else outer
    return EventLogRow(
        id=int(row["id"]),
        session_id=str(row["scope_id"]),
        event_type=str(row["event_type"]),
        created_at=str(row["created_at"]),
        payload=payload_dict,
    )


def _decode_json_object(raw: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return decoded if isinstance(decoded, dict) else {"raw": decoded}


def _event_summary(row: EventLogRow) -> str:
    payload = row.payload
    if row.event_type == "AgentInputAdded":
        return _format_fields(
            user_content=_truncate(str(payload.get("user_content", "")))
        )
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
        return _format_fields(
            content=_truncate(str(payload.get("content", "")))
        )
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
