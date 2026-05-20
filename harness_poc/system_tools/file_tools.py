"""Host-level file operations — direct Python I/O.

These are LLM-callable primitives. They execute synchronously on the host
filesystem. No Docker containers, no sub-agents, no LLM involvement.
"""

from __future__ import annotations

import ast as _ast
import difflib
import json as _json
import re
import shutil
import subprocess
import tomllib as _toml
from contextlib import suppress
from pathlib import Path
from typing import Any

from harness_poc.core.permissions import PROTECTED_PATHS
from harness_poc.system_tools import register as _register

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LINES = 2000
MAX_LINE_LENGTH = 2000
MAX_FILE_SIZE = 50 * 1024  # 50 KB
DEFAULT_READ_LIMIT = 500
MAX_READ_CHARS = 100_000
ASCII_CONTROL_BOUNDARY = 32
BINARY_NON_PRINTABLE_RATIO = 0.30
MIN_SUBSTRING_HINT_LENGTH = 2
RG_PARSE_PARTS = 2
RG_SEARCH_ERROR_EXIT_CODE = 2
IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}
)
BINARY_EXTENSIONS = (
    frozenset(
        {
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
            ".7z",
            ".rar",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".o",
            ".a",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
            ".mkv",
            ".flac",
            ".wav",
            ".ttf",
            ".otf",
            ".woff",
            ".woff2",
            ".pyc",
            ".pyo",
            ".class",
            ".db",
            ".sqlite",
            ".sqlite3",
            ".bin",
            ".dat",
            ".pkl",
            ".pickle",
            ".DS_Store",
        }
    )
    | IMAGE_EXTENSIONS
)

# Additional system paths to protect beyond permissions.PROTECTED_PATHS
_WRITE_DENIED_PREFIXES: tuple[str, ...] = (
    str(Path.home() / ".ssh"),
    str(Path.home() / ".aws"),
    str(Path.home() / ".gnupg"),
    "/etc/",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expand_path(path: str) -> str:
    """Expand ``~`` and ``~user`` to absolute paths."""
    if path.startswith("~"):
        return str(Path(path).expanduser())
    return path


def _resolve_abs(path: str, project_root: Path | None = None) -> Path:
    """Resolve a path to absolute, optionally relative to project root."""
    expanded = _expand_path(path)
    p = Path(expanded)
    if not p.is_absolute() and project_root is not None:
        p = project_root / p
    return p.resolve()


def _is_protected(path: str) -> bool:
    """Check if a path is in the write-deny list."""
    resolved = str(Path(path).resolve())
    for prefix in _WRITE_DENIED_PREFIXES:
        if resolved.startswith(prefix):
            return True
    for protected in PROTECTED_PATHS:
        if resolved.endswith(protected) or f"/{protected}" in resolved:
            return True
    return False


def _is_binary_by_extension(path: str) -> bool:
    ext = Path(path).suffix.lower()
    return ext in BINARY_EXTENSIONS


def _is_image_by_extension(path: str) -> bool:
    ext = Path(path).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def _is_likely_binary_content(sample: str) -> bool:
    """Heuristic: >30% non-printable chars in first 1000 bytes."""
    if not sample:
        return False
    check = sample[:1000]
    if "\x00" in check:
        return True
    non_printable = sum(
        1
        for c in check
        if ord(c) < ASCII_CONTROL_BOUNDARY and c not in "\n\r\t"
    )
    return non_printable / len(check) > BINARY_NON_PRINTABLE_RATIO


def _add_line_numbers(content: str, start_line: int = 1) -> str:
    """Format as ``     1|content`` (6-digit right-aligned line number)."""
    lines = content.split("\n")
    numbered: list[str] = []
    for i, raw_line in enumerate(lines, start=start_line):
        display_line = raw_line
        if len(display_line) > MAX_LINE_LENGTH:
            display_line = display_line[:MAX_LINE_LENGTH] + "... [truncated]"
        numbered.append(f"{i:6d}|{display_line}")
    return "\n".join(numbered)


def _suggest_similar_files(path: str, project_root: Path) -> list[str]:
    """Return up to 5 similar filenames from the same directory."""
    abs_path = _resolve_abs(path, project_root)
    dir_path = abs_path.parent
    filename = abs_path.name
    if not dir_path.exists():
        return []

    basename_no_ext = Path(filename).stem
    lower_name = filename.lower()
    scored: list[tuple[int, str]] = []

    try:
        for entry in sorted(dir_path.iterdir()):
            if not entry.is_file():
                continue
            ename = entry.name
            lname = ename.lower()
            score = 0
            if lname == lower_name:
                score = 100
            elif Path(ename).stem.lower() == basename_no_ext.lower():
                score = 90
            elif lname.startswith(lower_name) or lower_name.startswith(lname):
                score = 70
            elif lower_name in lname:
                score = 60
            elif lname in lower_name and len(lname) > MIN_SUBSTRING_HINT_LENGTH:
                score = 40
            if score > 0:
                scored.append((score, str(entry)))
    except OSError:
        pass

    scored.sort(key=lambda x: -x[0])
    return [fp for _, fp in scored[:5]]


def _run_rg(
    args: list[str], cwd: Path | None = None, timeout: int = 60
) -> tuple[str, int]:
    """Run ripgrep, return (stdout, exit_code)."""
    rg_path = shutil.which("rg")
    if rg_path is None:
        return "", -1
    try:
        result = subprocess.run(  # noqa: S603
            [rg_path, *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", 124
    else:
        return result.stdout, result.returncode


def _run_find(
    path: str, pattern: str, limit: int, offset: int, cwd: Path | None
) -> tuple[list[str], int]:
    """Fallback: find files by name pattern (no ripgrep)."""
    find_path = shutil.which("find")
    if find_path is None:
        return [], 0
    try:
        result = subprocess.run(  # noqa: S603
            [find_path, path, "-type", "f", "-name", pattern],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], 0
    else:
        all_files = [f for f in result.stdout.strip().split("\n") if f]
        page = all_files[offset : offset + limit]
        return page, len(all_files)


# ---------------------------------------------------------------------------
# Linting (in-process, no subprocess)
# ---------------------------------------------------------------------------


def _lint_python(content: str) -> tuple[bool, str]:
    try:
        _ast.parse(content)
    except SyntaxError as e:
        loc = f" (line {e.lineno}, column {e.offset})" if e.lineno else ""
        return False, f"SyntaxError: {e.msg}{loc}"
    else:
        return True, ""


def _lint_json(content: str) -> tuple[bool, str]:
    try:
        _json.loads(content)
    except _json.JSONDecodeError as e:
        return (
            False,
            f"JSONDecodeError: {e.msg} (line {e.lineno}, column {e.colno})",
        )
    else:
        return True, ""


def _lint_yaml(content: str) -> tuple[bool, str]:
    try:
        import yaml as _yaml  # noqa: PLC0415
    except ImportError:
        return True, "__SKIP__"
    try:
        _yaml.safe_load(content)
    except _yaml.YAMLError as e:
        return False, f"YAMLError: {e}"
    else:
        return True, ""


def _lint_toml(content: str) -> tuple[bool, str]:
    try:
        _toml.loads(content)
    except _toml.TOMLDecodeError as e:
        return False, f"{type(e).__name__}: {e}"
    else:
        return True, ""


_LINTERS: dict[str, Any] = {
    ".py": _lint_python,
    ".json": _lint_json,
    ".yaml": _lint_yaml,
    ".yml": _lint_yaml,
    ".toml": _lint_toml,
}


def _lint_file(path: str, content: str) -> tuple[bool, str]:
    """Run the appropriate in-process linter for a file extension."""
    ext = Path(path).suffix.lower()
    linter = _LINTERS.get(ext)
    if linter is None:
        return True, ""  # No linter for this extension
    ok, err = linter(content)
    if err == "__SKIP__":
        return True, ""
    return ok, err


# ---------------------------------------------------------------------------
# Fuzzy matching (3 strategies)
# ---------------------------------------------------------------------------


def _fuzzy_find_and_replace(  # noqa: PLR0911, PLR0912
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,  # noqa: FBT001, FBT002
) -> tuple[str, int, str | None]:
    """Find and replace using a 3-strategy chain.

    Returns (new_content, match_count, strategy_name).
    Strategy is None on failure.
    """
    if not old_string:
        return content, 0, None
    if old_string == new_string:
        return content, 0, None

    # Strategy 1: exact match
    count = content.count(old_string)
    if count > 0:
        if replace_all:
            return content.replace(old_string, new_string), count, "exact"
        if count == 1:
            return content.replace(old_string, new_string), 1, "exact"
        # Multiple matches but replace_all=False: report ambiguity
        return content, count, None

    # Strategy 2: line-trimmed (strip whitespace per line)
    old_lines = [line.strip() for line in old_string.split("\n")]
    content_lines = content.split("\n")
    new_lines = new_string.split("\n")

    match_indices: list[int] = []
    for i in range(len(content_lines) - len(old_lines) + 1):
        window = [
            line.strip() for line in content_lines[i : i + len(old_lines)]
        ]
        if window == old_lines:
            match_indices.append(i)

    if match_indices:
        if replace_all or len(match_indices) == 1:
            result_lines: list[str] = []
            last_end = 0
            for start in match_indices:
                result_lines.extend(content_lines[last_end:start])
                result_lines.extend(new_lines)
                last_end = start + len(old_lines)
            result_lines.extend(content_lines[last_end:])
            return "\n".join(result_lines), len(match_indices), "line_trimmed"
        return content, len(match_indices), None  # Multiple not allowed

    # Strategy 3: whitespace-normalized (collapse multiple spaces)
    def _normalize(text: str) -> str:
        return re.sub(r"[ \t]+", " ", text)

    old_normalized = _normalize(old_string)
    content_normalized = _normalize(content)

    count = content_normalized.count(old_normalized)
    if count > 0:
        if replace_all or count == 1:
            # Find the actual occurrence in original content using normalized positions
            idx = content_normalized.find(old_normalized)
            if idx >= 0:
                end_idx = idx + len(old_normalized)
                # Match original boundaries
                result = content[:idx] + new_string
                remaining = content[end_idx:]
                if replace_all:
                    while True:
                        remaining_norm = _normalize(remaining)
                        next_idx = remaining_norm.find(old_normalized)
                        if next_idx < 0:
                            break
                        # Find the boundary in the original remaining text
                        next_end = next_idx + len(old_normalized)
                        result += remaining[:next_idx] + new_string
                        remaining = remaining[next_end:]
                result += remaining
                return result, count, "whitespace_normalized"
        return content, count, None  # Multiple not allowed

    return content, 0, None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def read_file(  # noqa: PLR0911
    path: str,
    offset: int = 1,
    limit: int = 500,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Read a text file with line numbers and pagination."""
    project = Path(project_root) if project_root else None
    abs_path = _resolve_abs(path, project)

    # Validate
    offset = max(1, int(offset))
    limit = max(1, min(int(limit), MAX_LINES))

    if not abs_path.exists():
        similar = _suggest_similar_files(path, project or Path.cwd())
        return {
            "error": f"File not found: {path}",
            "similar_files": similar,
        }

    if not abs_path.is_file():
        return {"error": f"Not a file: {path}"}

    file_size = abs_path.stat().st_size
    str_path = str(abs_path)

    # Image redirect
    if _is_image_by_extension(str_path):
        return {
            "is_image": True,
            "file_size": file_size,
            "hint": "Image file detected. Use vision_analyze to inspect.",
        }

    # Binary guard
    if _is_binary_by_extension(str_path):
        return {
            "is_binary": True,
            "file_size": file_size,
            "error": f"Binary file — cannot display as text ({Path(str_path).suffix}).",
        }

    # Read and check content
    try:
        raw = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": f"Failed to read: {e}"}

    # Binary content check
    if _is_likely_binary_content(raw[:1000]):
        return {
            "is_binary": True,
            "file_size": file_size,
            "error": "Binary file — cannot display as text.",
        }

    lines = raw.split("\n")
    total_lines = len(lines)

    # Paginate
    start_idx = offset - 1
    end_idx = min(start_idx + limit, total_lines)
    page_lines = lines[start_idx:end_idx]
    page_content = "\n".join(page_lines)

    # Enforce max output chars
    numbered = _add_line_numbers(page_content, offset)
    if len(numbered) > MAX_READ_CHARS:
        numbered = numbered[:MAX_READ_CHARS] + "\n... [output truncated]"

    result: dict[str, Any] = {
        "content": numbered,
        "total_lines": total_lines,
        "file_size": file_size,
    }

    # Truncation hint
    if end_idx < total_lines:
        result["truncated"] = True
        result["hint"] = (
            f"Use offset={end_idx + 1} to continue reading "
            f"(showing {offset}-{end_idx} of {total_lines} lines)"
        )

    return result


def write_file(
    path: str,
    content: str,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Write content to a file, creating parent directories."""
    project = Path(project_root) if project_root else None
    abs_path = _resolve_abs(path, project)
    str_path = str(abs_path)

    # Protect sensitive paths
    if _is_protected(str_path):
        return {"error": f"Write denied: '{path}' is a protected path."}

    # Snapshot pre-write content for lint delta
    pre_content: str | None = None
    ext = Path(str_path).suffix.lower()
    if ext in _LINTERS and abs_path.exists():
        with suppress(OSError):
            pre_content = abs_path.read_text(encoding="utf-8")

    # Create parent directories
    dirs_created = False
    parent = abs_path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        dirs_created = True

    # Write
    try:
        abs_path.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"error": f"Failed to write: {e}"}

    bytes_written = abs_path.stat().st_size

    # Post-write lint with delta
    lint_info: dict[str, Any] | None = None
    if ext in _LINTERS:
        post_ok, post_err = _lint_file(str_path, content)
        if post_ok or not post_err:
            lint_info = {"status": "ok"}
        elif pre_content is not None:
            pre_ok, pre_err = _lint_file(str_path, pre_content)
            if pre_ok or not pre_err or pre_err == post_err:
                lint_info = {
                    "status": "warning",
                    "message": "Pre-existing lint errors — this write didn't introduce new ones.",
                    "output": post_err,
                }
            else:
                lint_info = {
                    "status": "error",
                    "message": "New lint errors introduced by this write.",
                    "output": post_err,
                }
        else:
            lint_info = {"status": "error", "output": post_err}

    result: dict[str, Any] = {
        "bytes_written": bytes_written,
        "dirs_created": dirs_created,
    }
    if lint_info:
        result["lint"] = lint_info

    return result


def patch(  # noqa: PLR0911
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,  # noqa: FBT001, FBT002
    project_root: str | None = None,
) -> dict[str, Any]:
    """Targeted find-and-replace edit in a file, with fuzzy matching."""
    project = Path(project_root) if project_root else None
    abs_path = _resolve_abs(path, project)
    str_path = str(abs_path)

    if _is_protected(str_path):
        return {"error": f"Write denied: '{path}' is a protected path."}

    if not abs_path.exists():
        return {"error": f"File not found: {path}"}

    # Read current content
    try:
        content = abs_path.read_text(encoding="utf-8")
    except OSError as e:
        return {"error": f"Failed to read: {e}"}

    # Fuzzy find-and-replace
    new_content, match_count, strategy = _fuzzy_find_and_replace(
        content, old_string, new_string, replace_all
    )

    if match_count == 0:
        error_msg = f"Could not find match for old_string in {path}"
        # Check if partial match exists (case-insensitive)
        lower_old = old_string.strip().lower()
        lower_content = content.lower()
        if lower_old in lower_content:
            error_msg += " (hint: a case-insensitive match exists — verify exact whitespace and indentation)"
        return {"error": error_msg}

    if not replace_all and match_count > 1 and strategy is None:
        return {
            "error": (
                f"Found {match_count} matches for old_string in {path}. "
                "Use replace_all=true to replace all, or make old_string more specific."
            )
        }

    # Write via write_file (gets lint + verification for free)
    write_result = write_file(path, new_content, project_root)
    if "error" in write_result:
        return {"error": f"Failed to write changes: {write_result['error']}"}

    # Generate unified diff
    old_lines = content.splitlines(keepends=True)
    new_lines_list = new_content.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines_list,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )

    result: dict[str, Any] = {
        "success": True,
        "diff": diff,
        "strategy": strategy,
        "match_count": match_count,
        "files_modified": [path],
    }
    if "lint" in write_result:
        result["lint"] = write_result["lint"]

    return result


def search_files(  # noqa: PLR0913
    pattern: str,
    target: str = "content",
    path: str = ".",
    file_glob: str | None = None,
    limit: int = 50,
    offset: int = 0,
    output_mode: str = "content",
    context: int = 0,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Search file contents (ripgrep) or find files by name."""
    project = Path(project_root) if project_root else None
    abs_path = _resolve_abs(path, project)
    cwd = abs_path if abs_path.is_dir() else abs_path.parent

    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 200))
    context = max(0, min(int(context), 10))

    if target == "files":
        return _search_files_by_name(pattern, str(abs_path), limit, offset, cwd)
    return _search_files_by_content(
        pattern,
        str(abs_path),
        file_glob,
        limit,
        offset,
        output_mode,
        context,
        cwd,
    )


def _search_files_by_content(  # noqa: PLR0912, PLR0913
    pattern: str,
    path: str,
    file_glob: str | None,
    limit: int,
    offset: int,
    output_mode: str,
    context: int,
    cwd: Path,
) -> dict[str, Any]:
    """Search inside files using ripgrep."""
    args = ["--line-number", "--no-heading", "--with-filename"]

    if context > 0:
        args.extend(["-C", str(context)])

    if file_glob:
        args.extend(["--glob", file_glob])

    if output_mode == "files_only":
        args.append("-l")
    elif output_mode == "count":
        args.append("-c")

    args.append(pattern)
    args.append(path)

    stdout, exit_code = _run_rg(args, cwd=cwd)

    if exit_code == -1:
        return {
            "error": "ripgrep (rg) is required. Install: https://github.com/BurntSushi/ripgrep"
        }
    if exit_code == RG_SEARCH_ERROR_EXIT_CODE and not stdout.strip():
        return {"error": "Search failed (exit code 2)"}

    if output_mode == "files_only":
        all_files = [f for f in stdout.strip().split("\n") if f]
        total = len(all_files)
        page = all_files[offset : offset + limit]
        return {"files": page, "total_count": total}

    if output_mode == "count":
        counts: dict[str, int] = {}
        for line in stdout.strip().split("\n"):
            if ":" in line:
                parts = line.rsplit(":", 1)
                if len(parts) == RG_PARSE_PARTS:
                    with suppress(ValueError):
                        counts[parts[0]] = int(parts[1])
        return {"counts": counts, "total_count": sum(counts.values())}

    # Content mode — parse match lines: "file:lineno:content"
    _match_re = re.compile(r"^([A-Za-z]:)?(.*?):(\d+):(.*)$")
    _dash_re = re.compile(r"^(.+?)-(\d+)-(.*)$")

    matches: list[dict[str, Any]] = []
    for line in stdout.strip().split("\n"):
        if not line or line == "--":
            continue
        m = _match_re.match(line)
        if m:
            matches.append(
                {
                    "path": (m.group(1) or "") + m.group(2),
                    "line": int(m.group(3)),
                    "content": m.group(4)[:500],
                }
            )
            continue
        # Context lines use dash separators
        if context > 0:
            dm = _dash_re.match(line)
            if dm:
                matches.append(
                    {
                        "path": dm.group(1),
                        "line": int(dm.group(2)),
                        "content": dm.group(3)[:500],
                    }
                )

    total = len(matches)
    page = matches[offset : offset + limit]

    result: dict[str, Any] = {"matches": page, "total_count": total}
    if total > offset + limit:
        result["truncated"] = True
    return result


def _search_files_by_name(
    pattern: str,
    path: str,
    limit: int,
    offset: int,
    cwd: Path,
) -> dict[str, Any]:
    """Find files by glob pattern using ripgrep --files."""
    glob_pattern = (
        f"*{pattern}"
        if "/" not in pattern and not pattern.startswith("*")
        else pattern
    )

    args = ["--files", "--sortr=modified", "-g", glob_pattern, path]
    stdout, exit_code = _run_rg(args, cwd=cwd, timeout=60)

    if exit_code == -1:
        # No ripgrep — fall back to find
        files, total = _run_find(path, pattern, limit, offset, cwd)
        return {"files": files, "total_count": total}

    if not stdout.strip():
        # retry without --sortr (older rg)
        args_plain = ["--files", "-g", glob_pattern, path]
        stdout, _exit = _run_rg(args_plain, cwd=cwd, timeout=60)

    all_files = [f for f in stdout.strip().split("\n") if f]
    page = all_files[offset : offset + limit]

    result: dict[str, Any] = {
        "files": page,
        "total_count": len(all_files),
    }
    if len(all_files) > offset + limit:
        result["truncated"] = True
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

_register(
    name="read_file",
    description=(
        "Read a text file with line numbers and pagination. "
        "Use this instead of cat/head/tail in terminal. "
        "Output format: 'LINE_NUM|CONTENT'. Suggests similar "
        "filenames if not found. Use offset and limit for large "
        "files. NOTE: Cannot read images or binary files — "
        "use vision_analyze for images."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (absolute, relative, or ~/path)",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed, default: 1)",
                "default": 1,
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum lines to read (default: 500, max: 2000)",
                "default": 500,
                "maximum": 2000,
            },
        },
        "required": ["path"],
    },
    handler=read_file,
)

_register(
    name="write_file",
    description=(
        "Write content to a file, completely replacing existing content. "
        "Use this instead of echo/cat heredoc in terminal. Creates parent "
        "directories automatically. OVERWRITES the entire file — "
        "use 'patch' for targeted edits. Auto-runs syntax checks on "
        ".py/.json/.yaml/.toml files; only NEW errors introduced by "
        "this write are surfaced."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path to the file to write (will be created if it doesn't exist, "
                    "overwritten if it does)"
                ),
            },
            "content": {
                "type": "string",
                "description": "Complete content to write to the file",
            },
        },
        "required": ["path", "content"],
    },
    handler=write_file,
)

_register(
    name="patch",
    description=(
        "Targeted find-and-replace edits in files. Uses fuzzy matching "
        "(3 strategies: exact, line-trimmed, whitespace-normalized) so "
        "minor whitespace differences won't break it. Returns a unified "
        "diff. Auto-runs syntax checks after editing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to edit.",
            },
            "old_string": {
                "type": "string",
                "description": (
                    "Exact text to find. Must be unique in the file unless "
                    "replace_all=True. Include surrounding context lines to ensure "
                    "uniqueness."
                ),
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text. Pass empty string to delete the matched text.",
            },
            "replace_all": {
                "type": "boolean",
                "description": (
                    "Replace all occurrences instead of requiring a unique match (default: false)"
                ),
                "default": False,
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
    handler=patch,
)

_register(
    name="search_files",
    description=(
        "Search file contents or find files by name. Uses ripgrep for "
        "fast, .gitignore-aware search. "
        "Content search (target='content'): Regex search inside files. "
        "File search (target='files'): Find files by glob pattern. "
        "Output modes: 'content' (matches with line numbers), "
        "'files_only' (file paths), 'count' (match counts per file)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": (
                    "Regex pattern for content search, or glob pattern (e.g., '*.py') "
                    "for file search"
                ),
            },
            "target": {
                "type": "string",
                "enum": ["content", "files"],
                "description": (
                    "'content' searches inside file contents, 'files' searches for files by name"
                ),
                "default": "content",
            },
            "path": {
                "type": "string",
                "description": (
                    "Directory or file to search in (default: current working directory)"
                ),
                "default": ".",
            },
            "file_glob": {
                "type": "string",
                "description": "Filter files by pattern (e.g., '*.py' to only search Python files)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default: 50)",
                "default": 50,
            },
            "offset": {
                "type": "integer",
                "description": "Skip first N results for pagination (default: 0)",
                "default": 0,
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_only", "count"],
                "description": (
                    "Output format: 'content' shows matching lines, 'files_only' lists "
                    "file paths, 'count' shows match counts"
                ),
                "default": "content",
            },
            "context": {
                "type": "integer",
                "description": "Number of context lines before and after each match",
                "default": 0,
            },
        },
        "required": ["pattern"],
    },
    handler=search_files,
)
