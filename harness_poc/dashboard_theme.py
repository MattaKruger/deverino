"""Dark theme constants and shared Plotly template for the pit-wall dashboard."""

from plotly import graph_objects as go

# ── Color palette ────────────────────────────────────────────────────────────
BG = "#0d1117"
CARD_BG = "#161b22"
CARD_BORDER = "#30363d"
TEXT = "#c9d1d9"
TEXT_MUTED = "#8b949e"
ACCENT_BLUE = "#58a6ff"
ACCENT_GREEN = "#3fb950"
ACCENT_RED = "#f85149"
ACCENT_YELLOW = "#d29922"
ACCENT_ORANGE = "#d97706"
ACCENT_PURPLE = "#a371f7"
ACCENT_CYAN = "#39d2c0"
GRID_LINE = "#21262d"

# ── Component styles ─────────────────────────────────────────────────────────
PAGE_STYLE: dict[str, str] = {
    "fontFamily": "Inter, ui-sans-serif, system-ui, sans-serif",
    "padding": "14px",
    "backgroundColor": BG,
    "minHeight": "100vh",
    "color": TEXT,
}

CARD_STYLE: dict[str, str] = {
    "border": f"1px solid {CARD_BORDER}",
    "borderRadius": "6px",
    "padding": "10px",
    "backgroundColor": CARD_BG,
}

HEADER_STYLE: dict[str, str] = {
    "fontSize": "13px",
    "fontWeight": "600",
    "color": TEXT_MUTED,
    "textTransform": "uppercase",
    "letterSpacing": "0.5px",
    "marginBottom": "8px",
}

TABLE_CELL_STYLE: dict[str, str] = {
    "fontFamily": "SF Mono, Fira Code, monospace",
    "fontSize": "12px",
    "padding": "4px 8px",
    "textAlign": "left",
    "backgroundColor": CARD_BG,
    "color": TEXT,
    "borderBottom": f"1px solid {GRID_LINE}",
}

TABLE_HEADER_STYLE: dict[str, str] = {
    "fontWeight": "600",
    "backgroundColor": "#1c2129",
    "color": TEXT_MUTED,
    "fontSize": "11px",
    "textTransform": "uppercase",
}

# ── Plotly dark template ─────────────────────────────────────────────────────
DARK_TEMPLATE = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=CARD_BG,
        plot_bgcolor=BG,
        font={"color": TEXT_MUTED, "size": 11, "family": "Inter, sans-serif"},
        title={"font": {"size": 13, "color": TEXT}},
        xaxis={
            "gridcolor": GRID_LINE,
            "zerolinecolor": GRID_LINE,
            "linecolor": GRID_LINE,
        },
        yaxis={
            "gridcolor": GRID_LINE,
            "zerolinecolor": GRID_LINE,
            "linecolor": GRID_LINE,
        },
        legend={"font": {"size": 10}},
        margin={"l": 40, "r": 12, "t": 36, "b": 28},
        hoverlabel={"font": {"size": 11}},
    )
)


def dark_figure(**layout_kw: object) -> go.Figure:
    """Return an empty figure pre-configured with the dark template."""
    fig = go.Figure()
    fig.update_layout(template=DARK_TEMPLATE, **layout_kw)  # type: ignore[arg-type]
    return fig


def empty_state(fig: go.Figure, text: str = "No data") -> go.Figure:
    """Add a centered 'no data' annotation to a figure."""
    fig.add_annotation(
        text=text,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 13, "color": TEXT_MUTED},
    )
    return fig


def status_color(status: str) -> str:
    """Map a status string to a color."""
    if status in ("success", "completed", "active", "running"):
        return ACCENT_GREEN
    if status in ("failed", "error", "cancelled", "timeout"):
        return ACCENT_RED
    if status in ("paused", "pending", "queued"):
        return ACCENT_YELLOW
    return ACCENT_BLUE


# Chart palette (10 colors, colorblind-friendly where possible)
CHART_PALETTE: list[str] = [
    "#58a6ff",  # blue
    "#3fb950",  # green
    "#f85149",  # red
    "#d29922",  # yellow
    "#a371f7",  # purple
    "#39d2c0",  # cyan
    "#f0883e",  # orange
    "#e5539a",  # pink
    "#8b949e",  # grey
    "#79c0ff",  # light blue
]
