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
Creates an ephemeral container for workflow execution. Mounts the project root at `/workspace`
read-only and a session scratch directory at `/scratch` (read-write). Environment variables
TMPDIR, TMP, TEMP, HOME, and PYTHONPYCACHEPREFIX are set to `/scratch` to ensure all
temporary/cache output is confined to the writable scratch area.

## Behavior
1. Resolves the container backend (podman → docker auto-detect).
2. If the image is not found locally and a `Dockerfile` exists at the project root,
   auto-builds the image with `<backend> build -t <image> .` (5 min timeout).
3. Generates a name from the session ID if none provided.
4. Checks if the container already exists (idempotent).
5. Removes stale harness-owned containers before creating a new one.
6. If not: `<backend> run -d --name <name> -v <project_root>:/workspace:ro -v <scratch>:/scratch:rw -w /workspace -e TMPDIR=/scratch -e TMP=/scratch -e TEMP=/scratch -e HOME=/scratch -e PYTHONPYCACHEPREFIX=/scratch/pycache <image> sleep infinity`.
7. Stores container name in blackboard memory.

## Expected Output
Returns a `SkillResult` with container name, backend, and image.
