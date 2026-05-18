---
name: container_spawn
description: Creates a detached container for the current workflow session. Returns the container name and backend used. Idempotent — if the container already exists, returns it without recreating.
version: "1.0"
parameters:
  type: object
  properties:
    image:
      type: string
      description: Container image to use (defaults to harness.yaml runtime.default_container_image).
    container_name:
      type: string
      description: Name for the container (defaults to harness-<session_id_short>).
  required: []
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: read
---

# Skill: Container Spawn (System)

## Purpose
Creates an ephemeral container for workflow execution. Mounts the project root at /workspace.

## Behavior
1. Resolves the container backend (podman → docker auto-detect).
2. Generates a name from the session ID if none provided.
3. Checks if the container already exists (idempotent).
4. If not: `<backend> run -d --name <name> -v <project_root>:/workspace -w /workspace <image> sleep infinity`.
5. Stores container name in blackboard memory.

## Expected Output
Returns a `SkillResult` with container name, backend, and image.
