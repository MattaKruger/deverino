# Spec Writer Skill Plan

Created: 2026-05-18 17:24:17 Europe/Brussels

## Goal

Add a project-local `spec_writer` skill that helps turn a rough feature idea into a structured implementation spec through an interactive process.

The skill should gather intent when it is missing, preserve unanswered questions, and produce a practical spec artifact that can guide later planning and execution. It should fit the current harness model: skills are discoverable in the REPL, executable with `/skill spec_writer ...`, and return `SkillResult` objects.

## Current Fit

The harness already supports:

- Project skills under `skills/<name>/`.
- Skill metadata and JSON-schema parameters in `SKILL.md`.
- Python entrypoints via `skill.py`.
- REPL execution of named skills with JSON, key-value, or single positional arguments.
- Slash completion for discovered skill names.
- Session memory and STATE via the blackboard database.

This means the first pass can be implemented as a normal project skill without changing CLI routing.

## Proposed Skill Contract

Name: `spec_writer`

Description: `Interactively drafts implementation specs from goals, context, constraints, and open questions.`

Parameters:

```yaml
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
      enum: [draft, refine, questions]
      description: Draft a spec, refine an existing draft, or return clarifying questions.
    output_key:
      type: string
      description: Optional memory key where the spec draft should be stored.
  required: []
```

Default behavior:

- If `goal` is missing, return `blocked` with concise clarifying questions.
- If important intent is unclear, return `needs_orchestrator_action` with questions instead of inventing requirements.
- If enough context exists, return a markdown spec and store it in session memory under `spec_writer_result` or the provided `output_key`.

## Interactive Process

The skill should use a small deterministic question model before drafting:

1. Confirm the problem or desired outcome.
2. Identify users or callers affected by the change.
3. Capture functional requirements.
4. Capture non-goals and constraints.
5. Capture acceptance criteria and test expectations.
6. Capture open questions instead of hiding ambiguity.

When intent is unclear, the skill should ask at most three focused questions. It should prefer questions that unblock implementation decisions, not broad product brainstorming.

## Spec Output Shape

The generated spec should be markdown with stable headings:

```markdown
# <Spec Title>

## Objective
## Background
## Requirements
## Non-Goals
## Proposed Behavior
## Acceptance Criteria
## Test Plan
## Open Questions
```

Keep output implementation-oriented. Avoid long prose unless the user provided complex domain context.

## Implementation Plan

### Phase 1: Scaffold the Skill

Create `skills/spec_writer/` with:

- `SKILL.md`
- `skill.py`
- `__init__.py`

Use the existing skill frontmatter pattern and declare read/write blackboard permission because the skill stores drafts in session memory.

### Phase 2: Implement Deterministic Drafting

In `skill.py`:

- Normalize `goal`, `context`, `mode`, and `output_key`.
- Route `mode="questions"` directly to clarifying questions.
- For `draft`, validate whether `goal` is present.
- Build a markdown spec from provided fields and safe defaults.
- Store the markdown spec with `ctx.database.write_memory(...)`.
- Return `SkillResult(status="success", content=spec, artifacts={...})`.

This keeps the first implementation reliable and testable without requiring an API key.

### Phase 3: Add Refine Mode

For `mode="refine"`:

- Read the previous draft from `output_key` or `spec_writer_result`.
- Apply supplied `goal` and `context` as additional input.
- Return a revised markdown spec.
- If no previous draft exists, fall back to `draft` or return `blocked` with a clear message.

### Phase 4: Add REPL/CLI Ergonomics If Needed

The current `/skill spec_writer ...` path should work automatically after discovery.

Optional later improvements:

- Add `/spec <goal>` as a REPL shortcut.
- Add `harness-poc spec draft <goal>` as a Typer command.
- Add completion hints for `mode=draft`, `mode=refine`, and `mode=questions`.

Do not add these until the base skill is useful.

### Phase 5: Tests

Add focused tests for:

- Missing `goal` returns `blocked` or `needs_orchestrator_action`.
- `mode="questions"` returns at most three questions.
- A valid draft returns markdown with the stable headings.
- Draft output is written to session memory.
- `mode="refine"` uses an existing memory value.

Use temporary SQLite databases like the existing skill tests. Avoid asserting on exact full markdown; assert on status, headings, artifacts, and persisted memory.

## Open Questions

- Resolved: spec drafts should be written to `/specs`.
- Resolved: the skill may call the configured LLM, but only after harness-side validation confirms enough intent is present for a concise implementation-ready spec.
- Resolved: open questions should appear in the final spec, not be written automatically to STATE.

## Recommended First Slice

Implement the project-local skill with deterministic `draft`, `questions`, and `refine` modes, store drafts in session memory, write markdown specs to `specs/`, and add tests. LLM drafting should be gated behind the same clarity checks and fall back to deterministic markdown when no API key is configured or the model output is not spec-shaped.
