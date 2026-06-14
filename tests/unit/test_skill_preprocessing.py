"""Unit tests for skill_preprocessing inline-shell blocked-binary guard."""

from __future__ import annotations

import pytest

from harness_poc.core.skills.skill_preprocessing import expand_inline_shell
from tests.helpers import BLOCKED_BINARIES


class TestInlineShellBlockedBinaries:
    """Inline shell snippets starting with a blocked binary are rejected."""

    @pytest.mark.parametrize(
        ("snippet", "expected_binary"),
        [(f"!`{binary}`", binary) for binary, _cmd in BLOCKED_BINARIES],
    )
    def test_blocked_inline_shell_rejected(self, snippet: str, expected_binary: str) -> None:
        """Each blocked binary produces an [inline-shell blocked: ...] marker."""
        result = expand_inline_shell(snippet, skill_dir=None, timeout=5)
        assert "[inline-shell blocked:" in result
        assert expected_binary in result

    def test_allowed_inline_shell_runs(self) -> None:
        """An allowed command like echo passes the guard and runs."""
        result = expand_inline_shell("!`echo hello`", skill_dir=None, timeout=5)
        assert result == "hello"

    def test_mixed_allowed_and_blocked(self) -> None:
        """Blocked snippet returns a marker, allowed snippet runs — both in one doc."""
        content = "before\n!`echo ok`\nmiddle\n!`vim bad`\nafter"
        result = expand_inline_shell(content, skill_dir=None, timeout=5)
        assert "ok" in result
        assert "[inline-shell blocked:" in result
        assert "before" in result
        assert "after" in result

    def test_no_inline_shell_passthrough(self) -> None:
        """Content without inline shell markers is returned unchanged."""
        content = "just some markdown\nno shell here"
        result = expand_inline_shell(content, skill_dir=None, timeout=5)
        assert result == content
