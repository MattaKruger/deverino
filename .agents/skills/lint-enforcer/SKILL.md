---
name: lint-enforcer
description: Run ruff and ty checks on changed files after any code edit. Use after every file write to catch regressions before reporting completion.
---

# Lint Enforcer

After editing Python files, run lint and type checks. Fix violations in your changed code before reporting done.

## Commands

```bash
uv run ruff check path/to/file.py
uv run ty check path/to/file.py
```

## Rules

1. Run both checks on every Python file you changed.
2. Fix violations on lines you wrote. Leave pre-existing issues in untouched code alone.
3. Report pass/fail for each file.

## Skip when

- Non-Python files (markdown, YAML, config)
- Pure deletion or docstring-only changes
