"""Tests for the ACI tool guards (Phase 1.1).

Coverage:
- GuardResult: creation, pass/fail semantics
- PathGuard: relative paths, traversal, protected paths
- SizeGuard: file size enforcement
- TypeGuard: schema validation, missing required fields
- IdempotencyGuard: repeated call detection
- ContentGuard: binary extension, secret detection
- QueryGuard: write rejection, LIMIT enforcement
- GuardPipeline: multi-guard aggregation
- ToolRunner: guard integration in execute_tool()
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_poc.core.tools.guards import (
    ContentGuard,
    GuardPipeline,
    GuardResult,
    IdempotencyGuard,
    PathGuard,
    QueryGuard,
    SizeGuard,
    TypeGuard,
)
from harness_poc.core.tools.tool_runner import ToolRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory with a dummy Python file."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    (tmp_path / "data.txt").write_text("hello world\n")
    return tmp_path


# ---------------------------------------------------------------------------
# GuardResult
# ---------------------------------------------------------------------------


class TestGuardResult:
    def test_pass(self) -> None:
        r = GuardResult.pass_()
        assert r.ok is True
        assert r.errors == []

    def test_fail_single(self) -> None:
        r = GuardResult.fail("bad input")
        assert r.ok is False
        assert r.errors == ["bad input"]

    def test_fail_multiple(self) -> None:
        r = GuardResult.fail("error 1", "error 2")
        assert r.ok is False
        assert r.errors == ["error 1", "error 2"]


# ---------------------------------------------------------------------------
# PathGuard
# ---------------------------------------------------------------------------


class TestPathGuard:
    def test_absolute_path_passes(self, tmp_project: Path) -> None:
        guard = PathGuard(project_root=tmp_project)
        result = guard("read_file", {"path": str(tmp_project / "src" / "main.py")})
        assert result is None  # no rejection

    def test_relative_path_rejected(self, tmp_project: Path) -> None:
        guard = PathGuard(project_root=tmp_project)
        result = guard("read_file", {"path": "src/main.py"})
        assert result is not None
        assert not result.ok
        assert any("relative" in e.lower() for e in result.errors)

    def test_path_traversal_rejected(self, tmp_project: Path) -> None:
        guard = PathGuard(project_root=tmp_project)
        result = guard("read_file", {"path": "/etc/../home/user/file.txt"})
        assert result is not None
        assert not result.ok
        assert any("traversal" in e.lower() for e in result.errors)

    def test_dotdot_traversal_rejected(self, tmp_project: Path) -> None:
        guard = PathGuard(project_root=Path("/tmp"))
        result = guard("read_file", {"path": "/tmp/../../etc/passwd"})
        assert result is not None
        assert not result.ok
        assert any("traversal" in e.lower() for e in result.errors)

    def test_protected_prefix_rejected(self, tmp_project: Path) -> None:
        guard = PathGuard(project_root=tmp_project)
        result = guard("write_file", {"path": str(Path.home() / ".ssh" / "id_rsa")})
        assert result is not None
        assert not result.ok
        assert any("protected" in e.lower() for e in result.errors)

    def test_etc_rejected(self, tmp_project: Path) -> None:
        guard = PathGuard(project_root=tmp_project)
        result = guard("read_file", {"path": "/etc/passwd"})
        assert result is not None
        assert not result.ok
        assert any("protected" in e.lower() for e in result.errors)

    def test_multiple_path_keys_checked(self, tmp_project: Path) -> None:
        guard = PathGuard(project_root=tmp_project)
        # All path-like keys are scanned
        result = guard(
            "move_file",
            {"source": "/etc/shadow", "target": "/home/user/.ssh/config"},
        )
        assert result is not None
        assert not result.ok
        # Two errors — one for each bad path
        assert len(result.errors) >= 1


# ---------------------------------------------------------------------------
# SizeGuard
# ---------------------------------------------------------------------------


class TestSizeGuard:
    def test_non_existent_file_passes(self, tmp_project: Path) -> None:
        guard = SizeGuard(max_file_size=100)
        result = guard("read_file", {"path": str(tmp_project / "nonexistent.py")})
        assert result is None

    def test_small_file_passes(self, tmp_project: Path) -> None:
        (tmp_project / "small.txt").write_text("x" * 10)
        guard = SizeGuard(max_file_size=1000)
        result = guard("read_file", {"path": str(tmp_project / "small.txt")})
        assert result is None

    def test_large_file_rejected(self, tmp_project: Path) -> None:
        (tmp_project / "big.txt").write_text("x" * 2000)
        guard = SizeGuard(max_file_size=100)
        result = guard("read_file", {"path": str(tmp_project / "big.txt")})
        assert result is not None
        assert not result.ok
        assert any("exceeding" in e for e in result.errors)

    def test_negative_limit_rejected(self) -> None:
        guard = SizeGuard()
        result = guard("read_file", {"limit": -5})
        assert result is not None
        assert not result.ok
        assert any("positive" in e for e in result.errors)

    def test_zero_offset_rejected(self) -> None:
        guard = SizeGuard()
        result = guard("read_file", {"offset": 0})
        assert result is not None
        assert not result.ok


# ---------------------------------------------------------------------------
# TypeGuard
# ---------------------------------------------------------------------------


class TestTypeGuard:
    def test_valid_args_pass(self) -> None:
        guard = TypeGuard(
            {
                "read_file": {
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "offset": {"type": "integer"},
                        },
                        "required": ["path"],
                    }
                }
            }
        )
        result = guard("read_file", {"path": "/tmp/test.py", "offset": 10})
        assert result is None

    def test_missing_required_rejected(self) -> None:
        guard = TypeGuard(
            {
                "write_file": {
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    }
                }
            }
        )
        result = guard("write_file", {"path": "/tmp/test.py"})
        assert result is not None
        assert not result.ok
        assert any("missing" in e.lower() for e in result.errors)

    def test_wrong_type_rejected(self) -> None:
        guard = TypeGuard(
            {
                "read_file": {
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "offset": {"type": "integer"},
                        },
                        "required": ["path"],
                    }
                }
            }
        )
        result = guard("read_file", {"path": "/tmp/test.py", "offset": "ten"})
        assert result is not None
        assert not result.ok
        assert any("integer" in e for e in result.errors)

    def test_enum_violation_rejected(self) -> None:
        guard = TypeGuard(
            {
                "search_files": {
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string", "enum": ["content", "files"]},
                        },
                        "required": [],
                    }
                }
            }
        )
        result = guard("search_files", {"target": "invalid"})
        assert result is not None
        assert not result.ok

    def test_unknown_tool_passes(self) -> None:
        guard = TypeGuard({})
        result = guard("unknown_tool", {"x": 1})
        assert result is None

    def test_bool_type_enforced(self) -> None:
        guard = TypeGuard(
            {
                "patch": {
                    "parameters": {
                        "type": "object",
                        "properties": {"replace_all": {"type": "boolean"}},
                        "required": [],
                    }
                }
            }
        )
        result = guard(
            "patch", {"path": "/x.py", "old_string": "a", "new_string": "b", "replace_all": "yes"}
        )
        assert result is not None
        assert not result.ok
        assert any("boolean" in e for e in result.errors)


# ---------------------------------------------------------------------------
# IdempotencyGuard
# ---------------------------------------------------------------------------


class TestIdempotencyGuard:
    def test_first_call_passes(self) -> None:
        guard = IdempotencyGuard()
        result = guard("read_file", {"path": "/tmp/test.py"})
        assert result is None

    def test_repeated_call_rejected(self) -> None:
        guard = IdempotencyGuard()
        guard("read_file", {"path": "/tmp/test.py"})
        result = guard("read_file", {"path": "/tmp/test.py"})
        assert result is not None
        assert not result.ok
        assert any("already called" in e.lower() for e in result.errors)

    def test_different_args_pass(self) -> None:
        guard = IdempotencyGuard()
        guard("read_file", {"path": "/tmp/a.py"})
        result = guard("read_file", {"path": "/tmp/b.py"})
        assert result is None

    def test_whitespace_normalization(self) -> None:
        guard = IdempotencyGuard()
        guard("read_file", {"path": "/tmp/test.py", "query": "hello  world"})
        result = guard("read_file", {"path": "/tmp/test.py", "query": "hello world"})
        assert result is not None  # whitespace collapsed → same key

    def test_history_limit(self) -> None:
        guard = IdempotencyGuard(max_history=2)
        guard("a", {"v": 1})
        guard("a", {"v": 2})
        guard("a", {"v": 3})
        # v=1 should be evicted
        result = guard("a", {"v": 1})
        assert result is None  # forgotten, so passes again


# ---------------------------------------------------------------------------
# ContentGuard
# ---------------------------------------------------------------------------


class TestContentGuard:
    def test_text_content_passes(self) -> None:
        guard = ContentGuard()
        result = guard("write_file", {"path": "/tmp/test.py", "content": "print('hello')"})
        assert result is None

    def test_binary_extension_rejected(self) -> None:
        guard = ContentGuard()
        result = guard("read_file", {"path": "/tmp/photo.png"})
        assert result is not None
        assert not result.ok
        assert any("binary" in e.lower() for e in result.errors)

    def test_pdf_extension_rejected(self) -> None:
        guard = ContentGuard()
        result = guard("read_file", {"path": "/tmp/doc.pdf"})
        assert result is not None
        assert not result.ok

    def test_api_key_in_content_rejected(self) -> None:
        guard = ContentGuard()
        result = guard(
            "write_file",
            {
                "path": "/tmp/test.py",
                "content": "API_KEY = 'sk-abc123def456ghi789jkl012mno345pqr678'",
            },
        )
        assert result is not None
        assert not result.ok
        assert any("api key" in e.lower() for e in result.errors)

    def test_aws_key_in_content_rejected(self) -> None:
        guard = ContentGuard()
        result = guard(
            "write_file",
            {"path": "/tmp/test.py", "content": "key = 'AKIAIOSFODNN7EXAMPLE'"},
        )
        assert result is not None
        assert not result.ok

    def test_github_token_in_content_rejected(self) -> None:
        guard = ContentGuard()
        result = guard(
            "write_file",
            {
                "path": "/tmp/test.py",
                "content": "token = 'ghp_1234567890abcdef1234567890abcdef12345678'",
            },
        )
        assert result is not None
        assert not result.ok


# ---------------------------------------------------------------------------
# QueryGuard
# ---------------------------------------------------------------------------


class TestQueryGuard:
    def test_select_passes(self) -> None:
        guard = QueryGuard()
        result = guard("query_database", {"query": "SELECT * FROM users LIMIT 10"})
        assert result is None

    def test_insert_rejected(self) -> None:
        guard = QueryGuard()
        result = guard("query_database", {"query": "INSERT INTO users VALUES (1)"})
        assert result is not None
        assert not result.ok
        assert any("write" in e.lower() for e in result.errors)

    def test_delete_rejected(self) -> None:
        guard = QueryGuard()
        result = guard("query_database", {"query": "DELETE FROM users WHERE id = 1"})
        assert result is not None
        assert not result.ok

    def test_drop_rejected(self) -> None:
        guard = QueryGuard()
        result = guard("query_database", {"query": "DROP TABLE users"})
        assert result is not None
        assert not result.ok

    def test_missing_limit_rejected(self) -> None:
        guard = QueryGuard()
        result = guard("query_database", {"query": "SELECT * FROM users"})
        assert result is not None
        assert not result.ok
        assert any("limit" in e.lower() for e in result.errors)

    def test_limit_exceeded_rejected(self) -> None:
        guard = QueryGuard(max_rows=10)
        result = guard("query_database", {"query": "SELECT * FROM users LIMIT 100"})
        assert result is not None
        assert not result.ok
        assert any("exceeds" in e for e in result.errors)

    def test_limit_within_bounds_passes(self) -> None:
        guard = QueryGuard(max_rows=10)
        result = guard("query_database", {"query": "SELECT * FROM users LIMIT 10"})
        assert result is None

    def test_sql_key_checked(self) -> None:
        guard = QueryGuard()
        result = guard("query_database", {"sql": "DROP TABLE users"})
        assert result is not None
        assert not result.ok

    def test_non_query_arg_ignored(self) -> None:
        guard = QueryGuard()
        result = guard("some_tool", {"param": "not a query"})
        assert result is None


# ---------------------------------------------------------------------------
# GuardPipeline
# ---------------------------------------------------------------------------


class TestGuardPipeline:
    def test_all_guards_pass(self) -> None:
        pipeline = GuardPipeline()
        result = pipeline.validate("read_file", {"path": "/tmp/test.py"})
        assert result.ok

    def test_first_guard_fails(self) -> None:
        class AlwaysFail:
            def __call__(self, _tn: str, _args: dict) -> GuardResult | None:
                return GuardResult.fail("always fail")

        pipeline = GuardPipeline([AlwaysFail()])
        result = pipeline.validate("read_file", {"path": "/tmp/test.py"})
        assert not result.ok
        assert result.errors == ["always fail"]

    def test_all_errors_collected(self) -> None:
        class Fail1:
            def __call__(self, _tn: str, _args: dict) -> GuardResult | None:
                return GuardResult.fail("error 1")

        class Fail2:
            def __call__(self, _tn: str, _args: dict) -> GuardResult | None:
                return GuardResult.fail("error 2")

        pipeline = GuardPipeline([Fail1(), Fail2()])
        result = pipeline.validate("read_file", {"path": "/tmp/test.py"})
        assert not result.ok
        assert result.errors == ["error 1", "error 2"]

    def test_add_method(self) -> None:
        pipeline = GuardPipeline()
        pipeline.add(PathGuard(project_root=Path("/tmp")))
        assert len(pipeline.guards) == 1

    def test_none_guard_return_passes(self) -> None:
        class AlwaysNone:
            def __call__(self, _tn: str, _args: dict) -> GuardResult | None:
                return None

        pipeline = GuardPipeline([AlwaysNone()])
        result = pipeline.validate("read_file", {"path": "/tmp/test.py"})
        assert result.ok


# ---------------------------------------------------------------------------
# ToolRunner guard integration
# ---------------------------------------------------------------------------


class TestToolRunnerGuards:
    """Verify guards run during execute_tool and reject bad calls."""

    def test_guard_rejects_bad_path(self, test_config) -> None:
        """ToolRunner.execute_tool rejects traversal paths when guards are active."""
        project_root = test_config.project_root
        guards = GuardPipeline([PathGuard(project_root=project_root)])
        runner = ToolRunner(test_config, guards=guards)

        result = runner.execute_tool("read_file", {"path": "../etc/passwd"}, session_id="test")
        import json as _json

        parsed = _json.loads(result)
        assert "guard_errors" in parsed, f"Expected guard_errors, got: {parsed}"
        assert any("traversal" in e.lower() for e in parsed["guard_errors"])

    def test_no_guards_allows_all(self, test_config, tmp_project: Path) -> None:
        """Without guards, existing behavior is preserved."""
        runner = ToolRunner(test_config, guards=GuardPipeline())

        test_file = tmp_project / "data.txt"
        test_file.write_text("hello")
        result = runner.execute_tool("read_file", {"path": str(test_file)}, session_id="test")
        import json as _json

        parsed = _json.loads(result)
        assert "error" not in parsed, f"Unexpected error: {parsed}"
