# Core Module Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `harness_poc/core/` from a flat namespace of ~35 files into cohesive subpackages, with each subpackage's `__init__.py` re-exporting its public API.

**Architecture:** Eight new subpackages (`storage`, `events`, `skills`, `tools`, `runtime`, `execution`, `retrieval`, `observability`) plus consolidation of `processor_supervisor.py` into the existing `processors/` package. Each `__init__.py` re-exports the full public API of the files it contains, so callers update from `from harness_poc.core.event_bus import X` to `from harness_poc.core.events import X` — one namespace hop instead of the old per-file imports. Files at `core/` root (`config.py`, `logging.py`, `permissions.py`) are not moved; everything depends on them and they're too foundational to isolate.

**Tech Stack:** Python 3.14, `git mv` for renames (preserves history), `sed` for mechanical import rewrites, `uv run pytest` + `uv run ruff check .` + `uv run ty check` to verify.

---

## Dependency order for migration (bottom → top)

```
config, logging, permissions  ← stay at core/ root, no deps
storage/      ← db_engine, models, state, database, blackboard_proxy
events/       ← events, event_bus, event_store, event_log_observer, context_map_events
skills/       ← skill_context, skill_runner, skill_catalog, skill_scaffolder, skill_preprocessing
tools/        ← tool_context, tool_result, tool_runner
runtime/      ← llm_client, message_history, token_accounting, reducers, pydantic_runtime, goal_runner
processors/   ← already exists; absorb processor_supervisor
execution/    ← workflow_runner, pipeline_runner, materializer_runner
retrieval/    ← retrieval, vespa_client, document_index, pdf_converter
observability/← dashboard, logfire_subscriber
```

**Import rewrite convention:** `from harness_poc.core.<old_flat_module> import X` → `from harness_poc.core.<subpackage> import X`. The `__init__.py` re-exports make this the canonical path.

---

## Task 1: `storage/` subpackage

Moves: `state.py`, `db_engine.py`, `models.py`, `database.py`, `blackboard_proxy.py`

Note: `state.py` goes here (not `runtime/`) because `database.py` imports `StatePayload`, `StateProposal`, `StateSection` from it directly.

**Files:**
- Create: `harness_poc/core/storage/__init__.py`
- Move: `harness_poc/core/state.py` → `harness_poc/core/storage/state.py`
- Move: `harness_poc/core/db_engine.py` → `harness_poc/core/storage/db_engine.py`
- Move: `harness_poc/core/models.py` → `harness_poc/core/storage/models.py`
- Move: `harness_poc/core/database.py` → `harness_poc/core/storage/database.py`
- Move: `harness_poc/core/blackboard_proxy.py` → `harness_poc/core/storage/blackboard_proxy.py`

- [ ] **Step 1: Move files with git (preserves history)**

```bash
mkdir -p harness_poc/core/storage
git mv harness_poc/core/state.py harness_poc/core/storage/state.py
git mv harness_poc/core/db_engine.py harness_poc/core/storage/db_engine.py
git mv harness_poc/core/models.py harness_poc/core/storage/models.py
git mv harness_poc/core/database.py harness_poc/core/storage/database.py
git mv harness_poc/core/blackboard_proxy.py harness_poc/core/storage/blackboard_proxy.py
```

- [ ] **Step 2: Fix intra-package imports in the moved files**

Each moved file that imported from another moved file must update to the new absolute path. Run these from the repo root:

```bash
# database.py imports db_engine, models, state
sed -i '' 's|from harness_poc\.core\.db_engine import|from harness_poc.core.storage.db_engine import|g' harness_poc/core/storage/database.py
sed -i '' 's|from harness_poc\.core\.models import|from harness_poc.core.storage.models import|g' harness_poc/core/storage/database.py
sed -i '' 's|from harness_poc\.core\.state import|from harness_poc.core.storage.state import|g' harness_poc/core/storage/database.py

# blackboard_proxy.py imports database, models, state
sed -i '' 's|from harness_poc\.core\.database import|from harness_poc.core.storage.database import|g' harness_poc/core/storage/blackboard_proxy.py
sed -i '' 's|from harness_poc\.core\.models import|from harness_poc.core.storage.models import|g' harness_poc/core/storage/blackboard_proxy.py
sed -i '' 's|from harness_poc\.core\.state import|from harness_poc.core.storage.state import|g' harness_poc/core/storage/blackboard_proxy.py

# models.py has no core deps to update
```

- [ ] **Step 3: Create `__init__.py` with full re-exports**

Inspect what each file exports first:
```bash
grep -n "^class \|^def \|^[A-Z][A-Za-z]* = " harness_poc/core/storage/state.py
grep -n "^class \|^def \|^[A-Z][A-Za-z]* = " harness_poc/core/storage/db_engine.py
grep -n "^class \|^def \|^[A-Z][A-Za-z]* = " harness_poc/core/storage/models.py
grep -n "^class \|^def " harness_poc/core/storage/database.py
grep -n "^class \|^def " harness_poc/core/storage/blackboard_proxy.py
```

Then write `harness_poc/core/storage/__init__.py`:

```python
from harness_poc.core.storage.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.storage.database import BlackboardDatabase
from harness_poc.core.storage.db_engine import create_db_engine
from harness_poc.core.storage.models import (
    DbContextMap,
    DbContextMapEvent,
    DbDocumentChunk,
    DbDocumentSource,
    DbProjectState,
    DbSession,
    DbSessionMessage,
    DbSessionState,
    DbSharedMemory,
    DbStateEvent,
    DbStateProposal,
    SQLModel,
)
from harness_poc.core.storage.state import (
    ProposalStatus,
    StatePayload,
    StateProposal,
    StateSection,
)

__all__ = [
    "BlackboardAccessProxy",
    "BlackboardDatabase",
    "create_db_engine",
    "DbContextMap",
    "DbContextMapEvent",
    "DbDocumentChunk",
    "DbDocumentSource",
    "DbProjectState",
    "DbSession",
    "DbSessionMessage",
    "DbSessionState",
    "DbSharedMemory",
    "DbStateEvent",
    "DbStateProposal",
    "SQLModel",
    "ProposalStatus",
    "StatePayload",
    "StateProposal",
    "StateSection",
]
```

> **Note:** Run `grep -n "^class \|^def \|^[A-Z]" harness_poc/core/storage/*.py` to verify the symbol list is complete before moving on. Add any missing public symbols to both the imports and `__all__`.

- [ ] **Step 4: Rewrite external imports to use new package path**

```bash
# All files across the repo that imported the flat modules
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.database import/from harness_poc.core.storage import/g' \
  -e 's/from harness_poc\.core\.models import/from harness_poc.core.storage import/g' \
  -e 's/from harness_poc\.core\.db_engine import/from harness_poc.core.storage import/g' \
  -e 's/from harness_poc\.core\.blackboard_proxy import/from harness_poc.core.storage import/g' \
  -e 's/from harness_poc\.core\.state import/from harness_poc.core.storage import/g'
```

> **Caveat:** This sed rewrites all matching lines to `from harness_poc.core.storage import`. If a file imports from both `database` and `models` separately, it will now have two lines both saying `from harness_poc.core.storage import ...` — that's fine, Python deduplicates at runtime. Ruff may flag duplicate imports; merge them manually if flagged.

- [ ] **Step 5: Run lint and type check**

```bash
uv run ruff check .
uv run ty check
```

Fix any reported issues before continuing. Common issues:
- Duplicate import lines from the sed merge (combine manually)
- Missing symbols in `__init__.py` `__all__` (add them)
- TYPE_CHECKING blocks that sed missed (update manually)

- [ ] **Step 6: Run tests**

```bash
uv run pytest -x -q
```

Expected: full suite passes. If failures mention `ModuleNotFoundError: harness_poc.core.database`, the sed missed a file — grep for it and fix manually:
```bash
grep -r "harness_poc\.core\.database" . --include="*.py"
```

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/storage/ harness_poc/core/storage/__init__.py
git add -u  # stage all modified files (import rewrites)
git commit -m "refactor: move storage modules into core/storage/ subpackage"
```

---

## Task 2: `events/` subpackage

Moves: `events.py`, `event_bus.py`, `event_store.py`, `event_log_observer.py`, `context_map_events.py`

Note: `events.py` becomes `core/events/events.py` — the package name matches the module name, but Python resolves the package directory over the `.py` file so this is safe. Callers using `from harness_poc.core.events import X` continue to work via `__init__.py`.

**Files:**
- Create: `harness_poc/core/events/__init__.py`
- Move: `harness_poc/core/events.py` → `harness_poc/core/events/events.py`
- Move: `harness_poc/core/event_bus.py` → `harness_poc/core/events/event_bus.py`
- Move: `harness_poc/core/event_store.py` → `harness_poc/core/events/event_store.py`
- Move: `harness_poc/core/event_log_observer.py` → `harness_poc/core/events/event_log_observer.py`
- Move: `harness_poc/core/context_map_events.py` → `harness_poc/core/events/context_map_events.py`

- [ ] **Step 1: Move files**

```bash
mkdir -p harness_poc/core/events
# Must rename events.py BEFORE creating the events/ directory, or git gets confused.
# Since we already have the directory from the mkdir, git mv works:
git mv harness_poc/core/events.py harness_poc/core/events/events.py
git mv harness_poc/core/event_bus.py harness_poc/core/events/event_bus.py
git mv harness_poc/core/event_store.py harness_poc/core/events/event_store.py
git mv harness_poc/core/event_log_observer.py harness_poc/core/events/event_log_observer.py
git mv harness_poc/core/context_map_events.py harness_poc/core/events/context_map_events.py
```

> **Important:** `events.py` is being moved INTO the `events/` directory. Git needs the destination directory to exist before the `git mv`. The `mkdir -p` above handles this.

- [ ] **Step 2: Fix intra-package imports**

```bash
# event_bus.py imports events (now events/events.py)
sed -i '' 's|from harness_poc\.core\.events import|from harness_poc.core.events.events import|g' harness_poc/core/events/event_bus.py
sed -i '' 's|from harness_poc\.core\.event_store import|from harness_poc.core.events.event_store import|g' harness_poc/core/events/event_bus.py

# event_store.py imports events
sed -i '' 's|from harness_poc\.core\.events import|from harness_poc.core.events.events import|g' harness_poc/core/events/event_store.py

# event_log_observer.py and context_map_events.py — check for cross-deps:
grep "from harness_poc.core" harness_poc/core/events/event_log_observer.py
grep "from harness_poc.core" harness_poc/core/events/context_map_events.py
# Update any hits following the same pattern above
```

- [ ] **Step 3: Create `__init__.py`**

```python
from harness_poc.core.events.context_map_events import ContextMapEvent
from harness_poc.core.events.event_bus import EventBus
from harness_poc.core.events.event_log_observer import EventLogObserver
from harness_poc.core.events.event_store import EventStore
from harness_poc.core.events.events import (
    AgentInputAdded,
    AgentStarted,
    AgentTurnRecorded,
    BaseEvent,
    GoalEvaluated,
    LLMActionEmitted,
    LLMTextEmitted,
    PipelineCompleted,
    PipelineNodeCompleted,
    PipelineNodeStarted,
    PipelineStarted,
    SkillCalled,
    SkillCancelled,
    SkillCompleted,
    SkillRequested,
    StreamPaused,
    SubAgentCompleted,
    SubAgentDispatched,
)

__all__ = [
    "ContextMapEvent",
    "EventBus",
    "EventLogObserver",
    "EventStore",
    "AgentInputAdded",
    "AgentStarted",
    "AgentTurnRecorded",
    "BaseEvent",
    "GoalEvaluated",
    "LLMActionEmitted",
    "LLMTextEmitted",
    "PipelineCompleted",
    "PipelineNodeCompleted",
    "PipelineNodeStarted",
    "PipelineStarted",
    "SkillCalled",
    "SkillCancelled",
    "SkillCompleted",
    "SkillRequested",
    "StreamPaused",
    "SubAgentCompleted",
    "SubAgentDispatched",
]
```

Run `grep "^class " harness_poc/core/events/events.py` to get the complete class list and ensure nothing is missed.

- [ ] **Step 4: Rewrite external imports**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.event_bus import/from harness_poc.core.events import/g' \
  -e 's/from harness_poc\.core\.event_store import/from harness_poc.core.events import/g' \
  -e 's/from harness_poc\.core\.event_log_observer import/from harness_poc.core.events import/g' \
  -e 's/from harness_poc\.core\.context_map_events import/from harness_poc.core.events import/g'
```

> `from harness_poc.core.events import` was already the canonical path for event types — those imports need no change (they now resolve via `__init__.py` which re-exports from `events/events.py`).

- [ ] **Step 5: Also update storage/ files that import from events**

The files moved in Task 1 (database.py, blackboard_proxy.py) may import `context_map_events`:
```bash
grep "harness_poc.core.context_map_events\|harness_poc.core.event" harness_poc/core/storage/*.py
# Update any hits manually or with sed
```

- [ ] **Step 6: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/events/
git add -u
git commit -m "refactor: move event modules into core/events/ subpackage"
```

---

## Task 3: `skills/` subpackage

Moves: `skill_context.py`, `skill_runner.py`, `skill_catalog.py`, `skill_scaffolder.py`, `skill_preprocessing.py`

**Files:**
- Create: `harness_poc/core/skills/__init__.py`
- Move each of the 5 files into `harness_poc/core/skills/`

- [ ] **Step 1: Move files**

```bash
mkdir -p harness_poc/core/skills
git mv harness_poc/core/skill_context.py harness_poc/core/skills/skill_context.py
git mv harness_poc/core/skill_runner.py harness_poc/core/skills/skill_runner.py
git mv harness_poc/core/skill_catalog.py harness_poc/core/skills/skill_catalog.py
git mv harness_poc/core/skill_scaffolder.py harness_poc/core/skills/skill_scaffolder.py
git mv harness_poc/core/skill_preprocessing.py harness_poc/core/skills/skill_preprocessing.py
```

- [ ] **Step 2: Fix intra-package imports**

```bash
# skill_context.py imports permissions (stays at core/ root) — no path update needed

# skill_runner.py imports skill_context and blackboard_proxy
sed -i '' 's|from harness_poc\.core\.skill_context import|from harness_poc.core.skills.skill_context import|g' harness_poc/core/skills/skill_runner.py
sed -i '' 's|from harness_poc\.core\.blackboard_proxy import|from harness_poc.core.storage import|g' harness_poc/core/skills/skill_runner.py

# skill_scaffolder.py imports skill_context
sed -i '' 's|from harness_poc\.core\.skill_context import|from harness_poc.core.skills.skill_context import|g' harness_poc/core/skills/skill_scaffolder.py

# Check remaining files for cross-deps
grep "from harness_poc.core" harness_poc/core/skills/skill_catalog.py
grep "from harness_poc.core" harness_poc/core/skills/skill_preprocessing.py
```

- [ ] **Step 3: Create `__init__.py`**

```python
from harness_poc.core.skills.skill_catalog import SkillCatalog
from harness_poc.core.skills.skill_context import (
    CancellationToken,
    SkillContext,
    SkillRequest,
    SkillResult,
    SkillStatus,
)
from harness_poc.core.skills.skill_preprocessing import SkillPreprocessor
from harness_poc.core.skills.skill_runner import SkillRunner
from harness_poc.core.skills.skill_scaffolder import SkillScaffolder

__all__ = [
    "SkillCatalog",
    "CancellationToken",
    "SkillContext",
    "SkillRequest",
    "SkillResult",
    "SkillStatus",
    "SkillPreprocessor",
    "SkillRunner",
    "SkillScaffolder",
]
```

Run `grep "^class \|^def \|^[A-Z][A-Za-z]* = " harness_poc/core/skills/*.py` to complete the symbol list and update `__all__` accordingly.

- [ ] **Step 4: Rewrite external imports**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.skill_context import/from harness_poc.core.skills import/g' \
  -e 's/from harness_poc\.core\.skill_runner import/from harness_poc.core.skills import/g' \
  -e 's/from harness_poc\.core\.skill_catalog import/from harness_poc.core.skills import/g' \
  -e 's/from harness_poc\.core\.skill_scaffolder import/from harness_poc.core.skills import/g' \
  -e 's/from harness_poc\.core\.skill_preprocessing import/from harness_poc.core.skills import/g'
```

- [ ] **Step 5: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/skills/
git add -u
git commit -m "refactor: move skill modules into core/skills/ subpackage"
```

---

## Task 4: `tools/` subpackage

Moves: `tool_context.py`, `tool_result.py`, `tool_runner.py`

**Files:**
- Create: `harness_poc/core/tools/__init__.py`
- Move 3 files into `harness_poc/core/tools/`

- [ ] **Step 1: Move files**

```bash
mkdir -p harness_poc/core/tools
git mv harness_poc/core/tool_context.py harness_poc/core/tools/tool_context.py
git mv harness_poc/core/tool_result.py harness_poc/core/tools/tool_result.py
git mv harness_poc/core/tool_runner.py harness_poc/core/tools/tool_runner.py
```

- [ ] **Step 2: Fix intra-package imports**

```bash
# tool_runner.py imports skill_context (now skills) and tool_context/tool_result
sed -i '' 's|from harness_poc\.core\.skill_context import|from harness_poc.core.skills import|g' harness_poc/core/tools/tool_runner.py
sed -i '' 's|from harness_poc\.core\.tool_context import|from harness_poc.core.tools.tool_context import|g' harness_poc/core/tools/tool_runner.py
sed -i '' 's|from harness_poc\.core\.tool_result import|from harness_poc.core.tools.tool_result import|g' harness_poc/core/tools/tool_runner.py

# tool_context.py imports skill_context
sed -i '' 's|from harness_poc\.core\.skill_context import|from harness_poc.core.skills import|g' harness_poc/core/tools/tool_context.py
```

- [ ] **Step 3: Create `__init__.py`**

```python
from harness_poc.core.tools.tool_context import ToolContext
from harness_poc.core.tools.tool_result import ToolResult
from harness_poc.core.tools.tool_runner import ToolRunner

__all__ = ["ToolContext", "ToolResult", "ToolRunner"]
```

- [ ] **Step 4: Rewrite external imports**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.tool_context import/from harness_poc.core.tools import/g' \
  -e 's/from harness_poc\.core\.tool_result import/from harness_poc.core.tools import/g' \
  -e 's/from harness_poc\.core\.tool_runner import/from harness_poc.core.tools import/g'
```

- [ ] **Step 5: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/tools/
git add -u
git commit -m "refactor: move tool modules into core/tools/ subpackage"
```

---

## Task 5: `runtime/` subpackage

Moves: `llm_client.py`, `message_history.py`, `token_accounting.py`, `reducers.py`, `pydantic_runtime.py`, `goal_runner.py`

Note: `state.py` was moved to `storage/` in Task 1. `reducers.py` likely imports `models.py` (now `storage`) — verify with grep.

**Files:**
- Create: `harness_poc/core/runtime/__init__.py`
- Move 6 files into `harness_poc/core/runtime/`

- [ ] **Step 1: Move files**

```bash
mkdir -p harness_poc/core/runtime
git mv harness_poc/core/llm_client.py harness_poc/core/runtime/llm_client.py
git mv harness_poc/core/message_history.py harness_poc/core/runtime/message_history.py
git mv harness_poc/core/token_accounting.py harness_poc/core/runtime/token_accounting.py
git mv harness_poc/core/reducers.py harness_poc/core/runtime/reducers.py
git mv harness_poc/core/pydantic_runtime.py harness_poc/core/runtime/pydantic_runtime.py
git mv harness_poc/core/goal_runner.py harness_poc/core/runtime/goal_runner.py
```

- [ ] **Step 2: Fix intra-package imports**

First, audit all cross-deps among these files and against moved packages:

```bash
grep "from harness_poc.core" harness_poc/core/runtime/*.py
```

Then apply fixes. Known patterns (verified against actual imports):

```bash
# pydantic_runtime.py only imports config (stays at core/ root) — no path update needed

# goal_runner.py imports pydantic_runtime (now runtime) and events (path unchanged)
sed -i '' 's|from harness_poc\.core\.pydantic_runtime import|from harness_poc.core.runtime.pydantic_runtime import|g' harness_poc/core/runtime/goal_runner.py

# token_accounting.py imports message_history
sed -i '' 's|from harness_poc\.core\.message_history import|from harness_poc.core.runtime.message_history import|g' harness_poc/core/runtime/token_accounting.py

# reducers.py imports models (storage)
sed -i '' 's|from harness_poc\.core\.models import|from harness_poc.core.storage import|g' harness_poc/core/runtime/reducers.py
```

- [ ] **Step 3: Create `__init__.py`**

```python
from harness_poc.core.runtime.goal_runner import GoalRunner
from harness_poc.core.runtime.llm_client import LLMClient, Message, Usage
from harness_poc.core.runtime.message_history import MessageHistory
from harness_poc.core.runtime.pydantic_runtime import (
    AgentDeps,
    PydanticAgentRuntime,
    build_model,
    build_runtime,
)
from harness_poc.core.runtime.reducers import derive_session_state
from harness_poc.core.runtime.token_accounting import account_for_model_run

__all__ = [
    "GoalRunner",
    "LLMClient",
    "Message",
    "Usage",
    "MessageHistory",
    "AgentDeps",
    "PydanticAgentRuntime",
    "build_model",
    "build_runtime",
    "derive_session_state",
    "account_for_model_run",
]
```

Run `grep "^class \|^def " harness_poc/core/runtime/*.py` to complete the symbol list and update `__all__` accordingly.

- [ ] **Step 4: Rewrite external imports**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.llm_client import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.message_history import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.token_accounting import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.reducers import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.pydantic_runtime import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.goal_runner import/from harness_poc.core.runtime import/g'
```

- [ ] **Step 5: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/runtime/
git add -u
git commit -m "refactor: move runtime modules into core/runtime/ subpackage"
```

---

## Task 6: Consolidate `processors/`

Moves: `processor_supervisor.py` into the existing `processors/` package.

**Files:**
- Modify: `harness_poc/core/processors/__init__.py` (add re-exports)
- Move: `harness_poc/core/processor_supervisor.py` → `harness_poc/core/processors/processor_supervisor.py`

- [ ] **Step 1: Move file**

```bash
git mv harness_poc/core/processor_supervisor.py harness_poc/core/processors/processor_supervisor.py
```

- [ ] **Step 2: Fix intra-package imports in moved file**

```bash
grep "from harness_poc.core" harness_poc/core/processors/processor_supervisor.py
# Update any hits following the same pattern as previous tasks
```

The processors already live in `processors/`, so their imports of `event_bus`, `pydantic_runtime`, etc. will need to use the new subpackage paths:

```bash
# Apply to all processor files (llm_worker, tool_worker, circuit_breaker, processor_supervisor)
find harness_poc/core/processors/ -name "*.py" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.event_bus import/from harness_poc.core.events import/g' \
  -e 's/from harness_poc\.core\.events import/from harness_poc.core.events import/g' \
  -e 's/from harness_poc\.core\.pydantic_runtime import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.reducers import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.token_accounting import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.database import/from harness_poc.core.storage import/g' \
  -e 's/from harness_poc\.core\.skill_runner import/from harness_poc.core.skills import/g' \
  -e 's/from harness_poc\.core\.skill_context import/from harness_poc.core.skills import/g'
```

- [ ] **Step 3: Replace `processors/__init__.py` content** (current file has only a docstring)

```python
from harness_poc.core.processors.circuit_breaker import CircuitBreaker
from harness_poc.core.processors.llm_worker import run_llm_worker
from harness_poc.core.processors.processor_supervisor import ProcessorSupervisor
from harness_poc.core.processors.tool_worker import run_tool_worker

__all__ = ["CircuitBreaker", "run_llm_worker", "ProcessorSupervisor", "run_tool_worker"]
```

Run `grep "^class \|^def \|^async def " harness_poc/core/processors/*.py` to complete the symbol list and update `__all__` accordingly.

- [ ] **Step 4: Rewrite external imports of `processor_supervisor`**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.processor_supervisor import/from harness_poc.core.processors import/g'
```

- [ ] **Step 5: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/processors/
git add -u
git commit -m "refactor: consolidate processor_supervisor into core/processors/ subpackage"
```

---

## Task 7: `execution/` subpackage

Moves: `workflow_runner.py`, `pipeline_runner.py`, `materializer_runner.py`

- [ ] **Step 1: Move files**

```bash
mkdir -p harness_poc/core/execution
git mv harness_poc/core/workflow_runner.py harness_poc/core/execution/workflow_runner.py
git mv harness_poc/core/pipeline_runner.py harness_poc/core/execution/pipeline_runner.py
git mv harness_poc/core/materializer_runner.py harness_poc/core/execution/materializer_runner.py
```

- [ ] **Step 2: Fix intra-package imports**

```bash
grep "from harness_poc.core" harness_poc/core/execution/*.py
```

Expected updates:

```bash
find harness_poc/core/execution/ -name "*.py" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.skill_context import/from harness_poc.core.skills import/g' \
  -e 's/from harness_poc\.core\.skill_runner import/from harness_poc.core.skills import/g' \
  -e 's/from harness_poc\.core\.goal_runner import/from harness_poc.core.runtime import/g' \
  -e 's/from harness_poc\.core\.events import/from harness_poc.core.events import/g' \
  -e 's/from harness_poc\.core\.database import/from harness_poc.core.storage import/g'
```

- [ ] **Step 3: Create `__init__.py`**

```python
from harness_poc.core.execution.materializer_runner import MaterializerRunner
from harness_poc.core.execution.pipeline_runner import PipelineRunner
from harness_poc.core.execution.workflow_runner import WorkflowRunner

__all__ = ["MaterializerRunner", "PipelineRunner", "WorkflowRunner"]
```

Run `grep "^class \|^def \|^async def " harness_poc/core/execution/*.py` to complete the symbol list and update `__all__` accordingly.

- [ ] **Step 4: Rewrite external imports**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.workflow_runner import/from harness_poc.core.execution import/g' \
  -e 's/from harness_poc\.core\.pipeline_runner import/from harness_poc.core.execution import/g' \
  -e 's/from harness_poc\.core\.materializer_runner import/from harness_poc.core.execution import/g'
```

- [ ] **Step 5: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/execution/
git add -u
git commit -m "refactor: move execution runners into core/execution/ subpackage"
```

---

## Task 8: `retrieval/` subpackage

Moves: `retrieval.py`, `vespa_client.py`, `document_index.py`, `pdf_converter.py`

Note: `retrieval.py` becomes `core/retrieval/retrieval.py` — same naming situation as `events.py`. `from harness_poc.core.retrieval import X` already worked and continues to work via `__init__.py`.

- [ ] **Step 1: Move files**

```bash
mkdir -p harness_poc/core/retrieval
git mv harness_poc/core/retrieval.py harness_poc/core/retrieval/retrieval.py
git mv harness_poc/core/vespa_client.py harness_poc/core/retrieval/vespa_client.py
git mv harness_poc/core/document_index.py harness_poc/core/retrieval/document_index.py
git mv harness_poc/core/pdf_converter.py harness_poc/core/retrieval/pdf_converter.py
```

- [ ] **Step 2: Fix intra-package imports**

```bash
# document_index.py imports retrieval, vespa_client, pdf_converter
sed -i '' 's|from harness_poc\.core\.retrieval import|from harness_poc.core.retrieval.retrieval import|g' harness_poc/core/retrieval/document_index.py
sed -i '' 's|from harness_poc\.core\.vespa_client import|from harness_poc.core.retrieval.vespa_client import|g' harness_poc/core/retrieval/document_index.py
sed -i '' 's|from harness_poc\.core\.pdf_converter import|from harness_poc.core.retrieval.pdf_converter import|g' harness_poc/core/retrieval/document_index.py

# vespa_client.py and pdf_converter.py import retrieval types
sed -i '' 's|from harness_poc\.core\.retrieval import|from harness_poc.core.retrieval.retrieval import|g' harness_poc/core/retrieval/vespa_client.py
sed -i '' 's|from harness_poc\.core\.retrieval import|from harness_poc.core.retrieval.retrieval import|g' harness_poc/core/retrieval/pdf_converter.py

# All these files may also import storage types (document_index.py imports models)
find harness_poc/core/retrieval/ -name "*.py" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.database import/from harness_poc.core.storage import/g' \
  -e 's/from harness_poc\.core\.blackboard_proxy import/from harness_poc.core.storage import/g' \
  -e 's/from harness_poc\.core\.models import/from harness_poc.core.storage import/g'
```

- [ ] **Step 3: Create `__init__.py`**

```python
from harness_poc.core.retrieval.document_index import DocumentIndex
from harness_poc.core.retrieval.pdf_converter import PdfConverter
from harness_poc.core.retrieval.retrieval import (
    DocumentChunk,
    Retriever,
    SearchRequest,
    SearchResult,
)
from harness_poc.core.retrieval.vespa_client import VespaClient

__all__ = [
    "DocumentIndex",
    "PdfConverter",
    "DocumentChunk",
    "Retriever",
    "SearchRequest",
    "SearchResult",
    "VespaClient",
]
```

Run `grep "^class \|^def \|^[A-Z]" harness_poc/core/retrieval/*.py` to complete the symbol list and update `__all__` accordingly.

- [ ] **Step 4: Rewrite external imports**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.vespa_client import/from harness_poc.core.retrieval import/g' \
  -e 's/from harness_poc\.core\.document_index import/from harness_poc.core.retrieval import/g' \
  -e 's/from harness_poc\.core\.pdf_converter import/from harness_poc.core.retrieval import/g'
```

> `from harness_poc.core.retrieval import X` already used the `retrieval` module name — those imports now resolve via `__init__.py` and need no change.

- [ ] **Step 5: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/retrieval/
git add -u
git commit -m "refactor: move retrieval modules into core/retrieval/ subpackage"
```

---

## Task 9: `observability/` subpackage

Moves: `dashboard.py`, `logfire_subscriber.py`

- [ ] **Step 1: Move files**

```bash
mkdir -p harness_poc/core/observability
git mv harness_poc/core/dashboard.py harness_poc/core/observability/dashboard.py
git mv harness_poc/core/logfire_subscriber.py harness_poc/core/observability/logfire_subscriber.py
```

- [ ] **Step 2: Fix intra-package imports**

```bash
grep "from harness_poc.core" harness_poc/core/observability/*.py
# logfire_subscriber.py imports events and event_bus — update to new paths:
find harness_poc/core/observability/ -name "*.py" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.event_bus import/from harness_poc.core.events import/g' \
  -e 's/from harness_poc\.core\.events import/from harness_poc.core.events import/g'
```

- [ ] **Step 3: Create `__init__.py`**

```python
from harness_poc.core.observability.dashboard import Dashboard
from harness_poc.core.observability.logfire_subscriber import LogfireSubscriber

__all__ = ["Dashboard", "LogfireSubscriber"]
```

Run `grep "^class \|^def " harness_poc/core/observability/*.py` to complete the symbol list and update `__all__` accordingly.

- [ ] **Step 4: Rewrite external imports**

```bash
find . -name "*.py" -not -path "./.git/*" | xargs sed -i '' \
  -e 's/from harness_poc\.core\.dashboard import/from harness_poc.core.observability import/g' \
  -e 's/from harness_poc\.core\.logfire_subscriber import/from harness_poc.core.observability import/g'
```

- [ ] **Step 5: Lint, type check, test, commit**

```bash
uv run ruff check .
uv run ty check
uv run pytest -x -q
git add harness_poc/core/observability/
git add -u
git commit -m "refactor: move observability modules into core/observability/ subpackage"
```

---

## Task 10: Final verification

- [ ] **Step 1: Confirm no old flat paths remain**

```bash
# Check for any remaining imports of moved flat modules
grep -r "from harness_poc\.core\.\(event_bus\|event_store\|event_log_observer\|context_map_events\|database\|db_engine\|blackboard_proxy\|skill_context\|skill_runner\|skill_catalog\|skill_scaffolder\|skill_preprocessing\|tool_context\|tool_result\|tool_runner\|llm_client\|message_history\|token_accounting\|reducers\|pydantic_runtime\|goal_runner\|workflow_runner\|pipeline_runner\|materializer_runner\|vespa_client\|document_index\|pdf_converter\|processor_supervisor\|logfire_subscriber\) import" \
  . --include="*.py"
```

Expected: zero matches. Any hits are missed import rewrites — fix them manually.

- [ ] **Step 2: Confirm no leftover flat modules at core/ root**

```bash
ls harness_poc/core/*.py
```

Expected: only `config.py`, `logging.py`, `permissions.py`, and `__init__.py`.

- [ ] **Step 3: Run full test suite and quality checks**

```bash
uv run pytest -v
uv run ruff check .
uv run ty check
```

All checks must pass green.

- [ ] **Step 4: Smoke-test the REPL**

```bash
uv run harness-poc --help
uv run harness-poc skill list
```

Expected: CLI starts, skills are discovered.

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "refactor: complete core/ module restructure into subpackages"
```
