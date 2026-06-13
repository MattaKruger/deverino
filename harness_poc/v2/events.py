"""V2 Event type constants — single registry to prevent string proliferation.

Every event type string used in v2 pub/sub MUST be defined here.
Mirrors the v1 EVENT_REGISTRY pattern but using string constants
instead of typed event classes.
"""

# ---------------------------------------------------------------------------
# Pipeline mode events
# ---------------------------------------------------------------------------

WORKFLOW_STARTED = "WORKFLOW_STARTED"
PROBE_COMPLETED = "PROBE_COMPLETED"
EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
GATE_COMPLETED = "GATE_COMPLETED"

# Pipeline step internal events (used by context_engine / execution_engine)
PROBE_FAILED = "PROBE_FAILED"
CONTEXT_WARMED = "CONTEXT_WARMED"
GATE_PASSED = "GATE_PASSED"
GATE_FAILED = "GATE_FAILED"
SPEC_COMMITTED = "SPEC_COMMITTED"

# Delegate task events
DELEGATE_TASK_COMPLETED = "delegate_task_completed"

# ---------------------------------------------------------------------------
# ReAct mode events
# ---------------------------------------------------------------------------

AGENT_INPUT = "AGENT_INPUT"
TOOL_REQUESTED = "TOOL_REQUESTED"
TOOL_COMPLETED = "TOOL_COMPLETED"
LLM_TEXT_EMITTED = "LLM_TEXT_EMITTED"
LLM_ACTION_EMITTED = "LLM_ACTION_EMITTED"
STREAM_PAUSED = "STREAM_PAUSED"
GOAL_EVALUATED = "GOAL_EVALUATED"

# ---------------------------------------------------------------------------
# Full registry (for introspection / logging subscribers)
# ---------------------------------------------------------------------------

ALL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        WORKFLOW_STARTED,
        PROBE_COMPLETED,
        EXECUTION_COMPLETED,
        GATE_COMPLETED,
        PROBE_FAILED,
        CONTEXT_WARMED,
        GATE_PASSED,
        GATE_FAILED,
        SPEC_COMMITTED,
        DELEGATE_TASK_COMPLETED,
        AGENT_INPUT,
        TOOL_REQUESTED,
        TOOL_COMPLETED,
        LLM_TEXT_EMITTED,
        LLM_ACTION_EMITTED,
        STREAM_PAUSED,
        GOAL_EVALUATED,
    }
)
