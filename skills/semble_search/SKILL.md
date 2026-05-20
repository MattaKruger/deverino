---
name: semble_search
type: tool
description: Search a codebase by describing what code does, or find code related to a specific file/line. Uses the Semble CLI.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    action:
      type: string
      description: Whether to search by description or find code related to a location.
      enum:
        - search
        - find_related
      default: search
    query:
      type: string
      description: Natural language or code query describing what to find.
    file_path:
      type: string
      description: File path to find related code for (required when action is find_related).
    line:
      type: integer
      description: Line number in file_path (required when action is find_related, 1-indexed).
    path:
      type: string
      description: "Local path or git URL to search (default: project root)."
    top_k:
      type: integer
      description: "Number of results to return (default: 5)."
      default: 5
    mode:
      type: string
      description: Search mode.
      enum:
        - hybrid
        - semantic
        - bm25
      default: hybrid
    include_text_files:
      type: boolean
      description: Also index non-code text files (.md, .yaml, .json, etc.).
      default: false
  required:
    - query
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: none
  workspace: read
---

# Skill: Semble Search

## Purpose
Search the codebase using the Semble CLI — find code by describing what it does or find code related to a specific file location.

## Prerequisites
Install Semble: `pip install semble` (or `uv add semble`).

## Behavior
1. Runs `semble search` or `semble find-related` as a subprocess.
2. Captures stdout and returns it as formatted markdown.
3. Falls back to a helpful error message if Semble is not installed.

## Expected Output
Returns a `SkillResult` with:
- `status`: "success" or "failed"
- `content`: Semble output formatted as markdown
- `artifacts.query`: The search query
- `artifacts.results`: Raw stdout lines
