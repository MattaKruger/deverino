---
name: inspect_db
type: tool
description: >-
  Run a read-only SQL query against the harness blackboard (PostgreSQL).
  Use this to inspect database state — sessions, events, context maps,
  memory, tokens, skill executions — without leaving the agent context.
  Only SELECT queries are permitted.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    query:
      type: string
      description: >-
        A SELECT-only SQL query to run. Common tables: sessions, events,
        context_map, context_map_events, memory_store, skill_executions,
        token_usage, tool_events. Use EXPLAIN to check query plans.
        Tables are in the public schema.
    limit:
      type: integer
      description: Max rows to return (default 50, max 200).
  required:
    - query
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_only
  workspace: none
---

# Skill: Inspect Database

## Purpose
Execute read-only SQL queries against the PostgreSQL blackboard for debugging
and state inspection. Equivalent to `psql` but available to agents mid-session
without context-switching to a terminal.

## Guardrails

- **SELECT only.** INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE are
  blocked. The skill validates the query before execution.
- **Limit rows.** Default 50, max 200. Use `limit` parameter to adjust.
- **Format results.** Returns JSON array of row objects for programmatic use,
  plus a human-readable table in the content string.
- **Use responsibly.** Don't `SELECT *` from large tables without a WHERE clause
  or LIMIT. The skill enforces a row cap but planning ahead saves tokens.

## Common Queries

| Goal | Query |
|------|-------|
| Active sessions | `SELECT * FROM sessions WHERE status = 'active'` |
| Recent events | `SELECT * FROM events ORDER BY timestamp DESC LIMIT 20` |
| Context map health | `SELECT corpus_key, version, token_count FROM context_map` |
| Pending events | `SELECT corpus_key, count(*) FROM context_map_events WHERE processed = 0 GROUP BY corpus_key` |
| Memory keys | `SELECT key, length(value::text) as size FROM memory_store WHERE session_id = '...'` |
| Skill failures | `SELECT * FROM events WHERE event_type = 'SkillFailed' ORDER BY timestamp DESC LIMIT 10` |
