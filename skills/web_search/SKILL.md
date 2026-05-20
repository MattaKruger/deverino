---
name: web_search
type: tool
description: Search the web using the LangSearch API. Returns titles, URLs, and descriptions for matching results.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    query:
      type: string
      description: The search query string.
    count:
      type: integer
      description: Number of results to return (max 20, default 5).
      default: 5
    freshness:
      type: string
      description: Time filter for results (noLimit, pastDay, pastWeek, pastMonth, pastYear).
      default: noLimit
    summary:
      type: boolean
      description: Whether to include a summary in the response.
      default: true
  required:
    - query
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: none
  workspace: none
---

# Skill: Web Search

## Purpose
Search the web via the LangSearch API and return structured results.

## Configuration
Set the `LANGSEARCH_API_KEY` environment variable before running.

Get a free API key at: https://langsearch.com

## Behavior
1. Reads `LANGSEARCH_API_KEY` from the environment.
2. Calls `POST https://api.langsearch.com/v1/web-search` with query, count, freshness, and summary params.
3. Returns a `SkillResult` with a human-readable summary and structured artifacts.
4. Falls back to a mock response when no API key is configured.

## Expected Output
Returns a `SkillResult` with:
- `status`: "success" or "failed"
- `content`: Formatted summary of top results
- `artifacts.results`: List of `{title, url, description}` objects
- `artifacts.query`: The original query
