---
name: delegate_task
description: Spawns an independent LLM agent with a specific persona to handle an isolated sub-task. Use this to prevent polluting your main context window with heavy research or specialized repetitive tasks.
version: "1.0"
parameters:
  type: object
  properties:
    persona:
      type: string
      description: The persona to load from the personas directory, such as web_researcher.
    objective:
      type: string
      description: A precise, atomic directive describing what the subagent must achieve.
    memory_key:
      type: string
      description: The shared memory key where the subagent result should be stored.
    context:
      type: string
      description: Optional variables, raw data, or prior conversation history the subagent needs.
  required:
    - persona
    - objective
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: Delegate Task (System)

## Purpose
Spawn a sub-agent loop using a persona template from the workspace personas directory.
Results are stored in the shared SQLite blackboard under the provided memory key.

## Behavior
1. Load the requested persona template from the personas directory.
2. Mock a read-only subagent execution.
3. Store the result in shared memory.

## Expected Output
Returns a `SkillResult` with the memory key and subagent result.
