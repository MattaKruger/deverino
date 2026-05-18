---
name: container_destroy
description: Stops and removes a container. Cleans up the blackboard memory entry.
version: "1.0"
parameters:
  type: object
  properties:
    container:
      type: string
      description: The container name or ID to destroy.
  required:
    - container
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: Container Destroy (System)

## Purpose
Tears down a workflow container — stops it, removes it, and clears the blackboard entry.

## Behavior
1. Resolves the container backend.
2. `<backend> stop <container>` (best-effort, ignores if already stopped).
3. `<backend> rm <container>`.
4. Removes the container entry from blackboard memory.

## Expected Output
Returns a `SkillResult` confirming the container was destroyed.
