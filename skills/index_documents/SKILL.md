---
name: index_documents
type: tool
description: Index project documents into Vespa for semantic and hybrid search.
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    paths:
      type: array
      items:
        type: string
      description: Files or directories to index, relative to the project root.
    glob:
      type: string
      description: Optional glob used when a path is a directory.
      default: "**/*"
    exclude_dirs:
      type: array
      items:
        type: string
      description: Directories to skip while indexing, relative to the project root.
      default: []
    force:
      type: boolean
      description: Reindex sources even when their content hash has not changed.
      default: false
  required:
    - paths
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: read
---

# Skill: Index Documents

## Purpose
Index project files into the configured retrieval backend.
