# Architecture docs

This directory is served as a static site by [Zensical](https://zensical.org), a
modern static site generator by the Material for MkDocs team. Mermaid diagrams
render inline.

## Prerequisites

Zensical requires Python >= 3.10 (this project uses 3.14). Run it ephemerally
with `uvx` — no project dependency changes required:

```sh
uvx zensical <command>
```

Or install it once as a `uv` tool and drop the `uvx` prefix:

```sh
uv tool install zensical
```

## Preview locally

From the repository root:

```sh
uvx zensical serve
```

Then open <http://localhost:8000>. The browser auto-reloads on edits.

Useful options:

| Option        | Short | Description                       |
| ------------- | ----- | --------------------------------- |
| --config-file | -f    | Path to the config file to use.   |
| --open        | -o    | Open preview in default browser.  |
| --dev-addr    | -a    | IP and port (default localhost:8000). |

## Build the static site

```sh
uvx zensical build
```

Output is written to `site/` (gitignored). Deploy it with any static host
(nginx, Apache, GitHub Pages, …).

## Configuration

The site is configured via `mkdocs.yml` at the repository root. It is scoped to
`docs/architecture` via `docs_dir`, so only this directory is served. Zensical
natively reads `mkdocs.yml`; this format is used (rather than `zensical.toml`)
because the Mermaid `superfences` custom fence relies on YAML `!!python/name:`
tags that have no clean TOML equivalent.
