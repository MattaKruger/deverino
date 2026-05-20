"""Visualize Deverino's pipeline DAG and workflow state machine architectures."""

import matplotlib.pyplot as plt
import networkx as nx


def draw_pipeline_dag():
    """Visualize the pipeline runner's DAG execution model.

    Pipelines support parallel execution waves using topological sort:
    independent nodes run concurrently, dependent nodes wait.
    """
    G = nx.DiGraph()

    # Nodes with their types
    nodes = [
        ("memory_research", "skill"),
        ("web_search", "skill"),
        ("read_memory", "skill"),
        ("synthesize", "agent"),
        ("review_output", "skill"),
    ]
    for name, node_type in nodes:
        G.add_node(name, type=node_type)

    # Dependencies (edges flow from dependency to dependent)
    edges = [
        ("memory_research", "synthesize"),
        ("web_search", "synthesize"),
        ("read_memory", "synthesize"),
        ("synthesize", "review_output"),
    ]
    G.add_edges_from(edges)

    # Layout: try graphviz dot for hierarchy, fall back to spring
    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog="dot")
    except (ImportError, ModuleNotFoundError, AttributeError):
        pos = nx.spring_layout(G, seed=42, k=2)

    plt.figure(figsize=(10, 7))

    # Color nodes by type
    color_map = {"skill": "#aec7e8", "agent": "#ffbb78"}
    node_colors = [color_map[G.nodes[n]["type"]] for n in G.nodes()]

    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=3500, edgecolors="#333")
    nx.draw_networkx_labels(G, pos, font_size=11, font_weight="bold")

    # Draw edges with dependency annotation
    nx.draw_networkx_edges(
        G, pos, arrowstyle="->", arrowsize=20, edge_color="#555", width=2, alpha=0.7,
    )

    # Annotate execution waves
    wave_labels = {
        "memory_research": "Wave 1\n(parallel)",
        "web_search": "Wave 1\n(parallel)",
        "read_memory": "Wave 1\n(parallel)",
        "synthesize": "Wave 2\n(depends_on)",
        "review_output": "Wave 3\n(depends_on)",
    }
    offset_pos = {k: (v[0] + 0.12, v[1] - 0.15) for k, v in pos.items()}
    for node, label in wave_labels.items():
        plt.text(
            offset_pos[node][0], offset_pos[node][1], label,
            fontsize=7, ha="left", va="top",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="gray", alpha=0.8),
        )

    # Legend
    legend_elements = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#aec7e8",
                   markersize=12, label="skill node"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#ffbb78",
                   markersize=12, label="agent node"),
    ]
    plt.legend(handles=legend_elements, loc="lower right", fontsize=9)

    plt.title("Pipeline DAG — research-and-write", fontsize=14, fontweight="bold")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig("pipeline_dag.png", dpi=150)
    plt.show()


def draw_workflow_statechart():
    """Visualize the workflow runner's linear state machine.

    Workflows are YAML state machines: each state calls a skill,
    passes output to the next state via {{template}} variables.
    """
    G = nx.DiGraph()

    # Workflow states from research_task.yaml
    states = [
        ("delegate", "delegate_task"),
        ("reflect", "reflect_on_result"),
        ("summarize", "read_memory"),
        ("done", None),
    ]
    for name, skill in states:
        G.add_node(name, skill=skill)

    # Linear state transitions
    transitions = [
        ("delegate", "reflect"),
        ("reflect", "summarize"),
        ("summarize", "done"),
    ]
    G.add_edges_from(transitions)

    # Layout: horizontal left-to-right
    pos = {
        "delegate": (0, 0),
        "reflect": (2, 0),
        "summarize": (4, 0),
        "done": (6, 0),
    }

    plt.figure(figsize=(12, 4))

    # Color states
    state_colors = ["#98df8a", "#ff9896", "#c5b0d5", "#d3d3d3"]
    nx.draw_networkx_nodes(
        G, pos, node_color=state_colors, node_size=4000, node_shape="s",
        edgecolors="#333", linewidths=2,
    )
    nx.draw_networkx_labels(G, pos, font_size=11, font_weight="bold")

    # Edge styling
    nx.draw_networkx_edges(
        G, pos, arrowstyle="->", arrowsize=25, edge_color="#555", width=2.5,
        connectionstyle="arc3,rad=0.1",
    )

    # Skill labels below each state
    skill_labels = {
        "delegate": "skill: delegate_task\nargs: persona, objective",
        "reflect": "skill: reflect_on_result\nargs: objective, memory_key",
        "summarize": "skill: read_memory\nargs: memory_key",
        "done": "terminal: true\n(output)",
    }
    for node, label in skill_labels.items():
        plt.text(
            pos[node][0], pos[node][1] - 0.45, label,
            fontsize=7, ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.9),
        )

    # Template arrows annotation
    plt.annotate(
        "{{states.delegate.artifacts.memory_key}}",
        xy=(1, 0.15), fontsize=7, ha="center", color="#555",
        bbox=dict(boxstyle="round,pad=0.1", fc="#fff9c4", ec="gray", alpha=0.8),
    )

    plt.title("Workflow State Machine — research_task", fontsize=14, fontweight="bold")
    plt.ylim(-0.8, 0.8)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig("workflow_statechart.png", dpi=150)
    plt.show()


def draw_event_bus_statechart():
    """Visualize the EventBus lifecycle as a statechart.

    The harness uses typed events (Pydantic) published through an EventBus.
    Subscribers (logfire, reducers, etc.) react to events asynchronously.
    """
    G = nx.DiGraph()

    # Event lifecycle
    events = [
        ("PipelineStarted", "event"),
        ("PipelineNodeStarted", "event"),
        ("AgentStarted", "event"),
        ("SkillCalled", "event"),
        ("SkillCompleted", "event"),
        ("AgentCompleted", "event"),
        ("PipelineNodeCompleted", "event"),
        ("PipelineCompleted", "event"),
    ]
    for name, etype in events:
        G.add_node(name, etype=etype)

    # Lifecycle flow
    lifecycle = [
        ("PipelineStarted", "PipelineNodeStarted"),
        ("PipelineNodeStarted", "AgentStarted"),
        ("AgentStarted", "SkillCalled"),
        ("SkillCalled", "SkillCompleted"),
        ("SkillCompleted", "AgentCompleted"),
        ("AgentCompleted", "PipelineNodeCompleted"),
        ("PipelineNodeCompleted", "PipelineCompleted"),
    ]
    # Add parallel branches
    lifecycle += [
        ("PipelineNodeStarted", "SkillCalled"),  # direct skill nodes skip agent
    ]
    G.add_edges_from(lifecycle)

    # Layout: try graphviz dot for hierarchy, fall back to spring
    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog="dot")
    except (ImportError, ModuleNotFoundError, AttributeError):
        pos = nx.spring_layout(G, seed=3)

    plt.figure(figsize=(10, 6))

    nx.draw_networkx_nodes(G, pos, node_color="#b2dfdb", node_size=3000, edgecolors="#333")
    nx.draw_networkx_labels(G, pos, font_size=9, font_weight="bold")
    nx.draw_networkx_edges(
        G, pos, arrowstyle="->", arrowsize=18, edge_color="#666", width=1.8,
    )

    # Subscriber annotations
    subscriber_notes = {
        "PipelineStarted": "→ logfire_subscriber\n→ state_reducer",
        "PipelineCompleted": "→ logfire_subscriber\n→ state_reducer",
        "SkillCalled": "→ logfire_subscriber",
    }
    for node, note in subscriber_notes.items():
        plt.text(
            pos[node][0] + 0.15, pos[node][1] + 0.1, note,
            fontsize=6, ha="left", va="bottom",
            bbox=dict(boxstyle="round,pad=0.2", fc="#fff9c4", ec="gray", alpha=0.8),
        )

    plt.title("EventBus Lifecycle — Typed Event Flow", fontsize=14, fontweight="bold")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig("eventbus_statechart.png", dpi=150)
    plt.show()


if __name__ == "__main__":
    draw_pipeline_dag()
    draw_workflow_statechart()
    draw_event_bus_statechart()
