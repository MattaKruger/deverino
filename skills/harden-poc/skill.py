"""Harden POC skill — maps spec to implementation, produces hardening report."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness_poc.core.skills import SkillResult

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillContext


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    """Generate a spec-to-implementation hardening review.

    Reads the spec, generates a diff, and produces a structured report
    mapping spec sections to implementation with findings.
    """
    spec_path = str(arguments.get("spec_path") or "")
    base_commit = str(arguments.get("base_commit") or "")
    head_commit = str(arguments.get("head_commit") or "HEAD")
    output_path = str(
        arguments.get("output_path")
        or f"docs/reviews/{datetime.now(tz=UTC).strftime('%Y-%m-%d')}-harden-review.md"
    )

    if not spec_path or not base_commit:
        return SkillResult(
            status="failed",
            content="spec_path and base_commit are required.",
            artifacts={},
        )

    spec_file = Path(spec_path)
    if not spec_file.exists():
        return SkillResult(
            status="failed",
            content=f"Spec not found: {spec_path}",
            artifacts={},
        )

    # Generate diff
    diff_result = subprocess.run(  # noqa: S603
        ["git", "diff", f"{base_commit}..{head_commit}", "--stat"],
        capture_output=True,
        text=True,
        cwd=ctx.config.project_root,
        check=False,
    )

    log_result = subprocess.run(  # noqa: S603
        ["git", "log", "--oneline", f"{base_commit}..{head_commit}"],
        capture_output=True,
        text=True,
        cwd=ctx.config.project_root,
        check=False,
    )

    # Read spec
    spec_content = spec_file.read_text(encoding="utf-8")

    # Build report scaffold
    date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    commit_count = len([l for l in log_result.stdout.strip().split("\n") if l])

    report = f"""# Implementation Review

**Date:** {date_str}
**Spec:** `{spec_path}`
**Base:** {base_commit}
**Head:** {head_commit}
**Commits:** {commit_count}

## Git Diff Stats

```
{diff_result.stdout}
```

## Commit Log

```
{log_result.stdout}
```

## Spec-to-Implementation Map

| Spec Section | Implementation | Status | Notes |
|---|---|---|---|
| (Fill in by reading spec and implementation) | | | |

## Findings

(Fill in by reviewing each changed file against the spec)

## Hardening Priorities

1. (Blockers)
2. (Should-fix)
3. (Tech debt)
4. (Accepted)

## Summary

Review complete. See `skills/harden-poc/SKILL.md` for the review process.
"""

    # Write report
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report, encoding="utf-8")

    return SkillResult(
        status="success",
        content=f"Review scaffold written to {output_path}. Read the spec at {spec_path}, the diff stats above, and fill in the spec-to-implementation map by reviewing each changed file.",
        artifacts={
            "report_path": str(output_file),
            "spec_path": str(spec_file),
            "commit_count": commit_count,
            "diff_stat": diff_result.stdout,
        },
    )
