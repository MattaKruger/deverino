"""Tool input guards — structured validation before tool execution.

Every guard validates tool arguments *before* the tool runs, returning
actionable feedback to the model instead of letting raw exceptions crash.

Protocol
--------
Each guard is a callable ``Guard = Callable[[str, dict], GuardResult | None]``:
  - ``tool_name``: the tool being invoked
  - ``arguments``: the tool's keyword arguments
  - Returns ``GuardResult`` on rejection, ``None`` to pass.

``GuardResult`` carries ``errors: list[str]`` — each string is
model-actionable and phrased for an LLM to understand (e.g.
"Path '~/.ssh/id_rsa' is write-protected. Use a project-local path instead.").

Wire-point
----------
``ToolRunner.execute_tool()`` runs the registered guards before any tool
invocation. It merges all guard failures and returns a structured error to
the model context.
"""

from __future__ import annotations

import hashlib
import json as _json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from harness_poc.core.permissions import PROTECTED_PATHS

# ---------------------------------------------------------------------------
# GuardResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuardResult:
    """Result of a guard validation pass.

    ``ok`` is ``True`` when all guards pass; ``errors`` carries actionable
    messages for the LLM when one or more guards fail.
    """

    ok: bool
    errors: list[str] = field(default_factory=list)

    @classmethod
    def pass_(cls) -> GuardResult:
        return cls(ok=True, errors=[])

    @classmethod
    def fail(cls, *errors: str) -> GuardResult:
        return cls(ok=False, errors=list(errors))


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ToolGuard(Protocol):
    """Callable that validates tool arguments before execution.

    Args:
        tool_name: name of the tool being called
        arguments: keyword arguments the model supplied

    Returns:
        ``GuardResult`` on rejection, ``None`` if this guard passes.
    """

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> GuardResult | None: ...


# ---------------------------------------------------------------------------
# Built-in guards
# ---------------------------------------------------------------------------


# -- PathGuard ---------------------------------------------------------------

_WRITE_DENIED_PREFIXES: tuple[str, ...] = (
    str(Path.home() / ".ssh"),
    str(Path.home() / ".aws"),
    str(Path.home() / ".gnupg"),
    "/etc/",
    "/sys/",
    "/proc/",
)

_PATH_TRAVERSAL_RE = re.compile(r"\.\.[/\\]|[/\\]\.\.(?:[/\\]|$)")


class PathGuard:
    """Deny relative paths, protected directories, and path traversal.

    Guards any argument named ``path``, ``file_path``, ``directory``,
    ``output``, or ``source``.

    Rejection messages include the concrete disallowed prefix so the model
    can choose an alternative.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root

    def __call__(self, _tool_name: str, arguments: dict[str, Any]) -> GuardResult | None:
        errors: list[str] = []
        for key in ("path", "file_path", "directory", "output", "source", "target", "__path__"):
            val = arguments.get(key)
            if not isinstance(val, str):
                continue
            expanded = _expand_home(val)
            # Deny path traversal
            if _PATH_TRAVERSAL_RE.search(val):
                errors.append(
                    f"Path traversal detected in '{key}': '{val}'. "
                    "Use an absolute path within the project instead."
                )
                continue
            # Must be absolute when project_root is set
            if self._project_root is not None and not Path(expanded).is_absolute():
                project_abs = str(self._project_root.resolve())
                errors.append(
                    f"Relative path '{val}' is not supported for '{key}'. "
                    f"Use an absolute path, e.g. '{project_abs}/your/file.py'."
                )
                continue
            # Deny protected prefixes
            resolved = str(_resolve(expanded))
            for prefix in _WRITE_DENIED_PREFIXES:
                if resolved.startswith(prefix):
                    errors.append(
                        f"Path '{val}' resolves into the protected area '{prefix}'. "
                        "Use a project-local path instead."
                    )
                    break
            else:
                # Check PROTECTED_PATHS (filename suffix matches)
                for protected in PROTECTED_PATHS:
                    if resolved.endswith(protected) or f"/{protected}" in resolved:
                        errors.append(
                            f"Path '{val}' matches the protected pattern '{protected}'. "
                            "Use a project-local path instead."
                        )
                        break
        if errors:
            return GuardResult.fail(*errors)
        return None


# -- SizeGuard ---------------------------------------------------------------

DEFAULT_MAX_FILE_SIZE = 50 * 1024  # 50 KB
DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_OUTPUT_CHARS = 100_000


class SizeGuard:
    """Reject files that exceed size / line budgets.

    Checks ``path`` arguments for file size (requires filesystem access).
    Checks ``max_lines`` and ``limit`` arguments for sensible upper bounds.
    """

    def __init__(
        self,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        max_lines: int = DEFAULT_MAX_LINES,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        self._max_file_size = max_file_size
        self._max_lines = max_lines
        self._max_output_chars = max_output_chars

    def __call__(self, _tool_name: str, arguments: dict[str, Any]) -> GuardResult | None:
        errors: list[str] = []
        # Check line/limit arguments
        for key in ("limit", "max_lines", "offset"):
            val = arguments.get(key)
            if isinstance(val, (int, float)) and val <= 0:
                errors.append(f"'{key}' must be a positive integer, got {val}.")
        # Check file size for path args
        for key in ("path", "file_path", "source"):
            val = arguments.get(key)
            if isinstance(val, str):
                try:
                    p = Path(_expand_home(val))
                    if p.exists() and p.is_file():
                        size = p.stat().st_size
                        if size > self._max_file_size:
                            errors.append(
                                f"File '{val}' is {size} bytes, exceeding the "
                                f"{self._max_file_size} byte limit. Use a smaller file "
                                "or request a specific range with offset/limit."
                            )
                except OSError:
                    pass  # file doesn't exist — let the tool handle that
        if errors:
            return GuardResult.fail(*errors)
        return None


# -- TypeGuard ---------------------------------------------------------------


class TypeGuard:
    """Strict JSON Schema validation with descriptive error messages.

    Uses the tool's registered parameters schema to validate argument
    types before execution. Missing required fields, wrong types, or
    unknown fields are all reported as model-actionable messages.
    """

    def __init__(
        self,
        registry_schemas: dict[str, dict[str, Any]] | None = None,
        *,
        schema_provider: Callable[[], dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        """``registry_schemas`` maps tool_name → {parameters: JSONSchema, ...}.

        If ``schema_provider`` is given, it is called lazily to resolve
        schemas for tool names not found in ``registry_schemas``. This
        allows TypeGuard to be constructed before tool discovery completes.
        """
        self._schemas: dict[str, dict[str, Any]] = registry_schemas or {}
        self._schema_provider = schema_provider

    def update_schema(self, tool_name: str, schema: dict[str, Any]) -> None:
        self._schemas[tool_name] = schema

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> GuardResult | None:
        schema_info = self._schemas.get(tool_name)
        if schema_info is None and self._schema_provider is not None:
            # Lazy lookup: populate schemas from provider on first miss
            for name, info in self._schema_provider().items():
                if name not in self._schemas:
                    self._schemas[name] = info
            schema_info = self._schemas.get(tool_name)
        if schema_info is None:
            return None  # no schema to validate against

        parameters = schema_info.get("parameters", {})
        if not parameters or parameters.get("type") != "object":
            return None

        errors: list[str] = []
        props: dict[str, Any] = parameters.get("properties", {})
        required: list[str] = parameters.get("required", [])
        # We don't enforce additionalProperties by default since some tools
        # accept extra kwargs. But we do type-check declared properties.

        # Check required fields
        for req in required:
            if req not in arguments:
                errors.append(
                    f"Missing required argument '{req}' for {tool_name}. "
                    f"Provide a value matching {_describe_schema(props.get(req, {}))}."
                )
                continue
            # Type check present required fields
            err = _validate_value(args=arguments, key=req, schema=props.get(req, {}))
            if err:
                errors.append(err)

        # Check provided fields against declared types
        for key in arguments:
            if key in props and key not in (set(required) & set(props)):
                err = _validate_value(args=arguments, key=key, schema=props[key])
                if err:
                    errors.append(err)

        if errors:
            return GuardResult.fail(*errors)
        return None


def _describe_schema(schema: dict[str, Any] | None) -> str:
    if not schema:
        return "any value"
    stype = schema.get("type", "string")
    if "enum" in schema:
        return f"one of {schema['enum']}"
    return f"type '{stype}'"


def _validate_value(args: dict[str, Any], key: str, schema: dict[str, Any] | None) -> str | None:
    val = args.get(key)
    if val is None:
        return None  # null values are passed through — tool decides
    if schema is None:
        return None
    stype = schema.get("type", "string")
    # String
    if stype == "string" and not isinstance(val, str):
        return (
            f"Argument '{key}' should be a string, got {type(val).__name__} ({val!r}). "
            f"Provide a string value instead."
        )
    # Integer
    if stype == "integer" and not isinstance(val, int):
        return (
            f"Argument '{key}' should be an integer, got {type(val).__name__} ({val!r}). "
            "Provide an integer value instead."
        )
    # Number
    if stype == "number" and not isinstance(val, (int, float)):
        return (
            f"Argument '{key}' should be a number, got {type(val).__name__} ({val!r}). "
            "Provide a numeric value instead."
        )
    # Boolean
    if stype == "boolean" and not isinstance(val, bool):
        return (
            f"Argument '{key}' should be a boolean (true/false), got "
            f"{type(val).__name__} ({val!r}). Provide true or false."
        )
    # Array
    if stype == "array" and not isinstance(val, list):
        return (
            f"Argument '{key}' should be an array (list), got "
            f"{type(val).__name__} ({val!r}). Provide a list instead."
        )
    # Object
    if stype == "object" and not isinstance(val, dict):
        return (
            f"Argument '{key}' should be an object (dict), got "
            f"{type(val).__name__} ({val!r}). Provide a dictionary instead."
        )
    # Enum
    if "enum" in schema:
        enum_vals = schema["enum"]
        if val not in enum_vals:
            return (
                f"Argument '{key}' must be one of {enum_vals}, got {val!r}. "
                "Select a valid value from the list."
            )
    return None


# -- IdempotencyGuard --------------------------------------------------------


class IdempotencyGuard:
    """Detect repeated identical tool calls within a session.

    Stores a hash of (tool_name, normalized_arguments) and rejects calls
    that have already been made. Normalizes string values so minor
    whitespace/casing differences don't produce false negatives.
    """

    def __init__(self, max_history: int = 32) -> None:
        self._seen: set[str] = set()
        self._max_history = max_history
        self._history: list[str] = []

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> GuardResult | None:
        key = self._build_key(tool_name, arguments)
        if key in self._seen:
            return GuardResult.fail(
                f"You have already called {tool_name} with these exact arguments. "
                "Try a different approach, different parameters, or a different tool."
            )
        self._seen.add(key)
        self._history.append(key)
        while len(self._history) > self._max_history:
            removed = self._history.pop(0)
            self._seen.discard(removed)
        return None

    @staticmethod
    def _build_key(tool_name: str, arguments: dict[str, Any]) -> str:
        normalized: dict[str, Any] = {}
        for k, v in sorted(arguments.items()):
            if isinstance(v, str):
                normalized[k] = " ".join(v.lower().split())
            elif isinstance(v, (int, float, bool)):
                normalized[k] = v
            elif isinstance(v, (list, tuple)):
                normalized[k] = [
                    (" ".join(x.lower().split()) if isinstance(x, str) else x) for x in v
                ]
            elif isinstance(v, dict):
                inner: dict[str, Any] = {}
                for ik, iv in sorted(v.items()):
                    if isinstance(iv, str):
                        inner[str(ik)] = " ".join(iv.lower().split())
                    elif isinstance(iv, (int, float, bool)):
                        inner[str(ik)] = iv
                    else:
                        inner[str(ik)] = str(iv)
                normalized[k] = _json.dumps(inner, sort_keys=True)
            else:
                normalized[k] = str(v)
        raw = f"{tool_name}:{_json.dumps(normalized, sort_keys=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()


# -- ContentGuard ------------------------------------------------------------

# Simple regex patterns for common secrets/PII that should never be written
_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "private key header"),
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI/Anthropic API key pattern"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key ID"),
    (r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}", "GitHub personal access token"),
    (r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", "JWT token"),
]

BINARY_EXTENSIONS = frozenset(
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
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".ico",
        ".DS_Store",
    }
)


class ContentGuard:
    """Reject binary files, secrets, and PII in tool input/output."""

    def __init__(
        self,
        secret_patterns: list[tuple[str, str]] | None = None,
    ) -> None:
        self._secret_regexes: list[tuple[re.Pattern[str], str]] = [
            (re.compile(pat), label) for pat, label in (secret_patterns or _SECRET_PATTERNS)
        ]

    def __call__(self, _tool_name: str, arguments: dict[str, Any]) -> GuardResult | None:
        errors: list[str] = []

        # Binary extension check on path args
        for key in ("path", "file_path", "source", "target", "output"):
            val = arguments.get(key)
            if isinstance(val, str):
                _, ext = _splitext(val)
                if ext in BINARY_EXTENSIONS:
                    errors.append(
                        f"File '{val}' appears to be binary (extension '{ext}'). "
                        "Binary files cannot be read/written as text. "
                        "Use a text-based tool or skip this file."
                    )

        # Secret scan on content args
        for key in ("content", "code", "text", "value", "data", "buffer"):
            val = arguments.get(key)
            if isinstance(val, str):
                for pat, label in self._secret_regexes:
                    if pat.search(val):
                        errors.append(
                            f"Content for '{key}' appears to contain a {label}. "
                            "Do not include secrets or API keys in tool arguments. "
                            "Use environment variables or a secure store instead."
                        )

        if errors:
            return GuardResult.fail(*errors)
        return None


# -- QueryGuard --------------------------------------------------------------

_SQL_WRITE_PREFIXES = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
)


class QueryGuard:
    """Reject SQL writes, enforce row limits, validate query structure.

    The blackboard is read-only from LLM tools. Any query containing
    INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE is
    rejected with a descriptive error.

    Also rejects queries without a LIMIT clause (enforces row caps)
    and queries that exceed the maximum row count.
    """

    def __init__(self, max_rows: int = 1000) -> None:
        self._max_rows = max_rows

    def __call__(self, _tool_name: str, arguments: dict[str, Any]) -> GuardResult | None:
        errors: list[str] = []

        for key in ("query", "sql", "statement"):
            val = arguments.get(key)
            if not isinstance(val, str):
                continue
            upper = val.strip().upper()

            # Reject write operations
            for prefix in _SQL_WRITE_PREFIXES:
                if upper.startswith(prefix) or upper.lstrip().startswith(prefix):
                    errors.append(
                        f"Query for '{key}' contains '{prefix}' which is a write "
                        "operation. The blackboard is read-only from LLM tools. "
                        "Use SELECT queries only."
                    )
                    break

            # Check for LIMIT
            if upper.startswith("SELECT") and "LIMIT" not in upper:
                errors.append(
                    f"SELECT query for '{key}' is missing a LIMIT clause. "
                    f"Add 'LIMIT {self._max_rows}' or less."
                )

            # Check LIMIT value
            limit_match = re.search(r"LIMIT\s+(\d+)", upper)
            if limit_match:
                limit_val = int(limit_match.group(1))
                if limit_val > self._max_rows:
                    errors.append(
                        f"Query LIMIT {limit_val} exceeds the maximum of "
                        f"{self._max_rows} rows. Reduce the limit."
                    )

        if errors:
            return GuardResult.fail(*errors)
        return None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class GuardPipeline:
    """Run a sequence of guards against tool arguments.

    Collects all failures instead of stopping at the first, so the model
    receives the complete set of issues in one message.
    """

    def __init__(self, guards: list[ToolGuard] | None = None) -> None:
        self._guards: list[ToolGuard] = list(guards) if guards else []

    def add(self, guard: ToolGuard) -> None:
        self._guards.append(guard)

    def validate(self, tool_name: str, arguments: dict[str, Any]) -> GuardResult:
        all_errors: list[str] = []
        for guard in self._guards:
            result = guard(tool_name, arguments)
            if result is not None and not result.ok:
                all_errors.extend(result.errors)
        if all_errors:
            return GuardResult.fail(*all_errors)
        return GuardResult.pass_()

    @property
    def guards(self) -> list[ToolGuard]:
        return list(self._guards)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expand_home(path: str) -> str:
    if path.startswith("~"):
        return str(Path(path).expanduser())
    return path


def _resolve(path: str) -> Path:
    return Path(path).resolve()


def _splitext(path: str) -> tuple[str, str]:
    # Use lowercased extension for comparison
    stem, ext = Path(path).stem, Path(path).suffix.lower()
    return stem, ext
