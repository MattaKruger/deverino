from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dash import Dash, Input, Output, callback, dash_table, dcc, html
from plotly import graph_objects as go

from harness_poc.core.observability import (
    fetch_context_map_entries,
    fetch_corpus_keys,
    fetch_dashboard_snapshot,
    fetch_session_events,
    fetch_session_ids,
    snapshot_to_dict,
)
from harness_poc.core.storage import create_db_engine

if TYPE_CHECKING:
    from sqlalchemy import Engine


CARD_STYLE = {
    "border": "1px solid #d7dde5",
    "borderRadius": "6px",
    "padding": "12px",
    "backgroundColor": "#ffffff",
}


def create_dashboard_app(database_url: str) -> Dash:
    engine = create_db_engine(database_url)
    app = Dash(__name__)
    app.title = "Harness Dashboard"
    app.layout = _layout()
    _register_callbacks(engine)
    return app


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


def _register_callbacks(engine: Engine) -> None:
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

        return (
            _session_timeline_figure(rows),
            _session_token_spend_figure(rows),
            rows,
            _columns(rows),
        )

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
    """Session Inspector tab layout."""
    return [
        html.Div(
            [
                dcc.Dropdown(
                    id="session-selector",
                    placeholder="Select a session to inspect...",
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
                    style_data_conditional=[
                        {
                            "if": {
                                "filter_query": (
                                    '{status} = "failed" || {status} = "error"'
                                    ' || {status} = "cancelled"'
                                ),
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
                                "filter_query": (
                                    '{event_type} = "SkillCompleted"'
                                    ' && {status} = "success"'
                                ),
                            },
                            "backgroundColor": "#dcfce7",
                        },
                    ],
                ),
            ],
            style={"paddingTop": "12px"},
        )
    ]


def _context_map_explorer_tab() -> list:
    """Context Map Explorer tab layout."""
    return [
        html.Div(
            [
                dcc.Dropdown(
                    id="explorer-corpus-selector",
                    placeholder="Select a corpus to explore...",
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
                marker={
                    "size": [max(8, min(24, r["tokens_used"] // 50 + 8)) for r in subset],
                    "color": color_map[et],
                    "opacity": 0.85,
                },
                text=[
                    f"{r['skill_name'] or '--'} | {r['status'] or '--'}<br>{r['content_preview']}"
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
                    f"<b>{r['key']}</b><br>{r['summary'][:80]}<br>"
                    f"materializations: {r['materialization_count']}"
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


def _summary_cards(summary: dict[str, Any]) -> list[html.Div]:
    labels = [
        ("Sessions", "total_sessions"),
        ("Events", "total_events"),
        ("Tokens", "total_tokens"),
        ("Skill Calls", "skill_calls"),
        ("Skill Failures", "skill_failures"),
        ("Map Backlog", "context_pending"),
    ]
    return [
        html.Div(
            [
                html.Div(label, style={"fontSize": "12px", "color": "#5f6b7a"}),
                html.Div(
                    f"{int(summary.get(key, 0)):,}",
                    style={"fontSize": "24px", "fontWeight": "650"},
                ),
            ],
            style=CARD_STYLE,
        )
        for label, key in labels
    ]


def _token_figure(rows: list[dict[str, Any]]) -> go.Figure:
    x = [row["bucket"] for row in rows]
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=x,
            y=[row["input_tokens"] for row in rows],
            name="Input",
            marker_color="#2563eb",
        )
    )
    figure.add_trace(
        go.Bar(
            x=x,
            y=[row["output_tokens"] for row in rows],
            name="Output",
            marker_color="#16a34a",
        )
    )
    figure.update_layout(
        title="LLM Tokens by Hour",
        barmode="stack",
        margin={"l": 36, "r": 16, "t": 48, "b": 36},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    return figure


def _columns(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not rows:
        return []
    return [{"name": key.replace("_", " ").title(), "id": key} for key in rows[0]]


def _table_cell_style() -> dict[str, str]:
    return {
        "fontFamily": "system-ui, sans-serif",
        "fontSize": "13px",
        "padding": "8px",
        "textAlign": "left",
        "maxWidth": "320px",
        "overflow": "hidden",
        "textOverflow": "ellipsis",
    }
