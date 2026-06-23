---
name: ahe_evolve
type: skill
description: Run the AHE Evolution Agent stages 1-3 (observe, diagnose, propose). Dry-run by default — no mutation.
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    corpus_key:
      type: string
      description: Corpus key to aggregate telemetry for. Default "default".
    window_days:
      type: integer
      description: Telemetry window in days. Default 7.
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read_write
  workspace: read_only
---

# ahe_evolve

Runs the first three stages of the AHE Evolution Agent loop:

1. **Observe** — aggregates telemetry from the event system into `ahe:telemetry:{cycle}`
2. **Diagnose** — delegates to `harness_engineer` subagent to attribute problems to harness components, stores `ahe:diagnosis:{cycle}`
3. **Propose** — delegates to `harness_engineer` subagent to generate candidate revisions with governance tiers, stores `ahe:proposal:{proposal_id}`

Dry-run by default. No mutation of harness config. Stages 4-5 (evaluate, promote) are separate.
