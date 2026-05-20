from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dash import Dash, Input, Output, callback, dash_table, dcc, html
from plotly import graph_objects as go

from harness_poc.core.dashboard import fetch_dashboard_snapshot, snapshot_to_dict
from harness_poc.core.db_engine import create_db_engine

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
            html.Div(
                id="summary",
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(auto-fit, minmax(150px, 1fr))",
                    "gap": "10px",
                    "marginBottom": "16px",
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
                },
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
        Output("last-updated", "children"),
        Input("refresh", "n_intervals"),
    )
    def update_dashboard(_: int) -> tuple[Any, ...]:
        snapshot = fetch_dashboard_snapshot(engine)
        data = snapshot_to_dict(snapshot)
        return (
            _summary_cards(data["summary"]),
            _token_figure(data["token_buckets"]),
            data["skills"],
            _columns(data["skills"]),
            data["recent_failures"],
            _columns(data["recent_failures"]),
            data["context_maps"],
            _columns(data["context_maps"]),
            "Refreshes every 10 seconds",
        )


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
