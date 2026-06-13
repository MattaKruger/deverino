"""Quick smoke test — verifies all contracts import and basic types work."""
from harness_poc.v2.contracts import (
    DelegatedTaskOutput,
    DelegatedTaskResult,
    Goal,
    GoalResult,
    SoulConstitution,
    map_delegated_to_external,
    map_goal_status_to_delegated,
)

# --- Status mapping ---
assert map_goal_status_to_delegated("blocked") == "failed"
assert map_goal_status_to_delegated("completed") == "success"
assert map_delegated_to_external("success") == "completed"
assert map_delegated_to_external("failed", original_goal_status="blocked") == "blocked"
assert map_delegated_to_external("failed") == "failed"

# --- Dataclass validation ---
g = Goal(goal_id="test-1", description="test")
gr = GoalResult(goal_id="test-1", status="completed")
dr = DelegatedTaskResult(task_id="t1", status="success")
do = DelegatedTaskOutput(task_id="t1", output_label="completed", summary="done")

# --- Protocol isolation ---
assert not isinstance(g, SoulConstitution)

print("ALL IMPORTS + RUNTIME CHECKS PASSED")
print()
print("Contracts live at: harness_poc/v2/contracts/")
print("  __init__.py")
print("  soul_constitution.py")
print("  context_map_pipeline.py")
print("  event_runtime.py")
print("  sub_agent_spawner.py")
