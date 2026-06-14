---
name: trace_session
type: tool
description: >-
  Trace the full execution chain for a session: metadata, event timeline,
  skill calls, tool invocations, token usage, and memory entries.
  Use this to understand what happened in a session without piecing
  together raw SQL queries.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    session_id:
      type: string
      description: The session UUID to trace.
    include_memory:
      type: boolean
      description: Include memory store entries in the trace (default false).
    limit_events:
      type: integer
      description: Max events to return from the timeline (default 100).
  required:
    - session_id
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_only
  workspace: none
---

# Skill: Trace Session

## Purpose
Produce a structured timeline of everything that happened in a session:
when it started, what skills and tools ran, what LLM calls were made,
how many tokens were consumed, and what errors occurred. The output
is a JSON trace artifact plus a human-readable summary.

## Output Sections

1. **Session metadata** — objective, status, corpus, created_at
2. **Event timeline** — ordered event list with type, timestamp, delta
3. **Skill execution summary** — each skill call with status, tokens, duration
4. **Tool invocation summary** — each tool call with status
5. **Error log** — all failures in the session
6. **Memory entries** (optional) — keys and sizes
7. **Context map events** — observations recorded during the session
