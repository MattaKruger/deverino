# Deverino Architecture

A multi-view architectural reference for the **Deverino harness** — a Python 3.14
LLM-agent harness backed by a PostgreSQL "blackboard".

This site is generated with [Zensical](https://zensical.org) and renders all
Mermaid diagrams inline. A standalone presentable version of the core diagrams
also lives in [`diagrams.html`](diagrams.html).

## Documentation

- **[Core Infrastructure Diagrams](core-infrastructure-diagrams.md)** — 15 diagrams
  covering system context, layered architecture, the blackboard data model, the event
  system, the two agent loops, the context-map materialization pipeline, skill/tool
  execution, the retrieval/RAG pipeline, durable state consolidation, and AHE
  (Autonomous Harness Evolution).
- **[Agentic Architecture](agentic-architecture.md)** — system overview and agentic
  architecture diagrams.
- **[Retrieval Design](retrieval-design.md)** — top-tier RAG design: Vespa-backed
  document retrieval and the PDF→text pipeline.
- **[V2 Architecture](v2-architecture.md)** — the v2 orchestration layer design.

## Diagram legend

> Solid arrows = runtime call / data flow; dashed arrows = async event publish or
> lazy / `TYPE_CHECKING` import; cylinder = datastore; box with double border =
> external system.

## Previewing & building this site

See [README.md](README.md) for the exact `zensical serve` / `zensical build` commands.
