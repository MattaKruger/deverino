from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text as sql_text

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext
_SESSION_QUERY = """
    SELECT session_id, global_objective, status, created_at, active_corpus_key
    FROM sessions WHERE session_id = :sid
"""

_EVENTS_QUERY = """
    SELECT
        e.id, e.event_type, e.created_at,
        coalesce(e.payload->'payload'->>'tool_name', '') as target_name,
        e.event_type IN ('SkillCalled', 'SkillCompleted') as is_skill,
        coalesce(e.payload->'payload'->>'status', '') as status,
        coalesce((e.payload->'payload'->>'tokens_used')::int, 0) as tokens_used,
        coalesce(
            nullif(e.payload->'payload'->>'content', ''),
            nullif(e.payload->'payload'->>'result', ''),
            nullif(e.payload->'payload'->>'goal', ''),
            nullif(e.payload->'payload'->>'reason', ''),
            ''
        ) as content
    FROM state_events e
    WHERE e.scope_id = :sid
    ORDER BY e.created_at ASC, e.id ASC
    LIMIT :lim
"""

_MEMORY_QUERY = """
    SELECT memory_key, length(data_payload) as size_bytes, created_at
    FROM shared_memory
    WHERE session_id = :sid
    ORDER BY created_at DESC
    LIMIT 100
"""

_CTX_EVENTS_QUERY = """
    SELECT event_type, corpus_key, timestamp,
           length(payload) as payload_size
    FROM context_map_events
    WHERE session_id = :sid
    ORDER BY timestamp ASC
    LIMIT 50
"""


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    session_id = str(arguments.get("session_id") or "").strip()
    if not session_id:
        return SkillResult(
            status="failed",
            content="Missing required argument: session_id",
            artifacts={},
        )

    include_memory = bool(arguments.get("include_memory", False))
    limit_events = int(arguments.get("limit_events", 100))
    limit_events = max(1, min(limit_events, 500))

    db = ctx.database._db  # noqa: SLF001
    engine = db._engine  # noqa: SLF001

    trace: dict[str, Any] = {"session_id": session_id}

    # 1. Session metadata
    with engine.connect() as conn:
        row = conn.execute(sql_text(_SESSION_QUERY), {"sid": session_id}).mappings().first()

    if row is None:
        return SkillResult(
            status="failed",
            content=f"No session found with id '{session_id}'",
            artifacts={"session_id": session_id},
        )

    trace["metadata"] = dict(row)

    # 2. Event timeline
    with engine.connect() as conn:
        events = (
            conn.execute(
                sql_text(_EVENTS_QUERY),
                {"sid": session_id, "lim": limit_events},
            )
            .mappings()
            .all()
        )

    event_list = [dict(e) for e in events]
    trace["event_count"] = len(event_list)
    trace["events"] = event_list

    # 3. Derived summaries
    skill_calls = [e for e in event_list if e.get("is_skill") and e.get("target_name")]
    tool_calls = [e for e in event_list if not e.get("is_skill") and e.get("target_name")]
    errors = [e for e in event_list if e.get("status") in ("failed", "error")]

    total_tokens = sum(e.get("tokens_used", 0) or 0 for e in event_list)

    trace["summary"] = {
        "total_events": len(event_list),
        "skill_calls": len(skill_calls),
        "tool_calls": len(tool_calls),
        "errors": len(errors),
        "total_tokens": total_tokens,
        "skills": _summarize_skills(skill_calls),
        "tools": _summarize_tools(tool_calls),
        "error_log": [
            {
                "event_type": e.get("event_type"),
                "target_name": e.get("target_name"),
                "content": _truncate(e.get("content", ""), 300),
            }
            for e in errors
        ],
    }

    # 4. Memory entries (optional)
    if include_memory:
        with engine.connect() as conn:
            mem_rows = conn.execute(sql_text(_MEMORY_QUERY), {"sid": session_id}).mappings().all()
        trace["memory_entries"] = [dict(r) for r in mem_rows]
    # 5. Context map events
    with engine.connect() as conn:
        ctx_rows = conn.execute(sql_text(_CTX_EVENTS_QUERY), {"sid": session_id}).mappings().all()
    trace["context_map_events"] = [dict(r) for r in ctx_rows]

    # Build human-readable output
    meta = trace["metadata"]
    summary = trace["summary"]
    lines = [
        f"Session: {session_id}",
        f"  Status:   {meta.get('status', '?')}",
        f"  Goal:     {_truncate(meta.get('global_objective', ''), 120)}",
        f"  Corpus:   {meta.get('active_corpus_key', '')}",
        f"  Created:  {meta.get('created_at', '')}",
        "",
        f"Events:   {summary['total_events']} total",
        f"Skills:   {summary['skill_calls']} calls",
        f"Tools:    {summary['tool_calls']} calls",
        f"Tokens:   {summary['total_tokens']}",
        f"Errors:   {summary['errors']}",
        "",
    ]

    if summary["skills"]:
        lines.append("Skills executed:")
        for s in summary["skills"]:
            status_mark = "✓" if s["status"] == "success" else "✗"
            lines.append(f"  {status_mark} {s['name']} ({s['calls']}×, {s['tokens']} tokens)")
        lines.append("")

    if summary["tools"]:
        lines.append("Tools used:")
        for t in summary["tools"]:
            status_mark = "✓" if t["status"] == "success" else "✗"
            lines.append(f"  {status_mark} {t['name']} ({t['calls']}×)")
        lines.append("")

    if summary["error_log"]:
        lines.append("Errors:")
        for err in summary["error_log"]:
            src = err.get("target_name") or err.get("event_type", "?")
            lines.append(f"  ✗ {src}: {err['content'][:120]}")
        lines.append("")

    return SkillResult(
        status="success",
        content="\n".join(lines),
        artifacts=trace,
    )


def _summarize_skills(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for c in calls:
        name = c.get("target_name", "?")
        if name not in groups:
            groups[name] = {"name": name, "calls": 0, "tokens": 0, "status": "success"}
        groups[name]["calls"] += 1
        groups[name]["tokens"] += c.get("tokens_used", 0) or 0
        if c.get("status") in ("failed", "error"):
            groups[name]["status"] = "failed"
    return sorted(groups.values(), key=lambda x: x["calls"], reverse=True)


def _summarize_tools(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for c in calls:
        name = c.get("target_name", "?")
        if name not in groups:
            groups[name] = {"name": name, "calls": 0, "status": "success"}
        groups[name]["calls"] += 1
        if c.get("status") in ("failed", "error"):
            groups[name]["status"] = "failed"
    return sorted(groups.values(), key=lambda x: x["calls"], reverse=True)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
