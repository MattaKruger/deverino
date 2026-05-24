"""Tests for _extract_references — Track B §4.2 citation extraction + §4.3 attribution."""

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
    """Build a minimal config stub.

    _extract_references only reads config.project_id,
    config.cartographer.cross_corpus_enabled, and
    config.cartographer.cross_corpus_related_corpora.
    """
    return SimpleNamespace(
        project_id=project_id,
        cartographer=CartographerConfig(
            cross_corpus_enabled=cross_corpus_enabled,
            cross_corpus_related_corpora=related or {},
        ),
    )


# ---------------------------------------------------------------------------
# Well-formed marker extraction
# ---------------------------------------------------------------------------


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


def test_unknown_entry_id_emits_nothing(db: BlackboardDatabase) -> None:
    db.write_map_and_mark_processed("deverino:codebase", [], 0, [])
    refs = _extract_references(
        content="Here is [entry:ab12cd34ef560789abcdef0123456789] an unknown marker.",
        session_id="s1",
        database=db,
        config=_make_config(),
    )
    assert refs == []


def test_deduplicates_per_turn(db: BlackboardDatabase) -> None:
    entry_id = uuid4().hex
    db.write_map_and_mark_processed("deverino:codebase", [_make_entry(entry_id)], 5, [])

    refs = _extract_references(
        content=f"First [entry:{entry_id}], then again [entry:{entry_id}].",
        session_id="s1",
        database=db,
        config=_make_config(),
    )

    assert len(refs) == 1


def test_dashed_id_in_marker_does_not_match_regex(db: BlackboardDatabase) -> None:
    """The regex is [0-9a-f]{32}; dashed UUID inside the bracket is malformed."""
    dashed = "ab12cd34-ef56-7890-abcd-ef0123456789"
    db.write_map_and_mark_processed("deverino:codebase", [_make_entry(dashed)], 5, [])

    refs = _extract_references(
        content=f"Cite [entry:{dashed}] here.",
        session_id="s1",
        database=db,
        config=_make_config(),
    )
    assert refs == []


def test_citation_context_window_is_about_160_chars(db: BlackboardDatabase) -> None:
    entry_id = uuid4().hex
    db.write_map_and_mark_processed("deverino:codebase", [_make_entry(entry_id)], 5, [])

    # Build a long surrounding context
    prefix = "A" * 100
    suffix = "B" * 100
    content = f"{prefix}[entry:{entry_id}]{suffix}"

    refs = _extract_references(
        content=content,
        session_id="s1",
        database=db,
        config=_make_config(),
    )

    assert len(refs) == 1
    ctx = refs[0].citation_context
    # Context window: up to 80 chars before + marker + up to 80 chars after
    # = at most marker_len + 160
    marker = f"[entry:{entry_id}]"
    assert len(ctx) <= len(marker) + 160
    assert marker in ctx


def test_no_markers_returns_empty_list(db: BlackboardDatabase) -> None:
    db.write_map_and_mark_processed("deverino:codebase", [], 0, [])
    refs = _extract_references(
        content="just text, no markers anywhere",
        session_id="s1",
        database=db,
        config=_make_config(),
    )
    assert refs == []


# ---------------------------------------------------------------------------
# Cross-corpus attribution (§4.3)
# ---------------------------------------------------------------------------


def test_cross_corpus_disabled_ignores_related_maps(db: BlackboardDatabase) -> None:
    active = "deverino:codebase"
    related = "other:codebase"
    entry_id = uuid4().hex

    db.write_map_and_mark_processed(active, [], 0, [])
    db.write_map_and_mark_processed(related, [_make_entry(entry_id)], 5, [])

    config = _make_config(
        cross_corpus_enabled=False,
        related={active: [related]},
    )
    refs = _extract_references(
        content=f"Cite [entry:{entry_id}] here.",
        session_id="s1",
        database=db,
        config=config,
    )
    assert refs == []


def test_cross_corpus_attribution(db: BlackboardDatabase) -> None:
    """A related-corpus citation must attribute to the source corpus, not active.

    This is the §4.3 contract: MapEntryReferenced.corpus_key is the source
    corpus, and cycle_n is the source's cycle.
    """
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


# ---------------------------------------------------------------------------
# Gap 2b: session corpus in reference extraction
# ---------------------------------------------------------------------------


def test_extract_references_uses_session_corpus(db: BlackboardDatabase) -> None:
    sid = db.start_session("obj", active_corpus_key="deverino:dashboard")
    entry_id = uuid4().hex
    db.write_map_and_mark_processed(
        "deverino:dashboard", [_make_entry(entry_id)], 5, [],
    )

    config = _make_config()
    refs = _extract_references(
        content=f"see [entry:{entry_id}]",
        session_id=sid,
        database=db,
        config=config,
    )
    assert len(refs) == 1
    assert refs[0].corpus_key == "deverino:dashboard"


# ---------------------------------------------------------------------------
# Gap 3: auto-discover references
# ---------------------------------------------------------------------------


def test_auto_discover_indexes_all_corpora(db: BlackboardDatabase) -> None:
    cb_id = uuid4().hex
    dash_id = uuid4().hex
    db.write_map_and_mark_processed(
        "deverino:codebase", [_make_entry(cb_id, key="cb-1")], 5, [],
    )
    db.write_map_and_mark_processed(
        "deverino:dashboard", [_make_entry(dash_id, key="dash-1")], 5, [],
    )
    sid = db.start_session("obj")  # primary defaults to :codebase

    config = _make_config(cross_corpus_enabled=True)
    refs = _extract_references(
        content=(
            f"cb [entry:{cb_id}] "
            f"dash [entry:{dash_id}]"
        ),
        session_id=sid, database=db, config=config,
    )
    assert {r.corpus_key for r in refs} == {
        "deverino:codebase", "deverino:dashboard",
    }


def test_whitelist_filter_still_applies_under_auto_discover(
    db: BlackboardDatabase,
) -> None:
    excluded_id = uuid4().hex
    db.write_map_and_mark_processed(
        "deverino:noise", [_make_entry(excluded_id, key="n-1")], 5, [],
    )
    db.write_map_and_mark_processed(
        "deverino:codebase", [], 0, [],
    )
    sid = db.start_session("obj")
    config = _make_config(
        cross_corpus_enabled=True,
        related={
            "deverino:codebase": ["deverino:dashboard"],  # excludes :noise
        },
    )
    refs = _extract_references(
        content=f"[entry:{excluded_id}]",
        session_id=sid, database=db, config=config,
    )
    assert refs == []


def test_auto_discover_disabled_falls_back_to_static_list(
    db: BlackboardDatabase,
) -> None:
    """auto_discover=False must reproduce pre-Gap-3 behaviour exactly."""
    related_id = uuid4().hex
    auto_id = uuid4().hex

    db.write_map_and_mark_processed(
        "deverino:codebase", [], 0, [],
    )
    db.write_map_and_mark_processed(
        "deverino:dashboard", [_make_entry(related_id, key="dash-1")], 5, [],
    )
    db.write_map_and_mark_processed(
        "deverino:benchmarks", [_make_entry(auto_id, key="bench-1")], 5, [],
    )
    sid = db.start_session("obj")

    # Cross-corpus enabled, auto_discover OFF, only dashboard in static list
    from harness_poc.core.context_map.config import CartographerConfig

    cc = CartographerConfig(
        cross_corpus_enabled=True,
        cross_corpus_auto_discover=False,
        cross_corpus_related_corpora={
            "deverino:codebase": ["deverino:dashboard"],
        },
    )
    stub_config = SimpleNamespace(
        project_id="deverino",
        cartographer=cc,
    )

    refs = _extract_references(
        content=(
            f"related [entry:{related_id}] "
            f"auto [entry:{auto_id}]"
        ),
        session_id=sid, database=db, config=stub_config,
    )
    # Only the static-list entry should resolve
    assert len(refs) == 1
    assert refs[0].corpus_key == "deverino:dashboard"


def test_unresolved_marker_emits_warning(
    db: BlackboardDatabase, caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    db.write_map_and_mark_processed("deverino:codebase", [], 0, [])
    sid = db.start_session("obj")
    with caplog.at_level(logging.WARNING):
        _extract_references(
            content="see [entry:" + "0" * 32 + "]",
            session_id=sid, database=db, config=_make_config(),
        )
    assert any("Unresolved" in rec.message for rec in caplog.records)
