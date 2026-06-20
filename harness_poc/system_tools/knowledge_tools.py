"""Built-in knowledge skill tools — skill_view, skills_list, skill_manage.

These three tools give the LLM progressive-disclosure access to knowledge
skills (SKILL.md files with ``type: knowledge``).  They mirror Hermes's
``tools/skills_tool.py`` but adapted for Deverino's PydanticAI runtime.

Progressive disclosure:
-  ``skills_list`` → name + description (token-efficient catalog)
-  ``skill_view``  → full markdown content (loaded on demand)
-  ``skill_manage`` → create / patch / delete (agent-authored skills)

Knowledge skill SKILL.md format::

    ---
    name: my-skill
    type: knowledge
    description: Use when <trigger>. <one-line summary>.
    version: 1.0.0
    ---

    # My Skill

    Full instructions...
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

import yaml

from harness_poc.core.skills import substitute_template_vars

if TYPE_CHECKING:
    from harness_poc.core.skills.skill_runner import SkillRunner

logger = logging.getLogger(__name__)

# ── Module-level context (set by app_factory at startup) ──────────────
_knowledge_dirs: list[Path] = []
"""Skill directories to scan for ``type: knowledge`` SKILL.md files."""

_project_root: Path | None = None
"""Project root for ``${PROJECT_ROOT}`` template substitution."""

_scratch_base: Path | None = None
"""Scratch base for ``${SCRATCH_DIR}`` template substitution."""

_session_id: str = ""
"""Current session ID for ``${SESSION_ID}`` template substitution."""

_skill_runner: SkillRunner | None = None
"""SkillRunner instance for bundle compilation lookups."""


def init_knowledge_context(
    knowledge_dirs: list[Path],
    *,
    project_root: Path | None = None,
    scratch_base: Path | None = None,
    session_id: str = "",
    skill_runner: SkillRunner | None = None,
) -> None:
    """Set the module-level context for knowledge skill discovery.

    Called once at startup by ``app_factory.py``.
    """
    global _knowledge_dirs, _project_root, _scratch_base, _session_id, _skill_runner
    _knowledge_dirs = knowledge_dirs
    _project_root = project_root
    _scratch_base = scratch_base
    _session_id = session_id
    _skill_runner = skill_runner


def update_session_id(session_id: str) -> None:
    """Update the session ID for template substitution."""
    global _session_id
    _session_id = session_id


# ── Tool handlers (called by ToolRunner) ──────────────────────────────


def skills_list(category: str = "") -> dict[str, Any]:  # noqa: ARG001
    """List all knowledge skills (name + description only).

    Returns a dict with ``{success, skills: [...], count}``.
    """
    skills = _discover_knowledge_skills()
    return {
        "success": True,
        "skills": [{"name": s["name"], "description": s["description"]} for s in skills],
        "count": len(skills),
        "hint": "Use skill_view(name) to load full content.",
    }


def skill_view(name: str, file_path: str = "", level: str = "") -> dict[str, Any]:
    """Load a knowledge skill at the requested disclosure level.

    Args:
        name: Skill name (matches the ``name`` field in SKILL.md frontmatter).
        file_path: Optional path to a supporting file (e.g. ``references/api.md``).
        level: Disclosure level — ``"summary"`` or ``"full"``.  Default:
            ``"summary"`` when a compiled bundle exists, ``"full"``
            (raw markdown) when no bundle is available.

    Returns a dict with ``{success, name, level, content, ...}``.
    """
    if not name.strip():
        return {"success": False, "error": "Skill name required."}

    # Search for the skill's SKILL.md
    skill_dir, skill_md = _find_skill_dir(name.strip())
    if skill_md is None:
        return {
            "success": False,
            "error": f"Skill '{name}' not found.",
            "hint": "Use skills_list() to see available skills.",
        }

    # If requesting a specific supporting file
    if file_path.strip() and skill_dir is not None:
        target = (skill_dir / file_path.strip()).resolve()
        try:
            target.relative_to(skill_dir.resolve())
        except ValueError:
            return {
                "success": False,
                "error": f"Path '{file_path}' escapes the skill directory.",
            }
        if not target.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
            }
        content = target.read_text(encoding="utf-8")
    else:
        raw = skill_md.read_text(encoding="utf-8")
        content = _strip_frontmatter(raw)

    # Template substitution
    content = substitute_template_vars(
        content,
        project_root=_project_root,
        scratch_dir=_scratch_base,
        session_id=_session_id,
    )

    # ── Bundle lookup ──
    # Try to get a compiled bundle.  If available, return content at the
    # requested level.  If not available, fall back to raw markdown.
    requested_level = level.strip().lower() if level.strip() else ""
    bundle = _get_bundle_for_name(name.strip())

    if bundle is not None and bundle.compilation_status != "rejected":
        # Bundle exists — determine effective level
        effective_level = requested_level or "summary"
        if effective_level == "summary":
            return _build_summary_result(name.strip(), bundle, skill_dir, content)
        if effective_level == "full":
            return _build_full_result(name.strip(), bundle, skill_dir, content)
        return {
            "success": False,
            "error": f"Unknown level: '{level}'. Use 'summary' or 'full'.",
        }

    # No bundle — return raw markdown (existing behavior)
    if requested_level == "summary":
        return {
            "success": True,
            "name": name.strip(),
            "level": "full",  # fallback: we serve the full raw markdown
            "content": content,
            "hint": "No compiled bundle available; serving raw markdown.",
        }

    return _build_raw_result(name.strip(), skill_dir, content)


def skill_manage(
    action: str,
    name: str = "",
    content: str = "",
    old_string: str = "",
    new_string: str = "",
) -> dict[str, Any]:
    """Create, patch, or delete a knowledge skill."""
    action = action.strip().lower()

    if action == "create":
        if not name.strip() or not content.strip():
            return {"success": False, "error": "name and content required for create."}
        return _create_skill(name.strip(), content)

    if action == "patch":
        if not name.strip():
            return {"success": False, "error": "name required for patch."}
        return _patch_skill(name.strip(), old_string, new_string)

    if action == "delete":
        if not name.strip():
            return {"success": False, "error": "name required for delete."}
        return _delete_skill(name.strip())

    return {
        "success": False,
        "error": f"Unknown action: '{action}'. Use create, patch, or delete.",
    }


# ── Internal helpers ──────────────────────────────────────────────────


def _discover_knowledge_skills() -> list[dict[str, str]]:
    """Walk knowledge dirs and return name + description for each skill."""
    skills: list[dict[str, str]] = []
    seen: set[str] = set()
    for d in _knowledge_dirs:
        if not d.exists():
            continue
        for skill_md in sorted(d.glob("*/SKILL.md")):
            frontmatter = _read_frontmatter(skill_md)
            if frontmatter.get("type") != "knowledge":
                continue
            name = str(frontmatter.get("name", skill_md.parent.name))
            if name in seen:
                continue
            seen.add(name)
            description = str(frontmatter.get("description", ""))
            skills.append({"name": name, "description": description})
    return skills


def _find_skill_dir(name: str) -> tuple[Path | None, Path | None]:
    """Find the skill directory + SKILL.md for a named knowledge skill."""
    for d in _knowledge_dirs:
        if not d.exists():
            continue
        for skill_md in sorted(d.glob("*/SKILL.md")):
            frontmatter = _read_frontmatter(skill_md)
            if frontmatter.get("type") != "knowledge":
                continue
            if str(frontmatter.get("name", "")) == name:
                return skill_md.parent, skill_md
    return None, None


def _read_frontmatter(skill_md: Path) -> dict[str, Any]:
    """Read just the YAML frontmatter from a SKILL.md file."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    frontmatter_end = text.find("\n---", 3)
    if frontmatter_end == -1:
        return {}
    try:
        parts = list(yaml.safe_load_all(text[3:frontmatter_end]))
        fm = parts[0] if parts else {}
    except yaml.YAMLError:
        return {}
    if not isinstance(fm, dict):
        return {}
    return fm


def _strip_frontmatter(text: str) -> str:
    """Return the body of a SKILL.md, without the YAML frontmatter."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].strip()


# ── Bundle-aware helpers ───────────────────────────────────────────────


def _get_bundle_for_name(name: str) -> object | None:
    """Return a compiled SkillBundle for the named skill, or None."""
    if _skill_runner is None:
        return None
    try:
        from harness_poc.core.skills.skill_compiler import bundle_for_skill

        return bundle_for_skill(name, skill_runner=_skill_runner)
    except Exception:
        logger.debug("Bundle lookup failed for %s", name, exc_info=True)
        return None


def _build_summary_result(
    name: str,
    bundle: object,
    skill_dir: Path | None,  # noqa: ARG001
    raw_content: str,  # noqa: ARG001
) -> dict[str, Any]:
    """Build the Level 2 (Summary) response from a compiled bundle."""
    # We access bundle attributes dynamically to avoid a hard import
    # of SkillBundle at module load time.
    b_contracts: dict = getattr(bundle, "contracts", {})
    b_templates: dict = getattr(bundle, "templates", {})
    b_version: str = getattr(bundle, "version", "")
    b_status: str = getattr(bundle, "compilation_status", "rejected")
    b_errors: list = getattr(bundle, "compilation_errors", [])

    contract_summaries: list[dict[str, Any]] = []
    for contract in b_contracts.values():
        inputs = {k: v.get("type", "any") for k, v in contract.inputs.items()}
        outputs = {k: v.get("type", "any") for k, v in contract.outputs.items()}
        contract_summaries.append(
            {
                "name": contract.name,
                "inputs": inputs,
                "outputs": outputs,
                "preconditions": contract.preconditions,
                "error_conditions": [
                    {"condition": ec.condition, "recovery_hint": ec.recovery_hint}
                    for ec in contract.error_conditions
                ],
            }
        )

    result: dict[str, Any] = {
        "success": True,
        "name": name,
        "level": "summary",
        "version": b_version,
        "compilation_status": b_status,
        "contracts": contract_summaries,
        "templates": list(b_templates.keys()),
    }
    if b_status != "full":
        result["hint"] = (
            "Compilation is partial — use level='full' to see raw markdown "
            "for contracts that failed verification."
        )
        result["compilation_errors"] = b_errors

    return result


def _build_full_result(
    name: str,
    bundle: object,
    skill_dir: Path | None,  # noqa: ARG001
    raw_content: str,  # noqa: ARG001
) -> dict[str, Any]:
    """Build the Level 3 (Full) response from a compiled bundle."""
    b_contracts: dict = getattr(bundle, "contracts", {})
    b_templates: dict = getattr(bundle, "templates", {})
    b_invoke: list = getattr(bundle, "invoke_patterns", [])
    b_version: str = getattr(bundle, "version", "")
    b_status: str = getattr(bundle, "compilation_status", "rejected")
    b_skeleton: str = getattr(bundle, "parent_skeleton", "")
    b_raw: str = getattr(bundle, "raw_body", "")
    b_errors: list = getattr(bundle, "compilation_errors", [])

    contracts_full: list[dict[str, Any]] = []
    for contract in b_contracts.values():
        contracts_full.append(
            {
                "name": contract.name,
                "description": contract.description,
                "inputs": {k: dict(v) for k, v in contract.inputs.items()},
                "outputs": {k: dict(v) for k, v in contract.outputs.items()},
                "side_effects": contract.side_effects,
                "preconditions": contract.preconditions,
                "postconditions": contract.postconditions,
                "error_conditions": [
                    {
                        "condition": ec.condition,
                        "output_shape": ec.output_shape,
                        "recovery_hint": ec.recovery_hint,
                    }
                    for ec in contract.error_conditions
                ],
                "cancellation_behavior": contract.cancellation_behavior,
            }
        )

    templates_full: list[dict[str, Any]] = []
    for tname, tmpl in b_templates.items():
        templates_full.append(
            {
                "name": tname,
                "kind": tmpl.kind,
                "template": tmpl.template,
                "argument_map": tmpl.argument_map,
            }
        )

    invoke_patterns: list[dict[str, Any]] = [
        {
            "contract_name": ip.contract_name,
            "arguments": ip.arguments,
            "rendered_call": ip.rendered_call,
        }
        for ip in b_invoke
    ]

    result: dict[str, Any] = {
        "success": True,
        "name": name,
        "level": "full",
        "version": b_version,
        "compilation_status": b_status,
        "content": b_skeleton,
        "contracts": contracts_full,
        "templates": templates_full,
        "invoke_patterns": invoke_patterns,
        "raw_body": b_raw,
    }
    if b_status != "full":
        result["compilation_errors"] = b_errors
        result["hint"] = (
            "Compilation is partial or rejected.  'content' and 'raw_body' "
            "contain the original markdown for contracts that failed verification."
        )

    return result


def _build_raw_result(
    name: str,
    skill_dir: Path | None,
    content: str,
) -> dict[str, Any]:
    """Build the legacy raw-markdown response (no bundle available)."""
    # List supporting files for the hint
    supporting: list[str] = []
    if skill_dir:
        for subdir in ("references", "templates", "scripts", "assets"):
            sd = skill_dir / subdir
            if sd.exists():
                for f in sorted(sd.rglob("*")):
                    if f.is_file() and not f.is_symlink():
                        supporting.append(str(f.relative_to(skill_dir)))

    result: dict[str, Any] = {
        "success": True,
        "name": name,
        "level": "full",
        "content": content,
    }
    if supporting:
        result["linked_files"] = {"supporting": supporting}
        result["hint"] = "Load supporting files with skill_view(name, file_path=...)."

    return result


def _create_skill(name: str, content: str) -> dict[str, Any]:
    """Write a new knowledge skill SKILL.md to the first writable dir."""
    for d in _knowledge_dirs:
        if d.exists():
            break
    else:
        if _knowledge_dirs:
            d = _knowledge_dirs[0]
            d.mkdir(parents=True, exist_ok=True)
        else:
            return {"success": False, "error": "No skill directory configured."}

    skill_dir = d / name
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "error": f"Failed to write skill: {exc}"}

    return {
        "success": True,
        "name": name,
        "path": str(skill_dir / "SKILL.md"),
        "message": f"Skill '{name}' created.",
    }


def _patch_skill(name: str, old_string: str, new_string: str) -> dict[str, Any]:
    """Find-and-replace in a knowledge skill's SKILL.md."""
    _skill_dir, skill_md = _find_skill_dir(name)
    if skill_md is None:
        return {"success": False, "error": f"Skill '{name}' not found."}

    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return {"success": False, "error": f"Failed to read skill: {exc}"}

    if old_string not in text:
        return {"success": False, "error": "old_string not found in skill content."}

    new_text = text.replace(old_string, new_string) if old_string else text
    try:
        skill_md.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "error": f"Failed to write skill: {exc}"}

    return {
        "success": True,
        "name": name,
        "message": f"Skill '{name}' patched.",
    }


def _delete_skill(name: str) -> dict[str, Any]:
    """Remove a knowledge skill directory."""
    skill_dir, skill_md = _find_skill_dir(name)
    if skill_md is None:
        return {"success": False, "error": f"Skill '{name}' not found."}

    import shutil

    try:
        shutil.rmtree(str(skill_dir))
    except OSError as exc:
        return {"success": False, "error": f"Failed to delete skill: {exc}"}

    return {
        "success": True,
        "name": name,
        "message": f"Skill '{name}' deleted.",
    }


# ── Register tools with the built-in tool registry ────────────────────
# These import-time calls let ToolRunner discover the three meta-tools
# alongside the other system_tools/ modules.

from harness_poc.system_tools import register as _register

_register(
    name="skills_list",
    description=(
        "List all available knowledge skills (progressive disclosure "
        "tier 1 — name + description only). Use skill_view(name) to "
        "load full content for skills that match your task."
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Optional category filter.",
            },
        },
    },
    handler=skills_list,
)

_register(
    name="skill_view",
    description=(
        "Load a knowledge skill at the requested disclosure level. "
        "Use level='summary' for contract signatures (fast, low-token). "
        "Use level='full' for complete contracts, templates, and examples. "
        "Default: 'summary' when a compiled bundle exists, 'full' raw "
        "markdown when no bundle is available."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to load (e.g. 'writing-plans').",
            },
            "file_path": {
                "type": "string",
                "description": (
                    "Optional path to a supporting file within the skill "
                    "(e.g. 'references/api.md', 'templates/config.yaml'). "
                    "Omit to load the main SKILL.md content."
                ),
            },
            "level": {
                "type": "string",
                "description": (
                    "Disclosure level: 'summary' or 'full'. "
                    "Default: 'summary' when a compiled skill bundle exists, "
                    "'full' when only raw markdown is available."
                ),
            },
        },
        "required": ["name"],
    },
    handler=skill_view,
)

_register(
    name="skill_manage",
    description=(
        "Create, patch, or delete a knowledge skill. Use this to save "
        "reusable workflows after completing complex tasks. Actions: "
        "create (requires name + content), patch (name + old_string + "
        "new_string), delete (name)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of: create, patch, delete.",
                "enum": ["create", "patch", "delete"],
            },
            "name": {
                "type": "string",
                "description": "Skill name (lowercase, hyphens, max 64 chars).",
            },
            "content": {
                "type": "string",
                "description": (
                    "Full SKILL.md content for 'create' action. Must start "
                    "with YAML frontmatter (--- ... ---) followed by "
                    "markdown body."
                ),
            },
            "old_string": {
                "type": "string",
                "description": "Text to find and replace (for 'patch' action).",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text (for 'patch' action).",
            },
        },
        "required": ["action"],
    },
    handler=skill_manage,
)
