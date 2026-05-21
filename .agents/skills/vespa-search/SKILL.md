---
name: vespa-search
description: Search indexed project documents (design docs, papers, specs, plans) via the local Vespa instance. Use this when the user asks about a concept that might be covered in the project's documentation, research papers, or implementation plans. Supports keyword, semantic, and hybrid (combined) retrieval modes.
---

# Vespa Document Search

Search the project's indexed document corpus via the local Vespa instance.

## What's Indexed

The `docs/` directory is automatically indexed into Vespa, including:

- Design specs (`docs/superpowers/specs/`)
- Implementation plans (`docs/superpowers/plans/`)
- Research papers (`docs/papers/`)
- General documentation (`docs/`)
- Other project documents

The corpus currently has ~2,847 document chunks across all sources.

## How to Search

Use `curl` to query the Vespa search API. The schema is `doc_chunk`, namespace is `deverino`.

### Hybrid Search (default — combines keyword BM25 + semantic embedding)

Use this for most queries. It balances exact term matching with semantic understanding:

```bash
curl -s -X POST "http://localhost:8080/search/" \
  -H "Content-Type: application/json" \
  -d '{
    "yql": "select source_id, uri, title, chunk_id, chunk_index, text from doc_chunk where (default contains ({targetHits:100}text(@query)) or ({targetHits:20}nearestNeighbor(embedding,q)))",
    "query": "YOUR SEARCH QUERY HERE",
    "input.query(q)": "embed(@query)",
    "ranking.profile": "hybrid",
    "hits": 8,
    "timeout": "10"
  }' | python3 -m json.tool
```

### Semantic Search (embedding vectors only, via HNSW ANN)

Use when the user's query is conceptual or paraphrased — not looking for exact keyword matches:

```bash
curl -s -X POST "http://localhost:8080/search/" \
  -H "Content-Type: application/json" \
  -d '{
    "yql": "select source_id, uri, title, chunk_id, chunk_index, text from doc_chunk where ({targetHits:20}nearestNeighbor(embedding,q))",
    "query": "YOUR SEARCH QUERY HERE",
    "input.query(q)": "embed(@query)",
    "ranking.profile": "semantic",
    "hits": 8,
    "timeout": "10"
  }' | python3 -m json.tool
```

### Keyword Search (BM25 text matching only)

Use when searching for specific terms, error messages, class names, or exact phrases:

```bash
curl -s -X POST "http://localhost:8080/search/" \
  -H "Content-Type: application/json" \
  -d '{
    "yql": "select source_id, uri, title, chunk_id, chunk_index, text from doc_chunk where default contains ({targetHits:100}text(@query))",
    "query": "YOUR SEARCH QUERY HERE",
    "ranking.profile": "keyword",
    "hits": 8,
    "timeout": "10"
  }' | python3 -m json.tool
```

### Filtering by Source or Kind

Add filter clauses to narrow results. The `source_id` is a slug derived from the file path (e.g., `docs-papers-2605-01920-pdf`). The `kind` is one of: `spec`, `plan`, `doc`, `source`.

Add these before the closing `where` clause:

```
and source_id contains "docs-papers-2605-01920-pdf"
and kind contains "spec"
```

Or with parameterized filters (add to the JSON body):

```json
"filter_source_id": "docs-superpowers-specs-2026-05-20-vespa-document-retrieval-design-md",
"filter_kind": "spec"
```

Then reference `@filter_source_id` and `@filter_kind` in the YQL.

### Adjusting Result Count

Change `"hits": 8` to any number. For a broad exploration, use 15–20; for focused lookups, use 3–5.

## Interpreting Results

Each hit contains:

| Field | Description |
|-------|-------------|
| `source_id` | Slug of the source document (e.g., `docs-workflow-runtime-design-md`) |
| `uri` | Relative path to the original file |
| `title` | Document title derived from filename |
| `chunk_id` | Unique chunk identifier |
| `chunk_index` | 0-based position within the document |
| `text` | The chunk's full text content |
| `relevance` | Relevance score (higher = better match) |

## Presenting Results to the User

When showing search results:

1. **Summarize**: State how many total matches were found (`totalCount`) and the top N results shown.
2. **Cite the source**: Always include the `uri` and `title` so the user knows which document each result came from.
3. **Show relevance**: Include the score to indicate match quality.
4. **Be selective**: If many results are from the same document, group them and note it. If some results are clearly off-topic, skip them.
5. **Offer follow-ups**: Ask if the user wants more results, a different mode, or to see a specific document.

## When to Use

- User asks about a concept, design decision, or architecture that might be documented in the project
- User asks "how does X work" where X might be in a spec or plan
- User asks about research papers indexed in the corpus
- User mentions a document and wants to find related information
- User wants to understand context before making code changes

Do NOT use for: code search (use `grep`), finding files by name (use `find_path`), or searching unindexed directories.
