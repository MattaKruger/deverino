# Deverino — common dev commands
# Run with: just <recipe>

default:
    @just --list

# Start interactive REPL
repl:
    uv run harness-poc

# List all discovered skills
skills:
    uv run harness-poc skill list

# Show durable project state
state:
    uv run harness-poc state show project

# Show lightweight dashboard snapshot
dashboard-summary:
    uv run harness-poc dashboard summary

# Run Dash dashboard server: just dashboard 8050
dashboard port="8050":
    uv run harness-poc dashboard serve --port {{port}}

# Run a workflow: just workflow <name> "<objective>"
workflow name objective:
    uv run harness-poc workflow run {{name}} "{{objective}}"

# Run full test suite
test:
    uv run pytest

# Run a single test file: just test-file tests/test_goal_runner.py
test-file file:
    uv run pytest {{file}}

# Lint with ruff
lint:
    uv run ruff check .

# Auto-fix lint issues
lint-fix:
    uv run ruff check . --fix

# Static type checks
types:
    uv run ty check

# Run lint + types + tests
check: lint types test
