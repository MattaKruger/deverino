# Dashboard Skill Metrics View

**Date:** 2026-06-20
**Status:** draft

## 1. Goal

Add a `/skills` view to the Deverino dashboard showing compilation status, contract metrics, and template details for every skill in the project. This surfaces the `SkillBundle` data produced by the skill compiler (see `docs/plans/2026-06-20-skill-pseudocode-refactor.md`) in the Vue 3 dashboard.

## 2. Current Architecture

```
dashboard-ui/src/
├── types/dashboard.ts          ← TypeScript interfaces (DashboardSummary, SkillPerformance, ...)
├── api/endpoints.ts            ← fetch*() functions → GET /api/*
├── stores/                     ← Pinia stores (createPollingStore composable, 5-15s poll)
├── views/                      ← Vue SFCs (OverviewView, SessionsView, TokensView, ...)
└── router.ts                   ← lazy-loaded routes

harness_poc/
├── api/routes.py               ← FastAPI router: @router.get("/api/...")
├── core/observability/dashboard.py ← fetch_*() functions + dataclasses
└── core/skills/skill_compiler.py   ← compile_skill(), bundle cache, get_compilation_status()
```

Pattern: `fetch_*()` → SQL queries → frozen dataclass → FastAPI route → `createPollingStore` → Vue `Panel` component.

## 3. Data Model

### 3.1 New Backend Types (`harness_poc/core/observability/dashboard.py`)

```python
@dataclass(frozen=True, slots=True)
class SkillContractSummary:
    name: str
    description: str
    input_count: int
    output_count: int
    precondition_count: int
    error_condition_count: int
    cancellation_behavior: str  # "safe" | "unsafe" | "unknown"

@dataclass(frozen=True, slots=True)
class SkillTemplateSummary:
    name: str
    kind: str  # "shell" | "python" | "api" | "db_query"
    template_preview: str  # first 120 chars of the template

@dataclass(frozen=True, slots=True)
class SkillCompilationSummary:
    name: str
    skill_type: str           # "knowledge" | "tool" | "skill"
    version: str
    compilation_status: str   # "full" | "partial" | "rejected" | "not_compiled"
    contract_count: int
    template_count: int
    invoke_pattern_count: int
    error_count: int
    compiled_at: str          # ISO timestamp, or "" if not compiled
    contracts: list[SkillContractSummary]
    templates: list[SkillTemplateSummary]
    compilation_errors: list[str]
    aliases: list[str]

@dataclass(frozen=True, slots=True)
class CompilationProgress:
    running: bool
    total: int
    completed: int
    errors: int
```

### 3.2 New Frontend Types (`dashboard-ui/src/types/dashboard.ts`)

Mirror of the above as TypeScript interfaces.  Also add a `SkillCompilationSummary` import to `endpoints.ts`.

### 3.3 Fetch Function (`harness_poc/core/observability/dashboard.py`)

```python
def fetch_skill_compilation_summaries(skill_runner) -> list[SkillCompilationSummary]:
    """Return compilation status for all discovered skills.

    Reads the skill compiler's in-memory bundle cache.  Skills that
    have never been compiled show ``compilation_status="not_compiled"``.
    Does NOT query the database — all data is from the compiler cache.
    """
```

The function walks `skill_runner.skills_dirs`, calls `skill_runner.discover_skills()` to get metadata, and checks `skill_compiler._cache` for bundles.  For each skill it constructs a `SkillCompilationSummary`.

## 4. API & Routes

### 4.1 New Endpoints

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/skills` | `list[SkillCompilationSummary]` |
| GET | `/api/skills/progress` | `CompilationProgress` |

### 4.2 Route Registration (`harness_poc/api/routes.py`)

```python
@router.get("/api/skills")
def get_skills(request: Request) -> list[SkillCompilationSummary]:
    # Needs access to skill_runner — currently routes only have engine.
    # The skill_runner is stored on app.state at startup.
    return fetch_skill_compilation_summaries(request.app.state.skill_runner)

@router.get("/api/skills/progress")
def get_compilation_progress(request: Request) -> CompilationProgress:
    from harness_poc.core.skills.skill_compiler import get_compilation_status
    status = get_compilation_status()
    return CompilationProgress(**status)
```

### 4.3 Wiring at Startup (`harness_poc/api/__init__.py`)

The `create_app()` function currently stores `engine` on `app.state`.  We also need to store `skill_runner`.  The `skill_runner` is created in `app_factory.py`'s `build_runtime_layer()` — but the FastAPI app is created separately via `create_app(database_url)`.  We have two options:

**Option A (simpler):** Store `skill_runner` on `app.state` when the FastAPI app is built.  Requires the `create_app()` factory to accept an optional `skill_runner` parameter.

**Option B:** Reconstruct `skill_runner` inside the route from the engine + config.  Simpler route code, duplicates the runner construction.

**Decision: Option A.**  Update `create_app()` and `create_app_from_config()` to accept and store `skill_runner`.

## 5. Frontend

### 5.1 New Files

| File | Purpose |
|------|---------|
| `dashboard-ui/src/stores/skills.ts` | Pinia store polling `/api/skills` every 15s |
| `dashboard-ui/src/views/SkillsView.vue` | Main view — summary cards + expandable skill list |

### 5.2 Modified Files

| File | Change |
|------|--------|
| `dashboard-ui/src/types/dashboard.ts` | Add `SkillCompilationSummary`, `SkillContractSummary`, `SkillTemplateSummary`, `CompilationProgress` |
| `dashboard-ui/src/api/endpoints.ts` | Add `fetchSkills()`, `fetchCompilationProgress()` |
| `dashboard-ui/src/router.ts` | Add `/skills` route |

### 5.3 View Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Compilation Progress  (hidden when idle)                    │
│  ████████████████░░░░░░  12/50 compiled · 2 errors           │
├──────────────────────────────────────────────────────────────┤
│  Summary cards                                                │
│  ┌──────────┬──────────┬──────────┬──────────┐              │
│  │ Full     │ Partial  │ Rejected │ Not      │              │
│  │   42     │    3     │    5     │ Compiled │              │
│  └──────────┴──────────┴──────────┴──────────┘              │
│                                                               │
│  Skill list (expandable rows)                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ ◉ semble_search     tool    v1.0   2 contracts  2 tmpl  │ │
│  │   ├─ Contract: semble_search                            │ │
│  │   │  inputs: query(str), top_k(int), mode(enum), ...    │ │
│  │   │  outputs: content(str), artifacts{query, results}   │ │
│  │   │  pre: [semble CLI installed]                        │ │
│  │   │  errors: [semble not found → pip install semble]    │ │
│  │   ├─ Template: search                                   │ │
│  │   │  "semble search '{query}' --top-k {top_k} --mode..." │ │
│  │   └─ Template: find_related                             │ │
│  │      "semble find-related {file_path} {line} --top-k..." │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ ○ read_memory       tool    v1.0   0 contracts  0 tmpl  │ │
│  │   ⚠ No procedural units found in body                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

Status indicators: ◉ green (full), ◎ amber (partial), ○ red (rejected), ◌ grey (not compiled).

### 5.4 Store

```typescript
export const useSkillsStore = createPollingStore<SkillCompilationSummary[]>(
  'skills',
  fetchSkills,
  15000,
)
```

The view also imports `useCompilationProgressStore` for the progress bar (polled at 5s via a separate store or inline `fetchCompilationProgress` call).

### 5.5 Navigation

Add "Skills" link to the dashboard sidebar alongside "Overview", "Sessions", "Sub-Agents", "Tokens", "Context Map".  The sidebar is rendered in `App.vue` — check if it uses explicit links or a route-driven nav.

## 6. Implementation Plan

```
Phase 1: Backend types + fetch function
  - Add SkillCompilationSummary, SkillContractSummary, SkillTemplateSummary to dashboard.py
  - Add CompilationProgress to dashboard.py (or import from skill_compiler)
  - Add fetch_skill_compilation_summaries(skill_runner) to dashboard.py
  - Add get_compilation_progress() endpoint data wrapper

Phase 2: API routes + wiring
  - Add /api/skills and /api/skills/progress routes to routes.py
  - Store skill_runner on app.state in create_app()
  - Update create_app_from_config() to pass skill_runner

Phase 3: Frontend types + API
  - Add TypeScript interfaces to dashboard.ts
  - Add fetchSkills(), fetchCompilationProgress() to endpoints.ts

Phase 4: Frontend view
  - Create SkillsView.vue with summary cards + expandable skill list
  - Create stores/skills.ts
  - Add route to router.ts

Phase 5: Navigation
  - Add "Skills" link to dashboard sidebar
```

## 7. Non-Goals

- Drill-down into individual TypedContract details (pre/post conditions fully expanded) — deferred
- Filtering/searching the skill list — deferred
- SSE-based real-time compilation progress — polling is sufficient
- Editing skills from the dashboard — read-only view
