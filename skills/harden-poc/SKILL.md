---
name: harden-poc
description: >
  Map a design spec against its implementation to find gaps, POC shortcuts,
  over-engineering, and hardening opportunities. Integrates ponytail-full
  principles: enforces the lazy ladder — stdlib before custom code, deletion
  before addition, one line before fifty. Produces a prioritized report for
  moving from POC to stable codebase. Use when reviewing a feature branch
  before merge, auditing a POC for production readiness, or planning a
  hardening sprint.
version: "1.1"
auto_invokable: false
parameters:
  type: object
  properties:
    spec_path:
      type: string
      description: Path to the design spec document (e.g., specs/20260724-feature.md).
    base_commit:
      type: string
      description: Git commit hash of the branch base (before changes).
    head_commit:
      type: string
      description: Git commit hash of the branch head (after changes). Defaults to HEAD.
    output_path:
      type: string
      description: Where to write the hardening report. Defaults to docs/reviews/.
  required:
    - spec_path
    - base_commit
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read
  workspace: read_only
---

# Harden POC

Map a design spec against its implementation. Find what's missing, what's a
shortcut, what will break in production. Produce a prioritized hardening report.

## When to Use

- Before merging a feature branch with subagent-generated code
- When a POC has grown complex enough to need stabilization
- When planning a hardening sprint from a set of feature branches
- After automated test suites pass but before declaring "done"

## Process

### 1. Spec-to-Implementation Map

Read the spec. Read every changed file. Build a table:

| Spec Section | Implementation File | Status | Notes |
|---|---|---|---|

Status values: `MATCH`, `DEVIATED`, `MISSING`, `PARTIAL`, `EXTRA` (implemented but not in spec).

For each `DEVIATED` entry, note whether the deviation is justified (improvement) or a regression (plan error, misread instruction).

### 2. Finding Categories

Scan the implementation for:

**Spec Drift** — implementation diverges from spec in load-bearing ways. Check:
- Function signatures match spec's interface contracts
- Config field names and defaults match spec
- Data flow matches spec's diagrams
- Error handling matches spec's stated behavior

**POC Shortcuts** — code that works for the demo but won't survive production:
- Hardcoded values that should be configurable (URLs, model names, thresholds)
- Synchronous calls in async paths
- Missing retries / timeouts on external calls
- `suppress(Exception)` without logging
- In-memory state that should be persisted
- No connection pooling or resource cleanup

**Missing Tests** — contracts without coverage:
- Edge cases the spec mentions but tests don't exercise
- Error paths (what happens when pgvector is unavailable, embedding fails, DB is empty)
- Concurrent access patterns
- Empty input / null input handling

**Performance** — patterns that scale poorly:
- N+1 queries (fetching entries one-by-one instead of batch)
- Embedding model loaded per-call instead of cached
- Full-table scans where indexed lookups would work
- Unbounded result sets without pagination

**Security** — input validation at trust boundaries:
- SQL injection (raw SQL with string concatenation)
- Unvalidated user input flowing into queries or prompts
- Secrets in code or logs
- Missing authorization checks

**Dead Code** — unused imports, unreachable branches, commented-out code, leftover debug logging.

**Over-Engineering** (ponytail-full) — code that exists but shouldn't, or is
more complex than needed. The ladder is enforced: stop at the first rung
that holds.

The ponytail ladder (check top-down, stop at first match):
1. **Does this need to exist at all?** Speculative need = delete it, say so.
2. **Stdlib does it?** Use it. Delete the custom code.
3. **Native platform feature covers it?** Use it over custom code.
4. **Already-installed dependency solves it?** Use it. Never add a new dep.
5. **Can it be one line?** One line. Delete the rest.
6. **Only then:** the minimum code that works.

Common over-engineering patterns to flag:
- Interface with one implementation — delete the interface, use the concrete type
- Factory for one product — inline the construction, delete the factory
- Config for a value that never changes — hardcode as a constant, delete the config field
- Custom wrapper around stdlib where the wrapper adds no value beyond what the lib already does — delete the wrapper, use the lib directly
- Speculative abstraction "for later" — delete it. Later can scaffold for itself.
- Dependency added for what a few lines of stdlib can do — remove the dep, use stdlib
- Boilerplate that duplicates an existing pattern in the codebase — delete the duplicate, reuse the pattern

For each finding: name the simpler alternative AND state what to delete.
The recommendation is prescriptive, not advisory — "delete X, replace with Y."

### 3. Severity Assignment

| Severity | Criteria |
|---|---|
| **Critical** | Will cause data loss, security breach, or crash in production. Must fix before merge. |
| **Important** | Will cause incorrect behavior, poor performance, or maintenance pain. Should fix before merge. |
| **Minor** | Code smell, missing docs, style issue, over-engineering. Fix when convenient. |
| **Info** | Observation, no action needed. Deviations that are improvements, design notes. |

### 4. Hardening Priorities

Rank findings into a sprint plan:

1. **Blockers** (Critical) — fix before merge
2. **Should-fix** (Important) — fix in the same PR or a follow-up within the sprint
3. **Tech debt** (Minor) — track in a debt ledger, address during refactoring
4. **Accepted** (Info) — document and move on

### 5. Report Format

Write to `docs/reviews/YYYY-MM-DD-<feature>-review.md`:

```markdown
# <Feature> Implementation Review

**Date:** YYYY-MM-DD
**Branch:** feat/...
**Commits:** N (base..head)
**Files changed:** N (+N/-N lines)

## Spec-to-Implementation Map

| Spec Section | Implementation | Status | Notes |
|---|---|---|---|

## Findings

### F001: [Title]
- **Severity:** Critical / Important / Minor / Info
- **Category:** Spec Drift / Missing Test / POC Shortcut / Performance / Security / Dead Code / Over-Engineering
- **Location:** `file.py:NNN`
- **Description:** What's wrong.
- **Recommendation:** What to do. For over-engineering: name the simpler alternative.

## Hardening Priorities

1. [Blockers — Critical findings]
2. [Should-fix — Important findings]
3. [Tech debt — Minor findings]
4. [Accepted — Info findings]

## Summary

N findings: X Critical, Y Important, Z Minor, W Info.
Recommendation: MERGE / MERGE WITH FIXES / DO NOT MERGE.
```

## Common POC Patterns to Flag

| Pattern | Why It's a Problem | Hardening Fix |
|---|---|---|
| `suppress(Exception)` | Swallows errors silently | Log at WARNING/ERROR, only suppress expected exceptions |
| Hardcoded model name | Can't swap without code change | Move to config |
| `retrieval_mode[0]` mutable hack | Works but fragile | Replace with a proper mutable container or threading-safe wrapper |
| N+1 DB queries per turn | Fine for <10 corpora, breaks at scale | Batch query across corpora |
| No embedding cache invalidation | Stale embeddings after rematerialization | Version-check embeddings against map cycle |
| `import` inside function | Lazy import for circular dep avoidance | Restructure imports or document why with `# noqa: PLC0415` |
| Test mocks entire DB | Tests pass but don't test real pgvector | Add integration test marker for PostgreSQL tests |
| `# noqa: PLC0415` without comment | Suppresses lint without explaining why | Add a comment: `# noqa: PLC0415 — lazy import to avoid circular dep` |
| Custom wrapper around stdlib | Adds indirection without value | Delete the wrapper, use the stdlib directly |
| Interface with one implementation | Speculative generality | Delete the interface, use the concrete type |
| Config field that never changes | Adds config surface for no benefit | Hardcode as a module constant, delete the config field |
| Factory for one product | Indirection without purpose | Inline the construction, delete the factory |
| Speculative abstraction "for later" | YAGNI — later can scaffold for itself | Delete it. Add when the need is real. |

## Integration with SDD

When using Subagent-Driven Development, run this skill as the final review step.
The per-task reviews catch local issues; this skill catches cross-task drift,
spec gaps, and systemic POC patterns that individual task reviews miss.
