# Multi-Corpus Context Map: Close the Remaining Gaps

**Date**: 2026-05-24
**Status**: draft
**Depends on**: `2026-07-25-multi-corpus-context-map-unblock.md` (implemented)

## Problem

The unblock plan delivered the plumbing — `observe` accepts a `corpus_key`
parameter, cross-corpus enrichment renders related maps in the prompt, and
`harness.yaml` wires `deverino:dashboard` and `deverino:benchmarks` as
related corpora. Three gaps remain that prevent the feature from being
usable without the developer holding explicit knowledge of what's valid:

1. **The agent can't discover which corpora exist.** `corpus_key` is
   free-form text. The agent has no runtime inventory of valid keys — it
   can't answer "what corpora do I have?", can't suggest a target, and
   can't validate existence before writing.

2. **The active corpus is still hardcoded to `:codebase`.** Every session
   loads the codebase map as primary. If the developer starts a session
   about the dashboard, the codebase map sits above the dashboard map, the
   agent can't edit dashboard entries, and citations default to the wrong
   corpus.

3. **Reference extraction is gated on a static YAML list.** The lookup
   dict in `_extract_references()` only indexes corpora listed under
   `cross_corpus.related_corpora`. Add a new corpus via `observe` without
   updating the YAML and its `[entry:<id>]` markers are silently dropped —
   no event, no warning, no reference-count credit.

## What Already Works (Since the Unblock)

| Component                                                  | Status |
| ---------------------------------------------------------- | ------ |
| `observe` accepts optional `corpus_key` parameter          | Done   |
| `observe` validates `:` is present in the key              | Done   |
| Cross-corpus enrichment renders related maps               | Done   |
| `cartographer.cross_corpus` config block in `harness.yaml` | Done   |
| `get_pending_corpus_keys()` enumerates unprocessed         | Done   |
| `get_context_maps(list[str])` bulk-reads maps              | Done   |

## Codebase Anchors

Re-verified against `main` before drafting this revision:

| Anchor | Path | Line |
| --- | --- | --- |
| Primary-corpus hardcode (session_message builder) | `harness_poc/app_factory.py` | 465 |
| Primary-corpus hardcode (runtime builder) — **missed by the unblock plan** | `harness_poc/app_factory.py` | 363 |
| Reference-extraction hardcode | `harness_poc/core/processors/llm_worker.py` | 137 |
| Static `related_keys` lookup | `harness_poc/core/processors/llm_worker.py` | 140-144 |
| `DbSession` table model | `harness_poc/core/storage/models.py` | 14-20 |
| Additive-column migration pattern | `harness_poc/core/storage/database.py` | 52-56 (`_ensure_*_column`) |
| System-tool registration | `harness_poc/system_tools/__init__.py` | 33-56 |

`_system_message_for()` and `build_runtime_layer()` both build the prompt
independently — fix one and you still ship the bug from the other. The
unblock plan only addressed the former in its commentary; this plan fixes
both, behind a shared helper so they can't drift again.

## Design

### Gap 1: Agent discoverability — system-prompt injection + tool

**A. System-prompt injection.** After the existing context-map block,
append a compact inventory of corpora the harness knows about (materialized
*or* pending). The agent gets ambient awareness without spending tool
calls; the inventory refreshes at the start of every turn. Worst-case
staleness is one turn, bounded by the materializer poll interval.

**B. `list_corpora` system tool.** A lightweight LLM-callable tool that
returns structured metadata (entry counts, cycle, pending event count).
This carries the rich detail that would bloat the system prompt, and lets
the agent re-query mid-conversation when a new corpus appears.

**Tradeoff accepted.** Two code paths surface overlapping information.
Kept because the prompt inventory is cheap ambient discovery, while the
tool answers "is it actually populated yet?" without growing the prompt
per turn.

### Gap 2: Configurable primary corpus — per-session, set at start

Store the active corpus key on the `sessions` row. Default
`{project}:codebase`. Set via `--corpus` flag at REPL start. **No
mid-session switching.**

Why per-session: switching mid-turn requires rebuilding the context-map
block, re-indexing the reference lookup, and reconciling in-flight tool
results keyed to the old corpus. That is a separate design problem worth
its own plan. The atomic unit is the session.

Validation: `--corpus` value must already exist as either a materialized
map or pending events. If it doesn't, warn but allow it — the agent can
bootstrap a new corpus by `observe`-ing into it and the materializer will
catch up. The warning is the signal; the failure mode this prevents is
the silent typo.

### Gap 3: Auto-discover references — DB query replaces static config

Replace the static `related_corpora` lookup with `get_all_corpus_keys()`.
Keep the YAML list as an **optional whitelist filter** when present —
this preserves the "exclude noisy corpora" use case. When absent or
empty, index everything.

Emit `logging.warning` on unresolved `[entry:<id>]` markers (currently a
silent `logger.debug` drop at `llm_worker.py:182`). Without this, a
typo'd citation looks identical to a genuinely-missing entry.

Add `cross_corpus_auto_discover: bool = True` to `CartographerConfig` as
the escape hatch.

## Implementation

### Gap 1a: `get_all_corpus_keys()` — new database method

Add to `BlackboardDatabase` after `get_pending_corpus_keys`
(`database.py:~496`):

```python
def get_all_corpus_keys(self) -> list[str]:
    """Return every known corpus key — materialized or pending.

    Union of (a) corpora with a materialized context map and (b) corpora
    that still have unprocessed events queued. Sorted lexicographically so
    callers get a stable order without re-sorting.
    """
    with Session(self._engine) as session:
        materialized = session.exec(select(DbContextMap.corpus_key)).all()
        pending = session.exec(
            select(DbContextMapEvent.corpus_key)
            .where(DbContextMapEvent.processed == 0)
            .distinct()
        ).all()
    return sorted(set(materialized) | set(pending))
```

Union (not just materialized) so a freshly-`observe`-d corpus appears in
the inventory immediately, not after the next materializer poll.

### Gap 1b: Prompt injection — both builders, via a shared helper

Two prompt-build paths, both currently hardcoded. Centralise inventory
rendering so they can't drift:

```python
# harness_poc/app_factory.py — new helper, near _render_cross_corpus

def _render_corpus_inventory(
    identity: Identity,
    active_corpus_key: str,
) -> str:
    """Render a one-line-per-corpus inventory, or '' when redundant.

    Suppressed for single-corpus deployments — there's nothing to choose
    between, and the active corpus is already implicit in the map block.
    """
    keys = identity.database.get_all_corpus_keys()
    if len(keys) <= 1:
        return ""
    lines = ["\n--- Available Corpora ---"]
    for ck in keys:
        marker = " (primary)" if ck == active_corpus_key else ""
        lines.append(f"{ck}{marker}")
    return "\n".join(lines)
```

Both builders then call the helper and fold the result into the final
join. Replacing `build_runtime_layer` lines 363-373:

```python
corpus_key = identity.database.get_session_corpus_key(
    identity.session_id,
    default=f"{identity.config_project_id}:codebase",
)
context_map = identity.database.get_context_map(corpus_key)
cycle_n = identity.database.get_cycle(corpus_key)
if context_map and config.cartographer.prompt_block != "none":
    map_body = render_context_map(
        context_map, cycle_n, prompt_mode=config.cartographer.prompt_block,
    )
    cross_body = _render_cross_corpus(identity, config, corpus_key)
    inventory = _render_corpus_inventory(identity, corpus_key)
    context_map_block = (
        f"--- Context Map ---\n{map_body}{cross_body}\n---{inventory}"
    )
else:
    context_map_block = ""
```

Apply the same three-line shape to `_system_message_for` (lines 465-476).

### Gap 1c: `list_corpora` system tool

System tools register via `harness_poc/system_tools/__init__.py`'s
`register()`, not via SKILL.md. New file
`harness_poc/system_tools/corpus_tools.py`:

```python
"""LLM-callable tool: inventory of context-map corpora."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.system_tools import register as _register

if TYPE_CHECKING:
    from harness_poc.core.storage import BlackboardDatabase


def _list_corpora(database: BlackboardDatabase, **_: Any) -> dict[str, Any]:
    all_keys = set(database.get_all_corpus_keys())
    pending_keys = set(database.get_pending_corpus_keys())

    out: list[dict[str, Any]] = []
    for ck in sorted(all_keys):
        entries = database.get_context_map(ck) or []
        out.append(
            {
                "key": ck,
                "materialized": bool(entries),
                "entry_count": len(entries),
                "cycle": database.get_cycle(ck),
                "has_pending_events": ck in pending_keys,
            }
        )
    return {"corpora": out}


_register(
    name="list_corpora",
    description=(
        "Return a structured inventory of every context-map corpus the "
        "harness knows about, including entry counts, current cycle, and "
        "whether pending events are queued. Use this to discover valid "
        "corpus_key values before observing or citing into a corpus."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_list_corpora,
)
```

Ensure the module is imported during `system_tools` startup so
`register()` fires (mirror whatever import-side-effect mechanism the
other `system_tools/*.py` modules rely on — check the `tool_runner`
discovery path).

If `has_pending_events` ever needs to become a count, add a single
`get_pending_corpus_key_counts() -> dict[str, int]` method to
`BlackboardDatabase`. Don't preemptively introduce it.

### Gap 2a: Session schema — add `active_corpus_key`

Follow the additive-migration pattern already used for context-map
columns (`database.py:52-56`). Column-on-row is the right shape here —
`DbSession` is flat and its peers are flat; do not jam this into a JSONB
blob.

```python
# harness_poc/core/storage/models.py — extend DbSession

class DbSession(SQLModel, table=True):
    __tablename__ = "sessions"  # type: ignore[assignment]

    session_id: str = Field(primary_key=True)
    global_objective: str
    status: str
    created_at: str
    active_corpus_key: str | None = Field(default=None)
```

```python
# harness_poc/core/storage/database.py — migration + helpers

def create_tables(self) -> None:
    SQLModel.metadata.create_all(self._engine)
    self._ensure_context_map_freeze_column()
    self._ensure_context_map_schema_version_column()
    self._ensure_context_map_cycles_table()
    self._ensure_sessions_active_corpus_column()  # new

def _ensure_sessions_active_corpus_column(self) -> None:
    """Add sessions.active_corpus_key for databases predating Gap 2."""
    inspector = inspect(self._engine)
    cols = {c["name"] for c in inspector.get_columns("sessions")}
    if "active_corpus_key" in cols:
        return
    with self._engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE sessions ADD COLUMN active_corpus_key TEXT"),
        )

def start_session(
    self,
    objective: str,
    *,
    active_corpus_key: str | None = None,
) -> str:
    session_id = str(uuid.uuid4())
    with Session(self._engine) as session:
        session.add(
            DbSession(
                session_id=session_id,
                global_objective=objective,
                status="active",
                created_at=self._utc_now(),
                active_corpus_key=active_corpus_key,
            )
        )
        session.commit()
    return session_id

def get_session_corpus_key(
    self,
    session_id: str,
    *,
    default: str,
) -> str:
    """Return the stored active_corpus_key, falling back to `default`.

    Default applies to legacy sessions created before the schema change
    and to fresh sessions started without an explicit --corpus flag.
    """
    with Session(self._engine) as session:
        row = session.get(DbSession, session_id)
    if row is None or not row.active_corpus_key:
        return default
    return row.active_corpus_key
```

### Gap 2b: Read session corpus in the LLM worker

`_extract_references()` already receives `session_id` and `database` at
`llm_worker.py:121-126` — no signature change needed. Replace line 137:

```python
# llm_worker.py — inside _extract_references
active_corpus_key = database.get_session_corpus_key(
    session_id,
    default=f"{config.project_id}:codebase",
)
```

Lines 140-144 (`related_keys`) are replaced by Gap 3b.

### Gap 2c: `--corpus` flag on REPL entrypoints

`cli.py:main_callback` and `cli.py:repl` both build app state. Thread
the flag through `_new_app_state` → `build_app_state` → `build_identity`
→ `start_session`:

```python
# harness_poc/cli.py

@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    resume: Annotated[
        str | None, typer.Option("--resume", help="Resume session by id."),
    ] = None,
    resume_last: Annotated[  # noqa: FBT002
        bool, typer.Option("--resume-last", help="Resume most recent session."),
    ] = False,
    corpus: Annotated[
        str | None,
        typer.Option(
            "--corpus", "-c",
            help=(
                "Active corpus key for new sessions (default: "
                "<project_id>:codebase). Must contain ':'. Unknown keys "
                "warn but are allowed so the agent can bootstrap them."
            ),
        ),
    ] = None,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    resolved_corpus = _validate_corpus(corpus)
    app_state = _new_app_state(
        session_id=_resolve_resume(resume, resume_last),
        corpus_key=resolved_corpus,
    )
    run_repl(app_state)
    raise typer.Exit


def _validate_corpus(corpus: str | None) -> str | None:
    if corpus is None:
        return None
    corpus = corpus.strip()
    if ":" not in corpus:
        print_error(
            f"--corpus value {corpus!r} must follow 'project:name' form.",
        )
        raise typer.Exit(1)

    # Soft warning, not a hard fail (see Gap 2 design).
    config = HarnessConfig.load()
    from harness_poc.core.storage import create_db_engine  # noqa: PLC0415
    db = BlackboardDatabase(create_db_engine(config.runtime.database_url))
    db.create_tables()
    if corpus not in set(db.get_all_corpus_keys()):
        console.print(
            f"[yellow]Note:[/yellow] corpus {corpus!r} not found in the "
            f"blackboard yet — it will materialize after the first observe.",
        )
    return corpus
```

`_new_app_state(session_id=..., corpus_key=...)` forwards to
`build_app_state(session_id=..., corpus_key=...)`, which forwards to
`build_identity(...)`. Inside `build_identity`, when `session_id` is
`None` (new session) pass `corpus_key` into `database.start_session`. On
resume, *do not* overwrite the stored value from the flag — the session
already remembers its corpus, and silently flipping it would surprise
the user.

### Gap 3a: Config field

```python
# harness_poc/core/context_map/config.py

_CARTOGRAPHER_KNOWN_KEYS = frozenset(
    {
        "token_budget",
        "tokenizer_name",
        "recency_bonus",
        "recency_cap",
        "staleness_penalty",
        "staleness_floor",
        "priority_weights",
        "prompt_block",
        "cross_corpus",
        "cross_corpus_auto_discover",  # new
    }
)


@dataclass(frozen=True, slots=True)
class CartographerConfig:
    # ... existing fields ...
    cross_corpus_auto_discover: bool = True
```

Wire it through `load_cartographer_config`:

```python
return CartographerConfig(
    # ... existing kwargs ...
    cross_corpus_auto_discover=bool(
        raw.get("cross_corpus_auto_discover", True),
    ),
)
```

### Gap 3b: Auto-discover in `_extract_references`

Replace the static lookup at `llm_worker.py:139-144`:

```python
cc = config.cartographer
if not cc.cross_corpus_enabled:
    related_keys: list[str] = []
elif cc.cross_corpus_auto_discover:
    all_keys = database.get_all_corpus_keys()
    related_keys = [k for k in all_keys if k != active_corpus_key]
    # Optional whitelist filter — when configured for this active key,
    # restrict the auto-discovered set to it.
    whitelist = cc.cross_corpus_related_corpora.get(active_corpus_key)
    if whitelist:
        whitelist_set = set(whitelist)
        related_keys = [k for k in related_keys if k in whitelist_set]
else:
    related_keys = cc.cross_corpus_related_corpora.get(active_corpus_key, [])
```

### Gap 3c: Warn on unresolved markers

Promote `llm_worker.py:181-183` from DEBUG to WARNING and include the
context needed to diagnose whitelist-induced misses:

```python
hit = lookup.get(entry_id)
if hit is None:
    logger.warning(
        "Unresolved [entry:%s] citation. active=%s related=%s known=%s",
        entry_id,
        active_corpus_key,
        related_keys,
        database.get_all_corpus_keys(),
    )
    continue
```

The fourth field (`known`) catches the common case where the cited corpus
exists but is excluded by the whitelist filter — without it, the warning
sends the reader hunting for a missing entry that is actually right there.

## Tests

All tests use the existing `test_config: HarnessConfig` and
`db_engine: Engine` conftest fixtures (the pattern landed by the unblock
plan; see `tests/skills/test_observe.py`).

### Gap 1

```python
# tests/storage/test_corpus_inventory.py

def test_get_all_corpus_keys_unions_materialized_and_pending(
    db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[], token_count=0, event_ids=[],
    )
    db.append_context_map_event(
        EntityReferenced(
            session_id="s", corpus_key="deverino:dashboard",
            entity_name="x", entity_type="concept", context="x",
        ),
    )
    assert db.get_all_corpus_keys() == [
        "deverino:codebase", "deverino:dashboard",
    ]


def test_inventory_omitted_for_single_corpus(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    identity = _identity_with_one_corpus(test_config, db_engine)
    assert _render_corpus_inventory(identity, "deverino:codebase") == ""


def test_inventory_marks_active(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    identity = _identity_with_two_corpora(test_config, db_engine)
    body = _render_corpus_inventory(identity, "deverino:dashboard")
    assert "deverino:dashboard (primary)" in body
    assert "deverino:codebase" in body
    assert "deverino:codebase (primary)" not in body
```

```python
# tests/system_tools/test_list_corpora.py

def test_list_corpora_returns_structured_inventory(
    db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        map_entries=[_entry(key="x", section="entities")],
        token_count=10, event_ids=[],
    )
    result = _list_corpora(database=db)

    assert result == {
        "corpora": [
            {
                "key": "deverino:codebase",
                "materialized": True,
                "entry_count": 1,
                "cycle": 0,
                "has_pending_events": False,
            },
        ],
    }
```

### Gap 2

```python
# tests/storage/test_session_corpus.py

def test_start_session_persists_active_corpus(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    sid = db.start_session("obj", active_corpus_key="deverino:dashboard")
    assert db.get_session_corpus_key(sid, default="x") == "deverino:dashboard"


def test_legacy_session_falls_back_to_default(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    sid = db.start_session("obj")
    assert (
        db.get_session_corpus_key(sid, default="deverino:codebase")
        == "deverino:codebase"
    )


def test_resume_does_not_overwrite_stored_corpus(
    db_engine: Engine,
) -> None:
    # Document the design rule: --corpus on resume is ignored in favour
    # of the corpus recorded on the session row.
    ...
```

```python
# tests/cli/test_corpus_flag.py

def test_corpus_flag_rejects_missing_colon() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--corpus", "no-colon"])
    assert result.exit_code == 1
    assert "must follow 'project:name'" in result.output


def test_corpus_flag_warns_on_unknown_but_proceeds(
    test_config: HarnessConfig, monkeypatch,
) -> None:
    # Patch HarnessConfig.load + create_db_engine to point at the test
    # blackboard, then invoke `--corpus deverino:brand-new`. Expect a
    # yellow "[Note:]" line in stderr but exit_code == 0.
    ...
```

```python
# tests/processors/test_reference_extraction.py

def test_extract_references_uses_session_corpus(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    sid = db.start_session("obj", active_corpus_key="deverino:dashboard")
    entry = _seed_entry(db, corpus="deverino:dashboard", key="card-1")

    refs = _extract_references(
        content=f"see [entry:{entry.entry_id.replace('-', '')}]",
        session_id=sid,
        database=db,
        config=test_config,
    )
    assert len(refs) == 1
    assert refs[0].corpus_key == "deverino:dashboard"
```

### Gap 3

```python
# tests/processors/test_reference_extraction.py (continued)

def test_auto_discover_indexes_all_corpora(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    cb = _seed_entry(db, corpus="deverino:codebase", key="cb-1")
    dash = _seed_entry(db, corpus="deverino:dashboard", key="dash-1")
    sid = db.start_session("obj")  # primary defaults to :codebase

    config = _config_with(test_config, cross_corpus_enabled=True)
    refs = _extract_references(
        content=(
            f"cb [entry:{cb.entry_id.replace('-', '')}] "
            f"dash [entry:{dash.entry_id.replace('-', '')}]"
        ),
        session_id=sid, database=db, config=config,
    )
    assert {r.corpus_key for r in refs} == {
        "deverino:codebase", "deverino:dashboard",
    }


def test_whitelist_filter_still_applies_under_auto_discover(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    # related_corpora set => acts as whitelist; auto_discover must still
    # honour the whitelist and exclude unlisted corpora.
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    cb = _seed_entry(db, corpus="deverino:codebase", key="cb-1")
    excluded = _seed_entry(db, corpus="deverino:noise", key="n-1")
    sid = db.start_session("obj")
    config = _config_with(
        test_config,
        cross_corpus_enabled=True,
        cross_corpus_auto_discover=True,
        cross_corpus_related_corpora={
            "deverino:codebase": ["deverino:dashboard"],  # excludes :noise
        },
    )
    refs = _extract_references(
        content=f"[entry:{excluded.entry_id.replace('-', '')}]",
        session_id=sid, database=db, config=config,
    )
    assert refs == []


def test_auto_discover_disabled_falls_back_to_static_list(
    test_config: HarnessConfig, db_engine: Engine,
) -> None:
    # auto_discover=False must reproduce pre-Gap-3 behaviour exactly.
    ...


def test_unresolved_marker_emits_warning(
    test_config: HarnessConfig, db_engine: Engine, caplog,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    sid = db.start_session("obj")
    with caplog.at_level(logging.WARNING):
        _extract_references(
            content="see [entry:" + "0" * 32 + "]",
            session_id=sid, database=db, config=test_config,
        )
    assert any("Unresolved" in rec.message for rec in caplog.records)
```

`_seed_entry` is a small helper that writes a single `MapEntry` to the
named corpus via `write_map_and_mark_processed` and returns it. Add to
`tests/processors/conftest.py` — it's reused across three tests.

`_config_with` clones `test_config` with cartographer overrides via
`dataclasses.replace(test_config.cartographer, ...)`.

### Tests that already exist and should be extended

- `tests/context_map/test_config.py` — add a case for
  `cross_corpus_auto_discover: false` parsing to lock in the
  backward-compat path.

## Known Gaps (Deferred)

- **Mid-session corpus switching.** Start a new session with `--corpus`.
- **Corpus metadata** (description, owner, created-at). The inventory is a
  flat list of keys. A `corpus_metadata` table is the natural follow-up.
- **Tool-aware corpus routing.** Tools like `semble_search` always search
  the codebase regardless of active corpus. Routing tool behaviour by
  corpus is its own design problem.
- **Lookup-dict cap.** `cross_corpus_max_entries` caps *rendered*
  entries but not the *indexed* lookup dict. A 10k-entry corpus would
  inflate the dict in `_extract_references`. Profile before adding a
  cap.

## Execution Order & Commits

1. `feat(database): add get_all_corpus_keys and active_corpus_key column`
   — Gap 1a + Gap 2a (schema + helpers + migration). Single commit so the
   column and its readers/writers ship together.
2. `feat(prompt): inject corpus inventory into system prompt` — Gap 1b
   (both builders via `_render_corpus_inventory`).
3. `feat(tools): add list_corpora system tool` — Gap 1c.
4. `feat(session): read active corpus per-session in llm_worker` — Gap 2b.
5. `feat(cli): add --corpus flag to REPL` — Gap 2c.
6. `feat(cartographer): auto-discover corpora for reference extraction`
   — Gap 3a + 3b + 3c.

Each commit ships with its tests.

## Acceptance / Verification

```bash
# Targeted
uv run pytest \
    tests/storage/test_corpus_inventory.py \
    tests/storage/test_session_corpus.py \
    tests/system_tools/test_list_corpora.py \
    tests/cli/test_corpus_flag.py \
    tests/processors/test_reference_extraction.py \
    tests/context_map/test_config.py \
    -v

# Full suite + lint + types
uv run pytest
uv run ruff check .
uv run ty check

# Manual smoke
uv run harness-poc --corpus deverino:dashboard
# In REPL: "what corpora are available?" — expect a list_corpora call
# Observe into deverino:dashboard, verify [entry:...] citations resolve
# and a [yellow]Note:[/yellow] line appears if the corpus is novel.
```

## Risk Assessment

- **Schema migration (Gap 2a).** `ALTER TABLE sessions ADD COLUMN
  active_corpus_key TEXT` is additive and nullable. Existing rows take
  the fallback path in `get_session_corpus_key`. SQLite and Postgres
  both support this without rewriting the table.
- **Two-builder drift (Gap 1b).** Mitigated by routing both through
  `_render_corpus_inventory` and `_render_cross_corpus`. A regression
  test snapshotting both prompt outputs side-by-side would harden this
  further — leave it as a follow-up unless drift bites.
- **Warning floods (Gap 3c).** Promoting unresolved-citation logs from
  DEBUG to WARNING is correct for the bootstrap case but could be loud
  if an agent hallucinates entry IDs frequently. Acceptable signal —
  hallucinated citations are exactly what we want surfaced.
- **Lookup-dict growth (Gap 3b).** See Known Gaps. No cap in v1.
- **Zero regression for single-corpus deployments.** Inventory block
  suppressed when `len(keys) <= 1`; primary defaults to `:codebase`;
  auto-discover yields the same single-key list as the legacy static
  config when only one corpus exists.
