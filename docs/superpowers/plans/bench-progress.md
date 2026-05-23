# Benchmark Progress

**Date:** 2026-05-23
**Plan:** [`docs/superpowers/plans/next-phases.md`](next-phases.md)
**Status:** Phase `create_rubrics` implemented — remaining phases not yet planned

---

## Completed: `create_rubrics` skill

### What was built

A harness skill that generates benchmark rubric `.md` files from natural-language
descriptions of expected agent behaviour. Conversational quality validation:
describe the scenario, review the generated rubric, confirm to persist, run
`just test-bench`.

**Files created:**

| File                                                        | Purpose                                               |
| ----------------------------------------------------------- | ----------------------------------------------------- |
| `skills/create_rubrics/SKILL.md`                            | YAML frontmatter: type=skill, parameters, permissions |
| `skills/create_rubrics/skill.py`                            | `execute()` entrypoint + LLM extraction + formatting  |
| `skills/create_rubrics/__init__.py`                         | Package marker                                        |
| `tests/GUIDE.md`                                            | Full testing guide extracted from README              |
| `docs/superpowers/specs/2026-05-23-create-rubrics-usage.md` | Usage guide with examples and troubleshooting         |

**Files modified:**

| File                               | Change                                                                                       |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| `README.md`                        | Testing section tightened (278 → 50 lines). Skills table updated. Points to `tests/GUIDE.md` |
| `tests/agent/harness.py`           | Moved `SkillResult` import to `TYPE_CHECKING`                                                |
| `tests/agent/test_skill_chains.py` | Fixed docstring format, `ITEM_COUNT` → `item_count`                                          |
| `tests/helpers.py`                 | Added `SkillResult` to `TYPE_CHECKING`, `# ty: ignore` annotations                           |
| `tests/bench/test_goal_quality.py` | `# ty: ignore` for pre-existing type issue                                                   |
| `tests/unit/test_*.py` (6 files)   | Import sorting, unused noqa cleanup, line length, `# ty: ignore`                             |

### Design decisions made

| Decision                                                           | Rationale                                                                                                                                                |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Structured LLM extraction** via `PromptedOutput(ExtractedGates)` | Uses PydanticAI's `Agent` with typed output model — the pattern from `GoalRunner`, now the preferred approach for skills that need structured LLM output |
| **Two-step HITL flow** (generate → review → confirm)               | Matches developer-pedagogy boundary condition: "Do not write files without showing the content first"                                                    |
| **Blackboard draft storage** (`rubric_draft:<slug>`)               | Durable inter-call state; artifacts on `SkillResult` don't survive between invocations                                                                   |
| **`needs_orchestrator_action` for preview**                        | Same pattern as `spec_writer` — orchestrator presents output, waits for user decision                                                                    |
| **Project skill** (`skills/`) not system                           | Rubrics are domain-specific, not harness infrastructure                                                                                                  |
| **Slug collision = blocked**                                       | No force-overwrite; user picks a new slug                                                                                                                |
| **No deterministic fallback**                                      | If LLM unavailable → `blocked`. Extracting structured gates from arbitrary natural language has no heuristic fallback                                    |
| **Rubric-only generation** (no test function auto-gen)             | Per plan: "Start with rubric-only — the test function follows a fixed template that can be automated later"                                              |
| **Judge model separate from extraction model**                     | Extraction uses harness-configured LLM; judge model stored in rubric config, defaults to haiku                                                           |

### What the plan got right

- **Integration surface was zero-change.** `rubric_loader.py` and `conftest.py` already parsed the exact format the skill generates. No modifications needed.
- **Rubric format** — the `Rubric` dataclass and `from_markdown()` parser handled the generated output without any adaptation.
- **Naming convention** — `test_<slug>` → `rubrics/<slug>.md` mapping worked as described.

### Divergence from plan

| Plan said                                                | Implemented as                                             | Why                                                                                                           |
| -------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| "Return the rubric content for review before persisting" | Two-step HITL with `needs_orchestrator_action` + `confirm` | Explicit confirmation step, not just "show and hope"                                                          |
| Skill auto-invokable during chat                         | Manual `/skill` invocation only                            | Rubric generation mutates the filesystem; auto-invocation would be surprising                                 |
| Temperature 0.0–0.2 for extraction                       | Default model temperature                                  | `LLMConfig` doesn't expose temperature; PydanticAI model defaults proved sufficient for structured extraction |

### Lint & type coverage

```
ruff check .    → All checks passed
ty check        → All checks passed
```

All 26 pre-existing ruff errors and 22 pre-existing ty errors fixed across the
test suite. Ruff auto-fixable issues (16) resolved with `--fix`. Remaining
manual fixes: import sorting, docstring formatting, `# noqa` annotations, and
`# ty: ignore` for `ty`'s lack of `# type: ignore` support.

### Documentation

- **Usage guide:** `docs/superpowers/specs/2026-05-23-create-rubrics-usage.md` — two-step flow, parameter reference, writing effective descriptions, slug conventions, troubleshooting, architecture diagram
- **Testing guide:** `tests/GUIDE.md` — full three-layer test documentation extracted from README (layer rules, unit/agent/bench examples, assertions table, rubric format, design decisions)
- **README:** Testing section now 50 lines (down from 278). Diagram, quick commands, `create_rubrics` quickstart, pointers to both guides

### Commits

```
e52166c Extract testing detail to tests/GUIDE.md, tighten README
50fa22a Add create_rubrics usage guide
a201838 Add create_rubrics skill for conversational benchmark generation
d323e6e Fix ruff and ty lint/type errors across test suite
```

---

## Remaining from plan

### Open questions (answered)

| Question                                | Answer                                                          |
| --------------------------------------- | --------------------------------------------------------------- |
| Generate benchmark test function too?   | No — rubric-only for now. Fixed template, automate later.       |
| Validate rubric by running immediately? | No — generation and execution stay separate. User decides when. |
| Namespace-scoped rubrics?               | Flat `tests/bench/rubrics/` for now. Namespace later if needed. |

### Future phases (not yet planned)

- Auto-generation of benchmark test functions from rubrics
- `--force` flag for slug overwrites
- Rubric validation/dry-run (parse + hard-gate check without LLM judge)
- Multi-model comparison (run same rubric against multiple benchmark models)
- Rubric namespacing (per session, per project)
