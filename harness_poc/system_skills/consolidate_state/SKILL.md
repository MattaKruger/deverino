---
name: consolidate_state
description: Preview, propose, or approve consolidation of the current session STATE into durable project STATE.
version: "1.0"
parameters:
  type: object
  properties:
    mode:
      type: string
      description: Consolidation mode. preview returns current session state; propose creates a pending proposal; approve creates and approves a proposal.
      enum:
        - preview
        - propose
        - approve
    project_id:
      type: string
      description: Project state id to approve into. Defaults to default.
  required: []
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: Consolidate State (System)

## Purpose
Move compact session STATE into durable project STATE using the existing proposal model.

## Behavior
1. Reads current session STATE.
2. In `preview` mode, returns the pending session STATE without mutating project STATE.
3. In `propose` mode, creates a pending state proposal.
4. In `approve` mode, creates a proposal and immediately approves it into project STATE.

## Expected Output
Returns a `SkillResult` with the selected mode, proposal id when applicable, and markdown for the relevant state payload.
