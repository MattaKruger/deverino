---
name: evaluate_goal
description: Evaluate whether the current goal is complete. Call with is_complete=true to stop the autonomous loop, or false to report status and continue.
version: "1.0"
parameters:
  type: object
  properties:
    is_complete:
      type: boolean
      description: True if the goal has been fully achieved, False otherwise.
    reasoning:
      type: string
      description: Concise explanation of the current state and next steps if incomplete.
  required:
    - is_complete
    - reasoning
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: none
  workspace: none
---

# Skill: Evaluate Goal

## Purpose
Explicit exit mechanism for the autonomous goal loop. The GoalRunner intercepts this skill call — it never executes as a normal skill during a goal run.

## Behavior
- If `is_complete` is true: GoalRunner breaks the loop and returns the reasoning to the user.
- If `is_complete` is false: GoalRunner appends the reasoning as a tool_observation and forces the loop to continue.

## Expected Output
Returns a `SkillResult` — but only if called outside the GoalRunner context (e.g., direct `/skill evaluate_goal`).
