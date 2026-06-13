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
if map_goal_status_to_delegated("blocked") != "failed":
    _msg = "map_goal_status_to_delegated('blocked') != 'failed'"
    raise AssertionError(_msg)
if map_goal_status_to_delegated("completed") != "success":
    _msg = "map_goal_status_to_delegated('completed') != 'success'"
    raise AssertionError(_msg)
if map_delegated_to_external("success") != "completed":
    _msg = "map_delegated_to_external('success') != 'completed'"
    raise AssertionError(_msg)
if map_delegated_to_external("failed", original_goal_status="blocked") != "blocked":
    _msg = "map_delegated_to_external('failed', blocked) != 'blocked'"
    raise AssertionError(_msg)
if map_delegated_to_external("failed") != "failed":
    _msg = "map_delegated_to_external('failed') != 'failed'"
    raise AssertionError(_msg)

# --- Dataclass validation ---
g = Goal(goal_id="test-1", description="test")
gr = GoalResult(goal_id="test-1", status="completed")
dr = DelegatedTaskResult(task_id="t1", status="success")
do = DelegatedTaskOutput(task_id="t1", output_label="completed", summary="done")

# --- Protocol isolation ---
if isinstance(g, SoulConstitution):
    _msg = "Goal should not be a SoulConstitution"
    raise AssertionError(_msg)  # noqa: TRY004

print("ALL IMPORTS + RUNTIME CHECKS PASSED")
print()
print("Contracts live at: harness_poc/v2/contracts/")
print("  __init__.py")
print("  soul_constitution.py")
print("  context_map_pipeline.py")
print("  event_runtime.py")
print("  sub_agent_spawner.py")
