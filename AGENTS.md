# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python 3.12 proof-of-concept LLM agent harness backed by a SQLite blackboard.

- `harness_poc/` contains the application package. `main.py` is the entrypoint, `cli.py` defines the Typer CLI, `repl.py` handles the interactive shell, and `core/` contains config, database, LLM, skill, and workflow runtime code.
- `harness_poc/system_skills/` stores built-in skills. `skills/` stores project-local skills. Each skill lives in its own directory with `SKILL.md`, `__init__.py`, and usually `skill.py`.
- `workflows/` contains YAML workflow definitions.
- `personas/` and `harness_poc/system_prompts/` contain prompt assets.
- `tests/` contains pytest coverage for CLI, REPL completion, state consolidation, and skill execution.
- `docs/` contains design notes and implementation plans.

## Build, Test, and Development Commands

- `uv run harness-poc` starts the interactive REPL.
- `uv run harness-poc --help` shows CLI commands.
- `uv run harness-poc skill list` lists discovered system and project skills.
- `uv run harness-poc state show project` prints durable project state and changelog.
- `uv run pytest` runs the full test suite. If the ACP runner drops, run focused tests such as `uv run pytest tests/test_consolidate_state.py`.
- `uv run ruff check .` runs lint checks.
- `uv run ty check` runs static type checks.

## Coding Style & Naming Conventions

Use 4-space indentation and Python 3.12 syntax. Ruff is configured with `line-length = 100`, double quotes, and broad lint coverage. Prefer small, typed functions and existing harness abstractions over ad hoc parsing. Name tests as `test_*.py`, skills with snake_case directory names, and workflows with descriptive snake_case YAML files.

## Testing Guidelines

Use pytest. Add focused tests near the behavior being changed, especially for command parsing, skill execution, workflow runtime behavior, and database-backed state transitions. Tests may use `assert`; Ruff ignores `S101` under `tests/`. Keep tests deterministic and avoid real network/model calls unless explicitly required.

## Commit & Pull Request Guidelines

This checkout has no Git history, so follow conventional, imperative commit messages such as `Add direct skill execution in REPL`. Pull requests should include a short summary, tests run, affected commands, and any state/database migration concerns. Include screenshots or terminal excerpts only when UI or CLI rendering changes.

## Security & Configuration Tips

Configuration lives in `harness.yaml`. Treat `harness_poc/blackboard.db` as local runtime state, not source data. Do not commit secrets or API keys; use environment variables for provider credentials.

## Code Search

Use `semble search` to find code by describing what it does or naming a symbol/identifier, instead of grep:

​```bash
semble search "authentication flow" ./my-project
semble search "save_pretrained" ./my-project
semble search "save model to disk" ./my-project --top-k 10
​```

Use `semble find-related` to discover code similar to a known location (pass `file_path` and `line` from a prior search result):

​```bash
semble find-related src/auth.py 42 ./my-project
​```

`path` defaults to the current directory when omitted; git URLs are accepted.

If `semble` is not on `$PATH`, use `uvx --from "semble[mcp]" semble` in its place.

### Workflow

1. Start with `semble search` to find relevant chunks.
2. Inspect full files only when the returned chunk is not enough context.
3. Optionally use `semble find-related` with a promising result's `file_path` and `line` to discover related implementations.
4. Use grep only when you need exhaustive literal matches or quick confirmation of an exact string.
