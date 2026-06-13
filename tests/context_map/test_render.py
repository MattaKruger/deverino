"""Tests for render_context_map — Track B §4.1 prompt rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

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
    """Build a MapEntry with sensible defaults.

    Defaults to a dashed UUID so render's dash-stripping is exercised.
    """
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


# ---------------------------------------------------------------------------
# Structured mode — grouping
# ---------------------------------------------------------------------------


def test_structured_mode_groups_by_section() -> None:
    e1 = _make_entry(section="parsing_schema", summary="ps")
    e2 = _make_entry(section="domain_constants", summary="dc")
    out = render_context_map([e1, e2], cycle_n=1)

    assert "section: parsing_schema" in out
    assert "section: domain_constants" in out
    # Both summaries present
    assert "ps" in out
    assert "dc" in out


def test_structured_mode_section_order_follows_priority_table() -> None:
    e1 = _make_entry(section="context_roadmap")
    e2 = _make_entry(section="parsing_schema")
    out = render_context_map([e1, e2], cycle_n=1)

    idx_ps = out.index("section: parsing_schema")
    idx_cr = out.index("section: context_roadmap")
    assert idx_ps < idx_cr  # parsing_schema comes before context_roadmap


def test_structured_mode_within_section_sorts_by_priority_desc_then_entry_id() -> None:
    e_low = _make_entry(priority=0.5, entry_id="11111111-1111-1111-1111-111111111111")
    e_high_a = _make_entry(priority=0.9, entry_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    e_high_b = _make_entry(priority=0.9, entry_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    out = render_context_map([e_low, e_high_b, e_high_a], cycle_n=1)
    idx_a = out.index("aaaa")
    idx_b = out.index("bbbb")
    idx_1 = out.index("1111")
    assert idx_a < idx_b < idx_1


def test_structured_mode_includes_cycle_header() -> None:
    out = render_context_map([], cycle_n=5)
    assert out.startswith("cycle: 5")


def test_structured_mode_strips_dashes_from_entry_id() -> None:
    dashed = "ab12cd34-ef56-7890-abcd-ef0123456789"
    entry = _make_entry(entry_id=dashed)
    out = render_context_map([entry], cycle_n=1)
    assert "[entry:ab12cd34ef567890abcdef0123456789]" in out
    assert dashed not in out  # dashed form must not appear anywhere


def test_structured_mode_collapses_whitespace_in_summary() -> None:
    entry = _make_entry(summary="line one\n  line two\t\tline three")
    out = render_context_map([entry], cycle_n=1)
    assert "line one line two line three" in out


# ---------------------------------------------------------------------------
# JSON mode
# ---------------------------------------------------------------------------


def test_json_mode_returns_valid_parseable_json() -> None:
    entries = [_make_entry(), _make_entry()]
    out = render_context_map(entries, cycle_n=1, prompt_mode="json")
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert all("entry_id" in e for e in parsed)


# ---------------------------------------------------------------------------
# None mode
# ---------------------------------------------------------------------------


def test_none_mode_returns_empty_string() -> None:
    out = render_context_map([_make_entry()], cycle_n=1, prompt_mode="none")
    assert out == ""


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_entries_returns_only_cycle_header() -> None:
    out = render_context_map([], cycle_n=3)
    assert out == "cycle: 3"


def test_deterministic_across_runs() -> None:
    e1 = _make_entry(entry_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", priority=0.9, summary="first")
    e2 = _make_entry(
        entry_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        priority=0.8,
        summary="second",
    )
    entries = [e2, e1]  # input order different from sort order
    out1 = render_context_map(entries, cycle_n=1)
    out2 = render_context_map(entries, cycle_n=1)
    assert out1 == out2
