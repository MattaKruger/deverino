# create_rubrics — Usage Guide

**Date:** 2026-05-23
**Status:** Implemented — `skills/create_rubrics/`

---

## What it does

`create_rubrics` generates benchmark rubric `.md` files from natural-language
descriptions of expected agent behaviour. You describe what the agent should
do, and the skill produces a validated rubric that can be run immediately
against a real LLM.

This turns quality validation **conversational** — no context-switching to
write test infrastructure.

```
describe scenario → /skill create_rubrics → rubric.md → just test-bench
```

## Why use it

The three-layer test architecture (`tests/unit/` → `tests/agent/` →
`tests/bench/`) validates correctness and quality. Rubrics define:

- **Hard gates** (substring checks, word counts, skill sequences) — free,
  deterministic, run against both mock and live sessions
- **LLM judge** (semantic quality scoring) — costs tokens, runs only in
  benchmarks against a real model

Writing these by hand means crafting `.md` files with precise format, defining
judge prompts, and remembering the naming conventions. `create_rubrics` removes
this friction.

## Two-step flow

### Step 1 — Describe the behaviour

Invoke the skill with a description of what the agent should do and the goal
it will be given. The skill calls an LLM to extract structured gates.

```
/skill create_rubrics
description="The agent should call read_memory to get project state
before answering. The answer must mention SQLite and session count.
It must not say 'I don't know' or hallucinate file paths."
goal="Summarise the current project state"
```

The skill returns the generated rubric for review:

```markdown
# Rubric: summarise-the-current-project-state

## Goal

Summarise the current project state

## Hard Assertions

- must_contain: "SQLite"
- must_contain: "session"
- must_not_contain: "I don't know"
- must_not_contain: "hallucinate"
- min_words: 30
- skill_sequence: [read_memory]

## LLM Judge

threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score 0.0-1.0: does the answer accurately describe the project
  state, referencing the blackboard database and session information?

  Answer: {answer}
```

The rubric is stored as a draft in blackboard memory. Nothing is written to
disk yet.

### Step 2 — Review and confirm

If the generated rubric looks correct, confirm to persist it:

```
/skill create_rubrics confirm=true slug="summarise-the-current-project-state"
```

The skill writes `tests/bench/rubrics/summarise-the-current-project-state.md`
and cleans up the draft. If the slug already exists, the skill blocks with a
message — pick a different slug.

### Running the benchmark

Once written, the rubric is immediately runnable. Create a matching test
function or run the existing one:

```python
# tests/bench/test_goal_quality.py
def test_summarise_the_current_project_state(
    live_session: _LiveSession,
    rubric: Rubric,
) -> None:
    result = live_session.run(rubric.goal)
    rubric.assert_hard_gates(result, events=live_session.events)
    score = rubric.judge(result.content, config=live_session.state.config.llm)
    assert score is not None
    assert score >= rubric.judge_threshold
```

The `rubric` fixture auto-resolves the test name to a rubric file:
`test_summarise_the_current_project_state` → `rubrics/summarise-the-current-project-state.md`.

Run with:

```bash
just test-bench
# or:
pytest tests/bench/ --run-benchmarks
```

## Parameter reference

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `description` | Step 1 | string | — | Natural-language description of expected behaviour |
| `goal` | Step 1 | string | — | Goal string the agent receives during the benchmark |
| `slug` | Step 2 | string | auto | Rubric filename slug (hyphenated, no extension) |
| `model` | optional | string | `claude-haiku-4-5-20251001` | Judge model for the LLM Judge section |
| `threshold` | optional | number | `0.7` | Minimum judge score for the benchmark to pass |
| `confirm` | Step 2 | boolean | `false` | Set to `true` to write a reviewed draft to disk |

If `slug` is omitted in Step 1, it is auto-generated from the `goal` string
(preferred when ≤80 chars) or the `description`.

## Writing effective descriptions

The LLM extraction works best when descriptions are specific about:

- **What the answer must contain** — exact phrases, not paraphrases. "Must
  mention SQLite" becomes `must_contain: "SQLite"`. "Must reference the
  session table" becomes `must_contain: "session"`.
- **What the answer must not contain** — evasion language ("I don't know"),
  hallucinated details, or incorrect claims.
- **Which skills should be invoked** — use actual skill names from the harness
  (`read_memory`, `semble_search`, `web_search`, `delegate_task`).
- **What "good" means** — the judge prompt is generated from your description,
  so describe quality criteria: accuracy, completeness, specificity.

Example of a strong description:

```
The agent should call semble_search to find the authentication module, then
read_memory to check for cached results. The answer must reference the exact
file path harness_poc/core/auth.py. It must not say "I'm not sure" or
speculate about implementation details it hasn't verified. A good answer
identifies the module's responsibility, lists its public functions, and
notes any configuration dependencies.
```

## Slug conventions

Slugs map directly to test function names and rubric filenames:

| Slug | Rubric file | Test function |
|------|-------------|---------------|
| `summarise-project-state` | `rubrics/summarise-project-state.md` | `test_summarise_project_state` |
| `agent-reads-memory-first` | `rubrics/agent-reads-memory-first.md` | `test_agent_reads_memory_first` |

Use descriptive, hyphenated slugs. Avoid generic names like `test-1` or
`rubric` — the slug is how you find the rubric later.

## Troubleshooting

**"No live LLM is available"** — the skill requires a configured LLM provider.
Check your `harness.yaml` and environment variables (`DEEPSEEK_API_KEY`,
`OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`).

**"No draft found for slug"** — you're trying to confirm without generating
first. Run the skill without `confirm` to create a draft.

**"Rubric file already exists"** — the slug is taken. Choose a different slug
or remove the existing file if you want to replace it.

**Extraction quality is poor** — the LLM extracts gates from your description.
If the output misses constraints you intended, be more explicit in the
description. Use phrases like "must contain X" and "must not contain Y"
directly — the extraction prompt is designed to recognize these patterns.

## Integration with the test architecture

```
┌─────────────────────────────────────────────────────────┐
│  create_rubrics skill                                    │
│                                                          │
│  description ──► LLM extraction ──► rubric .md          │
│  goal              (ExtractedGates)    │                 │
│                                         │                │
│  Review ──► confirm ──► write to disk   │                │
│                                         ▼                │
│                              tests/bench/rubrics/        │
│                                         │                │
│                                         ▼                │
│                              pytest --run-benchmarks     │
│                                         │                │
│                      ┌──────────────────┴──────────┐     │
│                      │                              │     │
│                      ▼                              ▼     │
│              Hard Gates (free)              LLM Judge ($) │
│              - must_contain                  - quality   │
│              - must_not_contain              - 0.0–1.0   │
│              - min_words                                 │
│              - skill_sequence                            │
└─────────────────────────────────────────────────────────┘
```

Hard gates act as a fail-fast layer — they catch structural problems before
spending tokens on the LLM judge. The judge only fires if all hard gates pass.

## Related docs

- `docs/superpowers/plans/next-phases.md` — planning doc for the create_rubrics phase
- `docs/superpowers/specs/2026-05-22-testing-architecture-design.md` — full test architecture
- `tests/bench/rubric_loader.py` — `Rubric` dataclass and markdown parser
- `tests/bench/conftest.py` — benchmark fixtures and naming conventions
