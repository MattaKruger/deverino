# Deterministic Cartographer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM Cartographer/Evictor stages with a deterministic Python engine, fed by a strict-schema LLM Distiller. Deliver the Cartographer + Distiller contract under `harness_poc/core/context_map/`; defer event-store wiring and ACDL injection to a follow-up spec.

**Architecture:** Pure-function Cartographer `(distilled, current_map, cycle_n, config) -> CartographerResult`. The Distiller is a PydanticAI agent with `output_type=DistilledBatch`, bounded retry, safe `[]` fallback. New package `harness_poc/core/context_map/` with one module per responsibility (schema, sections, config, distiller, cartographer). No I/O in the Cartographer; no event-bus calls in either component. Caller owns persistence and event emission.

**Tech Stack:** Python 3.14, Pydantic (schemas), `pydantic-ai` (Distiller agent + `TestModel`), `tiktoken` (token estimation), `pytest` + `pytest-asyncio`. Project uses frozen dataclasses for `HarnessConfig` — config additions follow that pattern; runtime schemas use Pydantic to match `pydantic-ai` output validation.

**Source spec:** `docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md`

---

## File Structure

**New files:**
- `harness_poc/core/context_map/__init__.py` — public exports
- `harness_poc/core/context_map/schema.py` — Pydantic models (DistillerEntry, MapEntry, DistilledBatch, EvictionRecord, CartographerResult)
- `harness_poc/core/context_map/sections.py` — `SECTION_MAP` + `assign_section`
- `harness_poc/core/context_map/config.py` — `DistillerConfig`, `CartographerConfig` (frozen dataclasses + loaders)
- `harness_poc/core/context_map/cartographer.py` — `deterministic_cartographer` pure function
- `harness_poc/core/context_map/distiller.py` — `run_distiller` (async)
- `harness_poc/core/context_map/prompts/__init__.py` — empty marker
- `harness_poc/core/context_map/prompts/distiller_v1.md` — system prompt template
- `tests/context_map/__init__.py`
- `tests/context_map/test_events.py`
- `tests/context_map/test_schema.py`
- `tests/context_map/test_sections.py`
- `tests/context_map/test_config.py`
- `tests/context_map/test_cartographer_dedup.py`
- `tests/context_map/test_cartographer_priority.py`
- `tests/context_map/test_cartographer_eviction.py`
- `tests/context_map/test_cartographer_determinism.py`
- `tests/context_map/test_cartographer_invariants.py`
- `tests/context_map/test_distiller_contract.py`

**Modified files:**
- `harness_poc/core/events/context_map_events.py` — add `MapEntryReferenced`; widen `MapEntryEvicted`
- `harness_poc/core/config.py` — add `DistillerConfigBlock`, `CartographerConfigBlock` to `HarnessConfig`
- `harness.yaml` — add `distiller` and `cartographer` sections

---

## Task 1: Event additions (`MapEntryReferenced`, widen `MapEntryEvicted`)

**Files:**
- Modify: `harness_poc/core/events/context_map_events.py`
- Test: `tests/context_map/test_events.py`

- [ ] **Step 1: Create the test directory marker**

Create `tests/context_map/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test**

Create `tests/context_map/test_events.py`:

```python
from __future__ import annotations

import pytest

from harness_poc.core.events.context_map_events import (
    CONTEXT_MAP_EVENT_REGISTRY,
    MapEntryEvicted,
    MapEntryReferenced,
    deserialize_event,
)


def test_map_entry_referenced_round_trip() -> None:
    event = MapEntryReferenced(
        session_id="s1",
        corpus_key="codebase",
        entry_id="e-1",
        entry_key="codebase-entry-point",
        section="context_understanding",
        cycle_n=4,
        citation_context="…cited at app_factory.py:42…",
    )
    dumped = event.model_dump()
    assert dumped["event_type"] == "map_entry_referenced"
    revived = deserialize_event(dumped)
    assert isinstance(revived, MapEntryReferenced)
    assert revived.entry_key == "codebase-entry-point"
    assert revived.cycle_n == 4


def test_map_entry_referenced_in_registry() -> None:
    assert CONTEXT_MAP_EVENT_REGISTRY["map_entry_referenced"] is MapEntryReferenced


def test_map_entry_evicted_carries_materialization_count() -> None:
    event = MapEntryEvicted(
        session_id="s1",
        corpus_key="codebase",
        entry_key="stale-key",
        section="context_understanding",
        reason="stale@cycle=10,age=8,type=entity",
        materialization_count=2,
    )
    dumped = event.model_dump()
    assert dumped["materialization_count"] == 2
    assert dumped["reason"] == "stale@cycle=10,age=8,type=entity"


def test_map_entry_evicted_defaults_materialization_count_to_zero() -> None:
    event = MapEntryEvicted(
        session_id="s1",
        corpus_key="codebase",
        entry_key="k",
        section="domain_constants",
        reason="budget@cycle=1,priority=0.400",
    )
    assert event.materialization_count == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_events.py -v`
Expected: FAIL with `ImportError: cannot import name 'MapEntryReferenced'`.

- [ ] **Step 4: Implement the event changes**

Edit `harness_poc/core/events/context_map_events.py`. Add the `materialization_count` field to `MapEntryEvicted` and add `MapEntryReferenced`. Replace the existing `MapEntryEvicted` class and the `CONTEXT_MAP_EVENT_REGISTRY` block with the following:

```python
class MapEntryEvicted(ContextMapEvent):
    event_type: Literal["map_entry_evicted"] = "map_entry_evicted"
    entry_id: str | None = None
    entry_key: str
    section: str
    reason: str  # Structured: "stale@cycle=N,age=M,type=X" or "budget@cycle=N,priority=P"
    materialization_count: int = 0


class MapEntryReferenced(ContextMapEvent):
    """Emitted (by a future wiring spec) when the agent's response cites a map entry.

    Defined here so the schema is stable; emission lives elsewhere.
    """

    event_type: Literal["map_entry_referenced"] = "map_entry_referenced"
    entry_id: str
    entry_key: str
    section: str
    cycle_n: int
    citation_context: str  # Snippet of agent output that cited the entry


CONTEXT_MAP_EVENT_REGISTRY: dict[str, type[ContextMapEvent]] = {
    "corpus_ingested": CorpusIngested,
    "document_retrieved": DocumentRetrieved,
    "entity_referenced": EntityReferenced,
    "schema_discovered": SchemaDiscovered,
    "search_failed": SearchFailed,
    "fact_disputed": FactDisputed,
    "contextual_insight_discovered": ContextualInsightDiscovered,
    "map_entry_promoted": MapEntryPromoted,
    "map_entry_evicted": MapEntryEvicted,
    "map_entry_referenced": MapEntryReferenced,
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/context_map/test_events.py -v`
Expected: 4 passed.

- [ ] **Step 6: Lint & type-check**

Run: `uv run ruff check harness_poc/core/events/context_map_events.py tests/context_map/test_events.py && uv run ty check harness_poc/core/events/context_map_events.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/events/context_map_events.py tests/context_map/__init__.py tests/context_map/test_events.py
git commit -m "feat(context-map): add MapEntryReferenced event; widen MapEntryEvicted"
```

---

## Task 2: Section assignment table

**Files:**
- Create: `harness_poc/core/context_map/__init__.py`
- Create: `harness_poc/core/context_map/sections.py`
- Test: `tests/context_map/test_sections.py`

- [ ] **Step 1: Create empty package marker**

Create `harness_poc/core/context_map/__init__.py` with the single line:

```python
"""Deterministic Cartographer + Distiller package (see docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md)."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/context_map/test_sections.py`:

```python
from __future__ import annotations

import pytest

from harness_poc.core.context_map.sections import SECTION_MAP, assign_section


def test_section_map_covers_all_seven_observation_types() -> None:
    assert set(SECTION_MAP.keys()) == {
        "entity",
        "schema",
        "insight",
        "dispute",
        "boundary",
        "constant",
        "result",
    }


def test_section_assignments_match_design() -> None:
    assert assign_section("schema") == "parsing_schema"
    assert assign_section("entity") == "context_understanding"
    assert assign_section("boundary") == "context_understanding"
    assert assign_section("insight") == "context_roadmap"
    assert assign_section("dispute") == "context_roadmap"
    assert assign_section("constant") == "domain_constants"
    assert assign_section("result") == "reusable_results"


def test_assign_section_rejects_unknown() -> None:
    with pytest.raises(KeyError, match="unknown observation_type"):
        assign_section("does-not-exist")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_sections.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness_poc.core.context_map.sections'`.

- [ ] **Step 4: Implement `sections.py`**

Create `harness_poc/core/context_map/sections.py`:

```python
"""Deterministic observation_type → section mapping (no LLM judgment)."""

from __future__ import annotations

SECTION_MAP: dict[str, str] = {
    "schema": "parsing_schema",
    "entity": "context_understanding",
    "boundary": "context_understanding",
    "insight": "context_roadmap",
    "dispute": "context_roadmap",
    "constant": "domain_constants",
    "result": "reusable_results",
}


def assign_section(observation_type: str) -> str:
    """Return the section name for a given observation_type.

    Raises KeyError with a descriptive message on unknown types.
    """
    try:
        return SECTION_MAP[observation_type]
    except KeyError as exc:
        msg = f"unknown observation_type: {observation_type!r}"
        raise KeyError(msg) from exc
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/context_map/test_sections.py -v`
Expected: 3 passed.

- [ ] **Step 6: Lint & type-check**

Run: `uv run ruff check harness_poc/core/context_map tests/context_map/test_sections.py && uv run ty check harness_poc/core/context_map`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/context_map/__init__.py harness_poc/core/context_map/sections.py tests/context_map/test_sections.py
git commit -m "feat(context-map): add deterministic section assignment table"
```

---

## Task 3: Pydantic schemas (`DistillerEntry`, `MapEntry`, `DistilledBatch`, `EvictionRecord`, `CartographerResult`)

**Files:**
- Create: `harness_poc/core/context_map/schema.py`
- Test: `tests/context_map/test_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/context_map/test_schema.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from harness_poc.core.context_map.schema import (
    CartographerResult,
    DistilledBatch,
    DistillerEntry,
    EvictionRecord,
    MapEntry,
)


def _now() -> datetime:
    return datetime(2026, 5, 23, tzinfo=UTC)


def test_distiller_entry_round_trip() -> None:
    entry = DistillerEntry(
        key="codebase-entry-point",
        observation_type="entity",
        summary="The repl is the primary entry point.",
        source_event_ids=["ev-1"],
        tags=["novel"],
    )
    dumped = entry.model_dump()
    revived = DistillerEntry.model_validate(dumped)
    assert revived == entry


def test_distiller_entry_requires_at_least_one_source_event() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry(
            key="k",
            observation_type="entity",
            summary="s",
            source_event_ids=[],
        )


def test_distiller_entry_forbids_section_field() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry.model_validate(
            {
                "key": "k",
                "observation_type": "entity",
                "summary": "s",
                "source_event_ids": ["ev-1"],
                "section": "context_understanding",
            }
        )


def test_distiller_entry_forbids_priority_field() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry.model_validate(
            {
                "key": "k",
                "observation_type": "entity",
                "summary": "s",
                "source_event_ids": ["ev-1"],
                "priority": 0.9,
            }
        )


def test_distiller_entry_rejects_unknown_observation_type() -> None:
    with pytest.raises(ValidationError):
        DistillerEntry.model_validate(
            {
                "key": "k",
                "observation_type": "mystery",
                "summary": "s",
                "source_event_ids": ["ev-1"],
            }
        )


def test_distilled_batch_round_trip() -> None:
    batch = DistilledBatch(
        entries=[
            DistillerEntry(
                key="k1",
                observation_type="schema",
                summary="s",
                source_event_ids=["ev-1"],
            )
        ]
    )
    revived = DistilledBatch.model_validate(batch.model_dump())
    assert revived == batch


def test_map_entry_round_trip() -> None:
    entry = MapEntry(
        entry_id="uuid-1",
        key="k",
        section="context_understanding",
        observation_type="entity",
        summary="s",
        priority=0.6,
        source_event_ids=["ev-1"],
        first_seen=_now(),
        last_updated=_now(),
        materialization_count=1,
        first_seen_cycle=0,
        last_seen_cycle=0,
        token_estimate=5,
    )
    revived = MapEntry.model_validate(entry.model_dump())
    assert revived == entry


def test_cartographer_result_holds_evictions() -> None:
    result = CartographerResult(
        new_map=[],
        evictions=[
            EvictionRecord(
                entry_id="uuid-2",
                key="old",
                section="context_understanding",
                observation_type="entity",
                materialization_count=3,
                reason="stale@cycle=5,age=8,type=entity",
            )
        ],
        cycle_n=5,
    )
    assert result.cycle_n == 5
    assert result.evictions[0].reason.startswith("stale@")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `schema.py`**

Create `harness_poc/core/context_map/schema.py`:

```python
"""Pydantic schemas for the Distiller → Cartographer pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ObservationType = Literal[
    "entity",
    "schema",
    "insight",
    "dispute",
    "boundary",
    "constant",
    "result",
]
Tag = Literal["confirmed", "novel", "correcting"]


class DistillerEntry(BaseModel):
    """A single observation emitted by the Distiller LLM call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(..., description="Stable slug, e.g. 'codebase-entry-point'")
    observation_type: ObservationType
    summary: str = Field(..., description="One-paragraph orientation fact")
    source_event_ids: list[str] = Field(..., min_length=1)
    tags: list[Tag] = Field(default_factory=list)


class DistilledBatch(BaseModel):
    """Top-level output_type passed to the Distiller agent."""

    model_config = ConfigDict(extra="forbid")

    entries: list[DistillerEntry]


class MapEntry(BaseModel):
    """A materialized context-map row."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    key: str
    section: str
    observation_type: ObservationType
    summary: str
    priority: float
    source_event_ids: list[str]
    first_seen: datetime
    last_updated: datetime
    materialization_count: int = 0
    first_seen_cycle: int
    last_seen_cycle: int
    token_estimate: int


class EvictionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str
    key: str
    section: str
    observation_type: ObservationType
    materialization_count: int
    reason: str  # Structured: see schema doc


class CartographerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_map: list[MapEntry]
    evictions: list[EvictionRecord]
    cycle_n: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/context_map/test_schema.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint & type-check**

Run: `uv run ruff check harness_poc/core/context_map/schema.py tests/context_map/test_schema.py && uv run ty check harness_poc/core/context_map/schema.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/context_map/schema.py tests/context_map/test_schema.py
git commit -m "feat(context-map): add DistillerEntry/MapEntry/CartographerResult schemas"
```

---

## Task 4: Config blocks + `harness.yaml`

**Files:**
- Create: `harness_poc/core/context_map/config.py`
- Modify: `harness_poc/core/config.py`
- Modify: `harness.yaml`
- Test: `tests/context_map/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/context_map/test_config.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness_poc.core.config import HarnessConfig
from harness_poc.core.context_map.config import (
    CartographerConfig,
    DistillerConfig,
    load_cartographer_config,
    load_distiller_config,
)


def test_distiller_config_defaults() -> None:
    cfg = load_distiller_config({})
    assert cfg.model is None
    assert cfg.max_retries == 3
    assert cfg.prompt_template == "distiller_v1"


def test_distiller_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown distiller config key"):
        load_distiller_config({"banana": True})


def test_cartographer_config_defaults() -> None:
    cfg = load_cartographer_config({})
    assert cfg.token_budget == 1024
    assert cfg.tokenizer_name == "cl100k_base"
    assert cfg.recency_bonus == pytest.approx(0.01)
    assert cfg.recency_cap == pytest.approx(0.5)
    assert cfg.staleness_penalty == pytest.approx(0.05)
    assert cfg.staleness_floor == pytest.approx(0.2)
    assert cfg.priority_weights["dispute"] == pytest.approx(1.0)
    assert cfg.priority_weights["constant"] == pytest.approx(0.4)


def test_cartographer_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown cartographer config key"):
        load_cartographer_config({"mystery": 1})


def test_cartographer_config_requires_all_seven_weights() -> None:
    with pytest.raises(ValueError, match="priority_weights missing"):
        load_cartographer_config({"priority_weights": {"dispute": 1.0}})


def test_harness_config_loads_cartographer_and_distiller(tmp_path: Path) -> None:
    config_path = tmp_path / "harness.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "llm": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                "runtime": {
                    "database_url": "sqlite:///x.db",
                    "default_container_image": "python:3.14-slim",
                },
                "observability": {"logfire": False},
                "distiller": {"model": "anthropic/claude-haiku-4-5"},
                "cartographer": {"token_budget": 2048},
            }
        )
    )
    cfg = HarnessConfig.load(config_path)
    assert cfg.distiller.model == "anthropic/claude-haiku-4-5"
    assert cfg.cartographer.token_budget == 2048
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError` on `harness_poc.core.context_map.config`.

- [ ] **Step 3: Implement `context_map/config.py`**

Create `harness_poc/core/context_map/config.py`:

```python
"""Config blocks for Distiller + deterministic Cartographer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_DEFAULT_PRIORITY_WEIGHTS: dict[str, float] = {
    "dispute": 1.0,
    "schema": 0.9,
    "insight": 0.8,
    "boundary": 0.7,
    "entity": 0.6,
    "result": 0.5,
    "constant": 0.4,
}

_REQUIRED_WEIGHT_KEYS = frozenset(_DEFAULT_PRIORITY_WEIGHTS.keys())

_DISTILLER_KNOWN_KEYS = frozenset({"model", "max_retries", "prompt_template"})

_CARTOGRAPHER_KNOWN_KEYS = frozenset(
    {
        "token_budget",
        "tokenizer_name",
        "recency_bonus",
        "recency_cap",
        "staleness_penalty",
        "staleness_floor",
        "priority_weights",
    }
)


@dataclass(frozen=True, slots=True)
class DistillerConfig:
    model: str | None = None  # None → fall back to HarnessConfig.llm
    max_retries: int = 3
    prompt_template: str = "distiller_v1"


@dataclass(frozen=True, slots=True)
class CartographerConfig:
    token_budget: int = 1024
    tokenizer_name: str = "cl100k_base"
    recency_bonus: float = 0.01
    recency_cap: float = 0.5
    staleness_penalty: float = 0.05
    staleness_floor: float = 0.2
    priority_weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_PRIORITY_WEIGHTS)
    )


def load_distiller_config(raw: dict[str, Any]) -> DistillerConfig:
    unknown = set(raw) - _DISTILLER_KNOWN_KEYS
    if unknown:
        msg = f"unknown distiller config key(s): {sorted(unknown)}"
        raise ValueError(msg)
    return DistillerConfig(
        model=raw.get("model"),
        max_retries=int(raw.get("max_retries", 3)),
        prompt_template=str(raw.get("prompt_template", "distiller_v1")),
    )


def load_cartographer_config(raw: dict[str, Any]) -> CartographerConfig:
    unknown = set(raw) - _CARTOGRAPHER_KNOWN_KEYS
    if unknown:
        msg = f"unknown cartographer config key(s): {sorted(unknown)}"
        raise ValueError(msg)

    weights_raw = raw.get("priority_weights")
    if weights_raw is None:
        weights = dict(_DEFAULT_PRIORITY_WEIGHTS)
    else:
        if not isinstance(weights_raw, dict):
            msg = "cartographer.priority_weights must be a mapping"
            raise TypeError(msg)
        missing = _REQUIRED_WEIGHT_KEYS - set(weights_raw)
        if missing:
            msg = f"priority_weights missing key(s): {sorted(missing)}"
            raise ValueError(msg)
        weights = {k: float(weights_raw[k]) for k in _REQUIRED_WEIGHT_KEYS}

    return CartographerConfig(
        token_budget=int(raw.get("token_budget", 1024)),
        tokenizer_name=str(raw.get("tokenizer_name", "cl100k_base")),
        recency_bonus=float(raw.get("recency_bonus", 0.01)),
        recency_cap=float(raw.get("recency_cap", 0.5)),
        staleness_penalty=float(raw.get("staleness_penalty", 0.05)),
        staleness_floor=float(raw.get("staleness_floor", 0.2)),
        priority_weights=weights,
    )
```

- [ ] **Step 4: Wire into `HarnessConfig`**

Edit `harness_poc/core/config.py`:

(a) Add import below the existing dataclass imports:

```python
from harness_poc.core.context_map.config import (
    CartographerConfig,
    DistillerConfig,
    load_cartographer_config,
    load_distiller_config,
)
```

(b) Add two fields to `HarnessConfig` (between `tui` and `project_id`):

```python
    distiller: DistillerConfig = field(default_factory=DistillerConfig)
    cartographer: CartographerConfig = field(default_factory=CartographerConfig)
```

(c) In `HarnessConfig.load`, after the `tui` block and before the `project_raw` block, add:

```python
        distiller_raw = _mapping(raw.get("distiller"), "distiller")
        distiller_cfg = load_distiller_config(distiller_raw)

        cartographer_raw = _mapping(raw.get("cartographer"), "cartographer")
        cartographer_cfg = load_cartographer_config(cartographer_raw)
```

(d) Pass them into `cls(...)`:

```python
        return cls(
            project_root=project_root,
            config_path=resolved_config_path,
            paths=paths,
            llm=llm,
            runtime=runtime,
            observability=observability,
            retrieval=retrieval,
            tui=tui,
            distiller=distiller_cfg,
            cartographer=cartographer_cfg,
            project_id=project_id,
        )
```

- [ ] **Step 5: Add defaults to `harness.yaml`**

Append to `harness.yaml`:

```yaml
distiller:
  model: anthropic/claude-haiku-4-5
  max_retries: 3
  prompt_template: distiller_v1

cartographer:
  token_budget: 1024
  tokenizer_name: cl100k_base
  recency_bonus: 0.01
  recency_cap: 0.5
  staleness_penalty: 0.05
  staleness_floor: 0.2
  priority_weights:
    dispute: 1.0
    schema: 0.9
    insight: 0.8
    boundary: 0.7
    entity: 0.6
    result: 0.5
    constant: 0.4
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/context_map/test_config.py -v`
Expected: 6 passed.

- [ ] **Step 7: Run the full existing config test suite as regression guard**

Run: `uv run pytest tests -k "config" -v`
Expected: all pass (no regressions in `HarnessConfig.load`).

- [ ] **Step 8: Lint & type-check**

Run: `uv run ruff check harness_poc/core/config.py harness_poc/core/context_map/config.py tests/context_map/test_config.py && uv run ty check harness_poc/core/config.py harness_poc/core/context_map/config.py`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add harness_poc/core/context_map/config.py harness_poc/core/config.py harness.yaml tests/context_map/test_config.py
git commit -m "feat(context-map): add DistillerConfig and CartographerConfig"
```

---

## Task 5: Cartographer — dedup & merge (Operation 1)

**Files:**
- Create: `harness_poc/core/context_map/cartographer.py`
- Test: `tests/context_map/test_cartographer_dedup.py`

The cartographer is built incrementally across Tasks 5–8. Each task adds one operation and its tests.

- [ ] **Step 1: Write the failing test**

Create `tests/context_map/test_cartographer_dedup.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry, MapEntry


def _entry(
    key: str,
    obs_type: str = "entity",
    summary: str = "s",
    ids: tuple[str, ...] = ("ev-1",),
) -> DistillerEntry:
    return DistillerEntry(
        key=key,
        observation_type=obs_type,  # type: ignore[arg-type]
        summary=summary,
        source_event_ids=list(ids),
    )


def _config() -> CartographerConfig:
    # Use a huge budget so dedup tests are not affected by eviction.
    return CartographerConfig(token_budget=10_000)


def test_new_key_inserts_fresh_map_entry() -> None:
    distilled = [_entry("k1")]
    result = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=1,
        config=_config(),
    )
    assert len(result.new_map) == 1
    entry = result.new_map[0]
    assert entry.key == "k1"
    assert entry.materialization_count == 1
    assert entry.first_seen_cycle == 1
    assert entry.last_seen_cycle == 1
    assert entry.entry_id  # non-empty UUID


def test_existing_key_with_newer_events_replaces_summary_and_keeps_entry_id() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k1", summary="old", ids=("ev-1",))],
        current_map=[],
        cycle_n=1,
        config=_config(),
    )
    original = seed.new_map[0]

    result = deterministic_cartographer(
        distilled=[_entry("k1", summary="new", ids=("ev-1", "ev-2"))],
        current_map=seed.new_map,
        cycle_n=2,
        config=_config(),
    )
    updated = next(e for e in result.new_map if e.key == "k1")
    assert updated.entry_id == original.entry_id  # stable
    assert updated.first_seen == original.first_seen  # stable
    assert updated.summary == "new"
    assert updated.source_event_ids == ["ev-1", "ev-2"]
    assert updated.materialization_count == 2
    assert updated.last_seen_cycle == 2


def test_existing_key_with_subset_events_is_noop_but_credits_survival() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k1", summary="orig", ids=("ev-1", "ev-2"))],
        current_map=[],
        cycle_n=1,
        config=_config(),
    )

    result = deterministic_cartographer(
        distilled=[_entry("k1", summary="should-not-overwrite", ids=("ev-1",))],
        current_map=seed.new_map,
        cycle_n=2,
        config=_config(),
    )
    updated = next(e for e in result.new_map if e.key == "k1")
    assert updated.summary == "orig"  # unchanged
    assert updated.source_event_ids == ["ev-1", "ev-2"]  # unchanged
    assert updated.materialization_count == 2  # credited
    assert updated.last_seen_cycle == 2


def test_missing_distilled_entries_keep_existing_map_entries() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k1"), _entry("k2")],
        current_map=[],
        cycle_n=1,
        config=_config(),
    )

    result = deterministic_cartographer(
        distilled=[_entry("k1")],
        current_map=seed.new_map,
        cycle_n=2,
        config=_config(),
    )
    keys = {e.key for e in result.new_map}
    assert keys == {"k1", "k2"}  # k2 carried forward
    k2 = next(e for e in result.new_map if e.key == "k2")
    assert k2.last_seen_cycle == 1  # not bumped — wasn't in this cycle's distilled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_cartographer_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `cartographer.py` with dedup only**

Create `harness_poc/core/context_map/cartographer.py`:

```python
"""Deterministic Cartographer — pure function, no I/O, no clock."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Sequence

import tiktoken

from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import (
    CartographerResult,
    DistillerEntry,
    EvictionRecord,
    MapEntry,
)
from harness_poc.core.context_map.sections import assign_section


def deterministic_cartographer(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
    *,
    now: datetime | None = None,
) -> CartographerResult:
    """Run dedup → priority → staleness → budget. Pure function."""
    timestamp = now or datetime.now(tz=UTC)
    working = _dedup_and_merge(distilled, current_map, cycle_n, config, timestamp)
    # Priority, staleness, budget added in later tasks.
    return CartographerResult(new_map=working, evictions=[], cycle_n=cycle_n)


def _dedup_and_merge(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
    now: datetime,
) -> list[MapEntry]:
    by_key: dict[str, MapEntry] = {e.key: e for e in current_map}

    for d in distilled:
        existing = by_key.get(d.key)
        if existing is None:
            by_key[d.key] = _new_map_entry(d, cycle_n, config, now)
            continue

        if _is_strict_superset(d.source_event_ids, existing.source_event_ids):
            by_key[d.key] = existing.model_copy(
                update={
                    "summary": d.summary,
                    "source_event_ids": list(d.source_event_ids),
                    "last_updated": now,
                    "materialization_count": existing.materialization_count + 1,
                    "last_seen_cycle": cycle_n,
                    "token_estimate": _estimate_tokens(d.summary, config.tokenizer_name),
                }
            )
        else:
            by_key[d.key] = existing.model_copy(
                update={
                    "materialization_count": existing.materialization_count + 1,
                    "last_seen_cycle": cycle_n,
                }
            )

    return list(by_key.values())


def _new_map_entry(
    d: DistillerEntry,
    cycle_n: int,
    config: CartographerConfig,
    now: datetime,
) -> MapEntry:
    base_priority = config.priority_weights[d.observation_type]
    return MapEntry(
        entry_id=str(uuid.uuid4()),
        key=d.key,
        section=assign_section(d.observation_type),
        observation_type=d.observation_type,
        summary=d.summary,
        priority=base_priority,
        source_event_ids=list(d.source_event_ids),
        first_seen=now,
        last_updated=now,
        materialization_count=1,
        first_seen_cycle=cycle_n,
        last_seen_cycle=cycle_n,
        token_estimate=_estimate_tokens(d.summary, config.tokenizer_name),
    )


def _is_strict_superset(new_ids: Sequence[str], existing_ids: Sequence[str]) -> bool:
    new_set, existing_set = set(new_ids), set(existing_ids)
    return new_set != existing_set and existing_set.issubset(new_set)


@lru_cache(maxsize=4)
def _get_encoder(tokenizer_name: str) -> tiktoken.Encoding:
    return tiktoken.get_encoding(tokenizer_name)


def _estimate_tokens(text: str, tokenizer_name: str) -> int:
    return len(_get_encoder(tokenizer_name).encode(text))
```

- [ ] **Step 4: Run dedup tests to verify they pass**

Run: `uv run pytest tests/context_map/test_cartographer_dedup.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint & type-check**

Run: `uv run ruff check harness_poc/core/context_map/cartographer.py tests/context_map/test_cartographer_dedup.py && uv run ty check harness_poc/core/context_map/cartographer.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/context_map/cartographer.py tests/context_map/test_cartographer_dedup.py
git commit -m "feat(context-map): cartographer dedup & merge"
```

---

## Task 6: Cartographer — priority scoring (Operation 2)

**Files:**
- Modify: `harness_poc/core/context_map/cartographer.py`
- Test: `tests/context_map/test_cartographer_priority.py`

- [ ] **Step 1: Write the failing test**

Create `tests/context_map/test_cartographer_priority.py`:

```python
from __future__ import annotations

import pytest

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry


def _entry(key: str, obs_type: str) -> DistillerEntry:
    return DistillerEntry(
        key=key,
        observation_type=obs_type,  # type: ignore[arg-type]
        summary="summary text",
        source_event_ids=[f"ev-{key}"],
    )


def _config(**overrides: object) -> CartographerConfig:
    defaults = {
        "token_budget": 10_000,
        "recency_bonus": 0.01,
        "recency_cap": 0.5,
        "staleness_penalty": 0.05,
        "staleness_floor": 0.0,  # disable eviction in priority-only tests
    }
    defaults.update(overrides)
    return CartographerConfig(**defaults)  # type: ignore[arg-type]


def test_priority_for_fresh_entry_equals_base_weight() -> None:
    result = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    assert result.new_map[0].priority == pytest.approx(0.6)


def test_priority_uses_per_type_weights() -> None:
    result = deterministic_cartographer(
        distilled=[_entry("k", "dispute")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    assert result.new_map[0].priority == pytest.approx(1.0)


def test_recency_bonus_accumulates_with_age() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    result = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=seed.new_map,
        cycle_n=10,
        config=_config(),
    )
    # base 0.6 + (10 - 0) * 0.01 = 0.70
    assert result.new_map[0].priority == pytest.approx(0.70)


def test_recency_bonus_is_capped() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(recency_cap=0.05),
    )
    result = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=seed.new_map,
        cycle_n=100,
        config=_config(recency_cap=0.05),
    )
    # base 0.6 + min(0.05, 100 * 0.01) = 0.65
    assert result.new_map[0].priority == pytest.approx(0.65)


def test_staleness_penalty_reduces_priority_for_missed_cycles() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "entity")],
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    result = deterministic_cartographer(
        distilled=[],  # k is not refreshed this cycle
        current_map=seed.new_map,
        cycle_n=4,
        config=_config(),
    )
    # base 0.6 + (4-0)*0.01 - (4-0)*0.05 = 0.6 + 0.04 - 0.20 = 0.44
    assert result.new_map[0].priority == pytest.approx(0.44)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_cartographer_priority.py -v`
Expected: FAIL — priorities will equal base weights (no recency / staleness applied yet).

- [ ] **Step 3: Add priority scoring to `cartographer.py`**

Edit `harness_poc/core/context_map/cartographer.py`. Replace the body of `deterministic_cartographer` with:

```python
def deterministic_cartographer(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
    *,
    now: datetime | None = None,
) -> CartographerResult:
    """Run dedup → priority → staleness → budget. Pure function."""
    timestamp = now or datetime.now(tz=UTC)
    working = _dedup_and_merge(distilled, current_map, cycle_n, config, timestamp)
    working = [_apply_priority(e, cycle_n, config) for e in working]
    # Staleness and budget added in later tasks.
    return CartographerResult(new_map=working, evictions=[], cycle_n=cycle_n)
```

Then add this helper at the end of the module:

```python
def _apply_priority(
    entry: MapEntry,
    cycle_n: int,
    config: CartographerConfig,
) -> MapEntry:
    base = config.priority_weights[entry.observation_type]
    age = max(0, cycle_n - entry.first_seen_cycle)
    raw_recency = age * config.recency_bonus
    recency = min(raw_recency, config.recency_cap)
    missed = max(0, cycle_n - entry.last_seen_cycle)
    penalty = missed * config.staleness_penalty
    priority = base + recency - penalty
    return entry.model_copy(update={"priority": priority})
```

- [ ] **Step 4: Run priority tests**

Run: `uv run pytest tests/context_map/test_cartographer_priority.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run dedup regression**

Run: `uv run pytest tests/context_map/test_cartographer_dedup.py -v`
Expected: 4 passed.

- [ ] **Step 6: Lint & type-check**

Run: `uv run ruff check harness_poc/core/context_map/cartographer.py tests/context_map/test_cartographer_priority.py && uv run ty check harness_poc/core/context_map/cartographer.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/context_map/cartographer.py tests/context_map/test_cartographer_priority.py
git commit -m "feat(context-map): cartographer priority scoring with recency cap"
```

---

## Task 7: Cartographer — staleness eviction (Operation 3)

**Files:**
- Modify: `harness_poc/core/context_map/cartographer.py`
- Test: `tests/context_map/test_cartographer_eviction.py`

- [ ] **Step 1: Write the failing test (staleness portion)**

Create `tests/context_map/test_cartographer_eviction.py`:

```python
from __future__ import annotations

import pytest

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry


def _entry(key: str, obs_type: str = "entity", summary: str = "s") -> DistillerEntry:
    return DistillerEntry(
        key=key,
        observation_type=obs_type,  # type: ignore[arg-type]
        summary=summary,
        source_event_ids=[f"ev-{key}"],
    )


def _config(**overrides: object) -> CartographerConfig:
    defaults = {
        "token_budget": 10_000,
        "recency_bonus": 0.0,  # disable for clarity
        "recency_cap": 0.0,
        "staleness_penalty": 0.1,
        "staleness_floor": 0.2,
    }
    defaults.update(overrides)
    return CartographerConfig(**defaults)  # type: ignore[arg-type]


def test_entry_below_staleness_floor_is_evicted() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "constant")],  # base 0.4
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    # After 3 missed cycles: 0.4 - 3 * 0.1 = 0.1 < 0.2 → evict
    result = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=3,
        config=_config(),
    )
    assert result.new_map == []
    assert len(result.evictions) == 1
    eviction = result.evictions[0]
    assert eviction.key == "k"
    assert eviction.observation_type == "constant"
    assert eviction.reason == "stale@cycle=3,age=3,type=constant"


def test_entry_above_staleness_floor_survives() -> None:
    seed = deterministic_cartographer(
        distilled=[_entry("k", "dispute")],  # base 1.0
        current_map=[],
        cycle_n=0,
        config=_config(),
    )
    # After 3 missed cycles: 1.0 - 3 * 0.1 = 0.7 > 0.2 → survive
    result = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=3,
        config=_config(),
    )
    assert len(result.new_map) == 1
    assert result.evictions == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_cartographer_eviction.py -v`
Expected: FAIL — stale entry still present, no evictions emitted.

- [ ] **Step 3: Add staleness eviction**

Edit `harness_poc/core/context_map/cartographer.py`. Update `deterministic_cartographer`:

```python
def deterministic_cartographer(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
    *,
    now: datetime | None = None,
) -> CartographerResult:
    """Run dedup → priority → staleness → budget. Pure function."""
    timestamp = now or datetime.now(tz=UTC)
    working = _dedup_and_merge(distilled, current_map, cycle_n, config, timestamp)
    working = [_apply_priority(e, cycle_n, config) for e in working]
    working, stale_evictions = _evict_stale(working, cycle_n, config)
    # Budget eviction added in Task 8.
    return CartographerResult(
        new_map=working,
        evictions=stale_evictions,
        cycle_n=cycle_n,
    )
```

Add this helper at the end of the module:

```python
def _evict_stale(
    entries: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
) -> tuple[list[MapEntry], list[EvictionRecord]]:
    survivors: list[MapEntry] = []
    evictions: list[EvictionRecord] = []
    for entry in entries:
        if entry.priority < config.staleness_floor:
            age = cycle_n - entry.last_seen_cycle
            evictions.append(
                EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"stale@cycle={cycle_n},age={age},type={entry.observation_type}",
                )
            )
        else:
            survivors.append(entry)
    return survivors, evictions
```

- [ ] **Step 4: Run staleness tests**

Run: `uv run pytest tests/context_map/test_cartographer_eviction.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run regression for prior cartographer tests**

Run: `uv run pytest tests/context_map -v`
Expected: all prior tests still pass.

- [ ] **Step 6: Lint & type-check**

Run: `uv run ruff check harness_poc/core/context_map/cartographer.py tests/context_map/test_cartographer_eviction.py && uv run ty check harness_poc/core/context_map/cartographer.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/context_map/cartographer.py tests/context_map/test_cartographer_eviction.py
git commit -m "feat(context-map): cartographer staleness eviction"
```

---

## Task 8: Cartographer — budget enforcement (Operation 4)

**Files:**
- Modify: `harness_poc/core/context_map/cartographer.py`
- Modify: `tests/context_map/test_cartographer_eviction.py`

- [ ] **Step 1: Add budget tests to the existing eviction test file**

Append to `tests/context_map/test_cartographer_eviction.py`:

```python
def test_budget_eviction_trims_lowest_priority_tail() -> None:
    # Two entries of equal observation_type → equal base priority,
    # but only one fits in a tight token budget.
    distilled = [
        DistillerEntry(
            key="keeps",
            observation_type="dispute",  # base 1.0
            summary="kept summary",
            source_event_ids=["ev-a"],
        ),
        DistillerEntry(
            key="drops",
            observation_type="constant",  # base 0.4
            summary="dropped summary",
            source_event_ids=["ev-b"],
        ),
    ]
    config = CartographerConfig(
        token_budget=3,  # one short summary fits, not both
        recency_bonus=0.0,
        recency_cap=0.0,
        staleness_penalty=0.0,
        staleness_floor=0.0,
    )
    result = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=config,
    )
    survivor_keys = [e.key for e in result.new_map]
    assert survivor_keys == ["keeps"]
    assert len(result.evictions) == 1
    eviction = result.evictions[0]
    assert eviction.key == "drops"
    assert eviction.reason.startswith("budget@cycle=0,priority=")


def test_budget_eviction_tie_breaks_deterministically() -> None:
    # Two entries with identical priority — tie-break by last_updated desc,
    # then entry_id asc. With identical insertion in one cycle, last_updated
    # is identical, so entry_id order determines outcome.
    distilled = [
        DistillerEntry(
            key=f"k{i}",
            observation_type="entity",
            summary="x",
            source_event_ids=[f"ev-{i}"],
        )
        for i in range(3)
    ]
    config = CartographerConfig(
        token_budget=2,  # only ~2 tokens worth survive
        recency_bonus=0.0,
        recency_cap=0.0,
        staleness_penalty=0.0,
        staleness_floor=0.0,
    )
    result_a = deterministic_cartographer(
        distilled=list(distilled),
        current_map=[],
        cycle_n=0,
        config=config,
    )
    result_b = deterministic_cartographer(
        distilled=list(distilled),
        current_map=[],
        cycle_n=0,
        config=config,
    )
    # Survivor set may differ across runs because entry_ids are random UUIDs;
    # the deterministic guarantee is only over IDENTICAL inputs, which includes
    # current_map. Reuse the seed map to verify stable tie-break.
    seed = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=CartographerConfig(token_budget=10_000),  # no eviction
    )
    again_a = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=1,
        config=config,
    )
    again_b = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=1,
        config=config,
    )
    assert [e.entry_id for e in again_a.new_map] == [e.entry_id for e in again_b.new_map]
    assert [e.entry_id for e in again_a.evictions] == [e.entry_id for e in again_b.evictions]
```

Also add the imports at the top of the file (if not already present):

```python
from harness_poc.core.context_map.schema import DistillerEntry
```

(Already present from Task 7 — verify before editing.)

- [ ] **Step 2: Run new tests to verify they fail**

Run: `uv run pytest tests/context_map/test_cartographer_eviction.py -v`
Expected: FAIL on the new tests — budget logic absent.

- [ ] **Step 3: Add budget enforcement**

Edit `harness_poc/core/context_map/cartographer.py`. Update `deterministic_cartographer`:

```python
def deterministic_cartographer(
    distilled: Sequence[DistillerEntry],
    current_map: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
    *,
    now: datetime | None = None,
) -> CartographerResult:
    """Run dedup → priority → staleness → budget. Pure function.

    Pure: identical (distilled, current_map, cycle_n, config) → identical result,
    given identical now (or a stable clock supplied by the caller).
    """
    timestamp = now or datetime.now(tz=UTC)
    working = _dedup_and_merge(distilled, current_map, cycle_n, config, timestamp)
    working = [_apply_priority(e, cycle_n, config) for e in working]
    working, stale_evictions = _evict_stale(working, cycle_n, config)
    working, budget_evictions = _enforce_budget(working, cycle_n, config)
    return CartographerResult(
        new_map=working,
        evictions=[*stale_evictions, *budget_evictions],
        cycle_n=cycle_n,
    )
```

Add this helper at the end of the module:

```python
def _enforce_budget(
    entries: Sequence[MapEntry],
    cycle_n: int,
    config: CartographerConfig,
) -> tuple[list[MapEntry], list[EvictionRecord]]:
    # Sort desc by priority, then desc by last_updated, then asc by entry_id.
    ordered = sorted(
        entries,
        key=lambda e: (-e.priority, -e.last_updated.timestamp(), e.entry_id),
    )
    survivors: list[MapEntry] = []
    evicted: list[EvictionRecord] = []
    used = 0
    for entry in ordered:
        if used + entry.token_estimate <= config.token_budget:
            survivors.append(entry)
            used += entry.token_estimate
        else:
            evicted.append(
                EvictionRecord(
                    entry_id=entry.entry_id,
                    key=entry.key,
                    section=entry.section,
                    observation_type=entry.observation_type,
                    materialization_count=entry.materialization_count,
                    reason=f"budget@cycle={cycle_n},priority={entry.priority:.3f}",
                )
            )
    return survivors, evicted
```

- [ ] **Step 4: Run all cartographer tests**

Run: `uv run pytest tests/context_map -v`
Expected: all passing (events + sections + schema + config + dedup + priority + eviction).

- [ ] **Step 5: Lint & type-check**

Run: `uv run ruff check harness_poc/core/context_map tests/context_map && uv run ty check harness_poc/core/context_map`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add harness_poc/core/context_map/cartographer.py tests/context_map/test_cartographer_eviction.py
git commit -m "feat(context-map): cartographer budget enforcement with stable tie-break"
```

---

## Task 9: Determinism + invariants tests

**Files:**
- Create: `tests/context_map/test_cartographer_determinism.py`
- Create: `tests/context_map/test_cartographer_invariants.py`

- [ ] **Step 1: Write the determinism test**

Create `tests/context_map/test_cartographer_determinism.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry, MapEntry


def _entries() -> list[DistillerEntry]:
    return [
        DistillerEntry(
            key=f"k{i}",
            observation_type=t,  # type: ignore[arg-type]
            summary=f"summary {i} for type {t}",
            source_event_ids=[f"ev-{i}"],
        )
        for i, t in enumerate(
            ["entity", "schema", "insight", "dispute", "boundary", "constant", "result"]
        )
    ]


def _config() -> CartographerConfig:
    return CartographerConfig(token_budget=200)


def _seed_map() -> tuple[list[MapEntry], datetime]:
    fixed_now = datetime(2026, 5, 23, tzinfo=UTC)
    seed = deterministic_cartographer(
        distilled=_entries(),
        current_map=[],
        cycle_n=0,
        config=_config(),
        now=fixed_now,
    )
    return seed.new_map, fixed_now


def test_identical_inputs_produce_identical_output_json() -> None:
    current_map, fixed_now = _seed_map()
    distilled = _entries()
    a = deterministic_cartographer(
        distilled=distilled,
        current_map=current_map,
        cycle_n=5,
        config=_config(),
        now=fixed_now,
    )
    b = deterministic_cartographer(
        distilled=distilled,
        current_map=current_map,
        cycle_n=5,
        config=_config(),
        now=fixed_now,
    )
    assert a.model_dump_json() == b.model_dump_json()


def test_repeated_invocation_stable_over_many_runs() -> None:
    current_map, fixed_now = _seed_map()
    distilled = _entries()
    outputs = {
        deterministic_cartographer(
            distilled=distilled,
            current_map=current_map,
            cycle_n=5,
            config=_config(),
            now=fixed_now,
        ).model_dump_json()
        for _ in range(20)
    }
    assert len(outputs) == 1
```

- [ ] **Step 2: Write the invariants test**

Create `tests/context_map/test_cartographer_invariants.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import CartographerConfig
from harness_poc.core.context_map.schema import DistillerEntry


_TYPES = ("entity", "schema", "insight", "dispute", "boundary", "constant", "result")


def _distilled(n: int) -> list[DistillerEntry]:
    return [
        DistillerEntry(
            key=f"k{i}",
            observation_type=_TYPES[i % len(_TYPES)],  # type: ignore[arg-type]
            summary=f"sum {i} " * (i % 5 + 1),
            source_event_ids=[f"ev-{i}"],
        )
        for i in range(n)
    ]


def test_invariant_budget_never_exceeded() -> None:
    config = CartographerConfig(token_budget=40)
    result = deterministic_cartographer(
        distilled=_distilled(20),
        current_map=[],
        cycle_n=0,
        config=config,
    )
    total = sum(e.token_estimate for e in result.new_map)
    assert total <= config.token_budget


def test_invariant_no_survivor_below_staleness_floor() -> None:
    config = CartographerConfig(
        token_budget=10_000,
        recency_bonus=0.0,
        recency_cap=0.0,
        staleness_penalty=0.5,
        staleness_floor=0.5,
    )
    seed = deterministic_cartographer(
        distilled=_distilled(7),
        current_map=[],
        cycle_n=0,
        config=config,
    )
    result = deterministic_cartographer(
        distilled=[],
        current_map=seed.new_map,
        cycle_n=10,
        config=config,
    )
    for entry in result.new_map:
        assert entry.priority >= config.staleness_floor


def test_invariant_every_eviction_corresponds_to_known_entry() -> None:
    config = CartographerConfig(token_budget=20)
    distilled = _distilled(12)
    result = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=config,
    )
    known_keys = {d.key for d in distilled}
    for eviction in result.evictions:
        assert eviction.key in known_keys


def test_invariant_entry_id_stable_across_cycles_for_survivors() -> None:
    fixed_now = datetime(2026, 5, 23, tzinfo=UTC)
    config = CartographerConfig(token_budget=10_000)
    distilled = _distilled(5)
    a = deterministic_cartographer(
        distilled=distilled,
        current_map=[],
        cycle_n=0,
        config=config,
        now=fixed_now,
    )
    b = deterministic_cartographer(
        distilled=distilled,
        current_map=a.new_map,
        cycle_n=1,
        config=config,
        now=fixed_now,
    )
    a_ids = {(e.key, e.entry_id) for e in a.new_map}
    b_ids = {(e.key, e.entry_id) for e in b.new_map}
    assert a_ids == b_ids
```

- [ ] **Step 3: Run both test files**

Run: `uv run pytest tests/context_map/test_cartographer_determinism.py tests/context_map/test_cartographer_invariants.py -v`
Expected: all passing. If a determinism test fails, fix the underlying non-determinism in `cartographer.py` (likely tie-break or sort key) before continuing.

- [ ] **Step 4: Lint & type-check**

Run: `uv run ruff check tests/context_map && uv run ty check harness_poc/core/context_map`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/context_map/test_cartographer_determinism.py tests/context_map/test_cartographer_invariants.py
git commit -m "test(context-map): cartographer determinism and invariants"
```

---

## Task 10: Distiller prompt template

**Files:**
- Create: `harness_poc/core/context_map/prompts/__init__.py`
- Create: `harness_poc/core/context_map/prompts/distiller_v1.md`

- [ ] **Step 1: Create the package marker**

Create `harness_poc/core/context_map/prompts/__init__.py` (empty file).

- [ ] **Step 2: Create the prompt**

Create `harness_poc/core/context_map/prompts/distiller_v1.md`:

```markdown
# Distiller v1 — System Prompt

You are the Distiller stage of a deterministic context-map pipeline. Your single job is to read raw events and emit zero or more structured observations. You do NOT decide where observations go in the map, what their priority is, or whether to add/delete/replace existing entries — those decisions belong to a downstream deterministic component.

## Output contract

You MUST emit a JSON object matching this shape:

```
{
  "entries": [
    {
      "key": "<stable-slug>",
      "observation_type": "entity" | "schema" | "insight" | "dispute" | "boundary" | "constant" | "result",
      "summary": "<one-paragraph orientation fact>",
      "source_event_ids": ["<event_id>", ...],   // at least one, all from the input events
      "tags": ["confirmed" | "novel" | "correcting", ...]  // optional, descriptive only
    }
  ]
}
```

## Rules

1. Use the same `key` slug across cycles for the same underlying thing. The list of `prior_keys` in your input is the authoritative set of slugs already in the map — reuse them when applicable.
2. Every `source_event_id` MUST appear in the `events` payload you were given. Citing an unknown event_id is a contract violation.
3. Do NOT include `section`, `priority`, `operation`, or any field outside the schema above. Extra fields will cause the entire output to be rejected.
4. If no observations are warranted, emit `{"entries": []}`.
5. Prefer fewer, sharper observations over many noisy ones. A `summary` should be a single orientation paragraph, not a transcript.

## observation_type meanings

- `entity` — a named thing in the corpus (class, function, module, document, concept).
- `schema` — a structural fact about data or interfaces (function signature, JSON shape, table column).
- `insight` — a non-obvious relationship, pattern, or implication discovered across events.
- `dispute` — a correction to a previously-believed claim, with the corrected version.
- `boundary` — what is NOT in the corpus (prevents hallucination): missing files, absent features, undocumented areas.
- `constant` — a stable domain constant (a configuration value, a magic number, a fixed name).
- `result` — a reusable computation or analysis result that need not be re-derived.
```

- [ ] **Step 3: Commit**

```bash
git add harness_poc/core/context_map/prompts/
git commit -m "feat(context-map): add distiller v1 system prompt template"
```

---

## Task 11: Distiller implementation + contract tests

**Files:**
- Create: `harness_poc/core/context_map/distiller.py`
- Test: `tests/context_map/test_distiller_contract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/context_map/test_distiller_contract.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from harness_poc.core.context_map.config import DistillerConfig
from harness_poc.core.context_map.distiller import run_distiller
from harness_poc.core.context_map.schema import DistillerEntry, DistilledBatch
from harness_poc.core.events.context_map_events import EntityReferenced


pytestmark = pytest.mark.asyncio


def _event(event_id: str) -> EntityReferenced:
    return EntityReferenced(
        event_id=event_id,
        session_id="s",
        corpus_key="codebase",
        entity_name="SkillRunner",
        entity_type="class",
        context="dispatches skills",
    )


async def test_valid_distiller_output_returned() -> None:
    valid_batch = DistilledBatch(
        entries=[
            DistillerEntry(
                key="skill-runner",
                observation_type="entity",
                summary="SkillRunner dispatches skills",
                source_event_ids=["ev-1"],
            )
        ]
    )
    model = TestModel(custom_output_args=valid_batch.model_dump())
    result = await run_distiller(
        events=[_event("ev-1")],
        model=model,
        config=DistillerConfig(),
    )
    assert len(result) == 1
    assert result[0].key == "skill-runner"


async def test_unknown_source_event_id_triggers_retry_then_fallback() -> None:
    bad_batch = DistilledBatch(
        entries=[
            DistillerEntry(
                key="ghost",
                observation_type="entity",
                summary="cites a non-existent event",
                source_event_ids=["ev-does-not-exist"],
            )
        ]
    )
    model = TestModel(custom_output_args=bad_batch.model_dump())
    result = await run_distiller(
        events=[_event("ev-1")],
        model=model,
        config=DistillerConfig(max_retries=2),
    )
    assert result == []  # safe fallback


async def test_zero_entries_is_valid() -> None:
    empty = DistilledBatch(entries=[])
    model = TestModel(custom_output_args=empty.model_dump())
    result = await run_distiller(
        events=[_event("ev-1")],
        model=model,
        config=DistillerConfig(),
    )
    assert result == []
```

(Note: `TestModel(custom_output_args=...)` returns the supplied object for every call. If the installed `pydantic-ai` version uses a different stub API, adjust accordingly — see https://ai.pydantic.dev/testing/ for the current pattern. The contract under test is the same regardless of stub mechanism.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/context_map/test_distiller_contract.py -v`
Expected: FAIL — `ModuleNotFoundError` on `distiller`.

- [ ] **Step 3: Implement `distiller.py`**

Create `harness_poc/core/context_map/distiller.py`:

```python
"""LLM Distiller stage — strict schema, bounded retry, safe fallback."""

from __future__ import annotations

import json
from importlib import resources
from typing import Sequence

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import Model

from harness_poc.core.context_map.config import DistillerConfig
from harness_poc.core.context_map.schema import DistilledBatch, DistillerEntry
from harness_poc.core.events.context_map_events import ContextMapEvent


def _load_prompt(template_name: str) -> str:
    package = "harness_poc.core.context_map.prompts"
    filename = f"{template_name}.md"
    return resources.files(package).joinpath(filename).read_text(encoding="utf-8")


def _render_events(events: Sequence[ContextMapEvent]) -> str:
    payload = [e.model_dump() for e in events]
    return json.dumps({"events": payload}, indent=2, default=str)


def _validate_against_events(
    batch: DistilledBatch,
    known_event_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for entry in batch.entries:
        unknown = [eid for eid in entry.source_event_ids if eid not in known_event_ids]
        if unknown:
            errors.append(
                f"entry {entry.key!r} cites unknown source_event_ids: {unknown}"
            )
    return errors


async def run_distiller(
    events: Sequence[ContextMapEvent],
    model: Model,
    config: DistillerConfig,
) -> list[DistillerEntry]:
    """Run one Distiller cycle. Returns [] on any unrecoverable failure (safe fallback)."""
    system_prompt = _load_prompt(config.prompt_template)
    agent = Agent(model=model, output_type=DistilledBatch, system_prompt=system_prompt)
    known_ids = {e.event_id for e in events}
    user_prompt = _render_events(events)

    last_error: str | None = None
    for attempt in range(config.max_retries + 1):
        prompt = user_prompt
        if last_error is not None:
            prompt = (
                f"{user_prompt}\n\n"
                f"Previous output was rejected: {last_error}. "
                "Reissue conforming output."
            )
        try:
            run = await agent.run(prompt)
            batch: DistilledBatch = run.output
        except ValidationError as exc:
            last_error = f"schema validation failed: {exc}"
            continue

        errors = _validate_against_events(batch, known_ids)
        if not errors:
            return list(batch.entries)
        last_error = "; ".join(errors)

    return []  # safe fallback after max_retries
```

- [ ] **Step 4: Run distiller tests**

Run: `uv run pytest tests/context_map/test_distiller_contract.py -v`
Expected: 3 passed. If `TestModel(custom_output_args=...)` API has shifted in the installed pydantic-ai version, fix the stub setup and re-run; the contract (valid → returned, unknown ev_id → retry → fallback, empty → returned) is the spec — adjust the test mechanism, not the asserted behavior.

- [ ] **Step 5: Run the full context_map suite as regression**

Run: `uv run pytest tests/context_map -v`
Expected: all tests in the package pass.

- [ ] **Step 6: Lint & type-check**

Run: `uv run ruff check harness_poc/core/context_map tests/context_map && uv run ty check harness_poc/core/context_map`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add harness_poc/core/context_map/distiller.py tests/context_map/test_distiller_contract.py
git commit -m "feat(context-map): distiller with strict-schema retry and safe fallback"
```

---

## Task 12: Package public exports

**Files:**
- Modify: `harness_poc/core/context_map/__init__.py`

- [ ] **Step 1: Replace the placeholder docstring with explicit exports**

Replace the contents of `harness_poc/core/context_map/__init__.py` with:

```python
"""Deterministic Cartographer + Distiller package.

See docs/superpowers/specs/2026-05-23-deterministic-cartographer-design.md.
"""

from harness_poc.core.context_map.cartographer import deterministic_cartographer
from harness_poc.core.context_map.config import (
    CartographerConfig,
    DistillerConfig,
    load_cartographer_config,
    load_distiller_config,
)
from harness_poc.core.context_map.distiller import run_distiller
from harness_poc.core.context_map.schema import (
    CartographerResult,
    DistilledBatch,
    DistillerEntry,
    EvictionRecord,
    MapEntry,
    ObservationType,
    Tag,
)
from harness_poc.core.context_map.sections import SECTION_MAP, assign_section

__all__ = [
    "CartographerConfig",
    "CartographerResult",
    "DistillerConfig",
    "DistilledBatch",
    "DistillerEntry",
    "EvictionRecord",
    "MapEntry",
    "ObservationType",
    "SECTION_MAP",
    "Tag",
    "assign_section",
    "deterministic_cartographer",
    "load_cartographer_config",
    "load_distiller_config",
    "run_distiller",
]
```

- [ ] **Step 2: Smoke-test the public surface**

Run: `uv run python -c "from harness_poc.core.context_map import deterministic_cartographer, run_distiller, DistillerEntry, MapEntry, CartographerConfig, DistillerConfig; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest`
Expected: all tests pass (or only failures unrelated to this package — verify each is pre-existing).

- [ ] **Step 4: Lint & type-check the whole package**

Run: `uv run ruff check harness_poc/core/context_map tests/context_map && uv run ty check harness_poc/core/context_map`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add harness_poc/core/context_map/__init__.py
git commit -m "feat(context-map): define public package exports"
```

---

## Done

After Task 12 the spec is fully implemented within its declared scope:

- `MapEntryReferenced` event + structured `MapEntryEvicted.reason` (telemetry seams for future learning + calibration)
- Deterministic section assignment (7 obs types → 5 sections)
- `DistillerEntry` / `MapEntry` / `CartographerResult` Pydantic schemas with forbidden-field enforcement
- `DistillerConfig` + `CartographerConfig` wired into `HarnessConfig` and `harness.yaml`
- Pure-function `deterministic_cartographer` covering dedup, priority, staleness, budget
- `run_distiller` PydanticAI agent with schema validation, source-event-id validation, bounded retry, safe `[]` fallback
- Public package exports under `harness_poc.core.context_map`

Deferred (future spec):
- Fetching `ContextMapEvent`s from the event store
- Persisting `current_map` between cycles
- Emitting `MapEntryReferenced` / `MapEntryEvicted` onto the event bus
- ACDL `ContextMapBlock` injection
- Cross-corpus insight handling
