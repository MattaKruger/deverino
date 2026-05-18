# Workflow Runtime Design

## Context

The proof of concept started as a direct LLM tool loop: discover `SKILL.md` files,
send them to the model as tools, and route returned tool calls to hard-coded Python
branches. That proved the blackboard pattern and provider integration, but it does
not give enough control for delegation, reflection, review, and future worktree-based
subagents.

The next runtime shape is explicit and deterministic:

```text
user invokes workflow
-> WorkflowRunner loads project YAML
-> WorkflowRunner executes named skills in order
-> SkillRunner loads project-local executable skill plugins
-> skills interact through SkillContext and blackboard
-> every state output is recorded for later reflection and audit
```

## V1 Scope

The first implementation supports read-only workflows only.

In scope:

* Root `harness.yaml` project config.
* Project-local workflow YAML files.
* Project-local skills with `SKILL.md` metadata and `skill.py` executable code.
* `SkillContext` and `SkillResult` as the in-process plugin contract.
* A linear YAML workflow runner with simple template substitution.
* Explicit terminal invocation: `workflow <name> <objective>`.
* Migration of the current delegation and memory read behavior into skill plugins.
* A first `research_task` workflow:
  `delegate_task -> reflect_on_result -> read_memory -> done`.

Out of scope for this pass:

* Branching and loops in workflows.
* Git worktrees.
* Mutating workspace skills.
* Review agents.
* Human merge approval gates.
* Nested skill calls.

## Project Contract

The project owns its runtime policy and capabilities:

```text
harness.yaml
workflows/
  research_task.yaml
skills/
  delegate_task/
    SKILL.md
    skill.py
  reflect_on_result/
    SKILL.md
    skill.py
  read_memory/
    SKILL.md
    skill.py
templates/
  subagents/
    web_researcher.md
```

`harness.yaml` is intentionally root-level so humans can review the automation
contract alongside other project configuration files.

## Skill Contract

`SKILL.md` remains the public LLM/tool schema source. Optional frontmatter fields
declare the executable entrypoint and permissions:

```yaml
---
name: delegate_task
description: Delegate a bounded objective to a read-only subagent.
parameters:
  type: object
  properties: {}
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---
```

`skill.py` exposes:

```python
def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    ...
```

Skills run in-process for observability. They should not call other skills directly.
If a skill needs additional orchestration later, it should return requested actions
for the orchestrator to evaluate.

## Workflow Contract

Workflow YAML groups skills into deterministic lifecycle behavior:

```yaml
name: research_task
inputs:
  objective:
    type: string
    required: true
states:
  delegate:
    skill: delegate_task
    args:
      persona: web_researcher
      objective: "{{ inputs.objective }}"
      memory_key: research_result
    next: reflect
  done:
    terminal: true
```

The v1 runner supports:

* `inputs.objective`.
* `states.<state_name>.artifacts.<key>`.
* Linear `next` transitions.
* Terminal states.

The runner stores each state output under workflow-scoped memory keys and returns a
compact execution summary to the terminal.

## Direction After V1

Once the read-only workflow runtime is stable, the next major workflow can add
mutating subagents:

```text
create_agent_workspace
-> run_worker_agent
-> inspect_agent_diff
-> run_review_agent
-> request_revision or request_human_decision
```

Mutating subagents should work in dedicated git worktrees, commit changes on their
branches, and require explicit human approval before integration into the main
workspace.
