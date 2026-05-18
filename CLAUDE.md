# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv run harness-poc              # start interactive REPL
uv run harness-poc --help       # list CLI sub-commands
uv run harness-poc skill list   # discover system + project skills
uv run harness-poc state show project  # print durable project state
uv run harness-poc workflow run <name> "<objective>"  # execute a workflow

uv run pytest                          # full test suite
uv run pytest tests/test_consolidate_state.py  # focused single file
uv run ruff check .                    # lint (line-length=100, double quotes)
uv run ty check                        # static type checks
```

## Architecture

**Deverino** is a Python 3.12 proof-of-concept for autonomous LLM agent workflows backed by SQLite.

### Skill system

Each skill is a self-contained directory with `SKILL.md` (metadata: name, description, args schema) and `skill.py` (an `execute(ctx: SkillContext) -> SkillResult` function). Skills are discovered at startup by `core/skill_runner.py` scanning `harness_poc/system_skills/` and the project-local `skills/` directory. They are registered as OpenAI tool-call definitions so the LLM can invoke them.

System skills (built into the harness): `delegate_task`, `consolidate_state`, `container_spawn/exec/destroy`, `read_memory`.
Project skills (repo-local, user-defined): `reflect_on_result`, `review_work`, `spec_writer`, `summarize_memory`.

### Workflow runtime

`core/workflow_runner.py` executes YAML files from `workflows/`. Each workflow is a linear sequence of states; each state specifies a skill name and argument templates (using `{{variable}}` substitution). The runner loops through states, calls the skill, and passes output forward. Workflow definitions live in `workflows/*.yaml`.

### Blackboard (SQLite state)

`core/database.py` (`BlackboardDatabase`) owns a single SQLite file (`harness_poc/blackboard.db`). It has five tables:

| Table | Purpose |
|---|---|
| `sessions` | Per-run session records |
| `shared_memory` | Key-value LLM-written memory |
| `project_state` | Durable cross-session project facts |
| `session_state` | Ephemeral per-session facts |
| `state_proposals` | Proposed promotions from session → project state |

State promotion is a two-step process: a skill proposes a change (`state_proposals`), which must be approved before it is merged into `project_state`. The `consolidate_state` system skill drives this.

### AppState & wiring

`app_factory.py` constructs the `AppState` dataclass that is threaded through every command and the REPL. It wires together: `HarnessConfig` (from `harness.yaml`), `BlackboardDatabase`, `LLMClient`, discovered skills, and loaded workflows.

### LLM client

`core/llm_client.py` wraps the OpenAI SDK (also supports DeepSeek via base-URL override). It converts discovered skill definitions into tool schemas and manages the tool-call loop: send message → receive tool call → execute skill → send result → repeat until the model stops calling tools.

### REPL

`repl.py` uses `prompt-toolkit` to provide tab-completion over skill names, workflow names, and commands. It runs a message loop that feeds user input to the LLM client, which may invoke skills before returning a final response.

### Configuration

`harness.yaml` at the repo root is the primary config file. `core/config.py` (`HarnessConfig`) loads it via `pydantic-settings`. Provider credentials (API keys) must come from environment variables — never from config files.

## Key conventions

- Ruff: `line-length = 100`, double quotes, `S101` ignored under `tests/`.
- Prefer typed functions and existing harness abstractions (`SkillContext`, `SkillResult`, `BlackboardDatabase`) over ad hoc parsing.
- Tests must be deterministic; avoid real network or model calls unless the test explicitly requires it.
- `blackboard.db` is local runtime state — do not commit it.
- `AGENTS.md` contains commit and PR guidelines; follow conventional imperative commit messages.
