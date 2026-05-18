# Deverino

A Python 3.12 proof-of-concept for autonomous LLM agent workflows. It provides an interactive REPL and CLI where an orchestrating agent can invoke skills, delegate to sub-agents, manage state in a SQLite blackboard, and execute YAML-defined workflows.

## Quickstart

```bash
# Start the interactive REPL
uv run harness-poc

# Run a workflow
uv run harness-poc workflow run research_task "What is the ReAct prompting pattern?"

# List available skills
uv run harness-poc skill list
```

Set your LLM credentials before starting:

```bash
export OPENAI_API_KEY=sk-...
# or for DeepSeek
export OPENAI_BASE_URL=https://api.deepseek.com
export OPENAI_API_KEY=sk-...
```

## Architecture

```
harness_poc/
├── cli.py              # Typer CLI entry point
├── repl.py             # Interactive REPL with tab completion
├── app_factory.py      # Wires DB, LLM client, skills, workflows into AppState
├── core/
│   ├── database.py     # BlackboardDatabase — SQLite-backed session/memory/state
│   ├── llm_client.py   # OpenAI-compatible client with tool-call loop
│   ├── skill_runner.py # Discovers and executes skills
│   └── workflow_runner.py # Executes YAML workflow state machines
├── system_skills/      # Built-in skills (delegate_task, consolidate_state, etc.)
└── system_prompts/     # SOUL.md — system prompt for the primary agent
skills/                 # Project-local skills (spec_writer, reflect_on_result, etc.)
workflows/              # YAML workflow definitions
personas/               # Prompt templates for sub-agents
```

The **blackboard** (`harness_poc/blackboard.db`) is the shared memory bus. Skills read and write to it by session key. State is split into two layers: ephemeral session state and durable project state, with an explicit proposal/approval step to promote session facts to project state.

Skills are discovered at startup by scanning `harness_poc/system_skills/` and `skills/`. Each skill is a directory containing `SKILL.md` (metadata + parameter schema) and `skill.py` (an `execute(ctx, arguments) -> SkillResult` function). Discovered skills are registered as OpenAI tool definitions so the LLM can invoke them directly.

## The REPL

`uv run harness-poc` starts an interactive session. Type a message and the agent responds, calling skills as tools when needed.

### Built-in REPL commands

```
/skill list                          # list all skills
/skill show <name>                   # print a skill's SKILL.md
/skill <name> <args>                 # call a skill directly (bypasses LLM)
/skill <name> {"key": "value"}       # call with JSON arguments
/state show [project|session|all]    # inspect blackboard state
/state consolidate [preview|propose|approve]
/help
/exit
```

### Calling skills directly

Skills accept arguments as JSON, key=value pairs, or a bare string (mapped to the skill's primary parameter):

```
> /skill spec_writer {"mode": "gather", "gather_key": "my_spec"}
> /skill spec_writer mode=questions goal="Add export support"
> /skill read_memory research_result
```

## Skills

### System skills

| Skill | Description |
|---|---|
| `delegate_task` | Spawns an isolated LLM sub-agent with a persona to handle a sub-task |
| `consolidate_state` | Promotes session state to durable project state (preview / propose / approve) |
| `read_memory` | Reads a key from the blackboard for the current session |
| `container_spawn` | Creates a detached Docker/Podman container for the session |
| `container_exec` | Runs a shell command inside an existing container |
| `container_destroy` | Stops and removes a container |

### Project skills

| Skill | Description |
|---|---|
| `spec_writer` | Multi-turn Q&A that produces structured XML context and markdown specs |
| `reflect_on_result` | Assesses whether a sub-agent result satisfies the original objective |
| `review_work` | Reviews the current working tree |
| `summarize_memory` | Summarises a blackboard memory key into a compact result |

## Writing specs with spec_writer

`spec_writer` has a two-phase flow for producing implementation-ready technical specs.

### Phase 1 — gather (collect requirements)

`gather` mode runs a multi-turn Q&A loop, asking one question at a time:

1. Project overview (tech stack, architecture)
2. Feature request (user intent)
3. Component names (as a list)
4. Per-component detail — one question per component, loops until all are answered
5. Constraints

When all phases are complete, it writes a structured XML context document to `specs/` and stores it in the blackboard.

**Via the LLM (recommended)** — just describe what you want and let the agent drive:

```
> I want to write a spec for <feature>. Use spec_writer in gather mode.
```

The agent calls `spec_writer` with `mode=gather`, presents each question to you, and passes your answers back as the `answer` argument on the next call.

**Directly** — call the skill yourself, passing each answer manually:

```
# First call — no answer yet
> /skill spec_writer {"mode": "gather", "gather_key": "my_spec"}

# Subsequent calls — pass your answer to the previous question
> /skill spec_writer {"mode": "gather", "gather_key": "my_spec", "answer": "A Python LLM harness backed by SQLite."}
```

Use the same `gather_key` across REPL restarts — state is persisted in the blackboard.

### Phase 2 — draft (generate the spec)

Once gather is complete, draft mode feeds the XML context to the LLM and produces a markdown spec:

```
> /skill spec_writer {"mode": "draft", "gather_key": "my_spec", "use_llm": true}
```

Or without a prior gather session, using flat inputs:

```
> /skill spec_writer {"mode": "draft", "goal": "Add export support", "context": "...", "requirements": "...", "use_llm": true}
```

The spec is written to `specs/` and stored in the blackboard under `output_key` (default: `spec_writer_result`).

## Workflows

Workflows are YAML state machines in `workflows/`. Each state calls a skill and passes its output to the next state via template variables.

```bash
uv run harness-poc workflow run research_task "What is the ReAct pattern?"
uv run harness-poc workflow run research_plan_execute "Summarise the codebase"
```

A workflow definition looks like:

```yaml
name: research_task
states:
  delegate:
    skill: delegate_task
    args:
      persona: web_researcher
      objective: "{{ inputs.objective }}"
      memory_key: research_result
    next: reflect
  reflect:
    skill: reflect_on_result
    args:
      objective: "{{ inputs.objective }}"
      memory_key: "{{ states.delegate.artifacts.memory_key }}"
    next: done
  done:
    terminal: true
```

## Configuration

`harness.yaml` at the repo root controls paths and runtime settings. The database is local to the repo (`harness_poc/blackboard.db`) and should not be committed.

## Development

```bash
uv run pytest                  # full test suite
uv run pytest tests/test_spec_writer.py  # focused
uv run ruff check .            # lint
uv run ty check                # type check
uv run harness-poc skill create <name> "<description>"  # scaffold a new skill
```

Skills follow the `execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult` contract. See any skill in `skills/` or `harness_poc/system_skills/` for a working example.
