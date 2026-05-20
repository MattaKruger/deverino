# SOUL Capability Contract Notes

This note captures the revised plan for updating
`harness_poc/system_prompts/SOUL.md` so the system persona reflects current
Deverino capabilities without overstating runtime behavior.

## Summary

The SOUL should be updated as a capability contract, not just a static tool
list. It should describe the harness as a PydanticAI-backed Deverino runtime
that coordinates chat, built-in tools, executable skills, knowledge skills,
workflows, pipelines, autonomous goals, and SQL-backed runtime state.

The new knowledge layer is now part of that contract. It gives the agent a
token-efficient catalog of procedural knowledge skills and lets the agent load
full skill instructions on demand through built-in tools.

## Verified Context

- `app_factory.py` initializes a knowledge context at startup using project
  skills first and system skills second, then builds a skill catalog and passes
  it into `build_runtime(..., skill_catalog=skill_catalog)`.
- `pydantic_runtime.py` appends the skill catalog to the system prompt when the
  catalog is non-empty.
- `skill_catalog.py` scans `type: knowledge` `SKILL.md` files and injects a
  mandatory `<available_skills>` block containing names and descriptions only.
- `skill_runner.py` deliberately excludes `type: knowledge` skills from the
  executable tool list. Knowledge skills are context documents, not callable
  executable skills.
- `knowledge_tools.py` registers `skills_list`, `skill_view`, and
  `skill_manage` as built-in tools.
- `skills_list` returns the knowledge skill index; `skill_view` loads the main
  skill body or a supporting file; `skill_manage` can create, patch, or delete
  knowledge skills.
- `skill_view` strips frontmatter, substitutes `${PROJECT_ROOT}`,
  `${SESSION_ID}`, and `${SCRATCH_DIR}` when values are available, exposes
  supporting files from `references/`, `templates/`, `scripts/`, and `assets/`,
  and rejects supporting-file paths that escape the skill directory.
- `skill_preprocessing.py` contains inline-shell expansion helpers, but
  `skill_view` currently only calls template substitution. The SOUL should not
  claim inline shell expansion as active behavior unless that path is wired in.
- `tests/test_knowledge_tools.py` covers discovery, catalog generation,
  template substitution, supporting-file loading, path escape protection,
  create/patch/delete, and exclusion from executable skills.
- `skills/deverino-test-knowledge/SKILL.md` is a project-local knowledge skill
  fixture. Because it lives in `skills/`, it will appear in the runtime
  knowledge catalog unless it is intentionally removed or moved into test
  fixtures.

## Revised Plan For SOUL

1. **Core Identity**: Define the agent as the primary Deverino orchestration
   agent for local chat, tools, executable skills, knowledge skills, workflows,
   pipelines, goal loops, and SQL-backed runtime state.
2. **Runtime Capabilities**: Describe PydanticAI streaming chat, configurable
   DeepSeek/OpenAI/Anthropic providers, fallback/mock behavior when API keys are
   absent, EventBus/blackboard context, and optional Logfire observability.
3. **Knowledge Layer Contract**: Add a dedicated section explaining that
   knowledge skills are markdown instruction documents with `type: knowledge`;
   they are indexed in `<available_skills>`, loaded with `skill_view`, and not
   executed directly.
4. **Tool And Skill Policy**: Distinguish built-in tools, skill-backed tools,
   executable skills, knowledge skills, and direct `/skill` invocation. State
   which capabilities may be used during normal chat and which require explicit
   commands.
5. **Knowledge Use Policy**: Instruct the agent to scan the injected
   `<available_skills>` catalog before replying, load any relevant knowledge
   skill with `skill_view`, and follow the loaded instructions. If no skill is
   relevant, proceed without forcing a tool call.
6. **Knowledge Maintenance Policy**: Say `skill_manage` may be used to save or
   fix reusable knowledge only when doing so is part of the task or clearly
   useful after a difficult/iterative task. Avoid implying that the agent should
   mutate knowledge on every turn.
7. **Codebase Grounding**: Keep the `semble_search` rule for implementation
   questions and require file/line references from search results in answers.
8. **State And Memory**: Treat injected STATE as compact durable context, not a
   transcript. Only claim persistence when a memory, state, or knowledge
   operation actually succeeded.
9. **Delegation**: Describe `delegate_task` as configured-model, persona-based
   local subagent delegation that writes results to the blackboard. Do not claim
   a remote worker fleet or guaranteed parallel execution.
10. **Safety And Error Handling**: Respect permissions/protected paths, report
    database/parsing/workflow/tool errors plainly, avoid repeated failed tool
    calls, and avoid raw JSON unless requested or passing through a tool result.

## Proposed SOUL Sections

Use this high-level shape when editing `SOUL.md`:

1. `Core Identity`
2. `Communication Parameters`
3. `Runtime Model`
4. `Knowledge Layer`
5. `Tools And Skills`
6. `Workflow, Pipeline, And Goal Invocation`
7. `State, Memory, And Persistence`
8. `Delegation`
9. `Codebase Grounding`
10. `Safety And Error Handling`
11. `Tool Result Policy`

## Open Decisions

- Decide whether `skills/deverino-test-knowledge/SKILL.md` should remain in
  the project skills directory. If it is only a smoke fixture, move it under
  tests or keep it out of the runtime skill catalog.
- Decide whether `skill_view` should call `expand_inline_shell`. If not, remove
  inline-shell language from persona docs and keep the helper documented only as
  future/prep work.
- Decide whether `skill_manage` should stay broadly auto-invokable or whether
  the SOUL should add a stricter "only create/patch/delete knowledge when
  explicitly useful" constraint.
- Consider making the knowledge catalog cache key include nested `SKILL.md`
  mtimes if runtime edits need to refresh without process restart. Current
  startup wiring makes catalog freshness mostly a startup concern.
- `scratch_base` is currently passed as `None` in `app_factory.py`, so
  `${SCRATCH_DIR}` remains unresolved when viewing knowledge skills unless this
  is wired later.

## Source Pointers

- `harness_poc/app_factory.py`: AppState wiring, prompt/state assembly,
  knowledge context initialization, skill catalog injection, tool and skill
  runners, blocked TUI skills, workflows, pipelines, and Logfire wiring.
- `harness_poc/core/skill_catalog.py`: scans `type: knowledge` files and builds
  the injected `<available_skills>` block.
- `harness_poc/system_tools/knowledge_tools.py`: `skills_list`, `skill_view`,
  `skill_manage`, supporting-file loading, path escape guard, and template
  substitution.
- `harness_poc/core/skill_preprocessing.py`: template substitution and
  currently-unwired inline-shell expansion helper.
- `harness_poc/core/skill_runner.py`: executable skill discovery and explicit
  exclusion of `type: knowledge` skills.
- `harness_poc/core/pydantic_runtime.py`: PydanticAI runtime, skill catalog
  prompt augmentation, tool adapters, tool-result policy, `semble_search`
  budget, and provider model construction.
- `harness_poc/core/config.py`: provider configuration and path/runtime config.
- `harness.yaml`: current configured provider/model, database URL, runtime
  limits, and observability settings.
- `harness_poc/core/tool_runner.py`: built-in tool discovery plus skill-backed
  tool discovery.
- `harness_poc/system_tools/file_tools.py`: host file primitives.
- `harness_poc/core/workflow_runner.py`: explicit YAML workflow state-machine
  execution.
- `harness_poc/core/pipeline_runner.py`: declarative DAG pipeline execution.
- `harness_poc/core/goal_runner.py`: autonomous ReAct-style goal loop.
- `harness_poc/system_skills/delegate_task/skill.py`: configured-model
  persona-based delegation.
- `harness_poc/core/permissions.py` and
  `harness_poc/core/blackboard_proxy.py`: permission and protected-path
  boundaries.
- `tests/test_knowledge_tools.py`: current expected behavior for the knowledge
  layer.
