"""Self-check for the ACDL system-prompt executor against the real spec."""

from __future__ import annotations

from pathlib import Path

from harness_poc.core.acdl import parse
from harness_poc.core.acdl.executor import assemble_system_prompt

_SPEC_PATH = Path(__file__).resolve().parents[2] / "deverino_react.acdl"


def _spec():
    return parse(_SPEC_PATH.read_text(encoding="utf-8"), filename=str(_SPEC_PATH))


def test_composition_order_and_seam_boundaries() -> None:
    full = assemble_system_prompt(
        _spec(),
        {
            "sys.soul_charter": "SOUL-TEXT",
            "sys.project_state": "PROJ-STATE",
            "sys.session_state": "SESS-STATE",
            "sys.context_map": "MAP-BODY",
        },
    )
    # Spec order: SoulCharter -> StateBlock -> ContextMapBlock.
    assert full.index("SOUL-TEXT") < full.index("PROJ-STATE")
    assert full.index("PROJ-STATE") < full.index("MAP-BODY")
    # ContextMapBlock's literal wrapper comes from the spec, not Python.
    assert "--- Context Map ---" in full
    # Frags owned by other seams must not leak in here.
    assert "Tool Result Policy" not in full
    assert "available_skills" not in full


def test_context_map_conditional_drops_when_absent() -> None:
    no_map = assemble_system_prompt(_spec(), {"sys.soul_charter": "SOUL-TEXT"})
    assert "SOUL-TEXT" in no_map
    assert "Context Map" not in no_map
