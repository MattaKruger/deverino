from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text as sql_text

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext

_MAX_DAYS = 90
_DEFAULT_DAYS = 7
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20

_AGG_QUERY = """
    SELECT
        coalesce(e.payload->'payload'->>'skill_name', '') as skill_name,
        coalesce(e.payload->'payload'->>'tool_name', '') as tool_name,
        e.event_type,
        count(*) as error_count,
        min(e.created_at) as first_seen,
        max(e.created_at) as last_seen
    FROM state_events e
    WHERE e.scope = 'session'
      AND e.created_at >= (now() - (:days || ' days')::interval)::text
      AND (
          e.event_type ILIKE '%' || :pattern || '%'
          OR e.payload->'payload'->>'skill_name' ILIKE '%' || :pattern || '%'
          OR e.payload->'payload'->>'tool_name' ILIKE '%' || :pattern || '%'
          OR e.payload->'payload'->>'content' ILIKE '%' || :pattern || '%'
          OR e.payload->'payload'->>'result' ILIKE '%' || :pattern || '%'
      )
      AND (
          e.event_type ILIKE '%fail%'
          OR e.event_type ILIKE '%error%'
          OR e.payload->'payload'->>'status' IN ('failed', 'error')
      )
    GROUP BY 1, 2, 3
    ORDER BY error_count DESC, last_seen DESC
    LIMIT :agg_limit
"""

_DETAIL_QUERY = """
    SELECT
        e.id, e.event_type, e.created_at, e.scope_id as session_id,
        coalesce(e.payload->'payload'->>'skill_name', '') as skill_name,
        coalesce(e.payload->'payload'->>'tool_name', '') as tool_name,
        coalesce(e.payload->'payload'->>'status', '') as status,
        coalesce(
            nullif(e.payload->'payload'->>'content', ''),
            nullif(e.payload->'payload'->>'result', ''),
            nullif(e.payload->'payload'->>'reason', ''),
            ''
        ) as message
    FROM state_events e
    WHERE e.scope = 'session'
      AND e.created_at >= (now() - (:days || ' days')::interval)::text
      {extra_clause}
      AND e.event_type IN ({event_types})
    ORDER BY e.created_at DESC
    LIMIT :detail_limit
"""


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    pattern = str(arguments.get("pattern") or "").strip()
    event_type = str(arguments.get("event_type") or "").strip()
    skill_name = str(arguments.get("skill_name") or "").strip()
    days = int(arguments.get("days", _DEFAULT_DAYS))
    limit = int(arguments.get("limit", _DEFAULT_LIMIT))

    days = max(1, min(days, _MAX_DAYS))
    limit = max(1, min(limit, _MAX_LIMIT))

    if not pattern and not event_type and not skill_name:
        return SkillResult(
            status="failed",
            content="At least one filter is required: pattern, event_type, or skill_name",
            artifacts={},
        )

    db = ctx.database._db  # noqa: SLF001
    engine = db._engine  # noqa: SLF001
    # Build the detail filter clause
    extra_parts = []
    detail_event_types: list[str] = []
    params: dict[str, Any] = {
        "days": str(days),
        "pattern": pattern or "",
        "agg_limit": min(limit * 3, _MAX_LIMIT),
        "detail_limit": limit,
    }

    if event_type:
        detail_event_types.append(event_type)
    if skill_name:
        extra_parts.append("AND e.payload->'payload'->>'skill_name' = :skill_name")
        params["skill_name"] = skill_name

    # If no specific event_type, search all failure types
    if not detail_event_types:
        detail_event_types = [
            "SkillFailed",
            "ToolErrored",
            "GoalFailed",
            "PipelineFailed",
            "WorkflowFailed",
            "MaterializationFailed",
            "AgentFailed",
            "ErrorObserved",
        ]

    # Also add pattern-based search to detail if no specific type/skill
    if pattern and not event_type and not skill_name:
        extra_parts.append(
            "AND ("
            "  e.event_type ILIKE '%' || :pattern || '%'"
            "  OR e.payload->'payload'->>'skill_name' ILIKE '%' || :pattern || '%'"
            "  OR e.payload->'payload'->>'tool_name' ILIKE '%' || :pattern || '%'"
            "  OR e.payload->'payload'->>'content' ILIKE '%' || :pattern || '%'"
            "  OR e.payload->'payload'->>'result' ILIKE '%' || :pattern || '%'"
            ")"
        )

    extra_clause = "\n      ".join(extra_parts)
    event_type_placeholders = ", ".join(f":et{i}" for i in range(len(detail_event_types)))
    for i, et in enumerate(detail_event_types):
        params[f"et{i}"] = et

    # 1. Aggregated error stats
    with engine.connect() as conn:
        agg_rows = conn.execute(sql_text(_AGG_QUERY), params).mappings().all()

    # 2. Detailed recent errors
    detail_sql = _DETAIL_QUERY.format(
        extra_clause=extra_clause,
        event_types=event_type_placeholders,
    )

    with engine.connect() as conn:
        detail_rows = conn.execute(sql_text(detail_sql), params).mappings().all()

    # Build output
    agg_list = [dict(r) for r in agg_rows]
    detail_list = [dict(r) for r in detail_rows]

    total_errors = sum(a["error_count"] for a in agg_list)

    lines = [
        f"Error pattern search: '{pattern or event_type or skill_name}'",
        f"  Lookback: {days} days",
        f"  Total matching errors: {total_errors}",
        f"  Groups: {len(agg_list)}",
        "",
    ]

    if agg_list:
        lines.append("By frequency:")
        for a in agg_list[:10]:
            src = a["skill_name"] or a["tool_name"] or a["event_type"]
            lines.append(
                f"  {a['error_count']:>4}×  {src}  "
                f"(first: {a['first_seen'][:19]}, last: {a['last_seen'][:19]})"
            )
        lines.append("")

    if detail_list:
        lines.append(f"Most recent ({len(detail_list)}):")
        for d in detail_list:
            src = d["skill_name"] or d["tool_name"] or d["event_type"]
            msg = _truncate(str(d.get("message", "")), 100)
            lines.append(f"  [{d['created_at'][:19]}] {src} | {d['session_id'][:8]}... | {msg}")

    return SkillResult(
        status="success",
        content="\n".join(lines),
        artifacts={
            "pattern": pattern,
            "days": days,
            "total_errors": total_errors,
            "aggregated": agg_list,
            "recent": detail_list,
        },
    )


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
