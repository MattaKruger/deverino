---
name: context-map-materializer
type: tool
description: >
  Run the Distiller -> Cartographer -> Evictor pipeline for a corpus_key.
  Fetches unprocessed events, calls two LLM passes, and atomically updates the context map.
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    corpus_key:
      type: string
      description: The corpus to materialize, e.g. "deverino:codebase".
    max_event_tokens:
      type: integer
      description: Approximate token budget for event input to the Distiller.
      default: 8000
    token_budget:
      type: integer
      description: Maximum token budget for the context map.
      default: 1024
  required:
    - corpus_key
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: context-map-materializer

Runs the full Distiller -> Cartographer -> Evictor pipeline for one corpus.
Safe to run multiple times; idempotent already-processed events are skipped.
