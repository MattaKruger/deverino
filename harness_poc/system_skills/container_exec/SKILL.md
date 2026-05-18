---
name: container_exec
description: Executes a shell command inside a container (Podman, Docker, or auto-detected backend). The container must already exist — use container_spawn first.
version: "1.0"
parameters:
  type: object
  properties:
    command:
      type: string
      description: The shell command to execute inside the container.
    container:
      type: string
      description: The target container name or ID.
    backend:
      type: string
      description: Container runtime to use. One of 'podman', 'docker', or 'auto' (default).
      enum:
        - podman
        - docker
        - auto
    workdir:
      type: string
      description: Optional working directory inside the container (relative to /workspace).
  required:
    - command
    - container
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: none
  workspace: none
---

# Skill: Container Exec (System)

## Purpose
Run commands inside an existing container. The container should be created by `container_spawn` first.

## Behavior
1. Resolves the container backend (auto-detect or explicit).
2. Invokes `<backend> exec -w <workdir> <container> sh -c <command>`.
3. Captures and returns stdout, stderr, and exit code.

## Expected Output
Returns a `SkillResult` with the command output, exit code, and backend used.
