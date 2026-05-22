---
name: read_memory
type: tool
description: Retrieves data stored in the shared blackboard for the current session.
version: "1.0"
auto_invokable: true
parameters:
  type: object
  properties:
    memory_key:
      type: string
      description: Key to read. Omit to list all available keys.
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read
  workspace: none
---

# read_memory

Bridge skill — delegates to the built-in tool in `system_tools/read_memory.py`.
