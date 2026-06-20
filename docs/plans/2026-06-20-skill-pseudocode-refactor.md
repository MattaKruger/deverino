# Skill Pseudocode Refactor

**Date:** 2026-06-20
**Status:** draft
**Paper:** Skill-as-Pseudocode: Refactoring Skill Libraries to Pseudocode for LLM Agents (arXiv:2605.27955)

## 1. Problem

Deverino's skill body format is raw markdown prose. Every time an agent loads a skill via `skill_view()` or the skill runner mounts a knowledge skill into context, the LLM must re-derive structure from natural language: *what* the skill does (typed contract), *how* to invoke it (concrete syntax), and *with what* arguments (grounded invocation). This cost compounds across every retrieval.

The YAML frontmatter captures `name`, `description`, `parameters` (JSON Schema), and `entrypoint` — but the **body** remains unstructured prose. The agent sees this:

```markdown
## Behavior
1. Runs `semble search` or `semble find-related` as a subprocess.
2. Captures stdout and returns it as formatted markdown.
3. Falls back to a helpful error message if Semble is not installed.
```

And must derive: *the exact command to run, the argument mapping from input parameters to CLI flags, the exit-code interpretation, the output format contract.*

SaP proves this cost is recoverable **at index time** with a mostly-deterministic pipeline. Only 2 of 8 stages require an LLM; the rest are deterministic checks.

## 2. Desired Outcome

When a skill is loaded (whether as knowledge context or as an executed tool), the agent receives a **structured pseudocode bundle** — not raw markdown. The bundle contains:

| Component | What it delivers | SaP term |
|-----------|-----------------|----------|
| **Typed signature** | JSON Schema inputs/outputs + pre/post conditions | *contract* |
| **Concrete action templates** | Exact subprocess invocations, CLI flags, API calls, file paths the skill performs | *action templates* |
| **Grounded invocation patterns** | Fully-resolved examples mapping real argument values to real calls | *invoke placeholders* |
| **Parent skeleton** | The original skill body with sub-procedures replaced by typed `invoke(κ, args)` calls | *parent skeleton* |

The conversion from prose → pseudocode happens **once at index time** (when `SKILL.md` changes). The agent reads the already-structured bundle at retrieval time.

## 3. Current Architecture (Baseline)

### 3.1 Skill Types and Loading Paths

```
SkillRunner.discover_skills()
├── knowledge → SkillCatalog._scan_knowledge_skills()
│   └── Builds <available_skills> block (name + description only)
│   └── Agent calls skill_view(name) → loads full SKILL.md body
├── tool → Registered as LLM-callable tool
│   └── execute_tool() → execute_skill() → import skill.py → execute(context, args)
└── skill → Same execution path as tool, but not auto-invokable
```

### 3.2 Skill Document Structure (`SKILL.md`)

```
---                          ← YAML frontmatter (parsed by parse_skill_document)
name: semble_search
type: tool
description: ...
parameters: {...}            ← JSON Schema (already structured!)
entrypoint: {...}            ← module/function to call
permissions: {...}
---
# Markdown body              ← UNSTRUCTURED — this is the target
## Purpose
## Behavior
## Expected Output
```

### 3.3 What's Already Structured

- `parameters` — JSON Schema with types, enums, defaults, required fields
- `entrypoint` — module path and function name
- `permissions` — blackboard access, workspace access
- `type` — knowledge | tool | skill
- `auto_invokable` — boolean

**Note:** `version` appears in many skill frontmatters (e.g., `"1.0"`, `"1.0.0"`) but `SkillMetadata` (line 26-32 of `skill_runner.py`) does not capture it. The compiler will extract it and include it in `SkillBundle.version`.

### 3.4 What's Unstructured (the SaP Target)

- The markdown **body** — purpose, behavior steps, expected output format, error handling
- The mapping from `parameters` to actual tool invocations (CLI flags, API calls, DB queries)
- The output contract (what `SkillResult.content` and `.artifacts` will contain)
- Pre/post conditions, side effects, idempotency guarantees

### 3.5 Relevant Files

| File | Role |
|------|------|
| `harness_poc/core/skills/skill_runner.py` | Skill discovery, parsing, execution |
| `harness_poc/core/skills/skill_catalog.py` | Knowledge skill catalog for system prompt |
| `harness_poc/core/skills/skill_context.py` | `SkillContext`, `SkillRequest`, `SkillResult` |
| `harness_poc/core/skills/skill_preprocessing.py` | Template vars, inline shell expansion |
| `harness_poc/core/skills/skill_scaffolder.py` | Skill creation scaffolding |

## 4. Proposed Architecture

### 4.1 Skill Pseudocode Pipeline (Index Time)

A new module `harness_poc/core/skills/skill_compiler.py` runs when `SKILL.md` changes (detected via mtime, same cache strategy as `skill_catalog.py`). The pipeline is modeled on SaP's 8-stage process, compressed to 6 stages by merging grounded-example construction and invoke-placeholder generation into Stage 3 (a single LLM call per cluster can produce the contract, template, and invoke pattern simultaneously). SaP's optional recursive contract splitting and repair loops are deferred to v2 (see §9).

```
SKILL.md changed?
  │
  ▼
Stage 1: Parser
  Extract frontmatter (already structured) + body prose.
  Split body into procedural units:
    - A heading section (## X through next heading or EOF)
    - A fenced code block (``` ... ```) if it contains executable syntax
    - A numbered step (1. ...) describing a discrete action
    Units are non-overlapping; heading sections take precedence over
    contained code blocks and steps.
  │
  ▼
Stage 2: Candidate Clustering [deterministic, per-skill only in v1]
  Group procedural units within a single skill by semantic similarity
  (embedding cosine ≥ 0.65). Cross-skill pattern identification is
  deferred to v2 (see §8 Q6). Caching is per-file mtime — simple,
  no cascading invalidation.
  │
  ▼
Stage 3: Contract Extractor [LLM — single gpt-4o-mini call per cluster]
  For each cluster, generate a typed contract:
    - signature: inputs (mapped to frontmatter parameters), outputs, side effects
    - action template: exact shell command / API call / DB query
    - invoke pattern: grounded example with real argument values
    - error_conditions: known failure modes with recovery hints
  │
  ▼
Stage 4: Verifier [deterministic — four concrete checks]
  Each check returns "pass" or "fail with reason". All four must pass.

  Coverage: For every non-variable token in the action template,
    that token (case-insensitive, ignoring punctuation) must appear
    in the original body text OR in the frontmatter parameters.

  Binding: For each contract input name, there must exist a
    corresponding property in the frontmatter parameters.properties
    dict, OR the input must be in a "derived inputs" allowlist
    (e.g., action: enum[search, find_related] that the skill
    synthesizes from its own logic).

  Replacement: Substituting invoke(κ, args) placeholders into the
    parent body must produce syntactically valid markdown (balanced
    headings, no broken code fences, no orphaned list items).
    Semantic consistency with the original body is checked by the
    LLM pass (Stage 5/6), not by this deterministic check.

  Risk: No token in the contract name, input names, or output names
    may appear as a substring of an unrelated word in the parent body
    such that substitution would create a spurious match. E.g., if
    a contract is named "run", the parent body must not contain the
    word "runtime" in a way that would collide.
  │
  ▼
  Auto-promote (valid) or reject with check-level reason.
  Rejected contracts are recorded in compilation_errors.
  │
  ▼
Stage 5: Binding Evidence (BE) [LLM — optional, disabled by default]
  Confirm deterministic call-sites; drop spurious ones (~30% dropped).
  │
  ▼
Stage 6: Residual Cleanup (RC) [LLM — optional, disabled by default]
  Fix parent-residual conflicts (e.g., prose says "write to file"
  but actual code writes to DB).
  │
  ▼
  When BE and RC are disabled, the pipeline terminates at Stage 4.
  Contracts that pass verification are promoted directly into the
  SkillBundle. compilation_status is "full" if all contracts pass,
  "partial" if some pass and some are rejected.
  │
  ▼
Output: SkillBundle
  ├── metadata, version, entrypoint, aliases (from frontmatter)
  ├── parent_skeleton: body with invoke(κ, args) placeholders
  ├── contracts: dict[str, TypedContract] — promoted child procedures
  ├── templates: dict[str, ActionTemplate] — concrete invocation syntax
  ├── invoke_patterns: list[InvokePattern] — grounded examples
  ├── raw_body: original markdown (always present as fallback)
  ├── compilation_status: "full" | "partial" | "rejected"
  ├── compilation_errors: list[str] — rejection reasons
  └── compiled_at: float — timestamp
```

**Robustness — when the body has no parseable procedural units.** If Stage 1 produces zero units (e.g., pure narrative prose with no headings, steps, or code blocks), the pipeline short-circuits: `compilation_status = "rejected"`, `compilation_errors = ["No procedural units found in body"]`, `contracts` and `templates` are empty, `parent_skeleton = raw_body`. The agent receives the raw body with a prepended `[compilation-failed: No procedural units found]` notice. This preserves SaP's content-neutral property — the compiler doesn't judge skill quality, only structural parseability.

**Compilation failure fallback.** On any rejection ("rejected" or "partial"), the agent always receives `raw_body` alongside the partial bundle. The system prompt instructs the agent to use the raw prose for any skill whose `compilation_status` is not "full".

### 4.2 SkillBundle Data Model

**Supporting type: JSON Schema property descriptor**

```python
class JsonSchemaProperty(TypedDict, total=False):
    """A single property in a JSON Schema object. Mirrors JSON Schema draft."""
    type: str              # "string", "integer", "boolean", "array", "object"
    description: str
    enum: list[str]
    default: Any
    required: bool
    items: dict[str, Any]  # when type="array"
```

**Core types**

```python
@dataclass(slots=True)
class ErrorContract:
    """A specific failure mode the agent can recognize and handle."""
    condition: str          # e.g., "semble CLI is not installed"
    output_shape: str       # e.g., "skill_result.status = 'failed', content contains error message"
    recovery_hint: str      # e.g., "Install semble: pip install semble"

@dataclass(slots=True)
class ActionTemplate:
    """Concrete invocation syntax the skill actually executes."""
    kind: Literal["shell", "python", "api", "db_query"]
    template: str          # e.g., "semble search '{query}' --top-k {top_k}"
    argument_map: dict[str, str]  # parameter_name → template variable

@dataclass(slots=True)
class TypedContract:
    """Typed pseudocode signature for a sub-procedure."""
    name: str
    description: str
    inputs: dict[str, JsonSchemaProperty]    # subset of frontmatter parameters
    outputs: dict[str, JsonSchemaProperty]   # expected output shape
    side_effects: list[str]                  # "writes to blackboard", "creates file"
    preconditions: list[str]                 # "semble CLI is installed"
    postconditions: list[str]                # "skill_result.status is 'success'"
    error_conditions: list[ErrorContract]    # known failure modes with recovery hints
    cancellation_behavior: Literal["safe", "unsafe", "unknown"] = "unknown"
        # safe: no side effects if cancelled; unsafe: partial writes possible
    shared_from: str | None = None
        # v2: when this contract is factored from another skill's body

@dataclass(slots=True)
class InvokePattern:
    """Grounded example mapping real arguments to real calls.

    Invariant: arguments must conform to the corresponding TypedContract.inputs
    schema. Validated at compile time; note in compilation_errors if validation fails.
    """
    contract_name: str
    arguments: dict[str, Any]   # concrete values
    rendered_call: str          # fully-substituted action template

@dataclass(slots=True)
class SkillBundle:
    """The structured representation delivered to the agent."""
    metadata: SkillMetadata                # name, type, description, parameters, auto_invokable, permissions
    version: str                           # from frontmatter "version" field
    entrypoint: dict[str, str]             # {"module": "skill", "function": "execute"} — from frontmatter
    aliases: list[str]                     # e.g., ["delegate_to_subagent"] — from alias table
    parent_skeleton: str                   # body with invoke() placeholders
    contracts: dict[str, TypedContract]    # child procedures (empty for monolithic skills)
    templates: dict[str, ActionTemplate]   # concrete invocation syntax
    invoke_patterns: list[InvokePattern]   # grounded examples
    raw_body: str                          # original markdown (fallback)
    compilation_status: Literal["full", "partial", "rejected"]
        # full: all contracts passed verification
        # partial: some contracts passed, some rejected (agent gets partial bundle + raw_body)
        # rejected: no contracts passed (agent gets raw_body with diagnostics)
    compilation_errors: list[str]          # check-level rejection reasons
    compiled_at: float                     # time.time() when compilation completed
    shared_contracts: dict[str, TypedContract]  # v2: contracts shared across multiple skills
```

**Base case — monolithic skills.** When the body has no identifiable sub-procedures (e.g., a single flat paragraph), the compiler produces a single `TypedContract` named after the skill itself with `inputs` matching the frontmatter `parameters`. `contracts` contains this single entry. `parent_skeleton` is the raw body unchanged. This is the common case for simple skills like `evaluate_goal` or `read_memory`.

### 4.3 Retrieval-Time Substitution

When an agent loads a skill (either via `skill_view()` for knowledge skills, or during tool registration for executable skills), the `SkillBundle` is delivered instead of raw markdown:

```
Currently:
  Agent receives: raw SKILL.md body as string
  Agent must: parse markdown, infer steps, guess invocation syntax

Proposed:
  Agent receives: SkillBundle with typed contracts + action templates + invoke patterns
  Agent can: directly use the typed signature for argument mapping,
            reference the action template for exact invocation syntax,
            validate outputs against the contract's output schema
```

### 4.4 Integration Points

`parse_skill_document()` is **not** modified — it continues to return `SkillDocument` with raw `body` for tool registration and execution routing. A separate `compile_skill(skill_path)` → `SkillBundle` produces the structured representation. This keeps the hot path (tool discovery, execution) unchanged.

| Integration Point | Change |
|------------------|--------|
| `skill_compiler.compile_skill(path)` | **New.** Runs the pipeline, returns `SkillBundle`. Called when `SKILL.md` mtime changes. |
| `SkillCatalog._scan_knowledge_skills()` | Unchanged — continues returning name+description only (~50 tokens/skill). Summaries are loaded on demand via `skill_view()`. |
| `skill_view()` tool | Accepts optional `level` parameter: `"summary"` or `"full"`. Returns the bundle at the requested level (see §4.5). Default: `"summary"` when a bundle exists, `"full"` (raw markdown fallback) when no bundle exists. |
| System prompt builder | Unchanged — the `<available_skills>` catalog block is still name+description only. The eager-load instruction is updated: when bundles are available, the agent is told to prefer `skill_view(name, level='summary')` for contract signatures before escalating to `level='full'`. |
| `SkillContext` | Optional `bundle: SkillBundle | None` field (default `None`). Skills that want runtime self-validation against their contract can access it, but this is agent-facing documentation by default — no runtime enforcement in v1. |

### 4.5 Progressive Disclosure

The `SkillBundle` supports three levels of disclosure:

| Level | What's included | Token cost | When to use | `skill_view()` param |
|-------|----------------|-----------|-------------|---------------------|
| **Catalog** | `metadata.name` + `metadata.description` | ~50 tokens/skill | System prompt `<available_skills>` block | n/a (built into system prompt) |
| **Summary** | Contract signatures + template names + preconditions (no bodies, no invoke patterns) | ~150 tokens/skill | After `skill_view()` — decide if full load needed | `skill_view(name, level="summary")` |
| **Full** | Complete bundle: contracts, templates, invoke patterns, parent skeleton, error conditions | ~1-2K tokens/skill | When the agent needs to execute or deeply understand the skill | `skill_view(name, level="full")` |

**Level 2 (Summary) concrete format:**

```
Skill: semble_search
  Contract: semble_search(query: str, top_k: int = 5, mode: enum[hybrid|semantic|bm25] = hybrid,
              action: enum[search|find_related] = search, path: str?)
            → content: str (markdown), artifacts{query: str, results: list[str]}
  Templates: search, find_related
  Pre: semble CLI installed on PATH
  Errors: [semble not installed → content="semble CLI not found", recovery: pip install semble]
  Status: full
```

**`skill_view()` return schemas by level:**

Level `"summary"`:
```json
{
  "success": true,
  "name": "semble_search",
  "level": "summary",
  "version": "1.0",
  "compilation_status": "full",
  "contracts": [{"name": "semble_search", "inputs": {...}, "outputs": {...}, "preconditions": [...]}],
  "templates": ["search", "find_related"],
  "error_conditions": [{"condition": "...", "recovery_hint": "..."}]
}
```

Level `"full"`:
```json
{
  "success": true,
  "name": "semble_search",
  "level": "full",
  "version": "1.0",
  "compilation_status": "full",
  "content": "<parent_skeleton with invoke() placeholders>",
  "contracts": [{...full TypedContract...}],
  "templates": [{...ActionTemplate...}],
  "invoke_patterns": [{...InvokePattern...}],
  "raw_body": "<original markdown fallback>"
}
```

**Eager-load instruction update.** When the harness detects that bundles are available (at least one skill has `compilation_status != null`), the `<available_skills>` preamble changes from "you MUST load the skill" to:

> "If a skill matches your task, load it with `skill_view(name, level='summary')` first. If the summary provides enough detail, proceed. If the task requires deeper understanding (full contracts, templates, examples), escalate to `skill_view(name, level='full')`."

This resolves the tension between the current eager-load instruction and the fact that summaries already carry contract signatures.

## 5. What Changes vs. What Stays

### 5.1 New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `skill_compiler.py` | `harness_poc/core/skills/` | Index-time pseudocode pipeline (stages 1-6) |
| `SkillBundle` | `harness_poc/core/skills/skill_context.py` or new `skill_bundle.py` | Structured skill representation |
| `TypedContract`, `ActionTemplate`, `InvokePattern` | Same as above | Sub-components |
| Bundle cache | In-memory LRU, keyed by `SKILL.md` mtime | Avoid recompilation |

### 5.2 Modified Components

| Component | Change |
|-----------|--------|
| `skill_view()` tool | Accepts optional `level` parameter (`"summary"` or `"full"`); returns bundle at requested level; default `"summary"` when bundle exists, `"full"` (raw markdown) when no bundle |
| `SkillCatalog` system prompt preamble | Updated eager-load instruction: prefer `skill_view(name, level='summary')` when bundles exist |
| `SkillContext` | Optional `bundle: SkillBundle \| None` field added (default `None`); runtime consumers are opt-in |
| Skill alias table | Populates `SkillBundle.aliases` from `_resolve_alias` mappings |

**Not modified:** `SkillRunner.parse_skill_document()` — continues returning `SkillDocument` for tool registration and execution routing. The compilation path is a separate `skill_compiler.compile_skill()` call.

### 5.3 Unchanged Components

- **Frontmatter format** — `name`, `type`, `parameters`, `entrypoint`, `permissions` stay identical
- **Skill execution** — `execute_skill()`, `SkillContext`, `SkillResult` unchanged
- **Skill scaffolding** — `skill_scaffolder.py` unchanged
- **Permission system** — `SkillPermissions` unchanged
- **Template preprocessing** — `${PROJECT_ROOT}`, inline shell `!cmd` expansion runs at retrieval time on the `raw_body`, `parent_skeleton`, and `ActionTemplate.template` fields. It does NOT run at compile time, because `${PROJECT_ROOT}` and `${SESSION_ID}` have no concrete values at index time and running `!cmd` snippets prematurely could have unintended side effects. Inline shell snippets in the body are passed to the LLM as opaque tokens during Stage 3 compilation.
- **REPL `/skill show`** — continues displaying raw `SKILL.md` (developer-facing debugging). Bundle visualization is a separate future command (`/skill bundle <name>`).
- **`auto_invokable`** — compilation is uniform regardless of this flag. The consumer (agent, system prompt) decides whether to use contracts, templates, or both based on how the skill is loaded.

### 5.4 What Skill Authors Do Differently

Nothing. The pipeline reads existing `SKILL.md` files. Authors continue writing markdown as they do now. The compiler extracts structure from prose. No new authoring format.

(Cf. SaP conclusion: "SaP shows this cost is recoverable post hoc... paid at index time rather than at every read.")

However, if authors *want* to write structured contracts directly in the future, the pipeline can accept a `contracts:` frontmatter field as a pre-compiled input, skipping stages 2-4.

### 5.5 Runtime: `requested_actions` vs `parent_skeleton`

`SkillResult.requested_actions` (line 44-45 of `skill_context.py`) is the runtime mechanism for skills that chain other skills (e.g., `orchestrate` spawns workers). The `parent_skeleton`'s `invoke(κ, args)` placeholders conceptually model the same thing — but they are a **compile-time approximation** of what the skill *may* request at runtime. They are documentation for the agent, not runtime guarantees. The compiler does not validate runtime behavior against the skeleton in v1. Future work may add runtime validation of actual `requested_actions` against the parent skeleton.

### 5.6 Multi-File Skills (Supporting Files)

`skill_view()` already handles supporting files via `file_path` (line 116-133 of `knowledge_tools.py`). v1 compilation is scoped to `SKILL.md` body only. Supporting files (`references/`, `templates/`, `scripts/`, `assets/`) are loaded verbatim via the existing `file_path` mechanism and are not compiled. If `SKILL.md` references a supporting file ("See `references/api.md` for details"), the compiler treats this as an opaque cross-reference — it does not follow the link.

## 6. Concrete Example: `semble_search`

### 6.1 Current (Prose Body)

```markdown
## Behavior
1. Runs `semble search` or `semble find-related` as a subprocess.
2. Captures stdout and returns it as formatted markdown.
3. Falls back to a helpful error message if Semble is not installed.
```

### 6.2 Proposed (Generated SkillBundle)

```
SkillBundle
  version: "1.0"
  compilation_status: full
  aliases: []

TypedContract: semble_search
  inputs:
    action: enum[search, find_related]  (default: search)
    query: string                        (required)
    file_path: string                    (required when action=find_related)
    line: integer                        (required when action=find_related)
    path: string                         (default: project root)
    top_k: integer                       (default: 5)
    mode: enum[hybrid, semantic, bm25]   (default: hybrid)
  outputs:
    content: string   (markdown-formatted search results)
    artifacts:
      query: string   (echo of input query)
      results: list[string]  (raw stdout lines)
  side_effects: [spawns subprocess]
  preconditions: [semble CLI is installed on PATH]
  postconditions: [skill_result.status is "success" or "failed"]
  error_conditions:
    - condition: "semble CLI not installed"
      output_shape: "status='failed', content contains 'semble: command not found'"
      recovery_hint: "Install: pip install semble"
    - condition: "subprocess timeout"
      output_shape: "status='failed', content contains timeout message"
      recovery_hint: "Retry with smaller scope or increase timeout"
  cancellation_behavior: safe

ActionTemplate: search
  kind: shell
  template: >
    semble search '{query}'
    --top-k {top_k}
    --mode {mode}
    {path_flag}
  argument_map:
    query → query
    top_k → top_k
    mode → mode
    path → path_flag  (resolved to "--path {path}" or "" based on non-default)

ActionTemplate: find_related
  kind: shell
  template: >
    semble find-related {file_path} {line}
    --top-k {top_k}
  argument_map:
    file_path → file_path
    line → line
    top_k → top_k

InvokePattern: search example
  contract: semble_search
  arguments: {action: "search", query: "authentication flow", top_k: 5, mode: "hybrid"}
  rendered_call: "semble search 'authentication flow' --top-k 5 --mode hybrid"

ParentSkeleton:
  ## Behavior
  1. invoke(semble_search, {action, query, ...}) as a subprocess.
  2. Captures stdout and returns it as formatted markdown.
  3. invoke(fallback_error, {condition: "semble not installed"}) if precondition fails.
```

**Base case — monolithic skill (e.g., `evaluate_goal`).** A skill with a flat narrative body and no sub-procedures produces a bundle with a single self-named `TypedContract`, an empty `contracts` dict (the single contract IS the skill), `parent_skeleton = raw_body`, and `compilation_status = "full"` (if the contract passes verification). `templates` and `invoke_patterns` are empty — the skill has no templated invocation to extract.

## 7. LLM Budget & Performance

The compiler pipeline uses:

| Stage | LLM calls | Model | Notes |
|-------|-----------|-------|-------|
| Contract extractor | 1 per candidate cluster | gpt-4o-mini (configurable) | Only called when `SKILL.md` changes |
| BE (binding evidence) | 1 per skill | gpt-4o-mini (configurable) | Optional; disabled by default |
| RC (residual cleanup) | 1 per skill | gpt-4o-mini (configurable) | Optional; disabled by default |

With ~50 skills total and an average of 2-3 clusters per skill, the index-time LLM cost is approximately 100-150 calls — on the order of cents, paid once per change. The LLM provider is configurable (OpenAI, DeepSeek, Anthropic) via the existing PydanticAI provider configuration.

**Embedding model for Stage 2 clustering:** Uses the existing Vespa embedding service (see `docs/plans/2026-06-17-embedding-service.md`) or a local sentence-transformer as fallback. Per-skill clustering means vectors are computed once per `SKILL.md` change and cached alongside the bundle.

## 8. Open Questions

1. **Embedding model for clustering (Stage 2):** Resolved — uses the Vespa embedding service from the embedding service plan (`docs/plans/2026-06-17-embedding-service.md`). Per-skill clustering only, no cross-skill vector index in v1.

2. **Bundle cache invalidation:** Resolved — per-skill per-mtime caching for v1. No cascading invalidation because cross-skill sharing is deferred to v2.

3. **Knowledge skill bundles in the system prompt:** Resolved — catalog stays name+description only. Summaries loaded on demand via `skill_view(name, level='summary')`. No bundle content in the system prompt.

4. **LLM provider for contract extraction:** Should the pipeline also support DeepSeek or local models? The harness already supports multiple providers via PydanticAI. Implementation should accept a provider config parameter, defaulting to the harness's configured provider.

5. **Should we accept pre-compiled contracts?** Deferred to v2. The optional `contracts:` frontmatter field is a natural extension when authors want to bypass the pipeline, but no implementation in v1.

6. **Cross-skill contract sharing:** Deferred to v2. Data model reserves `TypedContract.shared_from` and `SkillBundle.shared_contracts` for this, but no implementation in v1.

7. **Runtime contract validation:** Should `execute_skill()` validate `SkillResult` against `TypedContract.outputs` and `error_conditions` at runtime? Deferred — contracts are agent-facing documentation in v1. Runtime validation is a natural v2 extension.

## 9. Non-Goals (Explicitly Out of Scope)

- **Changing the SKILL.md authoring format.** Authors continue writing markdown.
- **Modifying skill execution.** `execute_skill()`, `SkillContext`, `SkillResult` unchanged.
- **Real-time recompilation.** Pipeline runs only when `SKILL.md` changes on disk.
- **Recursive contract splitting / repair loops.** SaP's optional recursive stages are deferred (cf. SaP §5.1: "both are implemented but disabled by default").
- **Multi-language skill support.** English-only for v1 (cf. SaP §6 limitations).
- **Typed-API (Stripe/OpenAPI) skill ingestion.** Markdown-only for v1; cross-modality is architectural (cf. SaP §5.1).
- **Cross-skill contract sharing.** Data model reserves fields (`shared_from`, `shared_contracts`) but Stage 2 clustering is per-skill only in v1.
- **Runtime contract validation.** Contracts are agent-facing documentation in v1. No runtime enforcement of `TypedContract.outputs` against `SkillResult`.
- **Cancellation semantics in contracts.** `TypedContract.cancellation_behavior` is a data-model placeholder (default `"unknown"`). The compiler does not infer cancellation safety from the body in v1.
- **Multi-file skill compilation.** Only `SKILL.md` body is compiled. Supporting files (`references/`, `templates/`, etc.) are loaded verbatim via existing `skill_view(file_path=...)`.
- **REPL `/skill show` displaying bundles.** `/skill show` continues displaying raw `SKILL.md`. Bundle visualization is a separate future command.

## 10. Implementation Sketch

```
Phase 1: Data model + cache
  - Define SkillBundle, TypedContract, ActionTemplate, InvokePattern, ErrorContract,
    JsonSchemaProperty in skill_bundle.py
  - Add version, entrypoint, aliases extraction to parse_skill_document()'s SkillMetadata
  - Add in-memory LRU bundle cache keyed by per-file mtime
  - Add compile_skill(path) → SkillBundle entry point in skill_compiler.py

Phase 2: Deterministic pipeline (stages 1-2, 4)
  - Parser: extract procedural units from markdown body (headings, code blocks, numbered steps)
  - Clustering: per-skill embedding-based similarity (Vespa embedding service)
  - Verifier: four deterministic checks (coverage, binding, replacement, risk)
  - Fallback: return raw_body with compilation_status="rejected" when no units found

Phase 3: LLM passes (stages 3, 5-6)
  - Contract extractor: single LLM call per cluster, configurable provider
  - BE and RC: optional, disabled by default; enable with config flag

Phase 4: Retrieval-time integration
  - skill_view() accepts level="summary"|"full" parameter
  - System prompt preamble updated when bundles exist
  - SkillContext gets optional bundle field
  - skill_view() fallback to raw markdown when no bundle exists
```

## 11. References

- Skill-as-Pseudocode (arXiv:2605.27955) — `docs/papers/skill_as_pseudocode_refactoring_skill_libraries_to_pseudocode_for_llm_agents__2605.27955.pdf`
- SKCC (arXiv:2605.03353) — `docs/papers/skcc_portable_and_secure_skill_compilation_for_cross_framework_llm_agents__2605.03353.pdf`
- Skill Retrieval Augmentation (arXiv:2604.24594) — `docs/papers/skill_retrieval_augmentation_for_agentic_ai__2604.24594.pdf`
- Current skill runner: `harness_poc/core/skills/skill_runner.py`
- Current skill catalog: `harness_poc/core/skills/skill_catalog.py`
