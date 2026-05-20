---
name: search_documents
type: tool
description: Search indexed project documents with keyword, semantic, or hybrid retrieval.
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
  required:
    - query
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read
  workspace: none
---

# Skill: Search Documents

## Purpose
Search previously indexed project documents.
