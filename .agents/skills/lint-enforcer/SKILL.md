---
name: lint-enforcer
description: Run ruff and ty checks on changed files after any code edit. Use after every file write to catch regressions before reporting completion.
---

# Lint Enforcer

After any code change, run lint and type checks on the files you touched.
Do not report "done" unless both pass with zero new errors.

## Commands

```bash
# Lint changed files
uv run ruff check path/to/file1.py path/to/file2.py --statistics

# Type-check changed files
uv run ty check path/to/file1.py path/to/file2.py
```

## Rules

1. **Run after every file, not just at the end.** If you touch 3 files,
   run lint after each one. Finding an error on file 1 saves rework on
   files 2 and 3.

2. **Only count new errors.** Pre-existing warnings (import-outside-top-level,
   typing-only imports, etc.) are not your problem. Focus on errors your
   change introduced: unused imports, undefined names, type mismatches,
   missing arguments.

3. **Fix before continuing.** If ruff or ty reports an error in a file
   you changed, fix it immediately. Do not accumulate lint debt across
   files.

4. **Run both.** Ruff catches style and logic issues. Ty catches type
   errors. They cover different categories — one passing does not mean
   the other will.

5. **Report the result.** After running, state:
   - "Zero new lint errors on <files>"
   - "Zero new type errors on <files>"
   Or list the errors found and what you did about them.

## When to skip

Skip if:
- The file only had docstring/comment changes (no code)
- The change was a pure delete (no new logic)
- The file is a markdown/YAML/config (not Python)

## Failure modes this prevents

| Failure | Prevention |
|---------|-----------|
| Unused import from refactor | Ruff `F401` catches it |
| Missing type annotation on new function | Ty catches it |
| Wrong argument count after signature change | Ty catches it |
| Import of deleted/nonexistent module | Both catch it |
| Reporting "done" with broken code | Rule 1 forces per-file checks |
