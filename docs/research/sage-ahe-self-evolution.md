# SAGE & AHE: Self-Evolution in Agent Harnesses

**Date:** 2026-06-22
**Status:** Exploration notes — continuation pending
**Session focus:** Connecting AHE (Agentic Harness Engineering) from the Code as Agent Harness survey with the SAGE framework. The connecting thread: "programs that think about programs" — metaprogramming applied to agent architecture, with a cognitive psychology angle via the Ebbinghaus forgetting curve.

## Papers

| Paper | arXiv | Location | Indexed |
|---|---|---|---|
| Code as Agent Harness | 2605.18747 | `docs/papers_test/code_as_agent_harness__2605.18747.pdf` | Yes (~200 chunks) |
| SAGE: Self-evolving Agents with Reflective and Memory-augmented Abilities | 2409.00872 | `docs/papers/2409.00872.pdf` | Yes (42 chunks) |

**Note:** arXiv:2503.19271 (MARS) was withdrawn as a duplicate of 2409.00872 (SAGE). Same author group. MARS is the earlier name; SAGE is the Neurocomputing 2025 publication.

---

## 1. AHE — Agentic Harness Engineering (Code as Agent Harness §3.5)

### Definition
AHE names a harness-level design problem: how to measure and revise the software substrate that turns an LLM into a coding agent. Distinct from prompt engineering (changes instructions) and context engineering (changes evidence presented). AHE treats the **operating environment** as the object of analysis.

### Harness substrate components (the revision surface)
Tool schemas, planning artifacts, memory policies, retrieval strategies, sandbox config, verification sensors, permission tiers, routing rules, multi-agent workflows, human-review gates.

### §3.5.1 Deep Telemetry — the optimization substrate
Structured traces connecting model decisions → harness actions → environment states → outcomes.

- Shallow log: final answer / pass-fail only.
- Deep telemetry records: prompts, retrieved context, token usage/cost, model/tool latency, tool arguments, permission requests, edited files, sandbox snapshots, command outputs, test results, stack traces, lint warnings, branch decisions, rejected alternatives, human interventions, final task outcome.

Three complementary telemetry channels:
- Evaluators → task-level regressions
- Tracing stacks → trajectory-level causes
- Policy gateways → boundary violations

### §3.5.2 The Evolution Agent — the revision actor
Meta-level agent. Unlike a task agent (edits the target repo), the Evolution Agent **edits the operating conditions** under which later task agents work.

- Input: corpus of trajectories
- Output: revised prompt template, retrieval policy, tighter tool schema, added validator, changed permission rule, workflow-topology adjustment, new regression test

Five-stage loop:
1. **Observe** — collect telemetry from PEV executions
2. **Diagnose** — attribute cost, latency, invalid actions, test failures, permission denials to specific harness components
3. **Propose** — candidate revisions (rewrite tool descriptions, change context packing, add linter, modify retry limits, insert HITL gate)
4. **Evaluate** — run revised harness on held-out tasks / replayed traces via deterministic sensors + regression tests
5. **Promote** — only changes that improve reliability, cost, or safety without regressing previously solved cases

### §3.5.3 Governed Harness Mutation — the safety boundary
Not unconstrained self-modification. Candidate changes evaluated in sandboxes, compared against fixed regression suites, recorded with auditable rationales. HITL approval required for: permission boundaries, network access, credential handling, deployment behavior, human-review requirements. The Evolution Agent is itself subject to the PEV loop.

### Three strands in the literature
- AutoHarness [14] — automatic synthesis of code harnesses
- Meta-Harness [13] — harness design as optimization over model-facing infrastructure
- Observability-driven AHE [281] — telemetry-rich diagnosis of where the agent loop fails

### §3.4 PEV Loop (related)
PEV = Plan-Execute-Verify. Harness externalizes intended change + validation criteria, executes in sandboxed + permissioned environment, verifies via deterministic sensors + HITL gates.

Multi-tier permission model:
- Read-only: repo browsing, retrieval, static inspection, log analysis
- Sandbox-edit: local patching, test execution, temp dependency install in isolated workspace
- Full-access: network, credentials, deployment, package publishing, destructive FS ops, Git history mutation (mandatory HITL)

Key principle: "Reliability comes from governed state transitions, not better repair prompts."

---

## 2. SAGE Architecture

### Core structure
Three agents: User → Assistant → Checker

Assistant loop: observation → action → reflection → output

### Three core mechanisms

**1. Iterative feedback** — Checker provides feedback `ft` to Assistant, which updates policy `πθ` to maximize expected reward `R`.

**2. Reflection** — Assistant derives self-reflections from past performance:
- `rt = ref(o1:t, R1:t)` — reflection function over output sequence and rewards
- Reflections stored in long-term memory: `ML ← ML ∪ {rt}`
- Richer than scalar rewards; enables adaptive strategy adjustment

**3. MemorySyntax** — Ebbinghaus forgetting curve + linguistic optimization:
- Retention rate: `R(It, τ) = e^(-τ/S)` where `S` = information strength (importance + complexity)
- Linguistic optimization increases strength: `S* > S`
- Manages decay across short-term memory (STM) and long-term memory (LTM)

### Information-theoretic grounding (Appendix A)
Retention strength: `S(It) = H(It)/f(t)` — information entropy divided by forgetting function.

Objective: maximize utility of retained information under capacity constraint:
- `max Σ Mt · S(It)` s.t. `Σ Mt ≤ C`
- Optimal rule: retain `It` if `S(It) ≥ λ`, discard if `S(It) < λ`
- Lagrange-multiplier derivation

---

## 3. The SAGE ↔ AHE Mapping

| AHE Evolution Agent (§3.5.2) | SAGE |
|---|---|
| Observe trajectories (telemetry from PEV) | Observation of outputs `o1:t` and rewards `R1:t` |
| Diagnose failure modes → attribute to harness components | Reflection `rt = ref(o1:t, R1:t)` attributes outcomes to strategies |
| Propose candidate revisions | Policy update `πθ` based on feedback `ft` |
| Evaluate on held-out tasks | Checker evaluates Assistant output |
| Promote verified improvements | Store reflection in long-term memory `ML` |

### Key distinction — layer of evolution
- **AHE** = meta-level: a separate Evolution Agent revises the harness (operating environment) for other task agents. Top-down.
- **SAGE** = self-level: the agent evolves its own memory and strategies through reflection. Bottom-up.

In the code-as-harness framing, SAGE's memory policy (STM/LTM with forgetting curve) is a harness component. SAGE's reflection loop is a PEV-like control process. So SAGE is an instance of AHE principles applied at the agent level — the agent evolves its own harness substrate from within.

---

## 4. The Psychology Angle

SAGE's MemorySyntax is a literal application of cognitive psychology to LLM agent memory:

- **Ebbinghaus forgetting curve** (1885) — the foundational quantitative model of human memory decay
- SAGE operationalizes it as `R = e^(-τ/S)` — exponential decay modulated by information strength
- The information-theoretic extension (`S = H/f(t)`) bridges cognitive psychology and information theory: high-entropy information retained, low-entropy discarded

"Programs that think about programs" in a specific sense: the agent models its own memory decay using a human cognitive model, then optimizes its memory policy against that model. The program reasons about its own forgetting.

---

## 5. Deverino Relevance

- Deverino uses SKILL.md format (Anthropic Skills standard) — SAGE generalizes Voyager's approach of composing/refining executable code skills
- 2605.10052 extends the Anthropic Skills standard to multi-agent — directly relevant to Deverino's `delegate_task` + skill system
- SAGE's reflection loop maps to Deverino's skill execution + state consolidation
- AHE's Evolution Agent concept maps to Deverino's `skill_manage` (currently agent-initiated, not self-evolving)
- The Ebbinghaus forgetting curve raises a design question for Deverino's blackboard/STATE: should durable context decay?

### Deverino mapping (from PEV section)
| Paper concept | Deverino | Gap |
|---|---|---|
| microVM/WASM isolation | — | No isolation tier; skills run in-process |
| Multi-tier permissions (read/sandbox/full) | Skill permissions, protected paths | Two tiers (allowed/blocked), not three |
| Reproducibility via stable substrate | PostgreSQL blackboard (state) | Execution env not reproducible |
| Governance outside the prompt | SOUL charter + skill permissions | Partial — no proxy/gateway layer |

---

## 6. Open Questions / Next Steps

1. **The evolution-layer question** — should Deverino's `delegate_task` subagents self-evolve (SAGE-style) or should a meta-agent evolve the harness for them (AHE-style)? Or both?

2. **The memory psychology question** (← current focus) — does the Ebbinghaus forgetting curve apply to Deverino's blackboard/STATE? Should STATE decay? What would information-strength-weighted retention look like for a PostgreSQL blackboard?

3. **The reflection-as-telemetry mapping** — SAGE's `rt` vs AHE's deep telemetry; what would Deverino need to capture to enable either? The blackboard stores results but does it store decision traces, branch decisions, rejected alternatives?

---

## Appendix: Corpus Context

### Other relevant papers identified
- **2605.10052** — extends Anthropic Skills standard to multi-agent environments; discusses SAGE, Voyager, ExpeL, EvoSkills in context of skill evolution
- **2605.19952** — "Rethinking How to Remember" — cognitive psychology distinction (semantic/episodic memory) applied to LLM agent memory
- **2604.24808** — references "Cognitive architectures for language agents" (Sumers, Griffiths et al., TMLR 2024)
- **2605.16821** — buddyMe framework, hierarchical memory inspired by cognitive science
- **2605.19337** — self-evolution mechanism taxonomy (Consolidation, Meta-Learning, Self-Reflection); Reflection Budget constraint

### Vespa search notes
- The Code as Agent Harness paper has ~200 chunks; AHE is in chunks 65-68, PEV in chunks 58-64
- SAGE paper has 42 chunks; core architecture in chunks 0-9, theoretical analysis in chunk 27
- Keyword mode is fast and precise for section-targeted queries; hybrid mode better for conceptual exploration
