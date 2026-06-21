---
name: paper-catalog
version: 1.1
description: >-
  Enumerate the indexed paper corpus from the database and search paper
  content via Vespa. Uses inspect_db(document_sources) for inventory and
  search_documents for content retrieval — never swap the two roles.
---

# Paper Catalog

## Problem

`search_documents` returns chunks ranked by semantic relevance, capped at 8
hits by default. It cannot enumerate — there is no "list all papers" option.
Using it for inventory produces an incomplete, relevance-skewed result.

Conversely, `inspect_db` on `document_sources` knows filenames and chunk
counts but knows nothing about *content*. It cannot answer "find papers about
self-reflection."

The correct split:

| Task | Tool | Why |
|------|------|-----|
| "List papers" | `inspect_db` → `document_sources` | Table has one row per source file |
| "Find papers about X" | `search_documents` | Vespa indexes chunk content |
| "Stats / status" | `inspect_db` → `document_sources` | Aggregate SQL over source rows |
| "Any duplicates?" | `inspect_db` → `document_sources` | GROUP BY extracted arXiv ID |
| "Get paper detail" | `search_documents` with `source_id` | Retrieve chunks for one paper |

## Design Principle

> **Inventory reflects the database. Content reflects Vespa.**
> The database owns *what* is indexed. Vespa owns *what is in it*.
> Never hardcode a paper list — query it.

## Data Source: Database (`inspect_db`)

The `document_sources` table is the authoritative inventory. Each row is one
indexed document (paper, plan, spec, etc.).

```sql
SELECT source_id, uri, title, kind, chunk_count, status
FROM document_sources
WHERE uri LIKE 'docs/papers/%'
ORDER BY uri
LIMIT 100;
```

Substitute the URI prefix to enumerate other corpora:

| Corpus | URI prefix |
|--------|-----------|
| Papers | `docs/papers/%` |
| Plans | `docs/plans/%` |
| Superpowers | `docs/superpowers/%` |
| Archive | `docs/archive/%` |
| All documents | (omit WHERE clause) |

## Data Source: Vespa (`search_documents`)

Use `search_documents` with `source_id` or `kind` filters to retrieve paper
*content*. This is for semantic search and chunk retrieval, not enumeration.

| Parameter | Use |
|-----------|-----|
| `source_id` | Filter to one source document (use the `source_id` from `document_sources`) |
| `kind` | Filter by document type (`"doc"`, `"notebook"`, etc.) |
| `mode` | `"hybrid"` (default), `"semantic"`, or `"keyword"` |

## Output Modes

The agent selects a mode based on user intent:

### Mode 1: Full Inventory (`list`)

A markdown table from the DB. Extract the arXiv ID from the URI using
regex `(\d{4}\.\d{5})`.

| arXiv ID | Title | Chunks | Status |
|----------|-------|--------|--------|
| 2401.07324 | Small LLMs Are Weak Tool Learners | 41 | indexed |
| 2605.18747 | Code as Agent Harness | 200 | indexed |

### Mode 2: Summary (`summary`)

Aggregate statistics:

```sql
SELECT
  COUNT(*) AS total_papers,
  SUM(chunk_count) AS total_chunks,
  ROUND(AVG(chunk_count)) AS avg_chunks,
  COUNT(*) FILTER (WHERE status = 'indexed') AS indexed,
  COUNT(*) FILTER (WHERE status = 'failed') AS failed
FROM document_sources
WHERE uri LIKE 'docs/papers/%';
```

### Mode 3: Filtered List (`filtered`)

Append WHERE conditions to the base query:

| Filter | SQL fragment |
|--------|-------------|
| By status | `AND status = 'indexed'` |
| By min chunks | `AND chunk_count >= 50` |
| By arXiv ID pattern | `AND uri LIKE '%2401%'` |
| By title substring | `AND title ILIKE '%harness%'` |
| By kind | `AND kind = 'doc'` |

### Mode 4: Content Search (`search`)

Use `search_documents` to find papers by content. Cross-reference results
back to the DB by extracting the arXiv ID from the `source_id` or URI.

```
search_documents(query="tool use in small language models", kind="doc")
→ returns ranked chunks with source_id, title, excerpt
→ cross-reference source_id against document_sources for full metadata
```

To retrieve **all chunks for one paper**, get its `source_id` from the DB
first, then:

```
search_documents(query="*", source_id="docs/papers/2401.07324", mode="keyword", hits=50)
```

### Mode 5: Deduplication Check (`dedup`)

Group by extracted arXiv ID and flag papers appearing more than once:

```sql
SELECT
  SUBSTRING(uri FROM '(\d{4}\.\d{5})') AS arxiv_id,
  COUNT(*) AS copies,
  ARRAY_AGG(uri ORDER BY uri) AS filenames
FROM document_sources
WHERE uri LIKE 'docs/papers/%'
GROUP BY arxiv_id
HAVING COUNT(*) > 1;
```

## Process

### Step 1: Determine intent

| User says | Mode |
|-----------|------|
| "List papers" / "what's indexed" | `list` |
| "How many?" / "stats" / "status" | `summary` |
| "Papers about X" / "find papers on Y" | `search` |
| "Show only indexed/failed" / "filter" | `filtered` |
| "Duplicates" / "two copies" | `dedup` |
| "Get full text of paper X" | `search` with `source_id` filter |

### Step 2: Route to the right tool

- **Inventory/list/summary/filtered/dedup** → `inspect_db` with SQL
- **Content search / retrieval** → `search_documents` with query + filters
- **Hybrid workflow** (e.g., "find papers about tool learning, then list them")
  → `search_documents` first, then cross-reference results against
  `inspect_db` query for full metadata

### Step 3: Format the result

- Inventory queries → markdown table (arXiv ID, Title, Chunks, Status)
- Summary → prose with key numbers
- Content search → ranked results with excerpts, linked to source
- Dedup → table of duplicate arXiv IDs with filenames

### Step 4: Surface anomalies

- **Failed indexing** → Report filenames and `status = 'failed'`. Suggest
  re-running `index_documents`.
- **Duplicates** → Report both filenames. Recommend deleting the redundant
  file and reindexing.
- **Zero results from search** → Try a different query, or check if the
  paper exists in inventory first.

## When NOT to Use This Skill

- **Do NOT use this skill for semantic search across non-paper documents.**
  Use the general `search_documents` tool directly for other corpora.
- **Do NOT hardcode paper lists.** The DB is the source of truth. If you
  need a reference list, query it.
- **Do NOT use `search_documents` to enumerate.** It retrieves chunks, not
  source files. Use `inspect_db` for enumeration.

## Contracts

### contract: list_papers
Query `document_sources` for papers and return a structured inventory.

**Inputs:** `prefix` (string, default `"docs/papers/%"`), `filters` (optional
dict: e.g. `{"status": "indexed", "min_chunks": 50}`)

**Outputs:** `papers` (list of dicts with arxiv_id, title, chunk_count, status,
uri), `total_count` (int)

**Preconditions:** `inspect_db` tool is available, `document_sources` table
exists.

**Postconditions:** User receives a complete paper inventory from the DB.

**Error conditions:**
- `document_sources` empty → report "No documents indexed yet"
- Query times out → retry with smaller LIMIT

### contract: search_papers
Search paper content via Vespa and return ranked results.

**Inputs:** `query` (string), `source_id` (optional string to scope to one
document), `kind` (optional string, default `"doc"`), `hits` (int, default 8)

**Outputs:** `results` (list of ranked chunks with source_id, title, excerpt,
relevance score)

**Preconditions:** `search_documents` tool is available, documents are indexed.

**Postconditions:** User sees ranked content matches from the paper corpus.

**Error conditions:**
- Zero results → suggest different query
- Source_id not found → check inventory first

### contract: dedup_papers
Detect duplicate entries in `document_sources` where the same arXiv ID
appears from multiple filenames.

**Inputs:** `prefix` (string, default `"docs/papers/%"`)

**Outputs:** `duplicates` (list of groups, each with arxiv_id, copy_count,
filenames)

**Preconditions:** `inspect_db` tool is available.

**Postconditions:** User is informed of any duplicate file entries.

**Error conditions:**
- No duplicates → report clean corpus

## Templates

### template: list_inventory_sql
```sql
SELECT source_id, uri, title, kind, chunk_count, status
FROM document_sources
WHERE uri LIKE '{prefix}'
ORDER BY uri
LIMIT {limit};
```

### template: summary_stats_sql
```sql
SELECT
  COUNT(*) AS total_papers,
  SUM(chunk_count) AS total_chunks,
  ROUND(AVG(chunk_count)) AS avg_chunks,
  COUNT(*) FILTER (WHERE status = 'indexed') AS indexed,
  COUNT(*) FILTER (WHERE status = 'failed') AS failed
FROM document_sources
WHERE uri LIKE '{prefix}';
```

### template: dedup_sql
```sql
SELECT
  SUBSTRING(uri FROM '(\d{4}\.\d{5})') AS arxiv_id,
  COUNT(*) AS copies,
  ARRAY_AGG(uri ORDER BY uri) AS filenames
FROM document_sources
WHERE uri LIKE '{prefix}'
GROUP BY arxiv_id
HAVING COUNT(*) > 1;
```

## Invoke Patterns

### "List all papers"
```
inspect_db(query="SELECT source_id, uri, title, kind, chunk_count, status FROM document_sources WHERE uri LIKE 'docs/papers/%' ORDER BY uri LIMIT 100")
→ extract arxiv_id from uri via regex (\d{4}\.\d{5})
→ render markdown table: | arXiv ID | Title | Chunks | Status |
```

### "How many papers do we have indexed?"
```
inspect_db(query="SELECT COUNT(*) AS total, SUM(chunk_count) AS total_chunks, ROUND(AVG(chunk_count)) AS avg_chunks, COUNT(*) FILTER (WHERE status = 'indexed') AS indexed, COUNT(*) FILTER (WHERE status = 'failed') AS failed FROM document_sources WHERE uri LIKE 'docs/papers/%'")
→ prose summary: "X papers, Y chunks total, Z avg chunks per paper, A indexed, B failed"
```

### "Find papers about blackboard architecture"
```
search_documents(query="blackboard architecture", kind="doc")
→ render ranked results with source_id, title, excerpt
→ optionally cross-reference source_id against document_sources for chunk counts
```

### "Get the full text of paper 2401.07324"
```
inspect_db(query="SELECT source_id FROM document_sources WHERE uri LIKE '%2401.07324%' LIMIT 1")
→ use returned source_id:
search_documents(query="*", source_id="docs/papers/2401.07324", mode="keyword", hits=50)
→ render all chunks as a readable document
```

### "Check for duplicate paper files"
```
inspect_db(query="SELECT SUBSTRING(uri FROM '(\d{4}\.\d{5})') AS arxiv_id, COUNT(*) AS copies, ARRAY_AGG(uri ORDER BY uri) AS filenames FROM document_sources WHERE uri LIKE 'docs/papers/%' GROUP BY arxiv_id HAVING COUNT(*) > 1")
→ report each duplicate: arxiv_id appears N times, filenames: [...]
```