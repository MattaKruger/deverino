---
name: append_event
type: tool
description: Append a typed event to the context map event store for later materialization.
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    event_type:
      type: string
      description: >
        One of: corpus_ingested, document_retrieved, entity_referenced, schema_discovered,
        search_failed, fact_disputed.
    corpus_key:
      type: string
      description: >
        {project_id}:{corpus_name}, e.g. "deverino:codebase".
    payload:
      type: object
      description: Fields required by the event_type (see context_map_events.py).
  required:
    - event_type
    - corpus_key
    - payload
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: append_event

Inserts a structured event into `context_map_events`. The MaterializerRunner
picks it up asynchronously and updates the context map.
