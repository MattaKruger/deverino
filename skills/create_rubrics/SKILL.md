---
name: create_rubrics
type: skill
description: >-
  Generates benchmark rubric .md files from natural-language descriptions
  of expected agent behaviour. Use this to create quality-validation rubrics
  conversationally — describe the scenario, review the generated rubric,
  confirm to write it to tests/bench/rubrics/.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    description:
      type: string
      description: >-
        Natural-language description of the expected agent behaviour.
        Include what the answer should and should not contain, what
        skills the agent should call, and what "good" means.
    goal:
      type: string
      description: The goal string to pass to the agent during the benchmark.
    slug:
      type: string
      description: >-
        Rubric filename slug (auto-generated from description if omitted).
        Required when confirming a previously generated draft.
    model:
      type: string
      description: Judge model override. Defaults to claude-haiku-4-5-20251001.
    threshold:
      type: number
      description: Judge score threshold. Defaults to 0.7.
    confirm:
      type: boolean
      description: >-
        Set to true to write a previously generated draft rubric to disk.
        Requires slug to locate the draft.
  required: [description, goal]
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: read_write
---

# create_rubrics

Generates benchmark rubric `.md` files from natural-language descriptions
of expected agent behaviour. Two-step flow:

1. **Describe** the scenario — the skill extracts hard gates
   (`must_contain`, `must_not_contain`, `skill_sequence`) and generates
   an LLM judge prompt from your description.
2. **Review** the generated rubric in the chat, then **confirm** to
   persist it to `tests/bench/rubrics/<slug>.md`.

Once written, run the benchmark with:

    just test-bench

Or directly:

    pytest tests/bench/ --run-benchmarks

## Examples

**Generate a rubric:**

    /skill create_rubrics
    description="The agent should call read_memory before answering.
    The answer must mention SQLite and session count.
    It must not say 'I don't know'."
    goal="Summarise the current project state"

**Confirm and write:**

    /skill create_rubrics confirm=true slug="summarise-project-state"

## Output

Returns the formatted rubric content for review. On confirmation,
writes the `.md` file and returns the path.
