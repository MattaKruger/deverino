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
