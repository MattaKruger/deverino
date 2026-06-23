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
- Research papers (`docs/papers/`, `docs/papers_2/`)
- General documentation (`docs/`)
- Other project documents

The corpus currently has ~4,428 document chunks across all sources.

## How to Search

Use the `documents search` CLI command. Embeddings are computed **client-side**
(Snowflake arctic-embed-l-v2.0, 1024-dim) — no Vespa server-side embedder is
required. The command outputs JSON to stdout (logs go to stderr, so redirect
stderr with `2>/dev/null` when piping to a parser).

```bash
uv run harness-poc documents search "YOUR SEARCH QUERY" --mode hybrid --hits 8 2>/dev/null
```

### Hybrid Search (default — combines keyword BM25 + semantic embedding)

Use this for most queries. It balances exact term matching with semantic
understanding:

```bash
uv run harness-poc documents search "YOUR SEARCH QUERY" --mode hybrid --hits 8 2>/dev/null
```

### Semantic Search (embedding vectors only, via HNSW ANN)

Use when the user's query is conceptual or paraphrased — not looking for exact
keyword matches. The first invocation loads the embedding model (~20 s cold
start):

```bash
uv run harness-poc documents search "YOUR SEARCH QUERY" --mode semantic --hits 8 2>/dev/null
```

### Keyword Search (BM25 text matching only)

Use when searching for specific terms, error messages, class names, or exact
phrases. Fastest mode — no embedding model loaded:

```bash
uv run harness-poc documents search "YOUR SEARCH QUERY" --mode keyword --hits 8 2>/dev/null
```

### Filtering by Source or Kind

Use the `--source-id` and `--kind` flags to narrow results. The `source_id` is
a slug derived from the file path (e.g., `docs-papers_2-2605-01920-pdf`). The
`kind` is one of: `spec`, `plan`, `doc`, `source`.

```bash
uv run harness-poc documents search "ACDL grammar" --source-id docs-papers_2-2605-01920-pdf --hits 5 2>/dev/null
uv run harness-poc documents search "retrieval design" --kind spec --hits 5 2>/dev/null
```

### Adjusting Result Count

Change `--hits` / `-n` to any number. For a broad exploration, use 15–20; for
focused lookups, use 3–5.

## Interpreting Results

The command outputs a JSON object to stdout:

```json
{
  "query": "...",
  "mode": "hybrid",
  "total_results": 3,
  "results": [
    {
      "source_id": "docs-papers_2-2605-01920-pdf",
      "uri": "docs/papers_2/2605.01920.pdf",
      "title": "2605.01920",
      "chunk_id": "docs-papers_2-2605-01920-pdf-0016",
      "chunk_index": 16,
      "relevance": 7.48,
      "kind": "doc",
      "text": "..."
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `source_id` | Slug of the source document (e.g., `docs-papers_2-2605-01920-pdf`) |
| `uri` | Relative path to the original file |
| `title` | Document title derived from filename |
| `chunk_id` | Unique chunk identifier |
| `chunk_index` | 0-based position within the document |
| `text` | The chunk's full text content |
| `relevance` | Relevance score (higher = better match) |
| `kind` | Document kind: `spec`, `plan`, `doc`, or `source` |

## Presenting Results to the User

When showing search results:

1. **Summarize**: State how many total matches were found (`total_results`) and the top N results shown.
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
