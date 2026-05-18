from __future__ import annotations

import shutil
import subprocess
from typing import Any, Literal

from harness_poc.core.skill_context import SkillContext, SkillResult

SEARCH_MODES = {"hybrid", "semantic", "bm25"}
DEFAULT_TOP_K = 5
DEFAULT_MODE = "hybrid"

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

    return _run_semble(cmd, query=query)


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

    return _run_semble(cmd, query=f"{file_path}:{line}")


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #


def _run_semble(cmd: list[str], *, query: str) -> SkillResult:
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

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SkillResult(
            status="failed",
            content="Semble search timed out after 120s.",
            artifacts={"query": query, "error": "timeout"},
        )
    except OSError as exc:
        return SkillResult(
            status="failed",
            content=f"Failed to run Semble: {exc}",
            artifacts={"query": query, "error": str(exc)},
        )

    output = proc.stdout.strip()
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
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
