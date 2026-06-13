---
name: multi-file-change
description: Pre-flight and incremental checklist for multi-file code changes. Use before touching more than one file to prevent edit-tool accidents, missing tests, and unverified design decisions.
---

# Multi-File Change Protocol

When any task requires editing more than one file, follow this protocol.
It prevents the three most common failure modes: import-strip edit-tool
accidents, untested multi-file cascades, and silent behavioral changes.

## Phase 0 — Pre-flight

Before touching any file:

1. **Run the existing test suite** and capture the pass count:
   ```bash
   TEST_DATABASE_URL=postgresql://deverino_test:deverino_test@localhost:5433/deverino_test uv run pytest harness_poc/v2/tests/ tests/event/ tests/unit/ -q
   ```
   Record the number. If it doesn't match the last known good count,
   investigate before proceeding.

2. **Read every file you're about to edit.** Never compose an edit from
   memory. The edit tool uses fuzzy matching — if `old_text` doesn't
   match the file exactly, it may match a larger block than intended.

3. **Identify the minimal change set.** For each file, write down:
   - Which function/class is being modified
   - Whether it's a signature change, a body change, or an import change
   - Whether callers need updating

## Phase 1 — Edit in Dependency Order

Make changes from the bottom of the dependency graph upward (no forward
references to code that doesn't exist yet).

### Edit tool safety rules

- **Small `old_text` blocks.** Prefer 1–5 lines over 20-line blocks.
  The fuzzy matcher is more predictable with small targets.
- **Read exact lines first.** Before an edit, read the specific line
  range you're replacing. Use the line numbers from the read output.
- **Avoid bracket notation in multi-line edits.** Strings containing
  `["key"]` or `{"key": ...}` can collide with the tool's JSON parser.
  When replacing dict/bracket access, do individual single-line edits.
- **Import additions: add one line,** not a block. When adding an import,
  edit just the line before or after, not the entire import section.

### After each file

Run the targeted test suite for that file:
```bash
TEST_DATABASE_URL=... uv run pytest path/to/tests/ -q
```
If anything fails, fix it before touching the next file. Do not accumulate
failures across files.

## Phase 2 — Integration verification

After all files are edited:

1. **Run the full targeted suite:**
   ```bash
   TEST_DATABASE_URL=... uv run pytest harness_poc/v2/tests/ tests/event/ tests/unit/ -q
   ```
   The pass count must equal the pre-flight count plus any new tests added.

2. **Smoke-test the CLI surface** for every changed command:
   ```bash
   uv run harness-poc <new-command> --help
   uv run harness-poc <new-command> <args>
   ```

3. **Run lint + type check on changed files:**
   ```bash
   uv run ruff check path/to/changed/file.py --statistics
   uv run ty check path/to/changed/file.py
   ```

## Phase 3 — Add tests for new behavior

New code paths need corresponding tests. At minimum:

- **New dataclass/model:** test construction with valid and edge-case inputs
- **New CLI command:** test `--help` output and one happy-path invocation
- **New REPL command:** test the `_is_*_command` parser and the handler
- **New dispatch path:** test that the correct handler is called for each mode

Copy patterns from existing tests in `tests/event/test_v2_fusion.py` and
`harness_poc/v2/tests/`.

## Phase 4 — Flag behavioral changes

Before finishing, ask: *"Does this change how the user interacts with the
system in a way they didn't explicitly request?"*

If yes, surface it explicitly:
> "Note: with this change, plain text input in pipeline mode now executes
> as a v2 objective. Previously it would have gone to chat. Is this the
> intended behavior?"

Do not silently introduce new dispatch paths, new default behaviors, or
new side effects. The developer's pedagogy profile says: "Prefer discussion
over generation when exploring new features."

## Failure modes this protocol prevents

| Failure | How this protocol prevents it |
|---------|------------------------------|
| Import strip (edit matches too much) | Small `old_text` blocks, read exact lines first |
| Batch edit JSON parse failure | Avoid bracket notation in multi-line edits |
| Multi-file cascade breaks silently | Incremental test after each file |
| Untested new behavior | Phase 3 mandates tests for new paths |
| Surprising UX change | Phase 4 flags behavioral changes for discussion |
| Baseline unknown | Phase 0 captures pre-flight pass count |

## When to use this skill

Activate this skill when:
- The user asks for changes spanning 2+ files
- You're implementing a multi-phase plan
- You're refactoring a shared interface (dataclass, function signature, import)
- The user says "implement this plan" with multiple file targets

Do NOT activate for single-file edits, read-only investigation, or
documentation-only changes.
