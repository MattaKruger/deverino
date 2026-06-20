"""Skill bundle data model — structured pseudocode representation.

Each SKILL.md is compiled into a SkillBundle containing typed contracts,
action templates, and grounded invocation patterns.  The bundle is what
the agent receives instead of raw markdown prose.

See: docs/plans/2026-06-20-skill-pseudocode-refactor.md
Paper: Skill-as-Pseudocode (arXiv:2605.27955)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from harness_poc.core.skills.skill_runner import SkillMetadata

# ── Supporting types ───────────────────────────────────────────────────


class JsonSchemaProperty(dict):
    """A single property descriptor in a JSON Schema object.

    Mirrors JSON Schema draft conventions.  Keys include ``type``,
    ``description``, ``enum``, ``default``, ``required``, ``items``.
    Used by TypedContract.inputs and TypedContract.outputs.
    """


@dataclass(slots=True)
class ErrorContract:
    """A specific failure mode the agent can recognize and handle.

    The compiler extracts these from prose body sections that describe
    error handling, fallbacks, or precondition violations.
    """

    condition: str
    """Human-readable trigger, e.g. "semble CLI is not installed"."""

    output_shape: str
    """What the SkillResult looks like on this error, e.g.
    "status='failed', content contains 'semble: command not found'"."""

    recovery_hint: str
    """Actionable fix, e.g. "Install: pip install semble"."""


# ── Core bundle types ───────────────────────────────────────────────────


@dataclass(slots=True)
class ActionTemplate:
    """Concrete invocation syntax the skill actually executes.

    For shell-based skills this is the exact command line; for API skills
    it's the HTTP request; for DB skills it's the SQL query.
    """

    kind: Literal["shell", "python", "api", "db_query"]
    """The execution substrate."""

    template: str
    """Template string with ``{variable}`` placeholders, e.g.
    ``"semble search '{query}' --top-k {top_k}"``."""

    argument_map: dict[str, str] = field(default_factory=dict)
    """Mapping from frontmatter parameter names to template variables.

    Keys are parameter names from the YAML frontmatter ``parameters``
    block.  Values are the ``{variable}`` names used in ``template``.
    """


@dataclass(slots=True)
class TypedContract:
    """Typed pseudocode signature for a sub-procedure.

    Extracted from the skill's markdown body.  A monolithic skill
    produces a single self-named contract whose inputs mirror the
    frontmatter ``parameters``.  A skill with multiple sub-procedures
    produces one contract per procedure.
    """

    name: str
    """Contract name — used in ``invoke(name, args)`` placeholders."""

    description: str
    """One-line summary of what this procedure does."""

    inputs: dict[str, JsonSchemaProperty] = field(default_factory=dict)
    """Expected inputs, a subset of the frontmatter ``parameters``
    or derived inputs synthesised by the skill."""

    outputs: dict[str, JsonSchemaProperty] = field(default_factory=dict)
    """Expected output shape (content + artifacts)."""

    side_effects: list[str] = field(default_factory=list)
    """Observable effects, e.g. "writes to blackboard", "creates file"."""

    preconditions: list[str] = field(default_factory=list)
    """What must be true before invocation, e.g. "semble CLI installed"."""

    postconditions: list[str] = field(default_factory=list)
    """What must be true after successful invocation,
    e.g. "skill_result.status is 'success'"."""

    error_conditions: list[ErrorContract] = field(default_factory=list)
    """Known failure modes with recovery hints."""

    cancellation_behavior: Literal["safe", "unsafe", "unknown"] = "unknown"
    """Whether cancelling mid-execution leaves clean state.
    ``"safe"``: no side effects on cancel.
    ``"unsafe"``: partial writes possible.
    ``"unknown"``: not determined (default)."""

    shared_from: str | None = None
    """v2: when this contract is factored from another skill's body,
    the name of the source skill."""


@dataclass(slots=True)
class InvokePattern:
    """Grounded example mapping real argument values to a concrete call.

    The compiler generates these so the agent can see what a real
    invocation looks like without inferring from the template alone.

    Invariant: ``arguments`` should conform to the corresponding
    ``TypedContract.inputs`` schema.  Validated at compile time;
    recorded in ``compilation_errors`` if validation fails.
    """

    contract_name: str
    """Which ``TypedContract`` this pattern exercises."""

    arguments: dict[str, Any] = field(default_factory=dict)
    """Concrete argument values, e.g. ``{"action": "search", "query": "..."}``."""

    rendered_call: str = ""
    """Fully-substituted action template, e.g.
    ``"semble search 'authentication flow' --top-k 5 --mode hybrid"``."""


CompilationStatus = Literal["full", "partial", "rejected"]


@dataclass(slots=True)
class SkillBundle:
    """The structured representation delivered to the agent.

    Produced by ``skill_compiler.compile_skill()`` when a SKILL.md
    changes.  The agent receives the bundle (or a summary level) instead
    of raw markdown prose.
    """

    # ── Frontmatter-derived fields ──
    metadata: SkillMetadata
    """Name, type, description, parameters, auto_invokable, permissions."""

    version: str = ""
    """From the YAML frontmatter ``version`` field."""

    entrypoint: dict[str, str] = field(default_factory=dict)
    """From the YAML frontmatter ``entrypoint`` field,
    e.g. ``{"module": "skill", "function": "execute"}``."""

    aliases: list[str] = field(default_factory=list)
    """Alternate names for this skill, e.g. ``["delegate_to_subagent"]``
    for ``delegate_task``.  Populated from the harness alias table."""

    # ── Compiled content ──
    parent_skeleton: str = ""
    """The original body with sub-procedures replaced by
    ``invoke(κ, args)`` placeholders."""

    contracts: dict[str, TypedContract] = field(default_factory=dict)
    """Child procedures extracted from the body.  Empty for
    monolithic skills that produce a single self-named contract."""

    templates: dict[str, ActionTemplate] = field(default_factory=dict)
    """Concrete invocation syntax keyed by contract name."""

    invoke_patterns: list[InvokePattern] = field(default_factory=list)
    """Grounded examples showing real argument → real call mappings."""

    # ── Fallback ──
    raw_body: str = ""
    """The original markdown body, always present as escape hatch."""

    # ── Compilation metadata ──
    compilation_status: CompilationStatus = "rejected"
    """``"full"``: all contracts passed verification.
    ``"partial"``: some passed, some rejected.
    ``"rejected"``: no contracts passed (agent uses raw_body)."""

    compilation_errors: list[str] = field(default_factory=list)
    """Check-level rejection reasons from the verifier."""

    compiled_at: float = 0.0
    """``time.time()`` when compilation completed."""

    # ── v2 reserved fields ──
    shared_contracts: dict[str, TypedContract] = field(default_factory=dict)
    """v2: contracts shared across multiple skills (cross-parent factoring)."""
