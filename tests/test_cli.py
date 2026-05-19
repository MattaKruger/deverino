from __future__ import annotations

from typer.testing import CliRunner

from harness_poc.cli import app

runner = CliRunner()


def test_help_lists_command_groups() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "workflow" in result.output
    assert "state" in result.output
    assert "skill" in result.output
    assert "events" in result.output


def test_state_show_project_renders_project_state() -> None:
    result = runner.invoke(app, ["state", "show", "project"])

    assert result.exit_code == 0
    assert "Project State" in result.output
    assert "Next Actions" in result.output


def test_skill_list_renders_discovered_skills() -> None:
    result = runner.invoke(app, ["skill", "list"])

    assert result.exit_code == 0
    assert "container_exec" in result.output
    assert "reflect_on_result" in result.output
    assert "consolidate_state" in result.output


def test_workflow_run_executes_workflow_without_container_block() -> None:
    result = runner.invoke(app, ["workflow", "run", "research_task", "smoke"])

    assert result.exit_code == 0
    assert "Workflow research_task completed with status: completed" in result.output
