An analysis of the updated architecture layout shows a structural consolidation in how state, context framing, and constraints are organized.

### Key Architectural Shifts to Reflect in the Spec

1. **Implicit Coupling of Persona and Pedagogy:** `developer-pedagogy.md` is no longer a detached global configuration; its profile explicitly **adapts to the selected persona** (e.g., a `Reviewer` persona dictates a precise, pedantic pedagogy profile). They form a singular conceptual layer.
2. **Dynamic Layering of the Context Map:** The `Context Map` is no longer a static structural overview. It is **materialized based on the working context** and is explicitly **tied to the persona + pedagogy profile**. This means the underlying codebase data is filtered, emphasized, and presented through the ideological lens of the combined persona/pedagogy layer.
3. **Dual-Mode Execution Separation:** The workflow explicitly bifurcates into **Exploration** and **Execution** modes using a precise three-stage pipeline:
* **`#1` Fail-Fast Probe:** Letting the agent deliberately fail in the sandbox to extract raw error details and constraints, which immediately **warms up the context map**.
* **`#2` Spec Execution:** Spawning targeted sub-agents or background (`bg`) sub-agents to handle isolated execution tracks.
* **`#3` Deterministic Review Gate:** The ultimate validation boundary. A successful execution here loops back to ensure the **context map reflects the "true" implementation state** of the codebase.



---

# Engineering Planning Specification: Deverino V2

**Status:** SPECIFICATION UPDATE

**Target Architecture:** Event-Sourced Layering + Persona-Driven Materialization + Adversarial Sandboxing

---

## 1. Unified System Context Model & Prompt Hierarchy

The system context is structured as a descending hierarchy where top-level ontological rules govern down-funneled, role-specific interaction profiles.

```
┌────────────────────────────────────────────────────────┐
│                        SOUL.MD                         │
│       (Immutable Team Constitution & Ontological Core) │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│         UNIFIED PERSONA (PERSONA.MD + PEDAGOGY)        │
│   (Role definition + Pedagogy Profile adapts to role)  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                MATERIALIZED CONTEXT MAP                │
│   (Materialized based on working context; filtered by) │
│   (active persona + developer-pedagogy requirements)   │
└────────────────────────────────────────────────────────┘

```

* **`soul.md` (The Constitution):** Dictates existential boundaries ("What am I?", "What am I not?"). Embodying core tacit team knowledge and immutable software constraints.
* **`persona.md` + `developer-pedagogy.md` (The Unified Lens):** Interchangeable, role-tuned configurations (e.g., `coder`, `architect`, `reviewer`). The developer pedagogy profile is embedded within or dynamically adapted to the selected persona, ensuring interaction patterns match the operational role.
* **`Context Map` (The Materialized State):** Programmatically generated based on the current active working context. It is explicitly bounded and formatted according to the combined Persona and Pedagogy constraints.

---

## 2. Agent Loop & Workspace Isolation

The execution workspace separates operational states to prevent code contamination during exploratory phases.

* **Working Context:** Tracks active prompting and active spec generation tasks required to complete a given codebase feature.
* **Runtime:** An event-sourced engine executing tools and specialized skills inside a secure, isolated Python sandbox environment.
* **Scratchpad (`/tmp`):** An ephemeral spatial directory explicitly bounded for generating, executing, and destroying one-off utility or investigative scripts.

---

## 3. The Two-Mode Workflow Lifecycle

The orchestrator manages state execution across **Exploration** and **Execution** modes divided into three sequential steps.

```
┌─────────────────────────────────────────────────────────────────┐
│                       WORKFLOW RUNTIME                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step #1: Exploration Mode (Fail-Fast Probe)                    │
│  [Agent Execution] ──► [Sandbox Failure] ──► [Warm Up Context] │
│                                                     │           │
│                                                     ▼           │
│  Step #2: Execution Mode (Spec Work)                           │
│  [Spawn Sub-Agents] ──► [Spawn Background (bg) Sub-Agents]      │
│                                                     │           │
│                                                     ▼           │
│  Step #3: Deterministic Review Gate                             │
│  [Test Suite Pass] ──► [Context Map reflects "True" State]      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

```

### Step #1: Fail-Fast Sandbox Probe (Exploration Mode)

The orchestrator deliberately allows the agent to execute code and fail within the sandbox environment. The raw stdout/stderr and trace stack outputs are intercepted and used immediately to **warm up the context map**, exposing missing system constraints, unresolved dependencies, or unstated architectural invariants before generation begins.

### Step #2: Spec Execution (Execution Mode)

Once the context map is stabilized, production work proceeds based on structured specifications. The primary agent loop is permitted to spin up specialized **sub-agents** or asynchronous **background (`bg`) sub-agents** to distribute component tasks without locking the orchestrator process thread.

### Step #3: Deterministic Review Gate

All generated code must clear a non-negotiable, programmatic validation gate backed by the team's automated testing suite. Upon verification success, the execution artifacts trigger a context refresh loop: **the updated Materialized Context Map reflects only the "true" verified implementation state of the repository.**

---

## 4. Component Architecture & System Methods

### Data Models & PostgreSQL Schema Updates

The database schemas bind the event ledger directly to the dynamic state materialization pipeline.

```python
from uuid import UUID
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

class Event(BaseModel):
    id: Optional[int] = None
    session_id: UUID
    team_member: str
    event_type: str  # 'PROBE_FAILED', 'SPEC_COMMITTED', 'GATE_PASSED', 'CONTEXT_WARMED'
    payload: Dict[str, Any]

class MaterializedContext(BaseModel):
    project_id: str
    active_persona: str
    pedagogy_snapshot: Dict[str, Any]
    working_context_delta: Dict[str, Any]
    verified_topology: Dict[str, Any]

```

```sql
CREATE TABLE context_events (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    team_member VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE materialized_context_maps (
    project_id VARCHAR(255) PRIMARY KEY,
    active_persona VARCHAR(100) NOT NULL,
    pedagogy_snapshot JSONB NOT NULL,
    verified_state JSONB NOT NULL,     -- Reflects only verified "true" implementation code
    last_event_id BIGINT NOT NULL REFERENCES context_events(id),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

```

---

### Core Class Interfaces

#### `ContextEngine`

Responsible for processing environmental telemetry and materializing prompt context layers.

* **`materialize_context_map(project_id: str, working_context: Dict[str, Any], persona_id: str) -> Dict[str, Any]`**
* *Purpose:* Constructs the customized prompt context window.
* *Logic:* Queries the latest verified state from PostgreSQL, extracts the specific `persona.md` and its adapted `developer-pedagogy.md` profile, and uses them to filter and format the working context map for model injection.


* **`warm_up_context_from_failure(session_id: UUID, execution_error: Dict[str, Any]) -> Dict[str, Any]`**
* *Purpose:* Executes the step `#1` exploration loop recovery.
* *Logic:* Commits a `PROBE_FAILED` event to the stream, extracts semantic errors, and mutates the current in-memory working context map with the newly discovered sandbox constraints.



#### `ExecutionEngine`

Manages background processes, task distribution, and boundary enforcement.

* **`spawn_sub_agent(agent_type: str, task_payload: Dict[str, Any], background: bool = False) -> str`**
* *Purpose:* Handles sub-task offloading as specified in step `#2`.
* *Logic:* Instantiates an isolated sub-agent worker. If `background=True`, it registers the worker to an asynchronous task pool (`bg sub-agent`) and provides non-blocking status tracking back to the primary agent loop.


* **`execute_deterministic_gate(workspace_path: str) -> bool`**
* *Purpose:* Programmatically enforces the step `#3` validation boundary.
* *Logic:* Triggers host-isolated validation commands. Returns `True` if all functional and safety tests pass cleanly, triggering an entry to `MaterializeProjection`. Returns `False` on any assertion anomaly.
