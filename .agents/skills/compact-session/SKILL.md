---
name: compact-session
description: >-
  Produce a structured session-compaction summary to free up context.
  Use when the conversation is getting long, when the user says "compact",
  "summarize session", "free up context", or "wrap up". Takes an optional
  subject to focus the summary; otherwise produces a general summary.
disable-model-invocation: false
---

# Compact Session

Produce a dense, structured summary of the current conversation that can bootstrap the next session. The user will copy this into a fresh conversation to continue work without replaying the full history.

## Input

The user may provide a **subject** to focus the summary on a specific topic, feature, or file area. If no subject is given, summarize the entire session.

## Output Format

Produce exactly one compact block following this structure:

```
## Session Compact — [subject or "General"]

**Accomplished:**
- [concrete thing done, with file paths]
- ...

**Decisions:**
- [decision made] — [brief rationale]
- ...

**State:**
- [current working state, e.g., "mid-refactor of X", "tests passing on Y"]
- [files changed and how]

**Unresolved / Next:**
- [thing not yet done]
- ...

**Key files touched:**
- `path/to/file` — [one-line description of change]
```

## Rules

1. **Be dense.** Every line should carry information. No filler, no conversational framing.
2. **Use file paths.** Reference exact files when possible.
3. **Group related items.** Don't interleave unrelated topics.
4. **Omit the obvious.** Don't list every tool call — only outcomes and decisions.
5. **Limit to ~20 lines total.** If the session is massive, prioritize what's needed to continue work.
6. **Keep decisions with rationale.** A decision without the "why" is useless next session.

## After Output

State the subject used and the line count. Do not add closing pleasantries — the compact block is the deliverable.
