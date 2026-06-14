"""Unit tests for container_exec blocked-binary guardrails.

Tests the interactive binary blocking added in the CLI Guru Option A
implementation — no containers needed.
"""

from __future__ import annotations

import pytest

from harness_poc.system_tools.container_exec import container_exec
from tests.helpers import BLOCKED_BINARIES


_BLOCKED_COMMANDS = [(cmd, binary) for binary, cmd in BLOCKED_BINARIES]


class TestBlockedBinaries:
    """Commands starting with a blocked binary are rejected before execution."""

    @pytest.mark.parametrize(
        ("command", "expected_binary"),
        [(binary, binary) for binary, _cmd in BLOCKED_BINARIES],
    )
    def test_blocked_binary_rejected(self, command: str, expected_binary: str) -> None:
        """Each blocked binary returns status='blocked' with the binary name."""
        result = container_exec(command=command, container="test-container")
        assert result.status == "blocked"
        assert expected_binary in result.content
        assert result.artifacts.get("binary") == expected_binary

    def test_blocked_binary_with_flags_rejected(self) -> None:
        """Vim with flags and quit command is still vim."""
        result = container_exec(command="vim -u NONE -c 'q!'", container="test-container")
        assert result.status == "blocked"
        assert result.artifacts["binary"] == "vim"

    def test_allowed_binary_passes_guard(self) -> None:
        """Allowed binary passes the block check.

        Fails later on backend resolution since there is no container
        runtime in tests — but not at the guard stage.
        """
        result = container_exec(command="echo hello", container="test-container")
        # Not blocked — should fail because no container runtime is available
        assert result.status != "blocked"
        assert "echo" not in (result.artifacts.get("binary") or "")
