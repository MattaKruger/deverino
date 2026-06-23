"""Skill compiler — index-time pseudocode extraction pipeline.

Runs when a SKILL.md changes (detected via mtime) and produces a
structured SkillBundle from the raw markdown prose.

Stages (see docs/plans/2026-06-20-skill-pseudocode-refactor.md):
  1. Parser   — extract procedural units from markdown body
  2. Clustering  — per-skill similarity grouping
  3. Contract Extractor — LLM: generate TypedContracts per cluster
  4. Verifier  — deterministic: coverage, binding, replacement, risk
  5. BE (optional) — LLM: binding evidence, drop spurious call-sites
  6. RC (optional) — LLM: residual cleanup, fix prose-code conflicts
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import numpy as np  # noqa: TC002 — runtime use for similarity matrix
from pydantic import BaseModel, ConfigDict, Field

from harness_poc.core.skills.skill_bundle import (
    ActionTemplate,
    ErrorContract,
    InvokePattern,
    JsonSchemaProperty,
    SkillBundle,
    TypedContract,
)
from harness_poc.core.skills.skill_runner import (
    SkillRunner,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from numpy.typing import NDArray
    from pydantic_ai import Model

    from harness_poc.core.config import CompilerConfig
    from harness_poc.core.skills.skill_runner import SkillDocument

logger = logging.getLogger(__name__)

# ── Bundle cache ───────────────────────────────────────────────────────
_cache: dict[tuple[float, str], SkillBundle] = {}

# ── Compilation progress (queried by TUI) ──────────────────────────────
_compilation_progress: dict[str, Any] = {
    "running": False,
    "total": 0,
    "completed": 0,
    "errors": 0,
}

# ── Embedding instance (lazy-loaded) ───────────────────────────────────


class _Embedder(Protocol):
    def embed_batch(self, texts: list[str]) -> NDArray[np.float32]: ...


_embedder: _Embedder | None = None

# ── Regex patterns ─────────────────────────────────────────────────────
_FENCED_BLOCK_RE = re.compile(r"^```(\w*)\s*\n(.*?)\n```", re.DOTALL | re.MULTILINE)
_NUMBERED_STEP_RE = re.compile(r"^\d+\.\s+", re.MULTILINE)
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_EXECUTABLE_LANGS: frozenset[str] = frozenset({"shell", "sh", "bash", "python", "sql", "console"})
_SHELL_INVOCATION_RE = re.compile(r"^\s*(\w[\w\-]*)\s+.*$", re.MULTILINE)
_DERIVED_INPUTS: frozenset[str] = frozenset(
    {
        "action",
        "mode",
        "format",
        "file",
        "file_path",
        "path",
        "input",
        "output",
        "query",
        "name",
        "directory",
        "url",
        "pattern",
    }
)

# ── Verifier constants ─────────────────────────────────────────────────
_MIN_TOKEN_LENGTH_COVERAGE = 2
_MIN_TOKEN_LENGTH_RISK = 3
_PUNCTUATION_TABLE = str.maketrans("", "", "'\"`|;&()[]{}!@#$%^&*+=<>?,./:\\")

# ── LLM prompt templates ───────────────────────────────────────────────

_STAGE3_SYSTEM_PROMPT = """\
You are a skill contract extractor. Given a cluster of procedural units
from a skill's markdown body, extract a typed contract, action template,
and invoke pattern.

Return ONLY a JSON object matching this schema:
{
  "contract": {
    "name": "snake_case_identifier",
    "description": "one-line summary of what this procedure does",
    "inputs": {"param_name": {"type": "string", "description": "..."}},
    "outputs": {"output_name": {"type": "string", "description": "..."}},
    "side_effects": ["spawns subprocess", "writes to blackboard"],
    "preconditions": ["semble CLI installed"],
    "postconditions": ["status is 'success'"],
    "error_conditions": [
      {"condition": "CLI not found", "output_shape": "...", "recovery_hint": "..."}
    ],
    "cancellation_behavior": "safe"
  },
  "action_template": {
    "kind": "shell",
    "template": "exact command with {param} placeholders",
    "argument_map": {"param_name": "template_variable"}
  },
  "invoke_pattern": {
    "arguments": {"param": "concrete_value"},
    "rendered_call": "fully-substituted command"
  }
}

Rules:
- contract.name must be snake_case and unique within the skill.
- Map input names to the frontmatter parameter names provided below.
- Extract the exact CLI command from code blocks as the action template.
  Use {variable} placeholders for parameterized parts.
- Include known error modes from the prose (e.g., "tool not installed").
- cancellation_behavior: "safe" if no side effects on cancel,
  "unsafe" if partial writes possible, "unknown" if unclear.
- If NO executable code or CLI command is found in the cluster,
  set action_template and invoke_pattern to null.
"""
_STAGE3_SYSTEM_PROMPT = _STAGE3_SYSTEM_PROMPT.strip()


# ── LLM wire-format models ─────────────────────────────────────────────


class _LlmErrorContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition: str
    output_shape: str
    recovery_hint: str


class _LlmJsonProperty(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str = "string"
    description: str = ""


class _LlmContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    inputs: dict[str, _LlmJsonProperty] = Field(default_factory=dict)
    outputs: dict[str, _LlmJsonProperty] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    error_conditions: list[_LlmErrorContract] = Field(default_factory=list)
    cancellation_behavior: str = "unknown"


class _LlmActionTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    template: str
    argument_map: dict[str, str] = Field(default_factory=dict)


class _LlmInvokePattern(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arguments: dict[str, Any] = Field(default_factory=dict)
    rendered_call: str


class LlmContractOutput(BaseModel):
    """Top-level LLM response for a single cluster."""

    model_config = ConfigDict(extra="forbid")
    contract: _LlmContract
    action_template: _LlmActionTemplate | None = None
    invoke_pattern: _LlmInvokePattern | None = None


# ── Pipeline stage datatypes ───────────────────────────────────────────


@dataclass(slots=True)
class ProceduralUnit:
    """A single extractable instruction from a markdown body."""

    unit_type: Literal["heading_section", "code_block", "numbered_step"]
    content: str
    start_line: int
    end_line: int
    heading_title: str | None = None
    heading_level: int | None = None
    code_language: str | None = None
    code_content: str | None = None


@dataclass(slots=True)
class UnitCluster:
    """A group of procedural units that share a procedure."""

    unit_indices: list[int]
    texts: list[str]
    representative_text: str


# ── Public API ─────────────────────────────────────────────────────────


def compile_skill(
    skill_file: Path,
    *,
    skill_runner: SkillRunner,
    force: bool = False,
    model: Model | None = None,
    compiler_config: CompilerConfig | None = None,
) -> SkillBundle:
    """Compile a SKILL.md into a structured SkillBundle.

    When ``model`` is provided and ``compiler_config.enabled`` is True,
    Stages 3, 5, and 6 use LLM calls.  Without a model, Stage 3 falls
    back to regex extraction (stub) and Stages 5/6 are skipped.
    """
    mtime = _safe_mtime(skill_file)
    cache_key = (mtime, str(skill_file))
    if not force and cache_key in _cache:
        return _cache[cache_key]

    try:
        doc: SkillDocument = skill_runner.parse_skill_document(skill_file)
    except (ValueError, TypeError, OSError) as exc:
        logger.warning("Failed to parse skill file: %s", exc)
        bundle = _rejected_bundle(skill_file, [str(exc)])
        _cache[cache_key] = bundle
        return bundle

    bundle = _compile_from_doc(doc, model=model, compiler_config=compiler_config)
    _cache[cache_key] = bundle
    _write_bundle_json(skill_file, bundle)
    return bundle


def bundle_for_skill(
    name: str,
    *,
    skill_runner: SkillRunner,
) -> SkillBundle | None:
    """Return the compiled bundle for a named skill, or None if unbuilt.

    Checks the in-memory cache first.  On miss, falls back to reading
    the persisted ``.skill_bundle.json`` from disk — this handles the
    case where a different process (e.g. the dashboard) compiled the
    skill.
    """
    skill_file = _find_skill_file_by_name(name, skill_runner.skills_dirs)
    if skill_file is None:
        return None
    key = (_safe_mtime(skill_file), str(skill_file))
    bundle = _cache.get(key)
    if bundle is not None:
        return bundle
    # Cache miss — try the persisted JSON (written by another process)
    json_data = read_bundle_json(skill_file)
    if json_data is not None:
        bundle = _bundle_from_json(json_data)
        _cache[key] = bundle
        return bundle
    return None


def invalidate_cache() -> None:
    """Clear the bundle cache (e.g., after skill mutation)."""
    _cache.clear()


def _bundle_json_path(skill_file: Path) -> Path:
    """Return the path to the persisted bundle JSON for a skill."""
    return skill_file.parent / ".skill_bundle.json"


def _write_bundle_json(skill_file: Path, bundle: SkillBundle) -> None:
    """Persist the bundle as JSON next to the SKILL.md."""
    import dataclasses  # noqa: PLC0415

    try:
        data = dataclasses.asdict(bundle)
        # Convert non-serializable types
        data["compiled_at"] = bundle.compiled_at
        text = json.dumps(data, default=str)
        _bundle_json_path(skill_file).write_text(text, encoding="utf-8")
    except OSError:
        logger.warning("Failed to write bundle JSON for %s", skill_file, exc_info=True)


def read_bundle_json(skill_file: Path) -> dict[str, Any] | None:
    """Read a persisted bundle JSON, returning None if absent or corrupt."""
    path = _bundle_json_path(skill_file)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        logger.warning("Failed to read bundle JSON for %s", skill_file, exc_info=True)
        return None


def _bundle_from_json(data: dict[str, Any]) -> SkillBundle:
    """Reconstruct a SkillBundle from a persisted JSON dict.

    Used when the in-memory cache misses (e.g. the dashboard compiled the
    skill in a different process) but the .skill_bundle.json file exists
    on disk.
    """
    # Reconstruct contracts
    contracts: dict[str, TypedContract] = {}
    for cname, cdata in data.get("contracts", {}).items():
        inputs = {k: JsonSchemaProperty(v) for k, v in cdata.get("inputs", {}).items()}
        outputs = {k: JsonSchemaProperty(v) for k, v in cdata.get("outputs", {}).items()}
        error_conditions = [
            ErrorContract(
                condition=ec.get("condition", ""),
                output_shape=ec.get("output_shape", ""),
                recovery_hint=ec.get("recovery_hint", ""),
            )
            for ec in cdata.get("error_conditions", [])
        ]
        contracts[cname] = TypedContract(
            name=cdata.get("name", cname),
            description=cdata.get("description", ""),
            inputs=inputs,
            outputs=outputs,
            side_effects=cdata.get("side_effects", []),
            preconditions=cdata.get("preconditions", []),
            postconditions=cdata.get("postconditions", []),
            error_conditions=error_conditions,
            cancellation_behavior=cdata.get("cancellation_behavior", "unknown"),
            shared_from=cdata.get("shared_from"),
        )

    # Reconstruct templates
    templates: dict[str, ActionTemplate] = {}
    for tname, tdata in data.get("templates", {}).items():
        templates[tname] = ActionTemplate(
            kind=tdata.get("kind", "shell"),
            template=tdata.get("template", ""),
            argument_map=tdata.get("argument_map", {}),
        )

    # Reconstruct invoke patterns
    invoke_patterns: list[InvokePattern] = [
        InvokePattern(
            contract_name=ipdata.get("contract_name", ""),
            arguments=ipdata.get("arguments", {}),
            rendered_call=ipdata.get("rendered_call", ""),
        )
        for ipdata in data.get("invoke_patterns", [])
    ]

    # Reconstruct shared contracts (v2)
    shared_contracts: dict[str, TypedContract] = {}
    for scname, scdata in data.get("shared_contracts", {}).items():
        sc_inputs = {k: JsonSchemaProperty(v) for k, v in scdata.get("inputs", {}).items()}
        sc_outputs = {k: JsonSchemaProperty(v) for k, v in scdata.get("outputs", {}).items()}
        sc_errors = [
            ErrorContract(
                condition=ec.get("condition", ""),
                output_shape=ec.get("output_shape", ""),
                recovery_hint=ec.get("recovery_hint", ""),
            )
            for ec in scdata.get("error_conditions", [])
        ]
        shared_contracts[scname] = TypedContract(
            name=scdata.get("name", scname),
            description=scdata.get("description", ""),
            inputs=sc_inputs,
            outputs=sc_outputs,
            side_effects=scdata.get("side_effects", []),
            preconditions=scdata.get("preconditions", []),
            postconditions=scdata.get("postconditions", []),
            error_conditions=sc_errors,
            cancellation_behavior=scdata.get("cancellation_behavior", "unknown"),
        )

    return SkillBundle(
        metadata=data.get("metadata", {}),
        version=data.get("version", ""),
        entrypoint=data.get("entrypoint", {}),
        aliases=data.get("aliases", []),
        parent_skeleton=data.get("parent_skeleton", ""),
        contracts=contracts,
        templates=templates,
        invoke_patterns=invoke_patterns,
        raw_body=data.get("raw_body", ""),
        compilation_status=data.get("compilation_status", "rejected"),
        compilation_errors=data.get("compilation_errors", []),
        compiled_at=float(data.get("compiled_at", 0.0)),
        shared_contracts=shared_contracts,
    )


def set_compilation_progress(
    *,
    total: int | None = None,
    completed: int | None = None,
    errors: int | None = None,
    running: bool | None = None,
) -> None:
    """Update the shared compilation progress dict (thread-safe enough for read-only TUI)."""
    if total is not None:
        _compilation_progress["total"] = total
    if completed is not None:
        _compilation_progress["completed"] = completed
    if errors is not None:
        _compilation_progress["errors"] = errors
    if running is not None:
        _compilation_progress["running"] = running


def get_compilation_status() -> dict[str, Any]:
    """Return the current compilation progress for TUI display."""
    return dict(_compilation_progress)


# ── Compilation SSE fan-out ──────────────────────────────────────────

# Per-client SSE queues for fan-out (one queue per connected browser tab).
# Bounded to 50 events — a slow client that falls behind gets pruned rather
# than allowing unbounded memory growth.
_clients: set[asyncio.Queue[dict[str, Any]]] = set()
_clients_lock = Lock()
_MAX_CLIENT_QUEUE = 50


def subscribe_compile_events() -> asyncio.Queue[dict[str, Any]]:
    """Register a new SSE client. Returns a bounded queue the client consumes from."""
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_CLIENT_QUEUE)
    with _clients_lock:
        _clients.add(q)
    return q


def unsubscribe_compile_events(q: asyncio.Queue[dict[str, Any]]) -> None:
    """Remove a disconnected SSE client."""
    with _clients_lock:
        _clients.discard(q)


def publish_compile_event(event: dict[str, Any]) -> None:
    """Push an event to all connected SSE clients. Thread-safe.

    Called from daemon compilation threads (non-async).  Holds _clients_lock
    for the duration of the fan-out loop to prevent interleaving with
    subscribe/unsubscribe.  Contention is minimal because publish is
    infrequent (once per skill, not per token).
    """
    with _clients_lock:
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in _clients:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _clients.discard(q)


def _build_skill_compiled_event(
    skill_name: str,
    bundle: SkillBundle,
) -> dict[str, Any]:
    """Convert a SkillBundle into a skill_compiled SSE event dict."""
    from datetime import datetime  # noqa: PLC0415

    compiled_at_iso = datetime.fromtimestamp(bundle.compiled_at, tz=UTC).isoformat()

    return {
        "event": "skill_compiled",
        "skill_name": skill_name,
        "skill_type": bundle.metadata.get("type", "") if bundle.metadata else "",
        "version": bundle.metadata.get("version", "") if bundle.metadata else "",
        "compilation_status": bundle.compilation_status,
        "contract_count": len(bundle.contracts),
        "template_count": len(bundle.templates),
        "invoke_pattern_count": len(bundle.invoke_patterns),
        "error_count": len(bundle.compilation_errors),
        "compiled_at": compiled_at_iso,
        "contracts": [
            {
                "name": c.name,
                "description": c.description,
                "input_count": len(c.inputs),
                "output_count": len(c.outputs),
                "precondition_count": len(c.preconditions),
                "error_condition_count": len(c.error_conditions),
                "cancellation_behavior": c.cancellation_behavior,
            }
            for c in bundle.contracts.values()
        ],
        "templates": [
            {
                "name": name,
                "kind": t.kind,
                "template_preview": t.template,
            }
            for name, t in bundle.templates.items()
        ],
        "compilation_errors": list(bundle.compilation_errors),
        "aliases": list(bundle.aliases) if bundle.aliases else [],
    }


# ── Internal helpers ───────────────────────────────────────────────────


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        return 0.0


def _rejected_bundle(skill_file: Path, errors: list[str]) -> SkillBundle:
    """Minimal bundle for a skill that couldn't be compiled."""
    return SkillBundle(
        metadata={  # type: ignore[typeddict-item]
            "name": skill_file.parent.name,
            "description": "",
            "type": "unknown",
            "parameters": {},
            "auto_invokable": False,
            "permissions": {},
            "version": "",
            "aliases": [],
        },
        raw_body="",
        compilation_status="rejected",
        compilation_errors=errors,
        compiled_at=time.time(),
    )


def _find_skill_file_by_name(name: str, skills_dirs: tuple[Path, ...]) -> Path | None:
    """Walk skills directories looking for a SKILL.md with the given name."""
    for skills_dir in skills_dirs:
        if not skills_dir.exists():
            continue
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            try:
                doc = SkillRunner.parse_skill_document(skill_md)
            except ValueError, TypeError, OSError:
                continue
            if doc["metadata"]["name"] == name:
                return skill_md
    return None


# ── Pipeline ───────────────────────────────────────────────────────────


def _compile_from_doc(
    doc: SkillDocument,
    *,
    model: Model | None = None,
    compiler_config: CompilerConfig | None = None,
) -> SkillBundle:
    """Run stages 1-6 on a parsed SkillDocument."""
    metadata = doc["metadata"]
    raw_body = doc["body"]
    entrypoint = doc["entrypoint"]
    aliases = _resolve_aliases(metadata["name"])

    # ── Stage 1: Parser ──
    units = _parse_units(raw_body)
    if not units:
        return SkillBundle(
            metadata=metadata,
            version=metadata.get("version", ""),
            entrypoint=entrypoint,
            aliases=aliases,
            parent_skeleton=raw_body,
            contracts={},
            templates={},
            invoke_patterns=[],
            raw_body=raw_body,
            compilation_status="full",
            compilation_errors=[],
            compiled_at=time.time(),
        )
    logger.debug("Stage 1: parsed %d procedural units", len(units))

    # ── Stage 2: Clustering ──
    clusters = _cluster_units(units)
    logger.debug("Stage 2: %d units → %d clusters", len(units), len(clusters))

    # ── Stage 3: Contract Extractor ──
    use_llm = model is not None and compiler_config is not None and compiler_config.enabled
    if use_llm:
        logger.debug("Stage 3: using LLM extraction")
        contracts, templates, invoke_patterns = _extract_contracts_llm(
            clusters, units, doc, model, compiler_config
        )
    else:
        logger.debug("Stage 3: using stub (regex) extraction")
        contracts, templates, invoke_patterns = _extract_contracts(clusters, units)
    logger.debug(
        "Stage 3: extracted %d contracts, %d templates",
        len(contracts),
        len(templates),
    )

    # ── Stage 4: Verifier ──
    promoted_contracts, errors = _verify_contracts(contracts, templates, raw_body, metadata)

    # ── Determine compilation status ──
    if not contracts:
        status: Literal["full", "partial", "rejected"] = "full"
    elif promoted_contracts and not errors:
        status = "full"
    elif promoted_contracts:
        status = "partial"
    else:
        status = "rejected"

    parent_skeleton = _build_parent_skeleton(raw_body, promoted_contracts)

    return SkillBundle(
        metadata=metadata,
        version=metadata.get("version", ""),
        entrypoint=entrypoint,
        aliases=aliases,
        parent_skeleton=parent_skeleton,
        contracts={c.name: c for c in promoted_contracts},
        templates=templates,
        invoke_patterns=invoke_patterns,
        raw_body=raw_body,
        compilation_status=status,
        compilation_errors=errors,
        compiled_at=time.time(),
    )


# ── Stage 1: Parser ────────────────────────────────────────────────────


def _parse_units(raw_body: str) -> list[ProceduralUnit]:
    r"""Extract procedural units from a markdown body."""
    if not raw_body.strip():
        return []
    lines = raw_body.split("\n")
    n = len(lines)
    consumed: list[bool] = [False] * n
    units: list[ProceduralUnit] = []
    units.extend(_parse_code_blocks(lines, consumed))
    units.extend(_parse_heading_sections(lines, n, consumed))
    units.extend(_parse_numbered_steps(lines, n, consumed))
    units.sort(key=lambda u: u.start_line)
    return units


def _parse_code_blocks(lines: list[str], consumed: list[bool]) -> list[ProceduralUnit]:
    units: list[ProceduralUnit] = []
    fence_start: int | None = None
    fence_lang: str = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            if fence_start is None:
                fence_start = i
                fence_lang = stripped[3:].strip()
            else:
                code_text = "\n".join(lines[fence_start + 1 : i])
                if fence_lang.lower() in _EXECUTABLE_LANGS and code_text.strip():
                    units.append(
                        ProceduralUnit(
                            unit_type="code_block",
                            content="\n".join(lines[fence_start : i + 1]),
                            start_line=fence_start + 1,
                            end_line=i + 1,
                            code_language=fence_lang.lower(),
                            code_content=code_text,
                        )
                    )
                    for j in range(fence_start, i + 1):
                        consumed[j] = True
                fence_start = None
                fence_lang = ""
    return units


def _parse_heading_sections(lines: list[str], n: int, consumed: list[bool]) -> list[ProceduralUnit]:
    units: list[ProceduralUnit] = []
    heading_starts: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        if consumed[i]:
            continue
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group().strip().split()[0])
            title = line[m.end() :].strip()
            heading_starts.append((i, level, title))
    for idx, (start, level, title) in enumerate(heading_starts):
        end = heading_starts[idx + 1][0] if idx + 1 < len(heading_starts) else n
        body_lines = [
            lines[j] for j in range(start + 1, end) if not consumed[j] and lines[j].strip()
        ]
        if body_lines:
            units.append(
                ProceduralUnit(
                    unit_type="heading_section",
                    content="\n".join(lines[start:end]),
                    start_line=start + 1,
                    end_line=end,
                    heading_title=title,
                    heading_level=level,
                )
            )
            for j in range(start, end):
                consumed[j] = True
    return units


def _parse_numbered_steps(lines: list[str], n: int, consumed: list[bool]) -> list[ProceduralUnit]:
    units: list[ProceduralUnit] = []
    i = 0
    while i < n:
        if consumed[i]:
            i += 1
            continue
        m = _NUMBERED_STEP_RE.match(lines[i])
        if m:
            step_start = i
            i += 1
            while i < n:
                if consumed[i]:
                    i += 1
                    continue
                if _NUMBERED_STEP_RE.match(lines[i]) or _HEADING_RE.match(lines[i]):
                    break
                i += 1
            step_text = "\n".join(lines[step_start:i]).strip()
            if step_text:
                units.append(
                    ProceduralUnit(
                        unit_type="numbered_step",
                        content=step_text,
                        start_line=step_start + 1,
                        end_line=i,
                    )
                )
            continue
        i += 1
    return units


# ── Stage 2: Clustering ─────────────────────────────────────────────────


def _cluster_units(units: list[ProceduralUnit]) -> list[UnitCluster]:
    """Group procedural units by semantic similarity."""
    n = len(units)
    if n <= 1:
        return [
            UnitCluster(
                unit_indices=[i],
                texts=[u.content],
                representative_text=u.content,
            )
            for i, u in enumerate(units)
        ]
    try:
        vectors = _embed_texts([u.content for u in units])
    except Exception:
        logger.warning(
            "Embedding failed — falling back to per-unit clusters",
            exc_info=True,
        )
        return [
            UnitCluster(
                unit_indices=[i],
                texts=[u.content],
                representative_text=u.content,
            )
            for i, u in enumerate(units)
        ]
    threshold = 0.65
    assigned: set[int] = set()
    clusters: list[UnitCluster] = []
    sim = _cosine_similarity_matrix(vectors)
    for i in range(n):
        if i in assigned:
            continue
        members = [i]
        members.extend(j for j in range(i + 1, n) if j not in assigned and sim[i, j] >= threshold)
        assigned.update(members)
        clusters.append(
            UnitCluster(
                unit_indices=members,
                texts=[units[k].content for k in members],
                representative_text=units[members[0]].content,
            )
        )
    for i in range(n):
        if i not in assigned:
            clusters.append(
                UnitCluster(
                    unit_indices=[i],
                    texts=[units[i].content],
                    representative_text=units[i].content,
                )
            )
            assigned.add(i)
    return clusters


def _ensure_embedder() -> _Embedder:
    """Return the shared TextEmbedder instance, loading on first call."""
    global _embedder  # noqa: PLW0603 — lazy singleton pattern
    if _embedder is None:
        from harness_poc.core.retrieval.embedder import (  # noqa: PLC0415
            TextEmbedder,
        )

        _embedder = cast("_Embedder", TextEmbedder())
    return _embedder


def _embed_texts(texts: list[str]) -> NDArray[np.float32]:
    embedder = _ensure_embedder()
    return embedder.embed_batch(texts)  # type: ignore[union-attr]


def _cosine_similarity_matrix(
    vectors: NDArray[np.float32],
) -> NDArray[np.float32]:
    return vectors @ vectors.T  # type: ignore[no-any-return]


# ── Stage 3: Contract Extractor (stub + LLM) ───────────────────────────


def _extract_contracts(
    clusters: list[UnitCluster],
    units: list[ProceduralUnit],
) -> tuple[
    list[TypedContract],
    dict[str, ActionTemplate],
    list[InvokePattern],
]:
    """Stub contract extractor using regex on code blocks."""
    contracts: list[TypedContract] = []
    templates: dict[str, ActionTemplate] = {}
    invoke_patterns: list[InvokePattern] = []

    for cluster_idx, cluster in enumerate(clusters):
        for unit_idx in cluster.unit_indices:
            unit = units[unit_idx]
            if unit.unit_type != "code_block" or not unit.code_content:
                continue
            for match in _SHELL_INVOCATION_RE.finditer(unit.code_content):
                cmd = match.group(0).strip()
                binary = match.group(1)
                if binary in ("", "#", "export", "set", "cd", "echo"):
                    continue
                contract_name = _contract_name_from_cmd(binary, cluster_idx)
                tmpl = ActionTemplate(kind="shell", template=cmd, argument_map={})
                templates[contract_name] = tmpl
                contract = TypedContract(
                    name=contract_name,
                    description=f"Run {binary} command",
                    inputs={},
                    outputs={},
                    side_effects=["spawns subprocess"],
                    preconditions=[],
                    postconditions=[],
                    error_conditions=[],
                )
                contracts.append(contract)
                invoke_patterns.append(
                    InvokePattern(
                        contract_name=contract_name,
                        arguments={},
                        rendered_call=cmd,
                    )
                )
                break
    return contracts, templates, invoke_patterns


def _extract_contracts_llm(
    clusters: list[UnitCluster],
    units: list[ProceduralUnit],
    doc: SkillDocument,
    model: Model,
    compiler_config: CompilerConfig,  # noqa: ARG001 — reserved for future use
) -> tuple[
    list[TypedContract],
    dict[str, ActionTemplate],
    list[InvokePattern],
]:
    """LLM-based contract extractor — one call per cluster.

    Falls back to stub extraction when the LLM call fails or returns
    unparseable output.
    """
    from pydantic_ai import Agent  # noqa: PLC0415 — optional heavy import

    metadata = doc["metadata"]
    frontmatter_params = metadata.get("parameters", {}).get("properties", {})

    contracts: list[TypedContract] = []
    templates: dict[str, ActionTemplate] = {}
    invoke_patterns: list[InvokePattern] = []

    for idx, cluster in enumerate(clusters):
        # Build user prompt with cluster texts + frontmatter params
        cluster_text = "\n\n---\n\n".join(f"[Unit {i}]\n{t}" for i, t in enumerate(cluster.texts))
        user_prompt = (
            f"Skill: {metadata['name']}\n"
            f"Frontmatter parameters: {json.dumps(frontmatter_params)}\n\n"
            f"Cluster {idx} procedural units:\n\n{cluster_text}"
        )

        try:
            agent = Agent(model, system_prompt=_STAGE3_SYSTEM_PROMPT)
            result = agent.run_sync(user_prompt)
            output = _parse_llm_json(result.output)
        except Exception:
            logger.warning(
                "Stage 3 LLM call failed for cluster %d, falling back to stub",
                idx,
                exc_info=True,
            )
            # Fall back to stub for this cluster
            stub_c, stub_t, stub_i = _extract_contracts([cluster], units)
            contracts.extend(stub_c)
            templates.update(stub_t)
            invoke_patterns.extend(stub_i)
            continue

        if output is None:
            logger.warning("Stage 3: unparseable LLM output for cluster %d", idx)
            continue

        # Convert wire-format → dataclass types
        contract, tmpl, inv = _llm_output_to_dataclasses(output)
        if contract is not None:
            contracts.append(contract)
        if tmpl is not None:
            templates[contract.name if contract else f"cluster_{idx}"] = tmpl
        if inv is not None:
            invoke_patterns.append(inv)

    return contracts, templates, invoke_patterns


def _parse_llm_json(raw: str) -> LlmContractOutput | None:
    """Parse LLM output, stripping markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if len(lines) > 1 else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return LlmContractOutput.model_validate_json(text)
    except Exception:
        logger.debug("Direct LLM JSON parse failed; trying raw decoder", exc_info=True)
    # Trailing text after the JSON object (e.g. from claude -p explanations)
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return LlmContractOutput.model_validate(obj)
    except Exception:
        logger.warning("Failed to parse LLM JSON output", exc_info=True)
        return None


def _llm_output_to_dataclasses(
    output: LlmContractOutput,
) -> tuple[TypedContract | None, ActionTemplate | None, InvokePattern | None]:
    """Convert wire-format Pydantic models to dataclass types."""
    c = output.contract
    contract = TypedContract(
        name=c.name,
        description=c.description,
        inputs={k: JsonSchemaProperty(v.model_dump()) for k, v in c.inputs.items()},
        outputs={k: JsonSchemaProperty(v.model_dump()) for k, v in c.outputs.items()},
        side_effects=c.side_effects,
        preconditions=c.preconditions,
        postconditions=c.postconditions,
        error_conditions=[
            ErrorContract(
                condition=ec.condition,
                output_shape=ec.output_shape,
                recovery_hint=ec.recovery_hint,
            )
            for ec in c.error_conditions
        ],
        cancellation_behavior=_coerce_cancellation_behavior(c.cancellation_behavior),
    )
    tmpl = None
    if output.action_template is not None:
        at = output.action_template
        kind = _coerce_action_kind(at.kind)
        if kind is not None:
            tmpl = ActionTemplate(
                kind=kind,
                template=at.template,
                argument_map=at.argument_map,
            )
    inv = None
    if output.invoke_pattern is not None:
        ip = output.invoke_pattern
        inv = InvokePattern(
            contract_name=c.name,
            arguments=ip.arguments,
            rendered_call=ip.rendered_call,
        )
    return contract, tmpl, inv


def _coerce_cancellation_behavior(value: str) -> Literal["safe", "unsafe", "unknown"]:
    if value in ("safe", "unsafe", "unknown"):
        return cast("Literal['safe', 'unsafe', 'unknown']", value)
    return "unknown"


def _coerce_action_kind(value: str) -> Literal["shell", "python", "api", "db_query"] | None:
    if value == "cli":
        return "shell"
    if value in ("shell", "python", "api", "db_query"):
        return cast("Literal['shell', 'python', 'api', 'db_query']", value)
    return None


def _contract_name_from_cmd(binary: str, cluster_idx: int) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", binary).strip("_").lower()
    return safe or f"cmd_{cluster_idx}"


# ── Stage 4: Verifier ───────────────────────────────────────────────────


def _verify_contracts(
    contracts: list[TypedContract],
    templates: dict[str, ActionTemplate],
    raw_body: str,
    metadata: Mapping[str, Any],
) -> tuple[list[TypedContract], list[str]]:
    """Run the four deterministic checks on extracted contracts."""
    errors: list[str] = []
    promoted: list[TypedContract] = []
    if not contracts:
        return promoted, errors
    frontmatter_params: dict[str, Any] = metadata.get("parameters", {}).get("properties", {})
    is_knowledge = metadata.get("type") == "knowledge"
    for contract in contracts:
        contract_errors: list[str] = []
        tmpl = templates.get(contract.name)
        if tmpl is not None:
            contract_errors.extend(_check_coverage(contract, tmpl, raw_body, frontmatter_params))
        if not is_knowledge:
            contract_errors.extend(_check_binding(contract, frontmatter_params))
        if not contract_errors:
            promoted.append(contract)
        else:
            errors.extend(f"[contract '{contract.name}'] {e}" for e in contract_errors)
    errors.extend(_check_replacement(promoted, templates, raw_body))
    errors.extend(_check_risk(promoted, raw_body, frontmatter_params))
    return promoted, errors


def _check_coverage(
    contract: TypedContract,  # noqa: ARG001 — reserved for Phase 3
    tmpl: ActionTemplate,
    raw_body: str,
    frontmatter_params: dict[str, Any],
) -> list[str]:
    """Coverage: template tokens must appear in body OR frontmatter parameters.

    Also strips common CLI prefixes (``--``, ``-``) before checking, so
    that ``--query`` matches ``query`` in the frontmatter parameters.
    Dotted tokens (e.g. ``deverino_react.acdl``) are checked as segments
    as well as whole, matching the approach in ``_check_risk``.
    """
    errors: list[str] = []
    body_lower = raw_body.lower()
    # Build a set of acceptable tokens from frontmatter param names
    param_tokens: set[str] = set()
    for pname in frontmatter_params:
        param_tokens.add(pname.lower())
        param_tokens.add(pname.lower().replace("_", "-"))
    # Build body segments (like _check_risk) so dotted paths resolve
    body_words_raw = set(body_lower.split())
    body_segments: set[str] = set(body_words_raw)
    for w in body_words_raw:
        bare = w.translate(_PUNCTUATION_TABLE)
        body_segments.add(bare)
        body_segments.update(bare.replace("_", "-").split("-"))
        body_segments.update(bare.replace("-", "_").split("_"))
        body_segments.update(bare.split("."))
    tokens = re.split(r"\{[\w_]+\}", tmpl.template)
    for token_part in tokens:
        for word in re.split(r"[\s(),=\[\]{}]", token_part):
            cleaned = word.translate(_PUNCTUATION_TABLE)
            if len(cleaned) < _MIN_TOKEN_LENGTH_COVERAGE:
                continue
            lowered = cleaned.lower()
            # Strip leading dashes for CLI flag matching
            bare = lowered.lstrip("-")
            if lowered in body_lower or bare in body_lower:
                continue
            if lowered in param_tokens or bare in param_tokens:
                continue
            # Check dotted segments (e.g. "deverino_react.acdl" → ["deverino_react", "acdl"])
            dotted_parts = lowered.split(".")
            if any(part in body_segments for part in dotted_parts):
                continue
            # Also try the original word (with dots) as a segment
            if word.lower() in body_segments:
                continue
            errors.append(f"Coverage: token '{cleaned}' not found in body or parameters")
    return errors


def _check_binding(
    contract: TypedContract,
    frontmatter_params: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for input_name in contract.inputs:
        if input_name in _DERIVED_INPUTS:
            continue
        if input_name not in frontmatter_params:
            errors.append(
                f"Binding: input '{input_name}' not in frontmatter "
                "parameters or derived-inputs allowlist"
            )
    return errors


def _check_replacement(
    contracts: list[TypedContract],
    templates: dict[str, ActionTemplate],  # noqa: ARG001 — reserved
    raw_body: str,
) -> list[str]:
    errors: list[str] = []
    if not contracts:
        return errors
    skeleton = raw_body
    for contract in contracts:
        placeholder = f"invoke({contract.name}, args)"
        skeleton = skeleton.replace(contract.name, placeholder)
    if skeleton.count("```") % 2 != 0:
        errors.append("Replacement: unbalanced code fences after substitution")
    return errors


def _check_risk(
    contracts: list[TypedContract],
    raw_body: str,
    frontmatter_params: dict[str, Any] | None = None,
) -> list[str]:
    """Risk: flag contract tokens that collide with UNRELATED body words.

    A token is a genuine match (not a risk) if it appears as a standalone
    word OR as a segment of a delimited body word (e.g., ``query`` inside
    ``artifacts.query``).  Only flags true substring collisions where the
    token is embedded in a word with no semantic relationship.
    """
    errors: list[str] = []
    known_params: frozenset[str] = frozenset(
        k.lower() for k in (frontmatter_params or {})
    )
    body_words_raw = set(raw_body.lower().split())
    # Build a set of token segments by splitting body words on delimiters.
    # Also strip surrounding backtick/quote/colon wrappers before splitting
    # on dots so that `artifacts.query`: → "artifacts.query" is recognised.
    body_segments: set[str] = set()
    for w in body_words_raw:
        bare = w.translate(_PUNCTUATION_TABLE)
        body_segments.add(bare)
        body_segments.update(bare.replace("_", "-").split("-"))
        body_segments.update(bare.replace("-", "_").split("_"))
        body_segments.update(bare.split("."))
        # Preserve dot-notation by stripping only surrounding punctuation
        stripped = w.strip("`'\",;:!?()[]{}| ")
        body_segments.add(stripped)
        body_segments.update(stripped.split("."))
    for contract in contracts:
        check_tokens: list[str] = [contract.name.lower()]
        check_tokens.extend(k.lower() for k in contract.inputs)
        check_tokens.extend(k.lower() for k in contract.outputs)
        for token in check_tokens:
            if len(token) < _MIN_TOKEN_LENGTH_RISK:
                continue
            if token in body_segments:
                continue  # genuine match — token appears standalone or as segment
            if token in known_params:
                continue  # legitimate frontmatter parameter, not a collision
            for body_word in body_words_raw:
                bare_word = body_word.translate(_PUNCTUATION_TABLE)
                if token in bare_word and len(token) != len(bare_word):
                    # Allow boundary matches (e.g. "result" in "skillresult")
                    if bare_word.startswith(token) or bare_word.endswith(token):
                        continue
                    errors.append(
                        f"Risk: contract token '{token}' is a substring of body word '{body_word}'"
                    )
                    break
    return errors




def _strip_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = lines[1:] if len(lines) > 1 else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


# ── Parent skeleton builder ─────────────────────────────────────────────


def _build_parent_skeleton(
    raw_body: str,
    contracts: list[TypedContract],
) -> str:
    skeleton = raw_body
    seen: set[str] = set()
    for contract in contracts:
        if contract.name in seen:
            continue
        seen.add(contract.name)
        placeholder = f"invoke({contract.name}, args)"
        skeleton = re.sub(
            r"\b" + re.escape(contract.name) + r"\b",
            placeholder,
            skeleton,
        )
    return skeleton


# ── Alias table ─────────────────────────────────────────────────────────
_SKILL_ALIASES: dict[str, str] = {
    "delegate_to_subagent": "delegate_task",
    "read_global_context": "read_memory",
}


def _resolve_aliases(skill_name: str) -> list[str]:
    return [alias for alias, target in _SKILL_ALIASES.items() if target == skill_name]
