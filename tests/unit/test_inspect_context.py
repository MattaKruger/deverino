"""Tests for the inspect_own_context system tool."""

from __future__ import annotations

from pathlib import Path

from harness_poc.core.tools import ToolContext
from harness_poc.system_tools.inspect_context import inspect_own_context


def test_returns_full_prompt_when_wired() -> None:
    """Tool returns the system prompt text and structural summary."""
    prompt = "## Section 1\n\nContent here.\n\n## Section 2\n\nMore.\n\n## Tool Result Policy\n- Rule"
    ctx = ToolContext(
        session_id="test",
        project_root=Path("/tmp"),
        system_prompt=prompt,
    )
    result = inspect_own_context(ctx)
    assert result.status == "success"
    assert result.content == prompt

    summary = result.artifacts["system_prompt_summary"]
    assert summary["total_chars"] == len(prompt)
    assert "## Section 1" in summary["sections_found"]
    assert "## Section 2" in summary["sections_found"]
    # Tool Result Policy excluded from section list
    assert "## Tool Result Policy" not in summary["sections_found"]


def test_returns_failure_when_not_wired() -> None:
    """Tool returns failure when system_prompt was not set on ToolContext."""
    ctx = ToolContext(
        session_id="test",
        project_root=Path("/tmp"),
        # system_prompt defaults to ""
    )
    result = inspect_own_context(ctx)
    assert result.status == "failed"
    assert "not available" in result.content.lower()


def test_structural_summary_accurate() -> None:
    """Word/line counts and section filtering are correct."""
    prompt = (
        "## 1. Identity\n\nI am the agent.\n\n"
        "## 2. Principles\n\nBe helpful.\n\nBe precise.\n\n"
        "## Tool Result Policy\n- Rule 1\n- Rule 2\n"
    )
    ctx = ToolContext(
        session_id="test",
        project_root=Path("/tmp"),
        system_prompt=prompt,
    )
    result = inspect_own_context(ctx)
    summary = result.artifacts["system_prompt_summary"]

    assert summary["total_chars"] == len(prompt)
    assert summary["total_lines"] == len(prompt.split("\n"))
    assert summary["sections_found"] == ["## 1. Identity", "## 2. Principles"]


def test_tool_is_registered() -> None:
    """inspect_own_context is discoverable in the tool registry."""
    from harness_poc.core.config import HarnessConfig
    from harness_poc.core.tools import ToolRunner

    config = HarnessConfig.load(Path("harness.yaml"))
    runner = ToolRunner(config)
    names = runner.list_tool_names()
    assert "inspect_own_context" in names
