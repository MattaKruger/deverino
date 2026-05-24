---
name: observe
type: tool
description: >-
  Record a structural observation about the project for the context map.
  Use sparingly — only for meaningful discoveries, not every class or function
  you encounter. The observation will be materialized into the context map
  and available in future sessions.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    observation_type:
      type: string
      description: >-
        What kind of observation. Pick the most specific match:
        - "entity": You identified a key class, function, module, or concept
        - "schema": You discovered a data format, config shape, or API contract
        - "dispute": You found a stale or incorrect entry in the current context map
        - "insight": You noticed a non-obvious relationship between components
        - "boundary": You identified something definitively NOT in the codebase
          (missing file, absent feature, undocumented area). Prevents hallucination.
        - "constant": You documented a stable domain constant (config value,
          magic number, fixed name).
        - "result": You recorded a reusable computation or analysis result
          that need not be re-derived.
      enum:
        - entity
        - schema
        - dispute
        - insight
        - boundary
        - constant
        - result
    summary:
      type: string
      description: >-
        One-line summary of the observation. Be specific and cite names/paths.
        Examples: "BlackboardDatabase owns all durable state writes",
        "harness.yaml runtime section has a materializer_poll_interval field",
        "The map entry for /api/search is stale — endpoint moved to /api/v2/search"
    detail:
      type: string
      description: >-
        Why this matters. 2-3 sentences explaining what the agent should
        do differently now that it knows this, or what would go wrong
        without this knowledge.
  required:
    - observation_type
    - summary
    - detail
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: Observe

## Purpose
Record a structural observation that enriches the context map. Unlike the raw
`append_event` tool, this skill has a constrained, opinionated interface
designed to keep the signal-to-noise ratio high.

## Guardrails

- **Call only for meaningful discoveries.** Not every class or function
  warrants an observation. If you've seen it before or it's obvious
  from the project structure, skip it.
- **Be specific.** `summary` must include concrete names, paths, or values.
- **Explain why.** `detail` must describe the impact — what changes in
  behavior because of this observation.

## Event Mapping

| observation_type | ContextMapEvent emitted     |
|------------------|----------------------------|
| entity           | EntityReferenced            |
| schema           | SchemaDiscovered            |
| dispute          | FactDisputed                |
| insight          | ContextualInsightDiscovered |
| boundary         | BoundaryIdentified          |
| constant         | ConstantDocumented          |
| result           | ResultRecorded              |
