# Dashboard: Session Inspector & Context Map Explorer

**Date:** 2026-05-25
**Scope:** Extend the existing Dash dashboard with two new tabs — Session Inspector and Context Map Explorer — while preserving all existing panels unchanged.

---

## Problem

The existing dashboard shows aggregate metrics. There is no way to drill into a single session's event sequence, nor to visually understand the composition and health of a context map corpus. Both are required for day-to-day debugging of agent runs.

---

## Architecture

### Tab structure

Wrap the existing `_layout()` body in `dcc.Tabs`. Three tabs:

| Tab | Content |
|---|---|
| **Overview** | All current panels, untouched |
| **Session Inspector** | Session drill-down: timeline, token spend, event log |
| **Context Map Explorer** | Corpus drill-down: sunburst, scatter, stickiness bar, entry table |

The existing corpus selector (`id="corpus-selector"`) and entry table (`id="entry-table"`) move into the Context Map Explorer tab under new component IDs. The Overview tab retains the existing context-maps health table (`id="context-table"`).

---

## Session Inspector tab

### Layout (top to bottom)

1. **`dcc.Dropdown(id="session-selector")`** — populated with recent sessions; label = truncated goal + short session_id suffix; refreshes on `dcc.Interval`
2. **`dcc.Graph(id="session-timeline")`** — event timeline scatter
3. **`dcc.Graph(id="session-token-spend")`** — cumulative token spend line
4. **`DataTable(id="session-event-log")`** — raw event log with conditional row colouring

### Timeline chart (`session-timeline`)

- `px.scatter`, x=`created_at`, y=`event_type` (categorical)
- Color by `event_type`
- Marker size: `tokens_used` for `LLMActionEmitted`, fixed size (8) for all others
- Hover: `skill_name`, `status`, `content_preview` (first 120 chars)
- Title: "Session Event Timeline"

### Cumulative token spend (`session-token-spend`)

- Filter events to `LLMActionEmitted` only, sorted by `created_at`
- `go.Scatter`, x=`created_at`, y=running cumulative sum of `tokens_used`
- `fill='tozeroy'`, color `#2563eb`
- Title: "Cumulative Tokens"

### Event log (`session-event-log`)

- All events for session, sorted by `created_at` asc
- Columns: `time_delta` (seconds from session start), `event_type`, `skill_name`, `status`, `tokens_used`, `content_preview`
- `style_data_conditional`:
  - Red background (`#fee2e2`) for rows where `status` not in `['', 'success']` or `event_type == 'StreamPaused'`
  - Green background (`#dcfce7`) for `event_type == 'SkillCompleted'` with `status == 'success'`

---

## Context Map Explorer tab

### Layout

1. **`dcc.Dropdown(id="explorer-corpus-selector")`** — same corpus list, separate component from the existing selector
2. Two-column row:
   - **`dcc.Graph(id="map-sunburst")`** — token budget by section
   - **`dcc.Graph(id="map-priority-scatter")`** — priority vs token cost
3. **`dcc.Graph(id="map-stickiness-bar")`** — entry stickiness (materialization count)
4. **`DataTable(id="explorer-entry-table")`** — existing filterable/sortable entry table, moved here

### Sunburst (`map-sunburst`)

- `px.sunburst`, `path=['section', 'observation_type']`, `values='token_estimate'`
- `color='observation_type'`
- Title: "Token Budget by Section"
- Empty state: text annotation "No corpus selected"

### Priority scatter (`map-priority-scatter`)

- `px.scatter`, x=`priority`, y=`token_estimate`, color=`observation_type`
- `hover_data=['key', 'summary', 'materialization_count']`
- Title: "Priority vs Token Cost"

### Stickiness bar (`map-stickiness-bar`)

- `go.Bar`, horizontal (`orientation='h'`)
- y=`key`, x=`materialization_count`, color by `observation_type`
- Sorted by `materialization_count` descending, top 20 entries
- Title: "Entry Stickiness (Materialization Count)"

### Entry table (`explorer-entry-table`)

- Identical to current `entry-table`: filterable, sortable, 15 rows/page
- Triggered by `explorer-corpus-selector` value instead of old `corpus-selector`

---

## Data layer

### New dataclass

```python
@dataclass(frozen=True, slots=True)
class SessionEventRow:
    event_id: int
    event_type: str
    created_at: str
    skill_name: str
    status: str
    tokens_used: int
    content_preview: str
```

### New fetch functions (`core/observability/dashboard.py`)

**`fetch_session_ids(engine, limit=50) -> list[dict]`**

Query `state_events` grouped by `scope_id`, returning the most recent N sessions ordered by latest `created_at`. Each row: `session_id`, `goal` (from `AgentStarted` payload), `last_seen`.

**`fetch_session_events(engine, session_id) -> list[SessionEventRow]`**

Select all `state_events` rows for `scope_id = session_id`, ordered by `created_at` asc. Extract from payload: `skill_name` (or `tool_name`), `status`, `tokens_used`, content preview. Compute `time_delta` as seconds from the earliest event in the result.

### Exports

Add both functions and `SessionEventRow` to `harness_poc/core/observability/__init__.py`.

---

## Callbacks

### Overview tab (updated)

The existing `update_dashboard` callback currently outputs to `corpus-selector` options. That output moves to the Explorer tab's `explorer-corpus-selector`. Remove the `corpus-selector` / `entry-table` components and their outputs from `update_dashboard`. All other outputs remain identical.

### Session Inspector callbacks

| Trigger | Output |
|---|---|
| `dcc.Interval` | `session-selector` options |
| `session-selector` value | `session-timeline` figure, `session-token-spend` figure, `session-event-log` data+columns |

### Context Map Explorer callbacks

| Trigger | Output |
|---|---|
| `dcc.Interval` | `explorer-corpus-selector` options |
| `explorer-corpus-selector` value | `map-sunburst`, `map-priority-scatter`, `map-stickiness-bar`, `explorer-entry-table` data+columns |

---

## Files touched

| File | Change |
|---|---|
| `harness_poc/dashboard_app.py` | Wrap layout in `dcc.Tabs`; add Session Inspector and Context Map Explorer tab layouts; register new callbacks; move corpus/entry section to Explorer tab |
| `harness_poc/core/observability/dashboard.py` | Add `SessionEventRow`, `fetch_session_ids`, `fetch_session_events` |
| `harness_poc/core/observability/__init__.py` | Export new symbols |

No new dependencies. `plotly.express` is already available.

---

## Out of scope

- Pipeline execution visualization
- Goal evaluation charts
- Sub-agent tree
- Any changes to the TUI or REPL
