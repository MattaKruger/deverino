# Deverino Rewrite — Component Extraction

A working inventory of what's in the current POC, what to carry over to the rewrite, and why.

## Conventions

### Layers

- `concept` — an architectural idea (e.g., "event-sourced runtime")
- `code` — a concrete module, class, or contract (e.g., `core/events/event_bus.py`)

A `concept` row in the inventory is followed by the `code` rows that realize it.

### Disposition

- `keep` — extract concept and code roughly as-is
- `redesign` — concept stays, implementation needs rework
- `defer` — out of scope for v1 of the rewrite, revisit later
- `drop` — not coming over
- `experiment` — still figuring out if it belongs

### Keeper template

Copy this stub for every `keep` and `redesign` entry. Promote to `docs/rewrite/components/<name>.md` with a back-link if it grows past ~200 lines.

```markdown
## <Component Name>

**Disposition:** keep | redesign
**Layer:** concept | code

**Concept:** One sentence at the architectural level.

**Current realization:**
- `path/to/code` — what's there

**Why keep:** What worked, what insight this captures. Be specific —
"events are typed and durable so we can rebuild state" beats
"good architecture."

**What to change:** Known warts, lessons learned, things to do
differently in the rewrite.

**Depends on:** Other entries in this doc this one needs.

**ACDL status:** spec'd | needs spec | N/A

**Tested via:** Pointer to one or two test files
(e.g., `tests/agent/test_goal_runner.py`). Keep it lightweight — a
path, not a chunk list.

**Notes:** Free-form.
```

## Inventory

| Component | Layer | Disposition | One-liner |
|---|---|---|---|
|   |   |   |   |

## Keepers

<!-- Use the keeper template above for each entry. Pre-seeded slots below. -->

### Event-sourced runtime

_TBD_

---

### Context map (PEEK)

_TBD_

---

### SOUL / pedagogy setup

_TBD_

---

### Self-introspection skills

_TBD_

---

### ACDL as the standard language

_TBD_

## Consciously dropped / deferred

| Component | Disposition | Why |
|---|---|---|
|   |   |   |
