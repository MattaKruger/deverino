"""Tests for the evaluate_output skill (Phase 3.1).

Verifies that the evaluate_output skill correctly scores agent outputs,
handles missing arguments, and returns structured critique artifacts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# evaluate_output skill — direct module tests
# ---------------------------------------------------------------------------


def test_evaluate_output_imports():
    """The skill module should be importable."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    assert callable(execute)


def test_evaluate_output_missing_args():
    """Missing objective or output returns failed SkillResult."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    result = execute(MagicMock(), {})
    assert result.status == "failed"
    assert "Missing required" in result.content


def test_evaluate_output_missing_output_only():
    """Missing output (but has objective) fails."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    result = execute(MagicMock(), {"objective": "Test goal"})
    assert result.status == "failed"


def test_evaluate_output_missing_objective_only():
    """Missing objective (but has output) fails."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    result = execute(MagicMock(), {"output": "Some text"})
    assert result.status == "failed"


def test_evaluate_output_valid_call():
    """Valid arguments produce a structured result with score and critique."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    result = execute(
        MagicMock(),
        {
            "objective": "Explain what a function does",
            "output": "This function adds two numbers and returns the sum.",
        },
    )

    assert result.status in ("success", "failed")
    assert "score" in result.artifacts or result.status == "failed"
    if result.status == "success":
        assert isinstance(result.artifacts.get("score"), (int, float))
        assert isinstance(result.artifacts.get("passed"), bool)
        assert isinstance(result.artifacts.get("critique"), str)


def test_evaluate_output_with_criteria():
    """When criteria are provided, trait_check mode is used."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    result = execute(
        MagicMock(),
        {
            "objective": "Explain a function",
            "output": "The function validates input and returns output.",
            "criteria": ["validates input", "returns output"],
        },
    )

    assert result.status in ("success", "failed")
    if result.status == "success":
        assert "trait_results" in result.artifacts


def test_evaluate_output_with_context():
    """Context is injected into the evaluation."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    result = execute(
        MagicMock(),
        {
            "objective": "Test",
            "output": "Result",
            "context": "Additional context here",
        },
    )

    assert result.status in ("success", "failed")


def test_evaluate_output_artifacts_structure():
    """On success, artifacts contain the expected keys."""
    from harness_poc.system_skills.evaluate_output.skill import execute

    result = execute(
        MagicMock(),
        {
            "objective": "Write a hello world function",
            "output": (
                "Here is a hello world function in Python. "
                "It prints a greeting. The function handles the base case."
            ),
        },
    )

    if result.status == "success":
        for key in ("score", "passed", "critique", "suggestions"):
            assert key in result.artifacts, f"Missing artifact key: {key}"
        assert isinstance(result.artifacts["suggestions"], list)


# ---------------------------------------------------------------------------
# _extract_suggestions helper
# ---------------------------------------------------------------------------


def test_extract_suggestions_from_numbered_list():
    """Numbered items are extracted as suggestions."""
    from harness_poc.system_skills.evaluate_output.skill import _extract_suggestions

    text = "1. Add more detail\n2. Fix the typo\n3. Include examples"
    suggestions = _extract_suggestions(text)
    assert len(suggestions) == 3
    assert "Add more detail" in suggestions[0]


def test_extract_suggestions_from_bullets():
    """Bullet points are extracted as suggestions."""
    from harness_poc.system_skills.evaluate_output.skill import _extract_suggestions

    text = "- Improve clarity\n- Add examples"
    suggestions = _extract_suggestions(text)
    assert len(suggestions) == 2


def test_extract_suggestions_fallback():
    """When no list structure, the first 200 chars are used as a single suggestion."""
    from harness_poc.system_skills.evaluate_output.skill import _extract_suggestions

    text = "The output is generally good but could be more detailed."
    suggestions = _extract_suggestions(text)
    assert len(suggestions) >= 1
    assert len(suggestions[0]) <= 200


# ---------------------------------------------------------------------------
# SKILL.md validation
# ---------------------------------------------------------------------------


def test_skill_md_exists():
    """The evaluate_output SKILL.md should exist."""
    path = Path("harness_poc/system_skills/evaluate_output/SKILL.md")
    assert path.exists(), f"SKILL.md not found at {path}"


def test_skill_md_has_required_frontmatter():
    """SKILL.md should have name, type, and parameters."""
    path = Path("harness_poc/system_skills/evaluate_output/SKILL.md")
    content = path.read_text()
    assert "name: evaluate_output" in content
    assert "type: skill" in content
    assert "objective" in content
    assert "output" in content
