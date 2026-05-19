---
name: execute_python
description: Executes Python code inside a session-scoped container for scratchpad analysis, hypothesis testing, and data inspection.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    code:
      type: string
      description: Python source code to execute inside the container.
    container:
      type: string
      description: Optional existing container name or ID. If omitted, a session-scoped container is created or reused.
    image:
      type: string
      description: Optional container image for the session container. Defaults to runtime.default_container_image.
    workdir:
      type: string
      description: Optional working directory inside /workspace.
      default: ""
    timeout_seconds:
      type: integer
      description: Optional execution timeout in seconds (default 30, max 300).
      default: 30
  required:
    - code
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: read_write
---

# Skill: Execute Python (System)

## Purpose
Run Python code in a container-backed scratchpad. This is intended for skills and agents to test hypotheses, inspect data, run small calculations, and prototype snippets without executing arbitrary Python on the host.

## Behavior
1. Validates that `code` is present.
2. Creates or reuses a session-scoped container when `container` is omitted.
3. Encodes the provided code as base64 and executes it through `container_exec`.
4. Returns stdout, stderr, exit code, backend, and container metadata.

## Expected Output
Returns a `SkillResult` with `status` set to `"success"` when Python exits 0, or `"failed"` for validation, container, timeout, or non-zero execution failures.
