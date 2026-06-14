---
name: find_error_pattern
type: tool
description: >-
  Search the event stream for error patterns matching a query string,
  skill name, or event type. Returns aggregated error counts, first/last
  occurrence times, and the most recent error details. Use this to find
  recurring failures or determine when a regression first appeared.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    pattern:
      type: string
      description: >-
        Substring to search for in error content, skill name, or event type.
        Searches event_type, skill_name, tool_name, and content fields.
    event_type:
      type: string
      description: Filter by exact event_type (e.g. 'SkillFailed', 'ToolErrored').
    skill_name:
      type: string
      description: Filter by exact skill name.
    days:
      type: integer
      description: Look back this many days (default 7, max 90).
    limit:
      type: integer
      description: Max error rows to return (default 20, max 100).
  required:
    - pattern
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_only
  workspace: none
---

# Skill: Find Error Pattern

## Purpose
Quickly identify recurring failures in the harness event stream.
Instead of grepping through logs or running manual SQL, agents can
ask "has this error happened before?" and get a structured answer.

## Use Cases

- **Regressions**: "When did this error first appear?"
- **Recurrence**: "How many times has skill X failed in the past week?"
- **Pattern matching**: "Are there other sessions hitting the same DB deadlock?"
- **Root cause**: "What's the most common error in the last 24 hours?"

## Output

Returns aggregated stats (count, first/last occurrence) plus the most
recent matching error rows with session context.
