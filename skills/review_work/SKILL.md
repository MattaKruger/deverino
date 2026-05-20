---
name: review_work
type: tool
description: Review current working tree
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    objective:
      type: string
      description: The original objective the result should satisfy.
    memory_key:
      type: string
      description: The memory key containing the result to evaluate.
    output_key:
      type: string
      description: The memory key where the reflection should be stored.
  required:
    - objective
    - memory_key
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: none
---
