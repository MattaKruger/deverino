# Stress Test Report — Context Map Materializer

**Date:** 2026-07-25  
**Test:** Deliberation Cascade Detection (Test 1 from deterministic-cartographer stress plan)  
**Tester:** Agent (Matthijs session)

---

## Test Objective

Feed the **same observation** through the Distiller → Cartographer → Evictor pipeline N=10 times
and measure whether the Cartographer produces divergent edits (a "deliberation cascade").
The deterministic-cartographer skill predicts that an LLM Cartographer may disagree with its own
prior decisions on identical input — a >20% edit disagreement rate is the cascade threshold.

## Protocol (adapted)

- Observation: architecture-level fact about `_enforce_budget` at `cartographer.py`
  (two-pass budget enforcement with per-section reservations)
- 10 identical observations injected, one per materialization cycle
- Token budget: 1024
- Map baseline: 11 entries, ~790 tokens (cycle 85)

The pure protocol (re-materialize the same event from identical map state) is **not supported**
by the event-sourced architecture — each materialization consumes pending events and evolves
the map. The adapted protocol injects one identical observation per cycle, sequentially,
against the **evolving** map state. This tests path-dependence rather than pure idempotency.

## Results

| Run | Cycle | Events | Token Count | Δ Tokens | Map Changed |
|-----|-------|--------|-------------|----------|-------------|
| 0   | 85    | —      | ~790        | —        | —           |
| 1   | 86    | 1      | 790         | +0       | yes         |
| 2   | 89    | 11     | 742         | −48      | yes         |
| 3   | 90    | 5      | 742         | 0        | yes         |
| 4   | 92    | 2      | 742         | 0        | yes         |
| 5   | 93    | 3      | 728         | −14      | yes         |
| 6   | 95    | 9      | 742         | +14      | yes         |
| 7   | 97    | 3      | 595         | −147     | yes         |
| 8   | 99    | 7      | 488         | −107     | yes         |
| 9   | 101   | 3      | 457         | −31      | yes         |
| 10  | 102   | 1      | 457         | 0        | yes         |

**Cycles continue after run 10:** pending events remain, map continues changing.

### Aggregate

- **Entry count:** 11 → 6 (−45%)
- **Token count:** ~790 → 457 (−42%)
- **Map changed every run:** 10/10
- **Stable state reached:** ❌ (still churning at cycle 102)

## Classification

### Not a Deliberation Cascade

The Cartographer did not produce divergent edits from identical input.
It produced **path-dependent** edits from an evolving map state.
Each run started from a different map than the previous run, so different
decisions are expected. The skill's >20% edit disagreement metric cannot
be applied to this protocol.

### Compounding Consolidation

The Cartographer treated repeated identical observations as amplified
signal, triggering increasingly aggressive compression:

- Early runs (1–6): map oscillated narrowly around 728–790 tokens
- Late runs (7–10): map collapsed from 742 → 457 tokens
- Long-lived entries that survived 80+ prior cycles were evicted

This is **rational behavior under signal amplification** — the Cartographer
interprets "same observation keeps arriving" as "this is the most important
thing, compress everything else." In a normal session, 10 identical
observations would never arrive consecutively, so this pathology is
artificial.

### Non-Convergence

The pipeline does not reach a fixed point. After 10 cycles:
- `map_changed: true` on every run
- Pending events still queued at cycle 102
- Each materialization generates derivation/eviction events that trigger
  further materializations

This is the **actual concern**: the pipeline lacks a convergence guarantee.
In theory, a runaway feedback loop is possible if eviction events themselves
trigger further materialization cycles indefinitely.

## Assessment

| Concern | Severity | Real-World Risk |
|---------|----------|-----------------|
| Compounding consolidation under repeated signal | Low | 10 identical observations never happen naturally |
| Non-convergent pipeline | Medium | Derivation events could loop; needs a max-cycle guard |
| Map instability across cycles | Low | Normal sessions have diverse observations, not repeats |

## Recommendations

1. **Add a max-cycles-per-materialization guard** to prevent runaway loops
   from derivation events. A limit of ~5 cycles per `context-map-materializer`
   call would be reasonable.

2. **Track cycle-churn as a metric.** If `map_changed: true` for >3 consecutive
   cycles on the same event batch, log a warning. This would catch the
   non-convergence pattern without false positives.

3. **Retest with diverse observations** (Test 2 from the stress plan):
   10 *different* observations of varying types to see if the Cartographer
   stabilizes under normal input diversity.

4. **Retest the pure idempotency protocol** if/when the materializer supports
   re-materialization from a snapshot (not event-consumption). This would
   directly test the deliberation cascade hypothesis.
