# Plan Mode With Vespa-Indexed Outputs

## Goal

Add a `/plan` mode to the harness for read-only project exploration and research. Plan mode must not write files to the project workspace, but it may write to the blackboard and should embed the resulting plan into Vespa so future agents and processes can retrieve it semantically.

## Core Semantics

- `/plan <question>` runs a one-shot planning request.
- `/plan` without arguments can enter sticky plan mode.
- `/chat` or `/plan off` exits sticky plan mode and returns to normal chat.
- Plan mode produces plans, findings, risks, assumptions, and open questions.
- Plan mode does not implement changes or modify project files.
- Plan mode should strongly prefer `search_documents` for project docs, specs, plans, papers, and prior indexed plans before using code/file search.

## Permission Boundary

Plan mode should enforce the no-project-write rule at the runtime/tool layer, not only in the prompt.

Allowed:

- `search_documents`
- `read_file`
- `search_files`
- `skills_list`
- `skill_view`
- `read_memory`
- blackboard writes for plan persistence and retrieval metadata
- Vespa feed/upsert for the completed plan

Blocked:

- `write_file`
- `patch`
- `skill_manage`
- `execute_python`
- direct project skill execution that can write the workspace
- workflows, pipelines, and autonomous goal loops unless explicitly run outside plan mode

Blackboard writes are allowed. This means `search_documents` can keep its current `blackboard: read_write` permission so it can record retrieval/context-map events. The important restriction is no project filesystem writes.

## Runtime Design

Add a second runtime to `AppState`:

```python
plan_runtime: PydanticAgentRuntime
plan_messages: list[ModelMessage]
```

Build it beside the normal chat runtime in `build_app_state()`, using the normal SOUL, state context, context map, and skill catalog plus an additional plan-mode prompt.

The runtime builder should accept tool allowlists:

```python
allowed_builtin_tools = {
    "read_file",
    "search_files",
    "skills_list",
    "skill_view",
}

allowed_skill_tools = {
    "search_documents",
    "read_memory",
}
```

Use allowlists rather than blocklists so newly added write-capable tools are not accidentally exposed in plan mode.

## Plan Mode Prompt

Create `harness_poc/system_prompts/PLAN_MODE.md` and append it to the plan runtime system prompt.

The prompt should state:

- You are in read-only planning mode.
- Do not write or modify project files.
- Do not create, patch, or delete skills.
- Do not run implementation workflows, pipelines, or autonomous goals.
- Use `search_documents` early when the answer might live in indexed docs, specs, plans, papers, or prior plans.
- Use code/file search only when exact current code behavior is needed.
- Produce a plan with enough structure for another agent or process to execute later.
- Include evidence, citations, assumptions, risks, and open questions where relevant.

## Vespa Indexing Of Plans

Do not write a markdown file just to index the plan. Add a direct-content indexing path that chunks and feeds generated text to Vespa.

Add an API similar to:

```python
DocumentIndexer.index_text(
    uri=f"blackboard://plans/{session_id}/{plan_id}",
    title=title,
    kind="plan",
    text=plan_text,
    metadata={
        "session_id": session_id,
        "plan_id": plan_id,
        "query": user_query,
        "source": "plan_mode",
    },
    force=True,
)
```

This can reuse the existing retrieval primitives:

- `make_document_chunks(...)`
- `compute_content_hash(...)`
- `make_source_id(...)`
- `LiveVespaDocumentClient.feed_chunks(...)`
- document source/chunk metadata tables

Use stable synthetic URIs:

```text
blackboard://plans/<session_id>/<plan_id>
```

Future agents can retrieve plans with:

```json
{
  "query": "how should we add plan mode",
  "mode": "semantic",
  "kind": "plan"
}
```

## Blackboard Persistence

After the plan runtime returns a final plan:

1. Generate a stable `plan_id`.
2. Write the plan content and metadata to blackboard memory, for example `plan:{plan_id}`.
3. Feed the same content into Vespa through `index_text(...)`.
4. Append the assistant response to `plan_messages`, not normal `pydantic_messages`, unless the user explicitly promotes it.

Suggested blackboard payload:

```json
{
  "plan_id": "<id>",
  "session_id": "<session>",
  "query": "<original user request>",
  "content": "<final plan markdown>",
  "vespa_uri": "blackboard://plans/<session>/<id>",
  "kind": "plan",
  "created_at": "<iso8601>"
}
```

## REPL And TUI Wiring

In `harness_poc/repl.py`:

- Add `/plan` command detection before `/goal` and direct resource dispatch.
- Add `handle_plan_command(...)`.
- Add `handle_plan_input(...)` for sticky mode.
- Reuse the existing streaming callbacks.
- Track plan responses separately from normal chat history.

In `harness_poc/repl_completion.py`:

- Add `/plan` and `/chat` to root completions.

In the TUI:

- Show a small mode indicator when sticky plan mode is active.
- Keep output rendering the same as chat output.

## Tests

Add focused tests for:

- `/plan <text>` calls `plan_runtime`, not `pydantic_runtime`.
- Plan history is stored in `plan_messages`, not `pydantic_messages`.
- Plan runtime exposes `search_documents`.
- Plan runtime does not expose `write_file`, `patch`, `skill_manage`, or `execute_python`.
- Completed plans are written to blackboard.
- Completed plans are fed into Vespa with `kind="plan"`.
- `/plan` and `/chat` appear in completions.

## Acceptance Criteria

- A user can ask `/plan <question>` and get a research-grounded plan.
- The plan mode agent cannot write project files through exposed tools.
- The plan mode agent can write plan metadata/content to blackboard.
- The resulting plan is embedded into Vespa without creating a project file.
- Another agent or process can retrieve the plan semantically through `search_documents`.
- Existing normal chat, skill execution, workflows, pipelines, and goal mode continue to behave unchanged.
