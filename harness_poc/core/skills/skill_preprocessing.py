"""Skill content preprocessing — template substitution and inline shell expansion.

Inspired by Hermes's ``agent/skill_preprocessing.py`` but adapted for
Deverino's config / session model.  Replaces ``${PROJECT_ROOT}``,
``${SESSION_ID}``, and ``${SCRATCH_DIR}`` tokens in skill content so
authors can write environment-independent instructions.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Matches ${PROJECT_ROOT} / ${SESSION_ID} / ${SCRATCH_DIR} tokens.
_SKILL_TEMPLATE_RE = re.compile(r"\$\{(PROJECT_ROOT|SESSION_ID|SCRATCH_DIR)\}")

# Matches inline shell snippets:  !`cmd`
# Non-greedy, single-line only — no newlines inside the backticks.
_INLINE_SHELL_RE = re.compile(r"!`([^`\n]+)`")

# Cap inline-shell output.
_INLINE_SHELL_MAX_OUTPUT = 4000

# Mirror of container_exec._BLOCKED_BINARIES — keep the two frozensets in sync.
# Shell snippets in SKILL.md files are developer-authored, not LLM-generated,
# but a misplaced interactive binary (e.g. `!`vim file``) would still hang
# skill preprocessing. Block early, fail clearly.
_BLOCKED_INLINE_SHELL_BINARIES: frozenset[str] = frozenset({
    "sudo",
    "ssh",
    "nano",
    "vim",
    "vi",
    "top",
    "htop",
    "watch",
    "less",
    "more",
})


def substitute_template_vars(
    content: str,
    *,
    project_root: Path | None = None,
    scratch_dir: Path | None = None,
    session_id: str | None = None,
) -> str:
    """Replace ``${PROJECT_ROOT}``, ``${SESSION_ID}``, ``${SCRATCH_DIR}``.

    Only substitutes tokens for which a concrete value is available;
    unresolved tokens are left in place.
    """
    if not content:
        return content

    project_str = str(project_root) if project_root else None
    scratch_str = str(scratch_dir) if scratch_dir else None

    def _replace(match: re.Match) -> str:
        token = match.group(1)
        if token == "PROJECT_ROOT" and project_str:
            return project_str
        if token == "SCRATCH_DIR" and scratch_str:
            return scratch_str
        if token == "SESSION_ID" and session_id:
            return str(session_id)
        return match.group(0)

    return _SKILL_TEMPLATE_RE.sub(_replace, content)


def _run_inline_shell(
    command: str,
    cwd: Path | None,
    timeout: int,
) -> str:
    """Execute a single inline-shell snippet and return its stdout.

    Failures return an ``[inline-shell error: ...]`` marker.
    """
    binary = command.split(maxsplit=1)[0] if command.split() else ""
    if binary in _BLOCKED_INLINE_SHELL_BINARIES:
        return f"[inline-shell blocked: interactive binary '{binary}' is not allowed]"

    try:
        completed = subprocess.run(
            ["bash", "-c", command],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"[inline-shell timeout after {timeout}s: {command}]"
    except FileNotFoundError:
        return "[inline-shell error: bash not found]"
    except OSError as exc:
        return f"[inline-shell error: {exc}]"

    output = (completed.stdout or "").rstrip("\n")
    if not output and completed.stderr:
        output = completed.stderr.rstrip("\n")
    if len(output) > _INLINE_SHELL_MAX_OUTPUT:
        output = output[:_INLINE_SHELL_MAX_OUTPUT] + "...[truncated]"
    return output


def expand_inline_shell(
    content: str,
    skill_dir: Path | None,
    timeout: int = 10,
) -> str:
    """Replace every ``!`cmd`` snippet in content with its stdout.

    Runs each snippet with the skill directory as CWD.
    """
    if "!`" not in content:
        return content

    def _replace(match: re.Match) -> str:
        cmd = match.group(1).strip()
        if not cmd:
            return ""
        return _run_inline_shell(cmd, skill_dir, timeout)

    return _INLINE_SHELL_RE.sub(_replace, content)
