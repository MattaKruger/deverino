# Dashboard Overhaul — Formula 1 Pit Wall for Agentic Systems

## Motivation

Current dashboard is table-heavy, tabbed, light-theme, and shows aggregate counters — no tool-call visibility, no sub-agent lifecycle, no real-time event flow. The user wants dark-theme, data-dense, real-time insights optimized for debugging and observing agentic pipelines.

## Design Principles

1. **Dark pit-wall aesthetic** — `#0d1117` background, high-contrast data, color-coded status (green/yellow/red)
2. **Everything at a glance** — single scrollable page, no tabs. Multiple small panels instead of few large ones.
3. **Visual, not textual** — charts, sparklines, topology trees, heatmaps; tables only as last resort
4. **Real-time** — 2s refresh for time-sensitive data (active sessions, event firehose), 10s for aggregates
5. **Drill-down** — hover tooltips with detail, clickable elements that filter/focus

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  HARNESS PIT WALL                          events/s  ████▓░ │
│  ═══════════════                          db: 2ms  ● active │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Sessions │ Tools    │ Tools    │ Sub-Ag   │ Sub-Ag Tree     │
│ active:3 │ freq bar │ latency  │ running:2│ [sunburst]      │
│ [gauges] │ [bar]    │ [violin] │ [gauge]  │                 │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│  Event Firehose (scroll, filter by type/session/severity)    │
│  ┌──────┬──────────┬──────────┬────────┬──────────────────┐ │
│  │ time │ type     │ session  │ tokens │ preview          │ │
│  │ 12ms │ SkillOK  │ s1       │ 450    │ read_file: ...   │ │
│  │ 18ms │ SubSpwn  │ s1       │ -      │ code_reviewer    │ │
│  └──────┴──────────┴──────────┴────────┴──────────────────┘ │
├──────────┬──────────┬──────────┬────────────────────────────┤
│ Token    │ Context  │ Error    │ Session Timeline           │
│ spend    │ Map Heat │ dist     │ [gantt of last N events]   │
│ [area]   │ [heatmap]│ [scatter]│                            │
└──────────┴──────────┴──────────┴────────────────────────────┘
```

## Data Sources

### `state_events` — Session-scoped events
- `SkillCalled`, `SkillCompleted`, `SkillCancelled`, `SkillRequested`
- `LLMActionEmitted`, `LLMTextEmitted`, `StreamPaused`
- `SubAgentDispatched`, `SubAgentCompleted`
- `AgentStarted`, `AgentInputAdded`, `GoalEvaluated`, `AgentTurnRecorded`
- Pipeline events, V2 events, Gate events

Payload is JSON with nested `payload` object containing event-specific fields.

### `context_map_events` — Corpus-scoped events
- `SubAgentTaskStarted`, `SubAgentTaskCompleted` (Approach B lifecycle events)
- `ContextWarmed`, `ProbeFailed` (via `ContextEventBridge`)
- `CorpusIngested`, `MapEntryInserted`, etc. (materialization events)

Payload is string-serialized JSON.

## Panels

### 1. System Health Bar (top)
- Active sessions count
- Events/second (trailing 60s average)
- DB latency (last query ms)
- Active sub-agents count
- Context map pending events count
- Refresh indicator

### 2. Tool Call Frequency (bar chart)
- Top 10 tools by call count in last hour
- Color-coded: blue=skills, green=system tools, orange=sub-agent spawns
- Hover: success rate, avg latency

### 3. Tool Latency Distribution (violin plot)
- Per-tool latency distribution (time between SkillCalled and SkillCompleted)
- Y-axis: tool name, X-axis: latency in seconds
- Split by status (success green, failed red)

### 4. Sub-Agent Topology (sunburst or treemap)
- Root: session
- Children: sub-agents spawned from that session
- Size: token spend
- Color: status (running green, completed blue, failed red)

### 5. Event Firehose (virtualized scrolling table)
- Last 200 events, newest first
- Columns: time delta, event type, session, skill/tool, tokens, preview
- Color-coded rows by event severity
- Filter dropdowns: event type, session
- Click row → expand detail panel

### 6. Token Economics (stacked area)
- Input/output tokens over time, stacked
- One trace per model
- Last 60 minutes, 1-minute buckets

### 7. Context Map Health (heatmap)
- Rows: corpus_keys
- Columns: time buckets (last 12 x 5-min intervals)
- Color: event count in that bucket
- Click → filter firehose to that corpus

### 8. Error Distribution (scatter plot)
- X: time, Y: skill/tool name
- Size: error count
- Color: error type (timeout, validation, crash, etc.)

### 9. Session Timeline (horizontal Gantt)
- Last 50 events across all sessions
- Each event = a bar positioned at its timestamp
- Color by event type
- Height by duration (for paired events like skill call→complete)

## Implementation Plan

### Phase 1: New data fetchers (`dashboard.py`)
Add queries for:
- `fetch_recent_events(engine, limit=200)` — unified event stream from both tables
- `fetch_tool_latency(engine, minutes=60)` — paired SkillCalled/SkillCompleted timing
- `fetch_sub_agent_tree(engine)` — parent-child relationships from SubAgentDispatched/Completed
- `fetch_event_throughput(engine, window_s=60)` — events/sec
- `fetch_error_summary(engine, hours=24)` — error distribution

### Phase 2: Dashboard rewrite (`dashboard_app.py`)
- Dark theme CSS variables
- Single-page grid layout, no tabs
- 2s + 10s dual-interval refresh
- All new panels

### Phase 3: Polish
- Hover tooltips on all charts
- Click-to-filter interactions
- Responsive grid
- Error/boundary handling for empty states

## Non-Goals
- Authentication/access control
- Persistent dashboard config (saved filters)
- Alerting/notifications
- Historical replay
