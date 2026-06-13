# Track B Testing & Feedback Loop — Implementation Plan

**Date:** 2026-05-24
**Status:** ready for implementation
**Source spec:** `docs/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md`
**Parent:** Track B implementation (code complete except for one bug in §4.3)

**Goal:** Make Track B operational by closing three gaps:

1. **Prompt instruction** — SOUL.md never teaches the model to emit `[entry:<id>]` markers. The citation extraction path is inert without it.
2. **Cross-corpus attribution bug** — `_extract_references` emits every `MapEntryReferenced` against the active corpus, even when the cited entry lives in a related corpus. Spec §4.3 mandates source-corpus attribution.
3. **Zero test coverage** — all four Track B features (render, reference extraction, cross-corpus injection, calibration) have no tests.

**No new production features.** One small code fix, one prompt edit, four test files.

**Tech stack.** `pytest`, existing project patterns: frozen dataclasses, in-memory SQLite via `BlackboardDatabase.from_url("sqlite:///:memory:")`, direct module-level imports of the functions under test. No new dependencies.

---

## Gap 1 — SOUL Citation Instruction (load-bearing)

**Problem.** `_extract_references()` in `harness_poc/core/processors/llm_worker.py` scans LLM output for `[entry:<32-hex>]` markers. The model has no instruction to emit these markers. The citation feedback loop (§4.2 → §4.4) is dead on arrival.

**File:** `harness_poc/system_prompts/SOUL.md`

**Placement decision.** The original spec text suggested §4.3 ("Document Retrieval Model"). That section is Vespa-specific — the Context Map is a different subsystem, so co-locating there is semantically off. Better: add a new `### 4.4 Context Map Citation` subsection immediately after §4.3. This keeps the two citation contracts adjacent without conflating them.

**Edit.** Insert after line 99 (end of §4.3):

```markdown
### 4.4 Context Map Citation

- The system prompt may include a `--- Context Map ---` block listing facts the
  harness has materialized for this corpus. Each line carries a bracketed id of
  the form `[entry:<32-hex>]`.
- When I use a fact from the Context Map in a response, I cite it inline by
  reproducing the bracketed id (e.g. "the default token budget is 1024
  [entry:ab12cd34ef560789abcdef0123456789]"). This is how the harness learns
  which entries earn their tokens — uncited entries get demoted over time.
- I do not invent ids. If I cannot find a relevant entry in the map, I cite
  nothing rather than fabricating an id.
```

The last bullet is non-negotiable. The regex (`[0-9a-f]{32}`) will accept any 32-hex string and `_extract_references` only emits events for ids in the current map, so fabricated ids waste lookup work but are harmless to the data — yet the prompt should still forbid them to keep model output honest.

**Verification.** Manual: start the REPL with a populated context map (`uv run harness-poc`), ask a question that touches a materialized fact, confirm the response contains `[entry:...]` markers and the event log shows `MapEntryReferenced` rows.

---

## Gap 2 — Cross-Corpus Attribution Bug (§4.3 contract violation)

**Problem.** Spec §4.3 says: _"if [the agent] cites one [related-corpus entry] with `[entry:<id>]`, the resulting `MapEntryReferenced` is emitted against the **source** corpus's `corpus_key`, not the active one."_

Current code at `harness_poc/core/processors/llm_worker.py:132,176` always uses the active corpus:

```python
corpus_key = f"{config.project_id}:codebase"  # line 132
...
refs.append(MapEntryReferenced(
    session_id=session_id,
    corpus_key=corpus_key,                    # line 176 — always active
    ...
))
```

Cross-corpus citations get mis-attributed. This silently corrupts the calibration signal in §4.4: a related corpus's entry that earns its tokens will look like the active corpus's entry doing so.

**Fix.** Track the source corpus alongside each entry in the lookup table.

**File:** `harness_poc/core/processors/llm_worker.py`

**Patch** (replace the entire body of `_extract_references`):

```python
def _extract_references(
    content: str,
    session_id: str,
    database: BlackboardDatabase,
    config: HarnessConfig,
) -> list[MapEntryReferenced]:
    """Scan assistant output for [entry:<id>] markers and emit MapEntryReferenced events.

    Track B §4.2: Inline regex post-processor that runs immediately before
    LLMTextEmitted is published. Cross-corpus citations are attributed to the
    source corpus per §4.3, not the active one.
    """
    logger = logging.getLogger(__name__)

    active_corpus_key = f"{config.project_id}:codebase"

    cc = config.cartographer
    related_keys: list[str] = (
        cc.cross_corpus_related_corpora.get(active_corpus_key, [])
        if cc.cross_corpus_enabled
        else []
    )

    # (entry, source_corpus_key) keyed by both dashed and undashed entry_id.
    # Active corpus wins on collision (see _index_active below).
    lookup: dict[str, tuple[object, str]] = {}

    def _index_related(entries: Iterable[object], source: str) -> None:
        for entry in entries:
            entry_id = getattr(entry, "entry_id", "")
            if not entry_id:
                continue
            lookup.setdefault(entry_id.replace("-", ""), (entry, source))
            lookup.setdefault(entry_id, (entry, source))

    def _index_active(entries: Iterable[object]) -> None:
        # Explicit overwrite — active corpus is authoritative on duplicate ids.
        for entry in entries:
            entry_id = getattr(entry, "entry_id", "")
            if not entry_id:
                continue
            lookup[entry_id.replace("-", "")] = (entry, active_corpus_key)
            lookup[entry_id] = (entry, active_corpus_key)

    related_maps = database.get_context_maps(related_keys) if related_keys else {}
    for source_key, entries in related_maps.items():
        _index_related(entries, source_key)
    _index_active(database.get_context_map(active_corpus_key) or [])

    # Per-turn dedup keyed on (source_corpus, entry_id). Same id in two corpora
    # is theoretical but the dedup must not collapse them.
    seen: set[tuple[str, str]] = set()
    refs: list[MapEntryReferenced] = []
    cycle_cache: dict[str, int] = {}

    for match in _CITATION_RE.finditer(content):
        entry_id = match.group(1)
        hit = lookup.get(entry_id)
        if hit is None:
            logger.debug("Citation marker references unknown entry_id=%s", entry_id)
            continue
        entry, source_corpus = hit
        dedup_key = (source_corpus, entry_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if source_corpus not in cycle_cache:
            cycle_cache[source_corpus] = database.get_cycle(source_corpus)

        refs.append(
            MapEntryReferenced(
                session_id=session_id,
                corpus_key=source_corpus,
                entry_id=entry_id,
                entry_key=str(getattr(entry, "key", "")),
                section=str(getattr(entry, "section", "")),
                cycle_n=cycle_cache[source_corpus],
                citation_context=content[
                    max(0, match.start() - 80) : match.end() + 80
                ],
            )
        )

    return refs
```

**What changed vs current code:**

1. `lookup` is now `dict[str, tuple[entry, source_corpus_key]]` instead of `dict[str, entry]`.
2. Related corpora are indexed first via `setdefault`; the active corpus overwrites via plain assignment. "Home corpus wins on duplicate id" is explicit.
3. `cycle_n` is looked up per source corpus and cached. Previously it used the active corpus's cycle for everyone, which was wrong for cross-corpus entries.
4. Dedup key is `(source_corpus, entry_id)`, not just `entry_id`.
5. Each emitted `MapEntryReferenced.corpus_key` is the source corpus.

**Required imports** at the top of `llm_worker.py` (add if missing):

```python
import logging
from collections.abc import Iterable
```

Move the existing inline `import logging` out of the function body and use the module-level `logger = logging.getLogger(__name__)` pattern.

**Verification.** Test `test_cross_corpus_attribution` in Task 2 below will fail before this patch and pass after.

---

## Gap 3 — Test Coverage

Four new test files, 35 tests total. No production code beyond the §4.3 fix above.

### Task 1: `tests/context_map/test_render.py`

Covers Track B §4.1 — `render_context_map()` in `harness_poc/core/context_map/render.py`.

**Setup helper** (put at top of file):

```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from harness_poc.core.context_map.render import render_context_map
from harness_poc.core.context_map.schema import MapEntry


def _make_entry(
    *,
    section: str = "parsing_schema",
    priority: float = 0.8,
    summary: str = "A fact about the codebase.",
    observation_type: str = "schema",
    key: str | None = None,
    entry_id: str | None = None,
) -> MapEntry:
    """Build a MapEntry with sensible defaults. Defaults to a dashed UUID
    so render's dash-stripping is exercised."""
    now = datetime.now(tz=UTC)
    return MapEntry(
        entry_id=entry_id or str(uuid4()),
        key=key or f"key-{uuid4().hex[:8]}",
        section=section,
        observation_type=observation_type,
        summary=summary,
        priority=priority,
        source_event_ids=[],
        first_seen=now,
        last_updated=now,
        materialization_count=0,
        first_seen_cycle=1,
        last_seen_cycle=1,
        token_estimate=10,
    )
```

**Test cases:**

| Test | What it validates |
|---|---|
| `test_structured_mode_groups_by_section` | Entries with same section appear together under one `section:` header |
| `test_structured_mode_section_order_follows_priority_table` | Sections render in the Part 1 §4 order (`parsing_schema` before `domain_constants`, etc.) regardless of input order |
| `test_structured_mode_within_section_sorts_by_priority_desc_then_entry_id` | Within a section, higher priority first; ties break on entry_id ascending |
| `test_structured_mode_includes_cycle_header` | First line is `cycle: <n>` |
| `test_structured_mode_strips_dashes_from_entry_id` | UUID input `"abc-def-..."` renders as `[entry:abcdef...]` with no dashes (32 hex chars) |
| `test_structured_mode_collapses_whitespace_in_summary` | Summary `"line one\n  line two"` renders as `"line one line two"` on a single line |
| `test_json_mode_returns_valid_parseable_json` | `prompt_mode="json"` → `json.loads(output)` succeeds and returns a list of dicts |
| `test_none_mode_returns_empty_string` | `prompt_mode="none"` → `""` exactly |
| `test_empty_entries_returns_only_cycle_header` | No entries → output is exactly `"cycle: <n>"` |
| `test_deterministic_across_runs` | Same input rendered twice produces byte-identical output |

**Sample tests:**

```python
def test_structured_mode_strips_dashes_from_entry_id() -> None:
    dashed = "ab12cd34-ef56-7890-abcd-ef0123456789"
    entry = _make_entry(entry_id=dashed)
    out = render_context_map([entry], cycle_n=1)
    assert "[entry:ab12cd34ef567890abcdef0123456789]" in out
    assert dashed not in out  # dashed form must not appear anywhere


def test_structured_mode_within_section_sorts_by_priority_desc_then_entry_id() -> None:
    e_low = _make_entry(priority=0.5, entry_id="11111111-1111-1111-1111-111111111111")
    e_high_a = _make_entry(priority=0.9, entry_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    e_high_b = _make_entry(priority=0.9, entry_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    out = render_context_map([e_low, e_high_b, e_high_a], cycle_n=1)
    idx_a = out.index("aaaa")
    idx_b = out.index("bbbb")
    idx_1 = out.index("1111")
    assert idx_a < idx_b < idx_1


def test_json_mode_returns_valid_parseable_json() -> None:
    entries = [_make_entry(), _make_entry()]
    out = render_context_map(entries, cycle_n=1, prompt_mode="json")
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert all("entry_id" in e for e in parsed)
```

### Task 2: `tests/processors/test_reference_extraction.py`

Covers Track B §4.2 and the §4.3 attribution fix above.

**New directory marker:** `tests/processors/__init__.py` (empty file).

**Setup pattern.** `_extract_references` takes `(content, session_id, database, config)`. The active `corpus_key` and `cycle_n` are derived internally from `config.project_id` and `database.get_cycle()` — tests must set up both.

```python
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.processors.llm_worker import _extract_references
from harness_poc.core.storage.database import BlackboardDatabase


@pytest.fixture
def db() -> BlackboardDatabase:
    return BlackboardDatabase.from_url("sqlite:///:memory:")


def _make_entry(entry_id: str, *, section: str = "parsing_schema", key: str = "k") -> MapEntry:
    now = datetime.now(tz=UTC)
    return MapEntry(
        entry_id=entry_id,
        key=key,
        section=section,
        observation_type="schema",
        summary="x",
        priority=0.8,
        source_event_ids=[],
        first_seen=now,
        last_updated=now,
        materialization_count=0,
        first_seen_cycle=1,
        last_seen_cycle=1,
        token_estimate=5,
    )


def _make_config(
    *,
    project_id: str = "deverino",
    cross_corpus_enabled: bool = False,
    related: dict[str, list[str]] | None = None,
) -> object:
    """Build a minimal config stub. _extract_references only reads:
       config.project_id, config.cartographer.cross_corpus_enabled,
       config.cartographer.cross_corpus_related_corpora.
    """
    return SimpleNamespace(
        project_id=project_id,
        cartographer=CartographerConfig(
            cross_corpus_enabled=cross_corpus_enabled,
            cross_corpus_related_corpora=related or {},
        ),
    )
```

> **Why SimpleNamespace, not a real `HarnessConfig`.** `_extract_references` reads only three attributes. A real config is heavy to construct. If a later change adds more reads, swap to a real config fixture — but for now, the stub is faster and more focused. The active `corpus_key` it derives will be `"deverino:codebase"`.
>
> **Seeding maps.** Use the real persistence path: `db.write_map_and_mark_processed(corpus_key, [entry, ...], token_count, processed_event_ids=[])`. Passing an empty `processed_event_ids` list is fine — there are no pending events to mark.

**Test cases:**

| Test | What it validates |
|---|---|
| `test_extracts_well_formed_marker` | One `[entry:<32-hex>]` matching an indexed entry → exactly one `MapEntryReferenced` |
| `test_ignores_malformed_markers` | `[entry:short]`, `[entry:nonhexZZZZ]`, `[entry:with-dashes-here]` → no refs |
| `test_unknown_entry_id_emits_nothing` | Well-formed marker but id not in any map → no refs, no exception |
| `test_deduplicates_per_turn` | Same marker twice in one `content` → one ref |
| `test_dashed_id_in_marker_does_not_match_regex` | The regex is `[0-9a-f]{32}`; dashed UUID inside the bracket is malformed by design |
| `test_citation_context_window_is_about_160_chars` | `len(ref.citation_context)` is `match_len + up to 160`; marker is contained in `citation_context` |
| `test_cross_corpus_disabled_ignores_related_maps` | Marker matches a related-corpus entry but `cross_corpus_enabled=False` → no ref |
| `test_cross_corpus_attribution` | **(formerly the bug)** Marker matches a related-corpus entry; `cross_corpus_enabled=True`, adjacency set → ref's `corpus_key` is the **source** corpus, `cycle_n` is the source's cycle |
| `test_active_corpus_wins_on_id_collision` | Same `entry_id` exists in active and related corpus → ref attributes to active |
| `test_no_markers_returns_empty_list` | `content="just text"` → `[]` |

**Sample tests:**

```python
def test_extracts_well_formed_marker(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    entry_id = uuid4().hex  # 32-char, no dashes
    db.write_map_and_mark_processed(active, [_make_entry(entry_id)], 5, [])

    refs = _extract_references(
        content=f"The fact is [entry:{entry_id}] here.",
        session_id="s1",
        database=db,
        config=_make_config(),
    )

    assert len(refs) == 1
    assert refs[0].entry_id == entry_id
    assert refs[0].corpus_key == active


def test_cross_corpus_attribution(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "harness_poc:codebase"

    # Active corpus: empty map, cycle 3
    db.write_map_and_mark_processed(active, [], 0, [])
    for _ in range(3):
        db.get_and_bump_cycle(active)

    # Related corpus: 1 entry, cycle 7
    entry_id = uuid4().hex
    related_entry = _make_entry(entry_id, key="related-key", section="domain_constants")
    db.write_map_and_mark_processed(related, [related_entry], 5, [])
    for _ in range(7):
        db.get_and_bump_cycle(related)

    config = _make_config(
        cross_corpus_enabled=True,
        related={active: [related]},
    )

    refs = _extract_references(
        content=f"The schema requires [entry:{entry_id}] for parsing.",
        session_id="s1",
        database=db,
        config=config,
    )

    assert len(refs) == 1
    ref = refs[0]
    assert ref.corpus_key == related, "must attribute to source corpus, not active"
    assert ref.cycle_n == 7, "must use source corpus's cycle, not active's"
    assert ref.entry_id == entry_id
    assert ref.entry_key == "related-key"
    assert ref.section == "domain_constants"


def test_active_corpus_wins_on_id_collision(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    shared_id = uuid4().hex

    db.write_map_and_mark_processed(
        active, [_make_entry(shared_id, key="active-key")], 5, []
    )
    db.write_map_and_mark_processed(
        related, [_make_entry(shared_id, key="related-key")], 5, []
    )

    config = _make_config(
        cross_corpus_enabled=True,
        related={active: [related]},
    )
    refs = _extract_references(
        content=f"Cite [entry:{shared_id}] here.",
        session_id="s1",
        database=db,
        config=config,
    )

    assert len(refs) == 1
    assert refs[0].corpus_key == active
    assert refs[0].entry_key == "active-key"


def test_ignores_malformed_markers(db: BlackboardDatabase) -> None:
    db.write_map_and_mark_processed("deverino:codebase", [], 0, [])
    refs = _extract_references(
        content=(
            "[entry:tooshort] "
            "[entry:ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ] "  # non-hex
            "[entry:ab12cd34-ef56-7890-abcd-ef0123456789] "  # dashes inside bracket
        ),
        session_id="s1",
        database=db,
        config=_make_config(),
    )
    assert refs == []
```

### Task 3: `tests/context_map/test_cross_corpus.py`

Covers Track B §4.3 — `_render_cross_corpus()` in `harness_poc/app_factory.py`.

**Stub strategy.** `_render_cross_corpus(identity, config, active_corpus_key)` only uses `identity.database`. Use a `SimpleNamespace` for both `identity` and `config`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from harness_poc.app_factory import _render_cross_corpus
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import MapEntry
from harness_poc.core.storage.database import BlackboardDatabase


@pytest.fixture
def db() -> BlackboardDatabase:
    return BlackboardDatabase.from_url("sqlite:///:memory:")


def _make_entry(*, priority: float = 0.8, section: str = "domain_constants") -> MapEntry:
    now = datetime.now(tz=UTC)
    return MapEntry(
        entry_id=str(uuid4()),
        key=f"k-{uuid4().hex[:6]}",
        section=section,
        observation_type="schema",
        summary="Some related-corpus fact.",
        priority=priority,
        source_event_ids=[],
        first_seen=now,
        last_updated=now,
        materialization_count=0,
        first_seen_cycle=1,
        last_seen_cycle=1,
        token_estimate=10,
    )


def _make_config(
    *,
    enabled: bool,
    related: dict[str, list[str]] | None = None,
    max_entries: int = 16,
    min_priority: float = 0.7,
) -> object:
    return SimpleNamespace(
        cartographer=CartographerConfig(
            cross_corpus_enabled=enabled,
            cross_corpus_related_corpora=related or {},
            cross_corpus_max_entries=max_entries,
            cross_corpus_min_priority=min_priority,
        ),
    )


def _identity_for(db: BlackboardDatabase) -> object:
    return SimpleNamespace(database=db)
```

**Test cases:**

| Test | What it validates |
|---|---|
| `test_disabled_returns_empty` | `cross_corpus_enabled=False` → `""` regardless of adjacency |
| `test_no_adjacency_returns_empty` | enabled but `related_corpora` has no entry for active key → `""` |
| `test_adjacency_with_no_persisted_maps_returns_empty` | related key listed but `get_context_maps` returns `{}` → `""` |
| `test_renders_corpus_header_and_entries` | Related corpus has 2 entries above threshold → output contains `# Related Corpora`, `## <corpus> (cycle N)`, both entry markers |
| `test_respects_max_cross_entries` | 30 entries seeded, `max_cross_entries=5` → exactly 5 entry lines per corpus |
| `test_respects_min_priority` | Mix of p=0.5 and p=0.9, `min_priority=0.7` → only p=0.9 entries appear |
| `test_returns_empty_when_all_entries_filtered_out` | All entries below `min_priority` → `""` (not just the header) |
| `test_multiple_related_corpora_both_rendered` | Two related corpora both populated → both `## <corpus>` headers present |

**Sample tests:**

```python
def test_disabled_returns_empty(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    db.write_map_and_mark_processed(related, [_make_entry()], 10, [])

    config = _make_config(enabled=False, related={active: [related]})
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert out == ""


def test_respects_min_priority(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    entries = [_make_entry(priority=0.5), _make_entry(priority=0.9)]
    db.write_map_and_mark_processed(related, entries, 20, [])
    db.get_and_bump_cycle(related)

    config = _make_config(enabled=True, related={active: [related]}, min_priority=0.7)
    out = _render_cross_corpus(_identity_for(db), config, active)

    assert "(p=0.90)" in out
    assert "(p=0.50)" not in out


def test_respects_max_cross_entries(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    entries = [_make_entry(priority=0.9) for _ in range(30)]
    db.write_map_and_mark_processed(related, entries, 300, [])
    db.get_and_bump_cycle(related)

    config = _make_config(enabled=True, related={active: [related]}, max_entries=5)
    out = _render_cross_corpus(_identity_for(db), config, active)

    # One header line + 5 entry lines for this single related corpus
    entry_lines = [line for line in out.splitlines() if line.lstrip().startswith("- [entry:")]
    assert len(entry_lines) == 5
```

### Task 4: `tests/cli/test_calibrate.py`

Covers Track B §4.4 — `run_calibration()` in `harness_poc/core/context_map/calibrate.py`.

**Signature reference** (from source, verified):

```python
def run_calibration(
    db: BlackboardDatabase,
    corpus_key: str,
    *,
    window_days: int = 14,
    min_events: int = 50,
    dry_run: bool = True,
    config_path: str | None = None,
) -> CalibrationResult: ...
```

`CalibrationResult` has: `status` (`"success" | "insufficient_data"`), `weights` (`dict[type, {"current": float, "target": float, "delta": float}]`), `total_references`, `total_evictions`, `total_insertions`, `message`, `corpus_key`, `window_days`.

> **Pre-flight: read these in `calibrate.py` before writing fixtures.**
>
> - `_count_references`, `_count_evictions`, `_count_insertions` — confirm which event field is used as the aggregation bucket. Inspection shows insertions bucket by `observation_type` (the event class carries it). The reference/eviction events as currently defined do NOT carry `observation_type` — they carry `section`. If the aggregator buckets references by section but insertions by observation_type, fixture types must align. **If the bucketing is inconsistent, that itself is a bug; flag and pause before working around it.**
> - `_write_calibrated_weights` (around line 270+) — confirm the backup filename pattern so `test_apply_writes_new_weights_and_backup` can assert the right path.

**Seeding events.** Use `db.append_context_map_event()` with the event dataclasses directly:

```python
from __future__ import annotations

from uuid import uuid4

import pytest

from harness_poc.core.context_map.calibrate import run_calibration
from harness_poc.core.events.context_map_events import (
    MapEntryEvicted,
    MapEntryInserted,
    MapEntryReferenced,
)
from harness_poc.core.storage.database import BlackboardDatabase


@pytest.fixture
def db() -> BlackboardDatabase:
    return BlackboardDatabase.from_url("sqlite:///:memory:")


def _seed_references(
    db: BlackboardDatabase,
    corpus_key: str,
    *,
    count: int,
    section: str = "parsing_schema",
) -> None:
    for _ in range(count):
        db.append_context_map_event(
            MapEntryReferenced(
                session_id="s",
                corpus_key=corpus_key,
                entry_id=uuid4().hex,
                entry_key="k",
                section=section,
                cycle_n=1,
                citation_context="ctx",
            )
        )


def _seed_evictions(
    db: BlackboardDatabase,
    corpus_key: str,
    *,
    count: int,
    reason: str = "budget@cycle=1,priority=0.4",
    materialization_count: int = 1,
) -> None:
    for _ in range(count):
        db.append_context_map_event(
            MapEntryEvicted(
                session_id="s",
                corpus_key=corpus_key,
                entry_id=uuid4().hex,
                entry_key="k",
                section="parsing_schema",
                reason=reason,
                materialization_count=materialization_count,
            )
        )


def _seed_insertions(
    db: BlackboardDatabase,
    corpus_key: str,
    *,
    count: int,
    observation_type: str = "schema",
) -> None:
    for _ in range(count):
        db.append_context_map_event(
            MapEntryInserted(
                session_id="s",
                corpus_key=corpus_key,
                entry_id=uuid4().hex,
                entry_key="k",
                section="parsing_schema",
                observation_type=observation_type,
                cycle_n=1,
            )
        )
```

**Test cases:**

| Test | What it validates |
|---|---|
| `test_insufficient_data_refused` | Seed < `min_events` references → `status == "insufficient_data"`, `message` mentions the threshold, `weights == {}` |
| `test_min_events_configurable` | 15 refs with `min_events=10` → `success`; 5 refs with `min_events=10` → `insufficient_data` |
| `test_dry_run_does_not_write_config` | `dry_run=True`, `config_path=tmp.yaml` with known contents → file bytes unchanged |
| `test_apply_writes_new_weights_and_backup` | `dry_run=False`, valid `config_path` → file contains new weights, backup file exists alongside, header comment with timestamp + counts present |
| `test_zero_insertions_yields_survival_one` | Refs but no `MapEntryInserted` events of type X → for that type, the formula treats `survival=1.0` (no ZeroDivisionError, no NaN) |
| `test_weights_clamped_to_bounds` | Synthetic ratios that would push weight to >1.0 or <0.1 → result stays in `[0.1, 1.0]` |
| `test_formula_smoke_check` | Hand-calculated: pre-seeded ratios produce a `target_weights[type]` within ±0.02 of `base * (0.5+ref_rate) * (0.5+survival)` |

**Sample tests:**

```python
def test_insufficient_data_refused(db: BlackboardDatabase) -> None:
    corpus = "deverino:codebase"
    _seed_references(db, corpus, count=5)  # well below default min_events=50

    result = run_calibration(db, corpus, dry_run=True)

    assert result.status == "insufficient_data"
    assert "50" in result.message
    assert result.weights == {}


def test_dry_run_does_not_write_config(tmp_path) -> None:
    db = BlackboardDatabase.from_url("sqlite:///:memory:")
    corpus = "deverino:codebase"
    _seed_references(db, corpus, count=60)

    cfg = tmp_path / "harness.yaml"
    original = "cartographer:\n  priority_weights:\n    schema: 0.5\n"
    cfg.write_text(original)

    result = run_calibration(
        db, corpus, dry_run=True, config_path=str(cfg), min_events=10
    )

    assert result.status == "success"
    assert cfg.read_text() == original, "dry_run must not mutate the file"


def test_min_events_configurable(db: BlackboardDatabase) -> None:
    corpus = "deverino:codebase"
    _seed_references(db, corpus, count=15)

    ok = run_calibration(db, corpus, dry_run=True, min_events=10)
    refused = run_calibration(db, corpus, dry_run=True, min_events=20)

    assert ok.status == "success"
    assert refused.status == "insufficient_data"
```

---

## File Summary

### Modified

| File | Change | Approx lines |
|---|---|---|
| `harness_poc/system_prompts/SOUL.md` | Insert new `### 4.4 Context Map Citation` after §4.3 | +10 |
| `harness_poc/core/processors/llm_worker.py` | Rewrite `_extract_references` body for source-corpus attribution (Gap 2) | ~+40 / −25 |

### Created

| File | Purpose | Tests |
|---|---|---|
| `tests/context_map/test_render.py` | `render_context_map()` output format | 10 |
| `tests/processors/__init__.py` | Package marker | — |
| `tests/processors/test_reference_extraction.py` | `_extract_references()` regex, dedup, **cross-corpus attribution** | 10 |
| `tests/context_map/test_cross_corpus.py` | `_render_cross_corpus()` config + filtering | 8 |
| `tests/cli/test_calibrate.py` | `run_calibration()` formula + safety | 7 |

**Total new tests:** 35.

---

## Verification

```bash
# Run all Track B tests
uv run pytest \
  tests/context_map/test_render.py \
  tests/processors/test_reference_extraction.py \
  tests/context_map/test_cross_corpus.py \
  tests/cli/test_calibrate.py \
  -v

# Lint + types on the one changed source file
uv run ruff check harness_poc/core/processors/llm_worker.py
uv run ty check harness_poc/core/processors/llm_worker.py

# Manual end-to-end smoke test
uv run harness-poc
# In the REPL: ask a question whose answer touches a materialized fact,
# confirm `[entry:...]` markers appear in the response, then query the
# context_map_events table for new MapEntryReferenced rows.
```

---

## Acceptance criteria

- [ ] SOUL.md has a `### 4.4 Context Map Citation` subsection containing the `[entry:<id>]` instruction and the "do not invent ids" rule
- [ ] `_extract_references` attributes `MapEntryReferenced.corpus_key` to the source corpus for cross-corpus citations
- [ ] `_extract_references` looks up `cycle_n` per source corpus, not just for the active corpus
- [ ] `_extract_references` dedups by `(source_corpus, entry_id)`, not just `entry_id`
- [ ] `test_render.py` — all 10 tests pass
- [ ] `test_reference_extraction.py` — all 10 tests pass, including `test_cross_corpus_attribution` and `test_active_corpus_wins_on_id_collision`
- [ ] `test_cross_corpus.py` — all 8 tests pass
- [ ] `test_calibrate.py` — all 7 tests pass
- [ ] All 35 new tests run in < 3 seconds combined (no external services)
- [ ] `ruff check` and `ty check` clean on `harness_poc/core/processors/llm_worker.py`

---

## Implementation order (recommended)

1. **SOUL.md edit** — trivial, makes the citation contract complete on its own.
2. **Write `test_cross_corpus_attribution` first (TDD)** — confirm it fails against the current code, proving the bug exists.
3. **Apply the §4.3 fix to `_extract_references`** — `test_cross_corpus_attribution` now passes.
4. **Fill in the rest of `test_reference_extraction.py`** — full coverage of the rewritten function, including `test_active_corpus_wins_on_id_collision`.
5. **Pre-flight read of `calibrate.py`** (see Task 4 callout) — confirm `_count_*` bucketing matches fixture assumptions before writing `test_calibrate.py`. If a bucketing inconsistency is found, stop and report; do not work around it.
6. **Write the remaining three test files** (`test_render.py`, `test_cross_corpus.py`, `test_calibrate.py`) — independent, any order.

---

## Out of scope / deferred

Track A test files from spec §6 are not part of this plan:

| Test file | Reason deferred |
|---|---|
| `tests/skills/test_context_map_materializer.py` | Materializer skill exercises real Distiller LLM calls; needs `pydantic_ai.models.test.TestModel` plumbing |
| `tests/storage/test_context_map_migration.py` | Migration is one-shot; no production data needs the round-trip |
| `tests/storage/test_cycle_counter.py` | `get_and_bump_cycle` is a thin DB wrapper; coverage falls out of the cross-corpus/render tests that call it |

A speculative refactor — extracting `render_cross_corpus` from `app_factory.py` into `context_map/render.py` — was considered and rejected. `_render_cross_corpus` only reads `identity.database`, so a `SimpleNamespace` stub is sufficient for testing; no source-code rearrangement is justified.
