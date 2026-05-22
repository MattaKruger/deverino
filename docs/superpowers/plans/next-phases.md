# Next Phases

**Date:** 2026-05-23
**Status:** Planning — not yet implemented

---

## Phase: `create_rubrics` skill

A harness skill that generates rubric `.md` files from a natural-language
description of expected agent behaviour.

### Why it matters

The three-layer test architecture (unit → agent → bench) validates correctness
and quality. But writing rubrics is manual — you craft a `.md` file, define
hard gates, write a judge prompt. This is friction when you want to check a
behaviour right now, in the middle of a session.

`create_rubrics` removes that friction. You describe what the agent should do,
and the skill produces a validated rubric file. From there, one command runs
the benchmark:

```
describe scenario → create_rubrics → rubric.md → just test-bench
```

This makes quality validation **conversational**. You don't switch contexts to
write test infrastructure — you describe the expectation, the skill codifies
it, and the benchmark runs against a real LLM.

### On-the-fly scenario testing

The core loop:

1. **You observe behaviour** — the agent did something unexpected, or you want
   to verify a claim about its capabilities.
2. **You describe the scenario** — "The agent should read memory before
   answering questions about project state. It should not hallucinate file
   paths."
3. **`create_rubrics` generates a rubric** — hard gates (must_contain,
   must_not_contain, skill_sequence) and an LLM judge prompt.
4. **You run the benchmark** — `just test-bench` validates the rubric against a
   real LLM.
5. **You iterate** — adjust the rubric, re-run, compare models.

This turns the harness's own testing infrastructure into a tool the agent can
use during a session. You're not writing tests about the agent — the agent is
helping you write tests for the agent.

### Skill design

**Type:** Executable skill (`type: skill` in SKILL.md frontmatter)

**Inputs:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `description` | Yes | Natural-language description of the expected behaviour |
| `goal` | Yes | The goal string to pass to the agent during the benchmark |
| `slug` | No | Rubric filename slug (auto-generated from description if omitted) |
| `model` | No | Judge model override (default: haiku) |
| `threshold` | No | Judge score threshold (default: 0.7) |

**Output:** A `SkillResult` with the generated rubric content and the file
path where it was written.

**Behaviour:**

1. Parse the description into structured expectations:
   - **Content gates:** phrases the answer must or must not contain
   - **Process gates:** skills the agent should call, in what order
   - **Quality criteria:** what "good" means for the judge prompt
2. Generate the rubric `.md` file at `tests/bench/rubrics/<slug>.md`
3. Optionally generate a matching benchmark test function in
   `tests/bench/test_<slug>.py`
4. Return the rubric content for review before persisting

### Example interaction

```
User: /skill create_rubrics
      description: "The agent should call read_memory to get project state
      before answering. The answer must mention SQLite and session count.
      It must not say 'I don't know'."
      goal: "Summarise the current project state"
      slug: "summarise-project-state"

Agent: Created rubric at tests/bench/rubrics/summarise-project-state.md

       ## Hard Assertions
       - must_contain: "SQLite"
       - must_contain: "session"
       - must_not_contain: "I don't know"
       - min_words: 30
       - skill_sequence: [read_memory]

       ## LLM Judge
       threshold: 0.7
       model: claude-haiku-4-5-20251001
       prompt: |
         Score 0.0-1.0: does the answer accurately describe
         the project state, referencing the blackboard database
         and session information?

         Answer: {answer}

       Run with: just test-bench
```

### Integration points

- **Rubric loader** (`tests/bench/rubric_loader.py`): already parses the
  format this skill generates. No changes needed.
- **Benchmark conftest** (`tests/bench/conftest.py`): already supports the
  naming convention (`rubric_slug` → `rubrics/<slug>.md`). No changes needed.
- **GoalRunner**: the skill executes as a normal skill during a session. The
  generated rubric runs as a separate benchmark — not inside the same session.

### Implementation notes

The skill's `execute()` function needs to:

1. Validate the description is substantive enough to generate gates from
2. Use a model call (or structured heuristics) to extract must_contain /
   must_not_contain / skill_sequence from the description
3. Format the rubric `.md` file using the `Rubric` dataclass fields as a
   template
4. Write to `tests/bench/rubrics/` directory (configurable via harness config)
5. Return the path and a preview of the generated content

The model call inside the skill could use the same LLM provider as the
harness — it's generating structured text, not scoring. Temperature should be
low (0.0–0.2) for deterministic output.

### Open questions

- Should the skill also generate the benchmark test function, or just the
  rubric? (Start with rubric-only — the test function follows a fixed template
  that can be automated later.)
- Should the skill validate the rubric by running it immediately? (No — keep
  generation and execution separate. The user decides when to run.)
- Should rubrics be namespace-scoped (per session, per project)? (Start
  flat — all rubrics in `tests/bench/rubrics/`. Namespace later if needed.)
