"""Tests for --corpus flag on REPL entrypoints — Gap 2c."""

from __future__ import annotations

from typer.testing import CliRunner

from harness_poc.cli import app

runner = CliRunner()


def test_corpus_flag_rejects_missing_colon() -> None:
    result = runner.invoke(app, ["--corpus", "no-colon"])
    assert result.exit_code == 1
    assert "must follow 'project:name'" in result.output


def test_corpus_flag_appears_in_help() -> None:
    """--corpus flag is registered and appears in help output."""
    result = runner.invoke(app, ["--help"])
    assert "--corpus" in result.output
    assert "Active corpus key" in result.output


def test_corpus_retrieval_flag_accepted() -> None:
    """--corpus-retrieval flag is accepted by the CLI."""
    # Use --help to avoid actually starting the REPL
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--corpus-retrieval" in result.output or "corpus-retrieval" in result.output
