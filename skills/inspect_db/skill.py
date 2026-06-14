from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import text as sql_text

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext

_MAX_ROWS = 200
_DEFAULT_ROWS = 50
_MAX_COL_WIDTH = 60
_DISPLAY_ROW_LIMIT = 25
_VALUE_TRUNCATE_AT = 200

# Block any statement that could modify data or schema
_BLOCKED_PREFIXES = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|VACUUM|"
    r"ANALYZE|REINDEX|CLUSTER|DISCARD|LISTEN|NOTIFY|UNLISTEN|COPY|CALL|SET|PREPARE|"
    r"DEALLOCATE|LOCK|REFRESH|MOVE|FETCH|CLOSE|DECLARE)",
    re.IGNORECASE,
)


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return SkillResult(
            status="failed",
            content="Missing required argument: query",
            artifacts={},
        )

    # Safety: block non-SELECT statements
    if _BLOCKED_PREFIXES.match(query):
        return SkillResult(
            status="failed",
            content="Only SELECT queries are allowed. Query starts with a blocked keyword.",
            artifacts={"blocked_query": query[:200]},
        )

    # Force read-only transaction
    if not query.lstrip().upper().startswith("SELECT") and not query.lstrip().upper().startswith(
        "EXPLAIN"
    ):
        return SkillResult(
            status="failed",
            content="Only SELECT and EXPLAIN queries are allowed.",
            artifacts={"blocked_query": query[:200]},
        )

    limit = int(arguments.get("limit", _DEFAULT_ROWS))
    limit = max(1, min(limit, _MAX_ROWS))

    # Append LIMIT if not present and not an EXPLAIN
    if "LIMIT" not in query.upper() and not query.lstrip().upper().startswith("EXPLAIN"):
        query = f"{query.rstrip(';').rstrip()} LIMIT {limit}"
    db = ctx.database._db  # noqa: SLF001 — proxy wraps BlackboardDatabase; need raw engine
    engine = db._engine  # noqa: SLF001 — read-only SQL execution

    try:
        with engine.connect() as conn:
            conn.execute(sql_text("SET TRANSACTION READ ONLY"))
            result = conn.execute(sql_text(query))
            if result.returns_rows:
                columns = list(result.keys())
                rows = [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
            else:
                columns = []
                rows = []
    except Exception as exc:
        return SkillResult(
            status="failed",
            content=f"Query failed: {exc}",
            artifacts={"query": query[:500], "error": str(exc)},
        )

    # Build a human-readable table and a clean JSON representation
    json_rows = []
    for row in rows:
        cleaned: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, (bytes, memoryview)):
                cleaned[k] = f"<binary {len(v)} bytes>"
            elif isinstance(v, str) and len(v) > _VALUE_TRUNCATE_AT:
                cleaned[k] = v[:_VALUE_TRUNCATE_AT] + "..."
            else:
                cleaned[k] = v
        json_rows.append(cleaned)

    table_lines = _format_table(columns, json_rows)

    return SkillResult(
        status="success",
        content=f"{len(rows)} row(s):\n{chr(10).join(table_lines)}",
        artifacts={
            "rows": json_rows,
            "columns": columns,
            "row_count": len(rows),
            "truncated": len(rows) >= limit,
        },
    )


def _format_table(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
    """Format rows as a compact aligned table."""
    if not columns or not rows:
        return ["(empty)"]

    # Calculate column widths
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            val = str(row.get(col, ""))
            widths[col] = max(widths[col], min(len(val), _MAX_COL_WIDTH))

    # Header
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    sep = "-+-".join("-" * widths[col] for col in columns)
    lines = [header, sep]

    # Rows (display limit, full in artifacts)
    for row in rows[:_DISPLAY_ROW_LIMIT]:
        vals = []
        for col in columns:
            val = str(row.get(col, ""))
            if len(val) > _MAX_COL_WIDTH:
                val = val[: _MAX_COL_WIDTH - 3] + "..."
            vals.append(val.ljust(widths[col]))
        lines.append(" | ".join(vals))

    if len(rows) > _DISPLAY_ROW_LIMIT:
        lines.append(f"... ({len(rows) - _DISPLAY_ROW_LIMIT} more rows in artifacts)")

    return lines
