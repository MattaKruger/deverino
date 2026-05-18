---
name: spec_writer
description: Interactively drafts implementation specs from goals, context, constraints, and open questions.
version: "1.0"
parameters:
  type: object
  properties:
    goal:
      type: string
      description: Feature, change, or product intent to turn into a spec.
    context:
      type: string
      description: Existing behavior, user need, or technical background.
    mode:
      type: string
      description: >
        gather = multi-turn Q&A that produces an XML context document;
        draft = write a markdown spec from flat inputs or a completed gather session;
        refine = improve an existing draft;
        questions = return clarifying questions only.
      enum:
        - gather
        - draft
        - refine
        - questions
    gather_key:
      type: string
      description: >
        Blackboard key for gather session state. In gather mode, persists phase
        progress across calls. In draft/refine mode, reads a completed XML context
        from this key if one exists. Defaults to spec_gather_state.
    answer:
      type: string
      description: >
        The user's answer to the most recent gather question. Pass on every gather
        call after the first. Empty string or omit on the first call.
    output_key:
      type: string
      description: Memory key where the spec draft should be stored. Defaults to spec_writer_result.
    title:
      type: string
      description: Optional title for the generated spec.
    requirements:
      type: string
      description: Known functional requirements or acceptance expectations.
    constraints:
      type: string
      description: Technical, product, or delivery constraints.
    non_goals:
      type: string
      description: Explicitly excluded scope.
    open_questions:
      type: string
      description: Known unresolved questions to include in the final spec.
    use_llm:
      type: boolean
      description: Whether to allow LLM drafting after clarity checks pass. Defaults to false.
  required: []
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: read_write
---

# Skill: Spec Writer

## Purpose
Interactively drafts implementation-ready specs while keeping the harness in charge of intent gathering.

## Behavior

### gather mode (multi-turn)
1. On each call, reads current phase from the blackboard (`gather_key`).
2. If `answer` is non-empty, applies it to the current phase and advances.
3. Returns the question for the new phase with `status: needs_orchestrator_action`.
4. Phase sequence: project overview → feature request → component names → per-component detail (one loop iteration per component) → constraints → complete.
5. When complete, generates and writes an XML context document to `specs/` and returns `status: success`.

### draft / refine mode
1. If `gather_key` points to a completed gather session, passes the XML context to the LLM instead of flat inputs (requires `use_llm: true`).
2. Falls back to flat inputs (`goal`, `context`, `requirements`, etc.) when no completed gather session is found or `use_llm` is false.
3. Writes the resulting markdown spec to `specs/` and stores it in blackboard memory under `output_key`.

### questions mode
Returns up to 3 clarifying questions without drafting anything.

## Expected Output
Returns a `SkillResult` with the markdown spec or clarifying questions plus artifacts for the memory key and spec path.
