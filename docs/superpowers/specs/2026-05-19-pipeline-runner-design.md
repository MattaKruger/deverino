# Pipeline Runner + Logfire Observability — Design Spec

**Date:** 2026-05-19
**Status:** Approved

## Overview

Add declarative DAG-based multi-agent pipelines to Deverino, with Logfire observability wired in via the existing EventBus. Pipelines are separate from workflows — workflows remain a linear, skill-only state machine. Pipelines support parallel node execution and autonomous agent nodes.

## Goals

- Define pipelines as YAML DAGs with sequential and parallel nodes
- Support two node types: single skill call (`skill`) and autonomous ReAct agent (`agent`)
- Run independent nodes concurrently using `ThreadPoolExecutor`
- Wire Logfire observability via EventBus subscribers with zero changes to the runner
- Add a `pipeline run` CLI command

## Non-Goals

- Replacing or migrating existing workflows
- LLM-driven routing between nodes (static DAG only)
- Async execution (synchronous `ThreadPoolExecutor` only)

## Architecture

Three new files, three modified files.

### New files

| File | Purpose |
|---|---|
| `harness_poc/core/pipeline_runner.py` | DAG execution, wave-based parallelism, result passing |
| `harness_poc/core/logfire_subscriber.py` | EventBus → Logfire span wiring |
| `pipelines/*.yaml` | Pipeline definitions |

### Modified files

| File | Change |
|---|---|
| `harness_poc/core/events.py` | 4 new pipeline event types |
| `harness_poc/app_factory.py` | Pipeline discovery, optional Logfire wiring |
| `harness_poc/cli.py` | `pipeline run <name> --input key=value` command |

## YAML Pipeline Schema

Pipelines live in `pipelines/` at the repo root, discovered at startup alongside `workflows/`.

```yaml
name: research-and-write
description: Research a topic in parallel, then synthesize

inputs:
  topic: string

nodes:
  - id: web_research
    type: agent
    goal: "Research this topic thoroughly: {{inputs.topic}}"
    allowed_skills: [read_memory, delegate_task]   # optional; omit for all skills

  - id: memory_research
    type: skill
    skill: read_memory
    arguments:
      query: "{{inputs.topic}}"

  # web_research and memory_research have no depends_on → run in parallel

  - id: synthesize
    type: agent
    goal: |
      Synthesize these findings into a document:
      Web: {{nodes.web_research.output}}
      Memory: {{nodes.memory_research.output}}
    depends_on: [web_research, memory_research]

  - id: review
    type: skill
    skill: review_work
    arguments:
      content: "{{nodes.synthesize.output}}"
    depends_on: [synthesize]
```

### Template variables

- `{{inputs.key}}` — from pipeline invocation arguments
- `{{nodes.node_id.output}}` — the output content of a completed node

### Node types

**`skill`** — calls a single skill once, no LLM reasoning. Fields: `skill`, `arguments`.

**`agent`** — spins up a `GoalRunner` ReAct loop. Fields: `goal`, `allowed_skills` (optional list; omit to allow all registered skills).

## Execution Model

```
1. Load YAML → validate nodes and dependency references
2. Topological sort → execution waves
3. For each wave:
   a. Submit all nodes to ThreadPoolExecutor concurrently
   b. skill node  → skill_runner.execute_skill(...)
      agent node  → GoalRunner(allowed_skills=...).run(goal, app_state)
   c. Collect results into shared dict keyed by node id
   d. Failed node → skip downstream dependents, continue independent nodes
4. Return PipelineRunResult(status, node_outputs, duration_s)
```

Example wave breakdown:
```
Wave 1 (parallel): web_research, memory_research
Wave 2 (sequential): synthesize
Wave 3 (sequential): review
```

### Error handling

A failed node aborts its downstream dependents only. Nodes in the same wave that do not depend on the failed node complete normally. The `PipelineRunResult` reports which nodes completed, failed, and were skipped.

## New Events

Added to `harness_poc/core/events.py`:

| Event | Fields |
|---|---|
| `PipelineStarted` | `pipeline_name`, `node_count` |
| `PipelineNodeStarted` | `node_id`, `node_type` |
| `PipelineNodeCompleted` | `node_id`, `status`, `output_preview` |
| `PipelineCompleted` | `pipeline_name`, `status`, `duration_s` |

Existing events (`AgentStarted`, `SkillCalled`, `SkillCompleted`, etc.) continue to be published inside agent nodes — no changes required.

## Logfire Integration

`harness_poc/core/logfire_subscriber.py` subscribes handlers to the EventBus:

```python
def wire_logfire(event_bus: EventBus) -> None:
    event_bus.subscribe(PipelineStarted, _on_pipeline_started)
    event_bus.subscribe(PipelineNodeStarted, _on_node_started)
    event_bus.subscribe(PipelineNodeCompleted, _on_node_completed)
    event_bus.subscribe(PipelineCompleted, _on_pipeline_completed)
    event_bus.subscribe(AgentStarted, _on_agent_started)
    event_bus.subscribe(SkillCalled, _on_skill_called)
    event_bus.subscribe(SkillCompleted, _on_skill_completed)
```

Logfire spans nest: **pipeline → node → agent loop → skill calls** — giving a full trace tree in the Logfire UI.

PydanticAI's auto-instrumentation captures every `Agent.run_sync` call for free once `logfire.configure()` is called, so agent node decision steps appear as child spans with no extra code.

### Configuration

Opt-in via `harness.yaml`:

```yaml
observability:
  logfire: true   # requires LOGFIRE_TOKEN env var
```

`app_factory.py` calls `wire_logfire(app_state.event_bus)` when the flag is set. `PipelineRunner` and `GoalRunner` require no changes.

## CLI

```bash
uv run harness-poc pipeline run <name> --input key=value --input key2=value2
uv run harness-poc pipeline list
```

## Relation to Workflows

Workflows remain unchanged — linear, skill-only, with container lifecycle support. Pipelines are additive. Migration of workflows to pipelines is a future concern.

| | Workflows | Pipelines |
|---|---|---|
| Shape | Linear state machine | DAG |
| Parallelism | None | Yes (ThreadPoolExecutor) |
| Node types | Skill only | Skill or autonomous agent |
| Observability | None | Logfire via EventBus |
| Container lifecycle | Built-in | Not included |
