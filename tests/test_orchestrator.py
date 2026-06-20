"""Tests for Phase 4 — Multi-Agent Mesh.

Coverage:
- Orchestrate skill: decomposition, parallel delegation requests
- Agent roles: loading and persona assignment
- Result synthesis: conflict detection, gap detection
- Delegation tree: traceability structure
"""

from __future__ import annotations

import pytest

from harness_poc.system_skills.orchestrate.skill import (
    _decompose,
    _detect_conflict,
    _pick_role,
    synthesize,
)

# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------


class TestDecompose:
    def test_refactor_decomposition(self) -> None:
        subtasks = _decompose("Refactor the file_tools module", ["code_reviewer", "architect"], "")
        assert len(subtasks) >= 3
        ids = {s["id"] for s in subtasks}
        assert {"analyze", "implement", "review"}.issubset(ids)
        # Roles assigned
        roles = {s["role"] for s in subtasks}
        assert len(roles) >= 1
        assert all(r in {"code_reviewer", "architect"} for r in roles)

    def test_research_decomposition(self) -> None:
        subtasks = _decompose(
            "Research the best Python agent frameworks", ["web_researcher", "data_validator"], ""
        )
        assert len(subtasks) >= 3
        ids = {s["id"] for s in subtasks}
        assert {"search", "validate", "synthesize"}.issubset(ids)

    def test_generic_decomposition(self) -> None:
        subtasks = _decompose("Do something vague", [], "")
        assert len(subtasks) >= 2
        ids = {s["id"] for s in subtasks}
        assert {"plan", "execute"}.issubset(ids)

    def test_empty_roles_fallback(self) -> None:
        subtasks = _decompose("Refactor X", [], "")
        for s in subtasks:
            assert s["role"] in {"architect", "code_reviewer"}  # fallback roles


# ---------------------------------------------------------------------------
# Role picking
# ---------------------------------------------------------------------------


class TestPickRole:
    def test_pick_from_list(self) -> None:
        assert _pick_role(["alpha", "beta"], 0, "fallback") == "alpha"
        assert _pick_role(["alpha", "beta"], 1, "fallback") == "beta"
        assert _pick_role(["alpha", "beta"], 2, "fallback") == "alpha"  # cycles

    def test_empty_list_fallback(self) -> None:
        assert _pick_role([], 0, "architect") == "architect"


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    def test_no_conflict(self) -> None:
        assert _detect_conflict("All tests pass", "Build succeeded") is None

    def test_contradiction_detected(self) -> None:
        result = _detect_conflict("This must not be called", "You must call this function")
        assert result is not None
        assert "must not" in result.lower()

    def test_reverse_order(self) -> None:
        result = _detect_conflict("You must call this function", "This must not be called")
        assert result is not None

    def test_different_topics_no_conflict(self) -> None:
        assert _detect_conflict("The cache is invalidated", "The database is updated") is None


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


class TestSynthesis:
    def test_basic_synthesis(self) -> None:
        results = [
            {
                "subtask_id": "analyze",
                "role": "architect",
                "content": "Analysis: 3 files affected. The tool_runner.py needs guards.",
                "status": "completed",
            },
            {
                "subtask_id": "implement",
                "role": "code_reviewer",
                "content": "Implementation: Added PathGuard and SizeGuard to guards.py.",
                "status": "completed",
            },
        ]
        synth = synthesize(results)
        assert "synthesis" in synth
        assert len(synth["conflicts"]) == 0
        assert synth["subtask_count"] == 2

    def test_conflict_detection_in_synthesis(self) -> None:
        results = [
            {
                "subtask_id": "a",
                "role": "reviewer",
                "content": "This must not use caching.",
                "status": "completed",
            },
            {
                "subtask_id": "b",
                "role": "architect",
                "content": "You must implement caching.",
                "status": "completed",
            },
        ]
        synth = synthesize(results)
        assert len(synth["conflicts"]) >= 1
        assert "must not" in str(synth["conflicts"]).lower()

    def test_gap_detection(self) -> None:
        results = [
            {
                "subtask_id": "empty",
                "role": "reviewer",
                "content": "",
                "status": "completed",
            },
        ]
        synth = synthesize(results)
        assert len(synth["gaps"]) >= 1
        assert "empty" in synth["gaps"][0]

    def test_delegation_tree(self) -> None:
        results = [
            {
                "subtask_id": "task-1",
                "role": "architect",
                "content": "Planned something.",
                "status": "completed",
            },
        ]
        synth = synthesize(results)
        tree = synth["delegation_tree"]
        assert len(tree["subtasks"]) == 1
        assert tree["subtasks"][0]["id"] == "task-1"
        assert tree["subtasks"][0]["role"] == "architect"


# ---------------------------------------------------------------------------
# LLM-driven decomposition
# ---------------------------------------------------------------------------


class TestLLMDecompose:
    def test_falls_back_when_llm_unavailable(self) -> None:
        """When LLM call raises, falls back to keyword-based."""
        from unittest.mock import MagicMock, patch

        from harness_poc.system_skills.orchestrate.skill import _llm_decompose

        ctx = MagicMock()
        ctx.config.project_root = __import__("pathlib").Path(".")

        # Patch build_model to raise — forces fallback path
        with patch(
            "harness_poc.core.runtime.build_model",
            side_effect=RuntimeError("no model"),
        ):
            subtasks = _llm_decompose(ctx, "Refactor file_tools module", [], "")

        assert len(subtasks) >= 2
        assert all(isinstance(s, dict) for s in subtasks)
        assert all("id" in s and "role" in s and "description" in s for s in subtasks)

    def test_decomposition_plan_model(self) -> None:
        """DecompositionPlan validates correctly."""
        from harness_poc.system_skills.orchestrate.skill import DecompositionPlan, SubTaskSpec

        plan = DecompositionPlan(
            subtasks=[
                SubTaskSpec(
                    id="analyze",
                    role="architect",
                    description="Analyze the codebase",
                    input="Look at the code",
                ),
                SubTaskSpec(
                    id="implement",
                    role="code_reviewer",
                    description="Implement changes",
                    input="Write code",
                ),
            ]
        )
        assert len(plan.subtasks) == 2

    def test_decomposition_plan_rejects_empty(self) -> None:
        """DecompositionPlan requires at least 1 subtask."""
        from harness_poc.system_skills.orchestrate.skill import DecompositionPlan

        with pytest.raises(Exception):
            DecompositionPlan(subtasks=[])


class TestLoadRoleDescriptions:
    def test_loads_existing_roles(self) -> None:
        """Loads role descriptions from agents/roles/ for known roles."""
        from pathlib import Path
        from unittest.mock import MagicMock

        from harness_poc.system_skills.orchestrate.skill import _load_role_descriptions

        ctx = MagicMock()
        ctx.config.project_root = Path()

        descs = _load_role_descriptions(ctx, ["architect", "code_reviewer"])
        assert isinstance(descs, str)

    def test_empty_when_dir_missing(self) -> None:
        """Returns empty string when agents/roles/ does not exist."""
        from pathlib import Path
        from unittest.mock import MagicMock

        from harness_poc.system_skills.orchestrate.skill import _load_role_descriptions

        ctx = MagicMock()
        ctx.config.project_root = Path("/nonexistent/path")

        descs = _load_role_descriptions(ctx, ["architect"])
        assert descs == ""
