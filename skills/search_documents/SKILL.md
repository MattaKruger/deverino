---
name: search_documents
type: tool
description: >-
  Search indexed project documents with keyword, semantic, or hybrid retrieval.
  By default returns a compact preview so the user can choose which results to
  load into context. Pass expand with 1-based result indices to load full
  excerpts for those results.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query.
    hits:
      type: integer
      description: Maximum chunks to return.
      default: 8
    mode:
      type: string
      description: Retrieval mode.
      enum:
        - hybrid
        - semantic
        - keyword
      default: hybrid
    source_id:
      type: string
      description: Optional source filter.
    kind:
      type: string
      description: Optional document kind filter.
    expand:
      type: array
      items:
        type: integer
      description: >-
        1-based indices of results to load with full excerpts. When omitted the
        skill returns a compact preview and asks the user which results to load.
        When provided (e.g. [1, 3]) the skill re-runs the search and returns
        full excerpts for only those results.
  required:
    - query
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---

# Skill: Search Documents

## Purpose
Search previously indexed project documents.

## Behavior

- **Preview mode (no `expand`):** Returns a compact list with short excerpts
  and asks the user which results to load. Status: `needs_orchestrator_action`.
- **Expand mode (`expand: [1, 3]`):** Re-runs the same search and returns full
  excerpts only for the selected indices. Status: `success`.
