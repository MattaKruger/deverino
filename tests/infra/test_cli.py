from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from harness_poc.cli import app
from harness_poc.core.skills import SkillResult

runner = CliRunner()


def test_help_lists_command_groups() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "workflow" in result.output
    assert "state" in result.output
    assert "skill" in result.output
    assert "documents" in result.output
    assert "dashboard" in result.output
    assert "events" in result.output


def test_state_show_project_renders_project_state() -> None:
    result = runner.invoke(app, ["state", "show", "project"])

    assert result.exit_code == 0
    assert "Project State" in result.output
    assert "Next Actions" in result.output


def test_skill_list_renders_discovered_skills() -> None:
    result = runner.invoke(app, ["skill", "list"])

    assert result.exit_code == 0
    # Agent skills still in system_skills/ + project_skills/
    assert "delegate_task" in result.output
    assert "reflect_on_result" in result.output
    assert "consolidate_state" in result.output


def test_documents_index_invokes_index_documents_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeSkillRunner:
        def execute_skill(
            self, tool_name: str, arguments: dict[str, object], session_id: str
        ) -> SkillResult:
            calls.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "session_id": session_id,
                }
            )
            return SkillResult(
                status="success",
                content="Indexed 1 source(s), 2 chunk(s). Skipped 0. Failed 0.",
            )

    monkeypatch.setattr(
        "harness_poc.cli._new_app_state",
        lambda: SimpleNamespace(session_id="test-session", skill_runner=FakeSkillRunner()),
    )

    result = runner.invoke(
        app,
        [
            "documents",
            "index",
            "docs/example.pdf",
            "--glob",
            "*.pdf",
            "--exclude-dir",
            "docs/generated",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert "Indexed 1 source(s)" in result.output
    assert calls == [
        {
            "tool_name": "index_documents",
            "arguments": {
                "paths": ["docs/example.pdf"],
                "glob": "*.pdf",
                "exclude_dirs": ["docs/generated"],
                "force": True,
            },
            "session_id": "test-session",
        }
    ]


@pytest.mark.integration
def test_workflow_run_executes_workflow_without_container_block() -> None:
    result = runner.invoke(app, ["workflow", "run", "research_task", "smoke"])

    assert result.exit_code == 0
    assert "Workflow research_task completed with status: completed" in result.output
