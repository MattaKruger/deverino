# Component Extraction Format

Design for `docs/rewrite/COMPONENTS.md` — the working inventory used to decide what carries from the Deverino POC into the rewrite.

## Goal

The POC has grown to ~14 subsystems (event-sourced runtime, context map, workflows, pipelines, retrieval, skills, blackboard, REPL/TUI, observability, ACDL parser, etc.). A rewrite is starting. We need a working document that:

1. Lists every subsystem currently in the POC with a disposition (`keep` / `redesign` / `defer` / `drop` / `experiment`), so nothing silently regrows in the rewrite.
2. Captures, for each keeper, the lessons that justify keeping it and the warts to design out — before re-implementation.
3. Surfaces an ACDL backlog: which keepers already have an ACDL spec and which need one (ACDL is the target lingua franca for the rewrite).

## Shape

Single hybrid doc at `docs/rewrite/COMPONENTS.md`:

1. **Conventions** — layer vocabulary, disposition vocabulary, keeper template.
2. **Inventory** — flat table; one row per subsystem at the `concept` layer, with `code` rows underneath.
3. **Keepers** — deep-dives using the Standard template.
4. **Consciously dropped / deferred** — short table.

Promote to `docs/rewrite/components/<name>.md` when a keeper deep-dive grows past ~200 lines, leaving a stub with a back-link in the main doc.

## Layer vocabulary

- `concept` — architectural idea (e.g., "event-sourced runtime")
- `code` — concrete module/class/contract (e.g., `core/events/event_bus.py`)

Concept rows precede the code rows that realize them.

## Disposition vocabulary

- `keep` — extract concept and code roughly as-is
- `redesign` — concept stays, implementation needs rework
- `defer` — out of scope for v1, revisit later
- `drop` — not coming over
- `experiment` — undecided

## Keeper template (Standard)

Every `keep` / `redesign` entry uses the same fields:

- **Disposition / Layer**
- **Concept** — one architectural sentence
- **Current realization** — paths to current code
- **Why keep** — what worked, what insight is captured (be specific)
- **What to change** — known warts, lessons learned
- **Depends on** — other entries this one needs
- **ACDL status** — `spec'd` | `needs spec` | `N/A`
- **Tested via** — lightweight test-file pointer (one or two paths, not a chunk list)
- **Notes** — free-form

## Pre-seeded keepers

The starting template includes empty stub headings for:

- Event-sourced runtime
- Context map (PEEK)
- SOUL / pedagogy setup
- Self-introspection skills
- ACDL as the standard language

These are the components the author already has conviction on. Contents are deliberately blank — the format is shipping as a starting template; the author will fill in the inventory and deep-dives as the rewrite plan firms up.

## Decisions

- **Inventory with light disposition over shortlist-only.** Forces a verdict on every subsystem so nothing gets re-grown by accident.
- **Standard template over Rich.** Why-keep and what-to-change capture the lessons; risk/complexity/lineage fields tend to become homework that doesn't get done.
- **Single hybrid doc over per-file from the start.** Easier to scan end-to-end; promote individual files only when warranted.
- **Lightweight `Tested via` pointer.** Avoid retrieval-style chunk lists; one or two test paths is enough.
- **No pre-filled inventory rows.** Author is still mapping features; ship empty scaffolding only.

## Out of scope

- Pre-filling inventory rows or keeper deep-dives.
- ACDL spec content itself. The `ACDL status` field flags backlog; the specs live elsewhere.
- Migration plans, ordering, or risk analysis — those belong in a follow-up rewrite plan once the inventory is populated.
