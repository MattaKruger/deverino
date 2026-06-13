# Dashboard: Session Inspector & Context Map Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Dash dashboard with two new tabs — Session Inspector (per-session event timeline + token spend + event log) and Context Map Explorer (sunburst, priority scatter, stickiness bar, entry table) — while keeping all existing panels unchanged.

**Architecture:** Wrap the existing layout in `dcc.Tabs`. Extract the corpus/entry section from Overview into a new Context Map Explorer tab with renamed component IDs. Add a Session Inspector tab backed by two new fetch functions. A single `dcc.Interval` callback handles all time-based refreshes; two separate value-driven callbacks handle per-session and per-corpus drill-downs.

**Tech Stack:** Dash 4+, Plotly `graph_objects`, SQLAlchemy, PostgreSQL (test DB at `postgresql://deverino_test:deverino_test@localhost:5433/deverino_test`)

---

## File Map

| File | Change |
|---|---|
| `harness_poc/core/observability/dashboard.py` | Add `SessionEventRow` dataclass + `fetch_session_ids` + `fetch_session_events` |
| `harness_poc/core/observability/__init__.py` | Export the three new symbols |
| `harness_poc/dashboard_app.py` | Restructure layout into tabs; add Session Inspector + Context Map Explorer layouts; update + add callbacks |
| `tests/infra/test_dashboard.py` | Add tests for the two new fetch functions |

---

## Task 1: Data layer — session fetch functions

**Files:**
- Modify: `harness_poc/core/observability/dashboard.py`
- Modify: `tests/infra/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/infra/test_dashboard.py`:

```python
from harness_poc.core.observability.dashboard import (
    fetch_session_ids,
    fetch_session_events,
)


def test_fetch_session_ids_returns_recent_sessions(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(AgentStarted(session_id="sess-aaa", goal="Find the answer"))
    store.persist(LLMActionEmitted(session_id="sess-aaa", model="fake", tokens_used=5, input_tokens=3, output_tokens=2))
    store.persist(AgentStarted(session_id="sess-bbb", goal="Do another thing"))

    results = fetch_session_ids(db_engine, limit=10)

    ids = [r[0] for r in results]
    assert "sess-aaa" in ids
    assert "sess-bbb" in ids
    # most recent first
    assert ids.index("sess-bbb") < ids.index("sess-aaa")
    # label contains truncated goal and session suffix
    labels = {r[0]: r[1] for r in results}
    assert "Find the answer" in labels["sess-aaa"]
    assert "sess-aaa"[-8:] in labels["sess-aaa"]


def test_fetch_session_events_returns_ordered_events_with_time_delta(db_engine: Engine) -> None:
    store = EventStore(db_engine)
    store.persist(AgentStarted(session_id="sess-xyz", goal="Run a test"))
    store.persist(SkillCalled(session_id="sess-xyz", tool_name="search_documents"))
    store.persist(
        SkillCompleted(
            session_id="sess-xyz",
            tool_name="search_documents",
            status="success",
            content="some result",
        )
    )
    store.persist(
        LLMActionEmitted(
            session_id="sess-xyz",
            model="fake",
            tokens_used=20,
            input_tokens=15,
            output_tokens=5,
        )
    )
    store.persist(StreamPaused(session_id="sess-xyz", reason="budget"))

    rows = fetch_session_events(db_engine, "sess-xyz")

    assert len(rows) == 5
    assert rows[0].event_type == "AgentStarted"
    assert rows[0].time_delta == 0.0
    # all subsequent time_deltas are >= 0
    assert all(r.time_delta >= 0.0 for r in rows)
    # LLMActionEmitted row has tokens_used populated
    llm_rows = [r for r in rows if r.event_type == "LLMActionEmitted"]
    assert llm_rows[0].tokens_used == 20
    # SkillCompleted has content_preview
    skill_rows = [r for r in rows if r.event_type == "SkillCompleted"]
    assert "some result" in skill_rows[0].content_preview
    # unknown session returns empty list
    assert fetch_session_events(db_engine, "no-such-session") == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/infra/test_dashboard.py::test_fetch_session_ids_returns_recent_sessions tests/infra/test_dashboard.py::test_fetch_session_events_returns_ordered_events_with_time_delta -v
```

Expected: `ImportError` or `AttributeError` — `fetch_session_ids` not defined yet.

- [ ] **Step 3: Add `SessionEventRow` and the two fetch functions**

In `harness_poc/core/observability/dashboard.py`, after the `SessionTokenUsage` dataclass and before `DashboardSnapshot`, add:

```python
@dataclass(frozen=True, slots=True)
class SessionEventRow:
    event_id: int
    event_type: str
    created_at: str
    time_delta: float
    skill_name: str
    status: str
    tokens_used: int
    content_preview: str
```

Then append these two functions at the bottom of the file (before `fetch_corpus_keys`):

```python
def fetch_session_ids(engine: Engine, *, limit: int = 50) -> list[tuple[str, str]]:
    """Return (session_id, display_label) pairs ordered most-recent-first."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        scope_id as session_id,
                        coalesce(
                            max(payload->'payload'->>'goal')
                                filter (where event_type = 'AgentStarted'),
                            ''
                        ) as goal,
                        max(created_at) as last_seen
                    from state_events
                    where scope = 'session'
                    group by scope_id
                    order by max(created_at) desc
                    limit :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )
    return [
        (
            str(row["session_id"]),
            f"{str(row['goal'])[:60] or '—'}  [{str(row['session_id'])[-8:]}]",
        )
        for row in rows
    ]


def fetch_session_events(engine: Engine, session_id: str) -> list[SessionEventRow]:
    """Return all events for *session_id* ordered by time, with a time_delta field."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    select
                        id,
                        event_type,
                        created_at,
                        coalesce(
                            nullif(payload->'payload'->>'skill_name', ''),
                            nullif(payload->'payload'->>'tool_name', ''),
                            ''
                        ) as skill_name,
                        coalesce(payload->'payload'->>'status', '') as status,
                        coalesce(
                            nullif(payload->'payload'->>'tokens_used', '')::int,
                            0
                        ) as tokens_used,
                        coalesce(
                            nullif(payload->'payload'->>'content', ''),
                            nullif(payload->'payload'->>'result', ''),
                            nullif(payload->'payload'->>'goal', ''),
                            nullif(payload->'payload'->>'reason', ''),
                            ''
                        ) as content
                    from state_events
                    where scope_id = :session_id
                    order by created_at asc, id asc
                    """
                ),
                {"session_id": session_id},
            )
            .mappings()
            .all()
        )

    if not rows:
        return []

    from datetime import datetime  # noqa: PLC0415

    def _parse_ts(s: str) -> datetime | None:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    first_ts = _parse_ts(str(rows[0]["created_at"]))
    result: list[SessionEventRow] = []
    for row in rows:
        ts = _parse_ts(str(row["created_at"]))
        delta = round((ts - first_ts).total_seconds(), 1) if ts and first_ts else 0.0
        result.append(
            SessionEventRow(
                event_id=int(row["id"]),
                event_type=str(row["event_type"]),
                created_at=str(row["created_at"]),
                time_delta=delta,
                skill_name=str(row["skill_name"] or ""),
                status=str(row["status"] or ""),
                tokens_used=int(row["tokens_used"] or 0),
                content_preview=str(row["content"] or "")[:120],
            )
        )
    return result
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/infra/test_dashboard.py::test_fetch_session_ids_returns_recent_sessions tests/infra/test_dashboard.py::test_fetch_session_events_returns_ordered_events_with_time_delta -v
```

Expected: both PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest tests/infra/test_dashboard.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/observability/dashboard.py tests/infra/test_dashboard.py
git commit -m "feat(dashboard): add fetch_session_ids and fetch_session_events"
```

---

## Task 2: Export new symbols

**Files:**
- Modify: `harness_poc/core/observability/__init__.py`

- [ ] **Step 1: Add imports and `__all__` entries**

In `harness_poc/core/observability/__init__.py`, update the import block and `__all__`:

```python
from harness_poc.core.observability.dashboard import (
    ContextMapEntrySummary,
    ContextMapHealth,
    DashboardSnapshot,
    DashboardSummary,
    ModelTokenUsage,
    RecentFailure,
    SessionActivity,
    SessionEventRow,
    SessionTokenUsage,
    SkillPerformance,
    TokenBucket,
    fetch_context_map_entries,
    fetch_context_map_health,
    fetch_corpus_keys,
    fetch_dashboard_snapshot,
    fetch_model_token_usage,
    fetch_recent_failures,
    fetch_session_activity,
    fetch_session_events,
    fetch_session_ids,
    fetch_session_token_usage,
    fetch_skill_performance,
    fetch_summary,
    fetch_token_buckets,
    snapshot_to_dict,
)
from harness_poc.core.observability.logfire_subscriber import configure_logfire, wire_logfire

__all__ = [
    "ContextMapEntrySummary",
    "ContextMapHealth",
    "DashboardSnapshot",
    "DashboardSummary",
    "ModelTokenUsage",
    "RecentFailure",
    "SessionActivity",
    "SessionEventRow",
    "SessionTokenUsage",
    "SkillPerformance",
    "TokenBucket",
    "configure_logfire",
    "fetch_context_map_entries",
    "fetch_context_map_health",
    "fetch_corpus_keys",
    "fetch_dashboard_snapshot",
    "fetch_model_token_usage",
    "fetch_recent_failures",
    "fetch_session_activity",
    "fetch_session_events",
    "fetch_session_ids",
    "fetch_session_token_usage",
    "fetch_skill_performance",
    "fetch_summary",
    "fetch_token_buckets",
    "snapshot_to_dict",
    "wire_logfire",
]
```

- [ ] **Step 2: Verify import resolves**

```bash
uv run python -c "from harness_poc.core.observability import fetch_session_ids, fetch_session_events, SessionEventRow; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add harness_poc/core/observability/__init__.py
git commit -m "feat(dashboard): export session fetch functions and SessionEventRow"
```

---

## Task 3: Restructure layout into three tabs

**Files:**
- Modify: `harness_poc/dashboard_app.py`

The goal: wrap existing content in an **Overview** tab, add empty-layout stubs for **Session Inspector** and **Context Map Explorer**, and update `update_dashboard` to drop the old `corpus-selector` output and add outputs for `explorer-corpus-selector` and `session-selector`.

- [ ] **Step 1: Refactor `_layout()` and extract helper functions**

Replace the entire `_layout()` function and add two stub tab helpers. The existing layout body becomes `_overview_tab()`. The existing corpus/entry-table section (the `html.Div` block with `id="corpus-selector"` and `id="entry-table"`) is **removed** from `_overview_tab()` — it will live in the Explorer tab in Task 4.

```python
def _layout() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.H1("Harness Dashboard", style={"margin": "0", "fontSize": "24px"}),
                    html.Div(
                        id="last-updated",
                        style={"color": "#5f6b7a", "fontSize": "13px"},
                    ),
                ],
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "baseline",
                    "gap": "16px",
                    "marginBottom": "16px",
                },
            ),
            dcc.Interval(id="refresh", interval=10_000, n_intervals=0),
            dcc.Tabs(
                [
                    dcc.Tab(label="Overview", children=_overview_tab()),
                    dcc.Tab(label="Session Inspector", children=_session_inspector_tab()),
                    dcc.Tab(label="Context Map Explorer", children=_context_map_explorer_tab()),
                ],
            ),
        ],
        style={
            "fontFamily": "Inter, ui-sans-serif, system-ui, sans-serif",
            "padding": "18px",
            "backgroundColor": "#f7f9fb",
            "minHeight": "100vh",
            "color": "#182230",
        },
    )


def _overview_tab() -> list:
    """Content of the Overview tab — all existing panels, minus the corpus/entry section."""
    return [
        html.Div(
            id="summary",
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fit, minmax(150px, 1fr))",
                "gap": "10px",
                "marginBottom": "16px",
                "paddingTop": "12px",
            },
        ),
        html.Div(
            [
                html.Div(
                    [dcc.Graph(id="token-chart", config={"displayModeBar": False})],
                    style={"minWidth": 0},
                ),
                html.Div(
                    [
                        html.H2("Context Maps", style={"fontSize": "16px"}),
                        dash_table.DataTable(
                            id="context-table",
                            page_size=8,
                            style_table={"overflowX": "auto"},
                            style_cell={
                                "fontFamily": "system-ui, sans-serif",
                                "fontSize": "13px",
                                "padding": "8px",
                                "textAlign": "left",
                                "maxWidth": "260px",
                                "overflow": "hidden",
                                "textOverflow": "ellipsis",
                            },
                            style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                        ),
                    ],
                    style={**CARD_STYLE, "minWidth": 0},
                ),
            ],
            style={
                "display": "grid",
                "gridTemplateColumns": "minmax(0, 1.4fr) minmax(320px, 0.8fr)",
                "gap": "12px",
                "marginBottom": "12px",
            },
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.H2("Session Activity", style={"fontSize": "16px"}),
                        dash_table.DataTable(
                            id="session-activity-table",
                            page_size=12,
                            style_table={"overflowX": "auto"},
                            style_cell=_table_cell_style(),
                            style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                        ),
                    ],
                    style={**CARD_STYLE, "minWidth": 0},
                ),
                html.Div(
                    [
                        html.H2("Tokens By Model", style={"fontSize": "16px"}),
                        dash_table.DataTable(
                            id="model-token-table",
                            page_size=12,
                            style_table={"overflowX": "auto"},
                            style_cell=_table_cell_style(),
                            style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                        ),
                    ],
                    style={**CARD_STYLE, "minWidth": 0},
                ),
                html.Div(
                    [
                        html.H2("Tokens By Session", style={"fontSize": "16px"}),
                        dash_table.DataTable(
                            id="session-token-table",
                            page_size=12,
                            style_table={"overflowX": "auto"},
                            style_cell=_table_cell_style(),
                            style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                        ),
                    ],
                    style={**CARD_STYLE, "minWidth": 0},
                ),
            ],
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fit, minmax(360px, 1fr))",
                "gap": "12px",
                "marginBottom": "12px",
            },
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.H2("Skill Performance", style={"fontSize": "16px"}),
                        dash_table.DataTable(
                            id="skill-table",
                            page_size=12,
                            style_table={"overflowX": "auto"},
                            style_cell=_table_cell_style(),
                            style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                        ),
                    ],
                    style={**CARD_STYLE, "minWidth": 0},
                ),
                html.Div(
                    [
                        html.H2("Recent Attention", style={"fontSize": "16px"}),
                        dash_table.DataTable(
                            id="failure-table",
                            page_size=12,
                            style_table={"overflowX": "auto"},
                            style_cell=_table_cell_style(),
                            style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                        ),
                    ],
                    style={**CARD_STYLE, "minWidth": 0},
                ),
            ],
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fit, minmax(360px, 1fr))",
                "gap": "12px",
                "marginBottom": "12px",
            },
        ),
    ]


def _session_inspector_tab() -> list:
    """Stub — callbacks populated in Task 4."""
    return [
        html.Div(
            [
                dcc.Dropdown(
                    id="session-selector",
                    placeholder="Select a session to inspect…",
                    style={"marginBottom": "12px"},
                ),
                dcc.Graph(id="session-timeline", config={"displayModeBar": False}),
                dcc.Graph(id="session-token-spend", config={"displayModeBar": False}),
                html.H2("Event Log", style={"fontSize": "16px", "marginTop": "12px"}),
                dash_table.DataTable(
                    id="session-event-log",
                    page_size=20,
                    sort_action="native",
                    style_table={"overflowX": "auto"},
                    style_cell={
                        **_table_cell_style(),
                        "maxWidth": "400px",
                    },
                    style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                ),
            ],
            style={"paddingTop": "12px"},
        )
    ]


def _context_map_explorer_tab() -> list:
    """Stub — callbacks populated in Task 5."""
    return [
        html.Div(
            [
                dcc.Dropdown(
                    id="explorer-corpus-selector",
                    placeholder="Select a corpus to explore…",
                    style={"marginBottom": "12px"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="map-sunburst", config={"displayModeBar": False}),
                        dcc.Graph(id="map-priority-scatter", config={"displayModeBar": False}),
                    ],
                    style={
                        "display": "grid",
                        "gridTemplateColumns": "1fr 1fr",
                        "gap": "12px",
                        "marginBottom": "12px",
                    },
                ),
                dcc.Graph(id="map-stickiness-bar", config={"displayModeBar": False}),
                html.H2("Map Entries", style={"fontSize": "16px", "marginTop": "12px"}),
                dash_table.DataTable(
                    id="explorer-entry-table",
                    data=[],
                    columns=[],
                    page_size=15,
                    sort_action="native",
                    filter_action="native",
                    style_table={"overflowX": "auto"},
                    style_cell={
                        **_table_cell_style(),
                        "maxWidth": "360px",
                    },
                    style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
                ),
            ],
            style={"paddingTop": "12px"},
        )
    ]
```

- [ ] **Step 2: Update `update_dashboard` callback signature**

In `_register_callbacks`, replace the existing `update_dashboard` callback with this updated version (outputs `explorer-corpus-selector` and `session-selector` options instead of old `corpus-selector`; removes `Output("corpus-selector", "options")`):

```python
@callback(
    Output("summary", "children"),
    Output("token-chart", "figure"),
    Output("skill-table", "data"),
    Output("skill-table", "columns"),
    Output("failure-table", "data"),
    Output("failure-table", "columns"),
    Output("context-table", "data"),
    Output("context-table", "columns"),
    Output("session-activity-table", "data"),
    Output("session-activity-table", "columns"),
    Output("model-token-table", "data"),
    Output("model-token-table", "columns"),
    Output("session-token-table", "data"),
    Output("session-token-table", "columns"),
    Output("last-updated", "children"),
    Output("explorer-corpus-selector", "options"),
    Output("session-selector", "options"),
    Input("refresh", "n_intervals"),
)
def update_dashboard(_: int) -> tuple[Any, ...]:
    snapshot = fetch_dashboard_snapshot(engine)
    data = snapshot_to_dict(snapshot)
    corpus_options = [
        {"label": key, "value": key} for key in fetch_corpus_keys(engine)
    ]
    session_options = [
        {"label": label, "value": sid}
        for sid, label in fetch_session_ids(engine)
    ]
    return (
        _summary_cards(data["summary"]),
        _token_figure(data["token_buckets"]),
        data["skills"],
        _columns(data["skills"]),
        data["recent_failures"],
        _columns(data["recent_failures"]),
        data["context_maps"],
        _columns(data["context_maps"]),
        data["session_activity"],
        _columns(data["session_activity"]),
        data["model_token_usage"],
        _columns(data["model_token_usage"]),
        data["session_token_usage"],
        _columns(data["session_token_usage"]),
        "Refreshes every 10 seconds",
        corpus_options,
        session_options,
    )
```

Also update the import at the top of `dashboard_app.py`:

```python
from harness_poc.core.observability import (
    fetch_context_map_entries,
    fetch_corpus_keys,
    fetch_dashboard_snapshot,
    fetch_session_events,
    fetch_session_ids,
    snapshot_to_dict,
)
```

- [ ] **Step 3: Remove old `update_entries` callback (it will be replaced in Task 5)**

Delete the existing `update_entries` callback function from `_register_callbacks`. Task 5 adds the replacement.

- [ ] **Step 4: Verify the app starts without errors**

```bash
uv run harness-poc dashboard 2>&1 | head -20
```

Expected: Dash starts on port 8050, no `KeyError` or `ComponentID` errors. (Ctrl-C to stop.)

- [ ] **Step 5: Commit**

```bash
git add harness_poc/dashboard_app.py
git commit -m "feat(dashboard): restructure layout into Overview / Session Inspector / Context Map Explorer tabs"
```

---

## Task 4: Session Inspector callbacks

**Files:**
- Modify: `harness_poc/dashboard_app.py`

Add the figure builders and the callback that populates the Session Inspector tab.

- [ ] **Step 1: Add `_session_timeline_figure`**

Add this function after `_token_figure` in `dashboard_app.py`:

```python
def _session_timeline_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not rows:
        fig.add_annotation(
            text="No session selected",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#5f6b7a"},
        )
        fig.update_layout(
            title="Session Event Timeline",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
        )
        return fig

    event_types = sorted({r["event_type"] for r in rows})
    palette = [
        "#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed",
        "#0891b2", "#be185d", "#64748b", "#059669", "#b45309",
    ]
    color_map = {et: palette[i % len(palette)] for i, et in enumerate(event_types)}

    for et in event_types:
        subset = [r for r in rows if r["event_type"] == et]
        fig.add_trace(
            go.Scatter(
                x=[r["created_at"] for r in subset],
                y=[r["event_type"] for r in subset],
                mode="markers",
                name=et,
                marker=dict(
                    size=[max(8, min(24, r["tokens_used"] // 50 + 8)) for r in subset],
                    color=color_map[et],
                    opacity=0.85,
                ),
                text=[
                    f"{r['skill_name'] or '—'} | {r['status'] or '—'}<br>{r['content_preview']}"
                    for r in subset
                ],
                hovertemplate="%{text}<extra>%{y}</extra>",
            )
        )

    fig.update_layout(
        title="Session Event Timeline",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        margin={"l": 160, "r": 16, "t": 48, "b": 36},
        legend={"orientation": "h", "y": -0.15},
        yaxis={"categoryorder": "array", "categoryarray": list(reversed(event_types))},
    )
    return fig
```

- [ ] **Step 2: Add `_session_token_spend_figure`**

```python
def _session_token_spend_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    llm_rows = [r for r in rows if r["event_type"] == "LLMActionEmitted"]
    if not llm_rows:
        fig.add_annotation(
            text="No LLM events in session",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#5f6b7a"},
        )
        fig.update_layout(
            title="Cumulative Tokens",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
        )
        return fig

    cumulative = 0
    xs, ys = [], []
    for r in llm_rows:
        cumulative += r["tokens_used"]
        xs.append(r["created_at"])
        ys.append(cumulative)

    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers",
            fill="tozeroy",
            line={"color": "#2563eb", "width": 2},
            marker={"size": 6, "color": "#2563eb"},
            name="Cumulative tokens",
        )
    )
    fig.update_layout(
        title="Cumulative Tokens",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        margin={"l": 60, "r": 16, "t": 48, "b": 36},
        yaxis_title="Tokens",
    )
    return fig
```

- [ ] **Step 3: Add the session drill-down callback**

Inside `_register_callbacks`, after `update_dashboard`, add:

```python
@callback(
    Output("session-timeline", "figure"),
    Output("session-token-spend", "figure"),
    Output("session-event-log", "data"),
    Output("session-event-log", "columns"),
    Input("session-selector", "value"),
)
def update_session_inspector(session_id: str | None) -> tuple[Any, ...]:
    from dataclasses import asdict  # noqa: PLC0415

    if not session_id:
        empty_fig = go.Figure()
        empty_fig.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff")
        return empty_fig, empty_fig, [], []

    events = fetch_session_events(engine, session_id)
    rows = [asdict(e) for e in events]

    failure_statuses = {"failed", "error", "cancelled"}
    conditional_style = [
        {
            "if": {
                "filter_query": " || ".join(
                    f'{{status}} = "{s}"' for s in failure_statuses
                )
            },
            "backgroundColor": "#fee2e2",
        },
        {
            "if": {
                "filter_query": '{event_type} = "StreamPaused"',
            },
            "backgroundColor": "#fef9c3",
        },
        {
            "if": {
                "filter_query": '{event_type} = "SkillCompleted" && {status} = "success"',
            },
            "backgroundColor": "#dcfce7",
        },
    ]

    # Apply style_data_conditional via component update — store it on the table
    # Dash doesn't support dynamic style_data_conditional from callbacks directly,
    # so we encode it by setting a dummy Output. Instead, declare the style statically
    # in the layout with a broad enough rule set. Here we just return data/columns;
    # conditional formatting is set in the layout definition (Task 3, Step 1).

    return (
        _session_timeline_figure(rows),
        _session_token_spend_figure(rows),
        rows,
        _columns(rows),
    )
```

> **Note:** Dash supports `style_data_conditional` as a callback Output since Dash 2.6+. To keep things simple, declare the three conditional style rules statically on `session-event-log` in the layout (add `style_data_conditional=[...]` to the `dash_table.DataTable` call in `_session_inspector_tab`). The rules use filter syntax shown above and don't need to be dynamic.

- [ ] **Step 4: Add static conditional formatting to the event log table**

In `_session_inspector_tab()`, update the `dash_table.DataTable` for `session-event-log` to include:

```python
dash_table.DataTable(
    id="session-event-log",
    page_size=20,
    sort_action="native",
    style_table={"overflowX": "auto"},
    style_cell={**_table_cell_style(), "maxWidth": "400px"},
    style_header={"fontWeight": "600", "backgroundColor": "#f2f5f8"},
    style_data_conditional=[
        {
            "if": {"filter_query": '{status} = "failed" || {status} = "error" || {status} = "cancelled"'},
            "backgroundColor": "#fee2e2",
        },
        {
            "if": {"filter_query": '{event_type} = "StreamPaused"'},
            "backgroundColor": "#fef9c3",
        },
        {
            "if": {
                "filter_query": '{event_type} = "SkillCompleted" && {status} = "success"',
            },
            "backgroundColor": "#dcfce7",
        },
    ],
),
```

- [ ] **Step 5: Remove the stale comment from `update_session_inspector`**

Delete the comment block starting with `# Apply style_data_conditional via component update...` from the callback body — it was a scratch note, not code.

- [ ] **Step 6: Smoke-test the Session Inspector tab**

```bash
uv run harness-poc dashboard
```

Open `http://localhost:8050`, click **Session Inspector**, select a session from the dropdown. Confirm the timeline chart, cumulative token chart, and event log appear. Ctrl-C to stop.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/dashboard_app.py
git commit -m "feat(dashboard): add Session Inspector tab with timeline and event log"
```

---

## Task 5: Context Map Explorer callbacks and charts

**Files:**
- Modify: `harness_poc/dashboard_app.py`

Add the three chart builders and the callback that populates the Context Map Explorer tab.

- [ ] **Step 1: Add `_map_sunburst_figure`**

Add after `_session_token_spend_figure`:

```python
def _map_sunburst_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not rows:
        fig.add_annotation(
            text="No corpus selected",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#5f6b7a"},
        )
        fig.update_layout(
            title="Token Budget by Section",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
        )
        return fig

    from collections import defaultdict  # noqa: PLC0415

    agg: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        agg[(r["section"], r["observation_type"])] += r["token_estimate"]

    labels: list[str] = []
    parents: list[str] = []
    values: list[int] = []
    seen_sections: set[str] = set()

    for (section, obs), total in sorted(agg.items()):
        if section not in seen_sections:
            labels.append(section)
            parents.append("")
            section_total = sum(v for (s, _), v in agg.items() if s == section)
            values.append(section_total)
            seen_sections.add(section)
        labels.append(f"{section}\n{obs}")
        parents.append(section)
        values.append(total)

    fig.add_trace(
        go.Sunburst(
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            insidetextorientation="radial",
        )
    )
    fig.update_layout(
        title="Token Budget by Section",
        paper_bgcolor="#ffffff",
        margin={"l": 0, "r": 0, "t": 48, "b": 0},
    )
    return fig
```

- [ ] **Step 2: Add `_map_priority_scatter_figure`**

```python
def _map_priority_scatter_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not rows:
        fig.add_annotation(
            text="No corpus selected",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#5f6b7a"},
        )
        fig.update_layout(
            title="Priority vs Token Cost",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
        )
        return fig

    obs_types = sorted({r["observation_type"] for r in rows})
    palette = [
        "#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed",
        "#0891b2", "#be185d", "#64748b", "#059669",
    ]
    color_map = {ot: palette[i % len(palette)] for i, ot in enumerate(obs_types)}

    for ot in obs_types:
        subset = [r for r in rows if r["observation_type"] == ot]
        fig.add_trace(
            go.Scatter(
                x=[r["priority"] for r in subset],
                y=[r["token_estimate"] for r in subset],
                mode="markers",
                name=ot,
                marker={"size": 10, "color": color_map[ot], "opacity": 0.8},
                text=[
                    f"<b>{r['key']}</b><br>{r['summary'][:80]}<br>materializations: {r['materialization_count']}"
                    for r in subset
                ],
                hovertemplate="%{text}<extra>%{fullData.name}</extra>",
            )
        )

    fig.update_layout(
        title="Priority vs Token Cost",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        margin={"l": 60, "r": 16, "t": 48, "b": 36},
        xaxis_title="Priority",
        yaxis_title="Token Estimate",
        legend={"orientation": "h", "y": -0.2},
    )
    return fig
```

- [ ] **Step 3: Add `_map_stickiness_figure`**

```python
def _map_stickiness_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    if not rows:
        fig.add_annotation(
            text="No corpus selected",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 14, "color": "#5f6b7a"},
        )
        fig.update_layout(
            title="Entry Stickiness (Materialization Count)",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
        )
        return fig

    top = sorted(rows, key=lambda r: r["materialization_count"], reverse=True)[:20]
    top = list(reversed(top))  # horizontal bar reads bottom-to-top

    palette = [
        "#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed",
        "#0891b2", "#be185d", "#64748b", "#059669",
    ]
    obs_types = sorted({r["observation_type"] for r in top})
    color_map = {ot: palette[i % len(palette)] for i, ot in enumerate(obs_types)}

    fig.add_trace(
        go.Bar(
            orientation="h",
            x=[r["materialization_count"] for r in top],
            y=[r["key"] for r in top],
            marker_color=[color_map[r["observation_type"]] for r in top],
            text=[r["observation_type"] for r in top],
            hovertemplate="<b>%{y}</b><br>count: %{x}<br>type: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Entry Stickiness (Materialization Count)",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        margin={"l": 180, "r": 16, "t": 48, "b": 36},
        xaxis_title="Materialization Count",
    )
    return fig
```

- [ ] **Step 4: Add the Context Map Explorer callback**

Inside `_register_callbacks`, after `update_session_inspector`, add:

```python
@callback(
    Output("map-sunburst", "figure"),
    Output("map-priority-scatter", "figure"),
    Output("map-stickiness-bar", "figure"),
    Output("explorer-entry-table", "data"),
    Output("explorer-entry-table", "columns"),
    Input("explorer-corpus-selector", "value"),
)
def update_explorer(corpus_key: str | None) -> tuple[Any, ...]:
    from dataclasses import asdict  # noqa: PLC0415

    if not corpus_key:
        empty = go.Figure()
        empty.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff")
        return empty, empty, empty, [], []

    entries = fetch_context_map_entries(engine, corpus_key)
    rows = [asdict(e) for e in entries]

    return (
        _map_sunburst_figure(rows),
        _map_priority_scatter_figure(rows),
        _map_stickiness_figure(rows),
        rows,
        _columns(rows),
    )
```

- [ ] **Step 5: Smoke-test the Context Map Explorer tab**

```bash
uv run harness-poc dashboard
```

Open `http://localhost:8050`, click **Context Map Explorer**, select a corpus. Confirm sunburst, scatter, and stickiness bar render. Click **Overview** and verify all existing panels are still present. Ctrl-C to stop.

- [ ] **Step 6: Run the full dashboard test suite**

```bash
uv run pytest tests/infra/test_dashboard.py -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/dashboard_app.py
git commit -m "feat(dashboard): add Context Map Explorer tab with sunburst, scatter, and stickiness bar"
```
