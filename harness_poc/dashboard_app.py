"""Formula 1 pit-wall dashboard for agentic systems.

Dark theme, single-page data-dense layout, dual-interval refresh (2s / 10s).
Replaces the old tabbed dashboard with visual-first panels: tool analytics,
sub-agent topology, event firehose, context map health, token economics.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from dash import Dash, Input, Output, callback, dcc, html
from plotly import graph_objects as go

from harness_poc.core.observability import (
    fetch_corpus_keys,
    fetch_dashboard_snapshot,
    fetch_event_throughput,
    fetch_recent_events,
    fetch_session_ids,
    fetch_sub_agent_tree,
    fetch_tool_latency,
    snapshot_to_dict,
)
from harness_poc.core.storage import create_db_engine
from harness_poc.dashboard_theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_PURPLE,
    ACCENT_RED,
    ACCENT_YELLOW,
    CARD_STYLE,
    CHART_PALETTE,
    GRID_LINE,
    HEADER_STYLE,
    PAGE_STYLE,
    TEXT_MUTED,
    dark_figure,
    empty_state,
    status_color,
)

if TYPE_CHECKING:
    from sqlalchemy import Engine

# ── Factory ──────────────────────────────────────────────────────────────────


def create_dashboard_app(database_url: str) -> Dash:
    engine = create_db_engine(database_url)
    app = Dash(__name__, title="Harness Pit Wall", update_title=None)
    app.layout = _layout()
    _register_callbacks(engine)
    return app


# ── Layout ───────────────────────────────────────────────────────────────────

def _layout() -> html.Div:
    return html.Div(
        [
            _top_bar(),
            html.Div(
                [
                    _sidebar(),
                    html.Div(
                        [
                            html.Div(
                                [
                                    _panel("TOOL FREQUENCY", dcc.Graph(id="tool-freq", config={"displayModeBar": False})),
                                    _panel("TOOL LATENCY", dcc.Graph(id="tool-latency", config={"displayModeBar": False})),
                                    _panel("SUB-AGENT TREE", dcc.Graph(id="subagent-tree", config={"displayModeBar": False})),
                                    _panel("TOKEN ECONOMICS", dcc.Graph(id="token-econ", config={"displayModeBar": False})),
                                ],
                                style=_row_style(4),
                            ),
                            html.Div(
                                [
                                    _panel("EVENT FIREHOSE", _event_firehose(), span=2),
                                    _panel("CONTEXT MAP HEALTH", dcc.Graph(id="ctx-health", config={"displayModeBar": False})),
                                    _panel("ERROR DISTRIBUTION", dcc.Graph(id="error-dist", config={"displayModeBar": False})),
                                ],
                                style=_row_style(4, cols=[2, 1, 1]),
                            ),
                            html.Div(
                                [
                                    _panel("SESSION TIMELINE", dcc.Graph(id="session-gantt", config={"displayModeBar": False}), span=4),
                                ],
                                style=_row_style(4),
                            ),
                            html.Div(
                                [
                                    _panel("CORPUS EXPLORER", dcc.Graph(id="corpus-sunburst", config={"displayModeBar": False})),
                                    _panel("ENTRY PRIORITY", dcc.Graph(id="corpus-scatter", config={"displayModeBar": False})),
                                    _panel("STICKINESS", dcc.Graph(id="corpus-stickiness", config={"displayModeBar": False})),
                                    _panel("ENTRIES", html.Div(id="corpus-entries-table")),
                                ],
                                style=_row_style(4),
                                id="corpus-explorer-row",
                            ),
                        ],
                        style={"flex": "1", "minWidth": "0"},
                    ),
                ],
                style={"display": "flex", "gap": "10px"},
            ),
            dcc.Interval(id="fast-refresh", interval=2_000, n_intervals=0),
            dcc.Interval(id="slow-refresh", interval=10_000, n_intervals=0),
            dcc.Store(id="selected-corpus"),
        ],
        style=PAGE_STYLE,
    )


def _sidebar() -> html.Div:
    return html.Div(
        [
            html.Div("SESSIONS", style={**HEADER_STYLE, "marginTop": "0"}),
            html.Div(id="sidebar-sessions", style={"marginBottom": "12px"}),
            html.Div("SUB-AGENTS", style=HEADER_STYLE),
            html.Div(id="sidebar-subagents", style={"marginBottom": "12px"}),
            html.Div("FILTERS", style=HEADER_STYLE),
            dcc.Dropdown(
                id="firehose-type-filter",
                options=[],
                multi=True,
                placeholder="Event types…",
                style={"marginBottom": "6px", "fontSize": "11px"},
            ),
            dcc.Dropdown(
                id="firehose-session-filter",
                options=[],
                multi=True,
                placeholder="Sessions…",
                style={"marginBottom": "12px", "fontSize": "11px"},
            ),
            html.Div("CORPORA", style=HEADER_STYLE),
            dcc.Dropdown(
                id="corpus-selector",
                options=[],
                placeholder="Select corpus…",
                style={"marginBottom": "12px", "fontSize": "11px"},
            ),
        ],
        style={
            **CARD_STYLE,
            "width": "240px",
            "minWidth": "240px",
            "flexShrink": "0",
            "overflowY": "auto",
            "maxHeight": "calc(100vh - 100px)",
            "fontSize": "12px",
        },
    )


def _top_bar() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span("⚡", style={"fontSize": "18px", "marginRight": "8px"}),
                    html.Span(
                        "HARNESS PIT WALL",
                        style={"fontSize": "16px", "fontWeight": "700", "letterSpacing": "1px"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            html.Div(
                [
                    _metric("sessions", "#", "metric-sessions"),
                    _metric("events/s", "0.0", "metric-throughput"),
                    _metric("db", "— ms", "metric-db-latency"),
                    _metric("sub-agents", "0", "metric-subagents"),
                    _metric("backlog", "0", "metric-backlog"),
                ],
                style={"display": "flex", "gap": "16px"},
            ),
        ],
        style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
            "padding": "8px 12px",
            "backgroundColor": "#0d1117",
            "borderBottom": f"2px solid {ACCENT_BLUE}",
            "marginBottom": "12px",
        },
    )


def _metric(label: str, value: str, metric_id: str) -> html.Div:
    return html.Div(
        [
            html.Div(label, style={"fontSize": "10px", "color": TEXT_MUTED, "textTransform": "uppercase"}),
            html.Div(
                value, id=metric_id,
                style={"fontSize": "18px", "fontWeight": "700", "fontVariantNumeric": "tabular-nums"},
            ),
        ],
        style={"textAlign": "right"},
    )


def _panel(title: str, *children: object, span: int = 1) -> html.Div:
    return html.Div(
        [
            html.Div(title, style=HEADER_STYLE),
            *children,
        ],
        style={
            **CARD_STYLE,
            "gridColumn": f"span {span}" if span > 1 else "auto",
            "minWidth": "0",
            "display": "flex",
            "flexDirection": "column",
        },
    )


def _event_firehose() -> html.Div:
    return html.Div(
        id="firehose-rows",
        style={
            "maxHeight": "340px",
            "overflowY": "auto",
            "fontFamily": "SF Mono, Fira Code, monospace",
            "fontSize": "11px",
            "lineHeight": "1.5",
        },
    )


def _row_style(total_cols: int, cols: list[int] | None = None) -> dict[str, str]:
    tracks = " ".join(f"{c}fr" for c in cols) if cols else f"repeat({total_cols}, 1fr)"
    return {
        "display": "grid",
        "gridTemplateColumns": tracks,
        "gap": "10px",
        "marginBottom": "10px",
    }


# ── Callbacks ────────────────────────────────────────────────────────────────


def _register_callbacks(engine: Engine) -> None:

    @callback(
        Output("tool-freq", "figure"),
        Output("tool-latency", "figure"),
        Output("subagent-tree", "figure"),
        Output("token-econ", "figure"),
        Output("ctx-health", "figure"),
        Output("error-dist", "figure"),
        Output("session-gantt", "figure"),
        Output("metric-sessions", "children"),
        Output("metric-throughput", "children"),
        Output("metric-db-latency", "children"),
        Output("metric-subagents", "children"),
        Output("metric-backlog", "children"),
        Output("firehose-type-filter", "options"),
        Output("firehose-session-filter", "options"),
        Output("sidebar-sessions", "children"),
        Output("sidebar-subagents", "children"),
        Output("corpus-selector", "options"),
        Input("slow-refresh", "n_intervals"),
    )
    def slow_update(_n: int) -> tuple[Any, ...]:
        import time as _time  # noqa: PLC0415
        t0 = _time.monotonic()
        snapshot = fetch_dashboard_snapshot(engine)
        data = snapshot_to_dict(snapshot)
        db_ms = round((_time.monotonic() - t0) * 1000, 1)

        summary = data["summary"]
        sessions = str(summary.get("total_sessions", 0))
        throughput = fetch_event_throughput(engine, window_s=60)
        subagents = len(fetch_sub_agent_tree(engine))
        backlog = str(summary.get("context_pending", 0))

        tool_freq_fig = _tool_frequency_figure(data["skills"])
        tool_latency_fig = _tool_latency_figure(engine)
        subagent_tree_fig = _sub_agent_tree_figure(engine)
        token_econ_fig = _token_economics_figure(data["token_buckets"])
        ctx_health_fig = _context_map_health_figure(data["context_maps"])
        error_dist_fig = _error_distribution_figure(data["recent_failures"])
        session_gantt_fig = _session_timeline_figure(data["session_activity"])

        type_opts = _EVENT_TYPE_OPTIONS
        session_opts = _session_id_options(engine)
        sidebar_sessions = _sidebar_sessions_html(engine)
        sidebar_subagents = _sidebar_subagents_html(engine)
        corpus_opts = _corpus_options(engine)

        return (
            tool_freq_fig, tool_latency_fig, subagent_tree_fig, token_econ_fig,
            ctx_health_fig, error_dist_fig, session_gantt_fig,
            sessions, f"{throughput:.1f}", f"{db_ms:.1f} ms",
            str(subagents), backlog,
            type_opts, session_opts,
            sidebar_sessions, sidebar_subagents, corpus_opts,
        )

    @callback(
        Output("firehose-rows", "children"),
        Input("fast-refresh", "n_intervals"),
        Input("firehose-type-filter", "value"),
        Input("firehose-session-filter", "value"),
    )
    def firehose_update(_n: int, types: list[str] | None, sessions: list[str] | None) -> list:
        return _render_firehose(engine, event_types=types, session_ids=sessions)

    @callback(
        Output("corpus-sunburst", "figure"),
        Output("corpus-scatter", "figure"),
        Output("corpus-stickiness", "figure"),
        Output("corpus-entries-table", "children"),
        Input("corpus-selector", "value"),
    )
    def corpus_explorer_update(corpus_key: str | None) -> tuple[Any, ...]:
        if not corpus_key:
            empty = dark_figure()
            return (empty_state(empty, "Select a corpus"),) * 3 + ([],)
        return _corpus_detail_panels(engine, corpus_key)


# ── Chart builders ───────────────────────────────────────────────────────────


def _tool_frequency_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Tool Call Frequency (last hour)")
    if not rows:
        return empty_state(fig)

    top = sorted(rows, key=lambda r: r.get("call_count", 0), reverse=True)[:12]
    names = [r.get("skill_name", "?") for r in top]
    counts = [r.get("call_count", 0) for r in top]
    fails = [r.get("fail_count", 0) for r in top]

    fig.add_trace(go.Bar(
        x=counts, y=names, orientation="h", name="OK",
        marker_color=ACCENT_GREEN, hovertemplate="%{x} calls<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=fails, y=names, orientation="h", name="Failed",
        marker_color=ACCENT_RED, hovertemplate="%{x} failures<extra></extra>",
    ))
    fig.update_layout(
        barmode="stack", xaxis_title="calls",
        yaxis={"categoryorder": "total ascending"},
        showlegend=False, margin={"l": 120, "r": 12, "t": 36, "b": 28}, height=280,
    )
    return fig


def _tool_latency_figure(engine: Engine) -> go.Figure:
    fig = dark_figure(title="Tool Latency Distribution (s)")
    rows = fetch_tool_latency(engine, minutes=60)
    if not rows:
        return empty_state(fig)

    by_tool: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_tool[r.skill_name].append(r.latency_s)

    palette = CHART_PALETTE
    items = sorted(by_tool.items(), key=lambda x: -sum(x[1]) / max(len(x[1]), 1))
    for i, (tool, latencies) in enumerate(items):
        fig.add_trace(go.Violin(
            x=[tool] * len(latencies), y=latencies, name=tool,
            line_color=palette[i % len(palette)],
            points=False, spanmode="hard",
            hovertemplate="%{x}: %{y:.2f}s<extra></extra>",
        ))

    fig.update_layout(
        showlegend=False, xaxis_title="tool", yaxis_title="latency (s)",
        margin={"l": 40, "r": 12, "t": 36, "b": 80}, height=280,
    )
    return fig


def _sub_agent_tree_figure(engine: Engine) -> go.Figure:
    fig = dark_figure(title="Sub-Agent Topology")
    nodes = fetch_sub_agent_tree(engine)
    if not nodes:
        return empty_state(fig, "No sub-agents spawned")

    ids: list[str] = []
    labels: list[str] = []
    parents: list[str] = []
    values: list[int] = []
    colors: list[str] = []

    seen_parents: dict[str, int] = {}
    for n in nodes:
        if n.parent_session_id not in seen_parents:
            seen_parents[n.parent_session_id] = len(ids)
            ids.append(n.parent_session_id)
            labels.append(n.parent_session_id[:8])
            parents.append("")
            values.append(1)
            colors.append(ACCENT_BLUE)

        ids.append(n.sub_session_id)
        label = n.persona or "sub"
        if n.objective:
            label += f": {n.objective[:30]}"
        labels.append(label)
        parents.append(n.parent_session_id)
        values.append(max(int(n.duration_s * 10) or 1, 1))
        colors.append(status_color(n.status))

    fig.add_trace(go.Sunburst(
        ids=ids, labels=labels, parents=parents, values=values,
        marker={"colors": colors},
        branchvalues="total", insidetextorientation="radial",
        hovertemplate="<b>%{label}</b><br>%{value}<extra></extra>",
    ))
    fig.update_layout(margin={"l": 0, "r": 0, "t": 36, "b": 0}, height=280)
    return fig


def _token_economics_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Token Spend by Hour")
    if not rows:
        return empty_state(fig)

    buckets = [r.get("bucket", "?") for r in rows]
    inp = [r.get("input_tokens", 0) for r in rows]
    out = [r.get("output_tokens", 0) for r in rows]

    fig.add_trace(go.Bar(x=buckets, y=inp, name="Input", marker_color=ACCENT_BLUE))
    fig.add_trace(go.Bar(x=buckets, y=out, name="Output", marker_color=ACCENT_GREEN))
    fig.update_layout(
        barmode="stack", xaxis_title="hour", yaxis_title="tokens",
        legend={"orientation": "h", "y": 1.05, "x": 1, "xanchor": "right"},
        margin={"l": 50, "r": 12, "t": 36, "b": 28}, height=280,
    )
    return fig


def _context_map_health_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Context Map Health")
    if not rows:
        return empty_state(fig, "No context maps")

    corpora = [r.get("corpus_key", "?")[:20] for r in rows]
    entries = [r.get("entry_count", 0) for r in rows]
    pending = [r.get("pending_events", 0) for r in rows]

    fig.add_trace(go.Bar(
        x=entries, y=corpora, orientation="h", name="entries",
        marker_color=ACCENT_BLUE, hovertemplate="%{x} entries<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=pending, y=corpora, orientation="h", name="pending",
        marker_color=ACCENT_YELLOW, hovertemplate="%{x} pending<extra></extra>",
    ))
    fig.update_layout(
        barmode="stack", xaxis_title="count",
        yaxis={"categoryorder": "total ascending"},
        legend={"orientation": "h", "y": 1.05},
        margin={"l": 140, "r": 12, "t": 36, "b": 28}, height=280,
    )
    return fig


def _error_distribution_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Error Distribution (24h)")
    if not rows:
        return empty_state(fig, "No errors")

    from collections import Counter  # noqa: PLC0415

    by_skill = Counter[str]()
    for r in rows:
        by_skill[r.get("skill_name", "?")] += 1

    skills = [s for s, _ in by_skill.most_common(10)]
    counts = [by_skill[s] for s in skills]

    fig.add_trace(go.Bar(
        x=counts, y=skills, orientation="h",
        marker_color=ACCENT_RED, hovertemplate="%{x} errors<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="error count", yaxis={"categoryorder": "total ascending"},
        margin={"l": 120, "r": 12, "t": 36, "b": 28}, height=280,
    )
    return fig


def _session_timeline_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Session Activity")
    if not rows:
        return empty_state(fig, "No session activity")

    sessions = [r.get("session_id", "?")[:10] for r in rows]
    events = [r.get("event_count", 0) for r in rows]
    tokens = [r.get("total_tokens", 0) for r in rows]
    last = [r.get("last_seen", "")[:19] for r in rows]

    hover_text = [
        f"{s}: {e} events, {t} tokens<br>last: {l_last}"
        for s, e, t, l_last in zip(sessions, events, tokens, last, strict=False)
    ]

    fig.add_trace(go.Scatter(
        x=last, y=sessions, mode="markers",
        marker={
            "size": [max(6, min(30, t // 100 + 6)) for t in tokens],
            "color": [ACCENT_BLUE if e > 0 else TEXT_MUTED for e in events],
        },
        text=hover_text,
        hovertemplate="%{text}<extra></extra>",
    ))
    fig.update_layout(
        yaxis={"categoryorder": "trace"},
        margin={"l": 100, "r": 12, "t": 36, "b": 28}, height=240,
    )
    return fig


# ── Firehose renderer ────────────────────────────────────────────────────────


def _render_firehose(
    engine: Engine,
    event_types: list[str] | None = None,
    session_ids: list[str] | None = None,
) -> list[html.Div]:
    rows = fetch_recent_events(
        engine, limit=100,
        event_types=event_types,
        session_id=session_ids[0] if session_ids else None,
    )
    if not rows:
        return [_firehose_row("—", "—", "No events yet", "—")]

    result: list[html.Div] = []
    for r in rows:
        ts = str(r.timestamp)[11:19] if r.timestamp else "?"
        evt_type = str(r.event_type)
        session = str(r.session_id)[:10] if r.session_id else "?"
        preview = _extract_preview(r.detail_json, evt_type)
        color = _event_row_color(evt_type)
        result.append(_firehose_row(ts, evt_type, preview, session, color=color))
    return result


def _extract_preview(detail_json: str, event_type: str) -> str:
    if not detail_json:
        return event_type
    try:
        import json as _json  # noqa: PLC0415
        detail = _json.loads(detail_json) if isinstance(detail_json, str) else detail_json
        return str(detail.get("skill_name", detail.get("tool_name", detail.get("objective", ""))))[:40]
    except Exception:
        return str(detail_json)[:40]


def _firehose_row(ts: str, evt_type: str, detail: str, session: str, color: str = TEXT_MUTED) -> html.Div:
    return html.Div(
        [
            html.Span(ts, style={"color": TEXT_MUTED, "minWidth": "70px", "textAlign": "right"}),
            html.Span(evt_type, style={"color": color, "minWidth": "160px", "fontWeight": "600", "padding": "0 8px"}),
            html.Span(detail, style={"flex": "1", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Span(session, style={"color": TEXT_MUTED, "minWidth": "80px", "textAlign": "right"}),
        ],
        style={
            "display": "flex", "gap": "6px", "padding": "2px 0",
            "borderBottom": f"1px solid {GRID_LINE}", "alignItems": "center",
        },
    )


_EVENT_COLORS: dict[str, str] = {
    "SkillCompleted": ACCENT_GREEN,
    "SkillCalled": ACCENT_BLUE,
    "SkillRequested": ACCENT_BLUE,
    "SkillCancelled": ACCENT_YELLOW,
    "LLMActionEmitted": ACCENT_CYAN,
    "SubAgentDispatched": ACCENT_PURPLE,
    "SubAgentCompleted": ACCENT_PURPLE,
    "SubAgentTaskStarted": ACCENT_PURPLE,
    "SubAgentTaskCompleted": ACCENT_PURPLE,
    "StreamPaused": ACCENT_YELLOW,
    "GoalEvaluated": ACCENT_GREEN,
    "GatePassed": ACCENT_GREEN,
    "GateFailed": ACCENT_RED,
    "SpecCommitted": ACCENT_GREEN,
}


def _event_row_color(event_type: str) -> str:
    for prefix, color in _EVENT_COLORS.items():
        if event_type.startswith(prefix):
            return color
    if "failed" in event_type.lower() or "error" in event_type.lower():
        return ACCENT_RED
    return TEXT_MUTED


_EVENT_TYPE_OPTIONS: list[dict[str, str]] = [
    {"label": "SkillCalled", "value": "SkillCalled"},
    {"label": "SkillCompleted", "value": "SkillCompleted"},
    {"label": "SkillCancelled", "value": "SkillCancelled"},
    {"label": "LLMActionEmitted", "value": "LLMActionEmitted"},
    {"label": "SubAgentDispatched", "value": "SubAgentDispatched"},
    {"label": "SubAgentCompleted", "value": "SubAgentCompleted"},
    {"label": "SubAgentTaskStarted", "value": "SubAgentTaskStarted"},
    {"label": "SubAgentTaskCompleted", "value": "SubAgentTaskCompleted"},
    {"label": "StreamPaused", "value": "StreamPaused"},
    {"label": "GoalEvaluated", "value": "GoalEvaluated"},
    {"label": "GatePassed", "value": "GatePassed"},
    {"label": "GateFailed", "value": "GateFailed"},
]


def _session_id_options(engine: Engine) -> list[dict[str, str]]:
    try:
        ids = fetch_session_ids(engine, limit=20)
        return [{"label": f"{label[:30]}", "value": sid} for sid, label in ids]
    except Exception:
        return []


# ── Sidebar helpers ──────────────────────────────────────────────────────────


def _sidebar_sessions_html(engine: Engine) -> list[html.Div]:
    """Render compact session list for the sidebar."""
    try:
        ids = fetch_session_ids(engine, limit=15)
    except Exception:
        return [_sidebar_empty("No sessions")]

    if not ids:
        return [_sidebar_empty("No sessions")]

    return [
        html.Div(
            [
                html.Span("●", style={"color": ACCENT_GREEN, "marginRight": "6px", "fontSize": "8px"}),
                html.Span(sid[:12], style={"color": TEXT_MUTED, "fontSize": "11px"}),
                html.Span(label[:20] if label else "", style={"fontSize": "11px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            ],
            style={"display": "flex", "alignItems": "center", "gap": "4px", "padding": "2px 0"},
        )
        for sid, label in ids[:10]
    ]


def _sidebar_subagents_html(engine: Engine) -> list[html.Div]:
    """Render sub-agent tree summary for the sidebar."""
    try:
        nodes = fetch_sub_agent_tree(engine)
    except Exception:
        return [_sidebar_empty("No sub-agents")]

    if not nodes:
        return [_sidebar_empty("No sub-agents")]

    active = [n for n in nodes if n.status in ("dispatched", "running", "active", "pending")]
    completed = [n for n in nodes if n.status in ("completed", "success")]
    failed = [n for n in nodes if n.status in ("failed", "error", "cancelled")]

    items: list[html.Div] = []

    if active:
        items.append(html.Div(f"▸ {len(active)} active", style={"color": ACCENT_GREEN, "fontSize": "12px", "padding": "2px 0"}))
        for n in active[:5]:
            label = n.persona or "sub"
            if n.objective:
                label += f": {n.objective[:20]}"
            items.append(html.Div(f"  {label}", style={"color": TEXT_MUTED, "fontSize": "11px", "paddingLeft": "8px"}))

    if completed:
        items.append(html.Div(f"▸ {len(completed)} completed", style={"color": ACCENT_BLUE, "fontSize": "12px", "padding": "2px 0"}))

    if failed:
        items.append(html.Div(f"▸ {len(failed)} failed", style={"color": ACCENT_RED, "fontSize": "12px", "padding": "2px 0"}))

    return items or [_sidebar_empty("No sub-agents")]


def _corpus_options(engine: Engine) -> list[dict[str, str]]:
    """Return corpus dropdown options."""
    try:
        keys = fetch_corpus_keys(engine)
        return [{"label": k, "value": k} for k in keys]
    except Exception:
        return []


def _corpus_detail_panels(engine: Engine, corpus_key: str) -> tuple[Any, ...]:
    """Return (sunburst, scatter, stickiness, entries_table) for a corpus."""
    from dataclasses import asdict  # noqa: PLC0415

    from harness_poc.core.observability import fetch_context_map_entries  # noqa: PLC0415

    try:
        entries = fetch_context_map_entries(engine, corpus_key)
        rows = [asdict(e) for e in entries]
    except Exception:
        empty = dark_figure()
        return (empty_state(empty, "Error loading corpus"),) * 3 + (
            html.Div("Error loading entries", style={"color": ACCENT_RED}),)

    sunburst = _corpus_sunburst_figure(rows)
    scatter = _corpus_scatter_figure(rows)
    stickiness = _corpus_stickiness_figure(rows)
    table = _corpus_entries_table(rows)
    return sunburst, scatter, stickiness, table


def _corpus_sunburst_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Token Budget by Section")
    if not rows:
        return empty_state(fig, "No entries")

    agg: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        agg[(r.get("section", "?"), r.get("observation_type", "?"))] += r.get("token_estimate", 0)

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

    fig.add_trace(go.Sunburst(
        labels=labels, parents=parents, values=values,
        branchvalues="total", insidetextorientation="radial",
    ))
    fig.update_layout(margin={"l": 0, "r": 0, "t": 36, "b": 0}, height=260)
    return fig


def _corpus_scatter_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Priority vs Token Cost")
    if not rows:
        return empty_state(fig, "No entries")

    obs_types = sorted({r.get("observation_type", "?") for r in rows})
    palette = CHART_PALETTE
    color_map = {ot: palette[i % len(palette)] for i, ot in enumerate(obs_types)}

    for ot in obs_types:
        subset = [r for r in rows if r.get("observation_type") == ot]
        fig.add_trace(go.Scatter(
            x=[r.get("priority", 0) for r in subset],
            y=[r.get("token_estimate", 0) for r in subset],
            mode="markers", name=ot,
            marker={"size": 8, "color": color_map[ot], "opacity": 0.8},
            text=[f"{r.get('key','?')[:40]}<br>{r.get('summary','')[:60]}" for r in subset],
            hovertemplate="%{text}<extra>%{fullData.name}</extra>",
        ))
    fig.update_layout(
        xaxis_title="priority", yaxis_title="tokens",
        legend={"orientation": "h", "y": -0.2},
        margin={"l": 50, "r": 12, "t": 36, "b": 60}, height=260,
    )
    return fig


def _corpus_stickiness_figure(rows: list[dict[str, Any]]) -> go.Figure:
    fig = dark_figure(title="Entry Stickiness")
    if not rows:
        return empty_state(fig, "No entries")

    top = sorted(rows, key=lambda r: r.get("materialization_count", 0), reverse=True)[:20]
    top = list(reversed(top))
    palette = CHART_PALETTE
    obs_types = sorted({r.get("observation_type", "?") for r in top})
    color_map = {ot: palette[i % len(palette)] for i, ot in enumerate(obs_types)}

    fig.add_trace(go.Bar(
        orientation="h",
        x=[r.get("materialization_count", 0) for r in top],
        y=[r.get("key", "?") for r in top],
        marker_color=[color_map.get(r.get("observation_type", "?"), TEXT_MUTED) for r in top],
        text=[r.get("observation_type", "?") for r in top],
        hovertemplate="<b>%{y}</b><br>count: %{x}<br>type: %{text}<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="materializations",
        margin={"l": 180, "r": 12, "t": 36, "b": 28}, height=260,
    )
    return fig


def _corpus_entries_table(rows: list[dict[str, Any]]) -> list[html.Div]:
    if not rows:
        return [html.Div("No entries", style={"color": TEXT_MUTED, "fontSize": "12px"})]

    # Header + 15 most recent rows
    header = html.Div(
        [
            html.Span("key", style={"minWidth": "160px", "fontWeight": "600", "color": TEXT_MUTED}),
            html.Span("section", style={"minWidth": "100px", "fontWeight": "600", "color": TEXT_MUTED}),
            html.Span("type", style={"minWidth": "120px", "fontWeight": "600", "color": TEXT_MUTED}),
            html.Span("pri", style={"minWidth": "30px", "fontWeight": "600", "color": TEXT_MUTED, "textAlign": "right"}),
            html.Span("mat", style={"minWidth": "30px", "fontWeight": "600", "color": TEXT_MUTED, "textAlign": "right"}),
            html.Span("tokens", style={"minWidth": "50px", "fontWeight": "600", "color": TEXT_MUTED, "textAlign": "right"}),
        ],
        style={"display": "flex", "gap": "8px", "padding": "4px 0", "borderBottom": f"2px solid {GRID_LINE}"},
    )

    body_rows: list[html.Div] = [header]
    body_rows.extend(
        html.Div(
            [
                html.Span(str(r.get("key", ""))[:22], style={"minWidth": "160px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
                html.Span(str(r.get("section", ""))[:14], style={"minWidth": "100px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
                html.Span(str(r.get("observation_type", ""))[:16], style={"minWidth": "120px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
                html.Span(str(r.get("priority", "")), style={"minWidth": "30px", "textAlign": "right"}),
                html.Span(str(r.get("materialization_count", "")), style={"minWidth": "30px", "textAlign": "right"}),
                html.Span(str(r.get("token_estimate", "")), style={"minWidth": "50px", "textAlign": "right"}),
            ],
            style={"display": "flex", "gap": "8px", "padding": "2px 0", "borderBottom": f"1px solid {GRID_LINE}", "fontSize": "11px"},
        )
        for r in rows[:15]
    )
    return body_rows

def _sidebar_empty(text: str) -> html.Div:
    return html.Div(text, style={"color": TEXT_MUTED, "fontSize": "11px", "fontStyle": "italic"})
