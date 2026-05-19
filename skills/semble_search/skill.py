from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any, Literal

from harness_poc.core.skill_context import SkillContext, SkillResult

SEARCH_MODES = {"hybrid", "semantic", "bm25"}
DEFAULT_TOP_K = 15
DEFAULT_MODE = "hybrid"
SEMBLE_TIMEOUT_SECONDS = 30
SEMBLE_PROGRESS_INTERVAL_SECONDS = 10

SemSearchAction = Literal["search", "find_related"]


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    """Run a Semble code search against the project codebase."""
    action: SemSearchAction = _parse_action(arguments.get("action"))

    if action == "find_related":
        return _find_related(ctx, arguments)

    return _search(ctx, arguments)


# --------------------------------------------------------------------------- #
#  search
# --------------------------------------------------------------------------- #


def _search(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return SkillResult(
            status="failed",
            content="semble_search requires a query string.",
            artifacts={"error": "missing_query"},
        )

    search_path = _resolve_path(ctx, arguments.get("path"))
    top_k = _parse_top_k(arguments.get("top_k"))
    mode = _parse_mode(arguments.get("mode"))
    include_text_files = bool(arguments.get("include_text_files", False))

    cmd = [
        _semble_binary(),
        "search",
        query,
        str(search_path),
        "--top-k",
        str(top_k),
        "--mode",
        mode,
    ]
    if include_text_files:
        cmd.append("--include-text-files")

    return _run_semble(ctx, cmd, query=query)


# --------------------------------------------------------------------------- #
#  find_related
# --------------------------------------------------------------------------- #


def _find_related(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    file_path = str(arguments.get("file_path", "")).strip()
    if not file_path:
        return SkillResult(
            status="failed",
            content=(
                "semble_search find_related requires a file_path "
                "(the file path shown in a prior search result)."
            ),
            artifacts={"error": "missing_file_path"},
        )

    line_raw = arguments.get("line")
    if line_raw is None:
        return SkillResult(
            status="failed",
            content="semble_search find_related requires a line number (1-indexed).",
            artifacts={"error": "missing_line"},
        )
    try:
        line = int(str(line_raw))
    except (ValueError, TypeError):
        return SkillResult(
            status="failed",
            content=f"Invalid line number: {line_raw!r}",
            artifacts={"error": "invalid_line"},
        )

    search_path = _resolve_path(ctx, arguments.get("path"))
    top_k = _parse_top_k(arguments.get("top_k"))
    include_text_files = bool(arguments.get("include_text_files", False))

    cmd = [
        _semble_binary(),
        "find-related",
        file_path,
        str(line),
        str(search_path),
        "--top-k",
        str(top_k),
    ]
    if include_text_files:
        cmd.append("--include-text-files")

    return _run_semble(ctx, cmd, query=f"{file_path}:{line}")


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #


def _run_semble(  # noqa: PLR0911
    ctx: SkillContext, cmd: list[str], *, query: str
) -> SkillResult:
    binary = cmd[0]
    if binary == "semble-not-found":
        return SkillResult(
            status="failed",
            content=(
                "Semble is not installed. Run: pip install semble\n"
                "Or: uv add semble\n\n"
                "See https://github.com/semblehq/semble for details."
            ),
            artifacts={"query": query, "error": "semble_not_installed"},
        )

    ctx.emit_tool_event(f"semble_search: running query={query!r}")
    started_at = time.monotonic()
    next_progress_at = started_at + SEMBLE_PROGRESS_INTERVAL_SECONDS

    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        while proc.poll() is None:
            elapsed = time.monotonic() - started_at
            if elapsed >= SEMBLE_TIMEOUT_SECONDS:
                proc.kill()
                stdout, stderr = proc.communicate()
                return _timed_out_result(query, stdout, stderr)
            if time.monotonic() >= next_progress_at:
                ctx.emit_tool_event(f"semble_search: still running ({int(elapsed)}s elapsed)")
                next_progress_at += SEMBLE_PROGRESS_INTERVAL_SECONDS
            time.sleep(0.2)
        stdout, stderr = proc.communicate()
    except subprocess.TimeoutExpired:
        return SkillResult(
            status="failed",
            content=f"Semble search timed out after {SEMBLE_TIMEOUT_SECONDS}s.",
            artifacts={"query": query, "error": "timeout"},
        )
    except OSError as exc:
        return SkillResult(
            status="failed",
            content=f"Failed to run Semble: {exc}",
            artifacts={"query": query, "error": str(exc)},
        )

    elapsed = time.monotonic() - started_at
    ctx.emit_tool_event(f"semble_search: finished in {elapsed:.1f}s")

    output = stdout.strip()
    if proc.returncode != 0:
        stderr = stderr.strip()
        return SkillResult(
            status="failed",
            content=f"Semble exited with code {proc.returncode}.\n\n{stderr or output}",
            artifacts={"query": query, "error": stderr, "exit_code": proc.returncode},
        )

    if not output:
        return SkillResult(
            status="success",
            content=f"No results found for: {query}",
            artifacts={"query": query, "results": []},
        )

    return SkillResult(
        status="success",
        content=output,
        artifacts={
            "query": query,
            "results": output.splitlines(),
        },
    )


def _timed_out_result(query: str, stdout: str, stderr: str) -> SkillResult:
    output = stdout.strip()
    error = stderr.strip()
    detail = f"\n\nPartial output:\n{output}" if output else ""
    if error:
        detail = f"{detail}\n\nstderr:\n{error}"
    return SkillResult(
        status="failed",
        content=f"Semble search timed out after {SEMBLE_TIMEOUT_SECONDS}s.{detail}",
        artifacts={
            "query": query,
            "error": "timeout",
            "partial_stdout": output,
            "stderr": error,
        },
    )


def _semble_binary() -> str:
    """Return the path to the semble binary, or a sentinel if missing."""
    path = shutil.which("semble")
    return path if path is not None else "semble-not-found"


def _resolve_path(ctx: SkillContext, raw: object) -> str:
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return str(ctx.project_root)


def _parse_action(raw: object) -> SemSearchAction:
    action = str(raw or "search").strip().lower()
    if action in {"find_related", "find-related", "findrelated"}:
        return "find_related"
    return "search"


def _parse_top_k(raw: object) -> int:
    try:
        val = int(str(raw))
    except (ValueError, TypeError):
        return DEFAULT_TOP_K
    return max(1, min(val, 50))


def _parse_mode(raw: object) -> str:
    mode = str(raw or DEFAULT_MODE).strip().lower()
    return mode if mode in SEARCH_MODES else DEFAULT_MODE
