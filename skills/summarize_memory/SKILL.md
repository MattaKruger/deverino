---
name: summarize_memory
description: Summarizes a memory key into a compact result
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    memory_key:
      type: string
      description: Memory key to summarize.
  required:
    - memory_key
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read
  workspace: none
---

# Skill: Summarize Memory

## Purpose
Summarizes a memory key into a compact result

## Behavior
1. Reads the requested memory key from the current session blackboard.
2. Produces a compact summary using the configured LLM client.
3. Falls back to deterministic mock summarization when no API key is configured.

## Expected Output
Returns a `SkillResult`.
