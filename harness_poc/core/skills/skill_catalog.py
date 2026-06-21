"""Skill catalog — builds the ``<available_skills>`` block for the system prompt.

Inspired by Hermes's ``agent/prompt_builder.py::build_skills_system_prompt``.
The catalog is a token-efficient index of every knowledge skill (name +
description only).  The LLM reads this and calls ``skill_view(name)`` to
load full content on demand — progressive disclosure.

Cache: an in-memory LRU cache indexed by the skill directories' mtime,
so changes get picked up on restart without slowing every prompt build.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── In-process cache ─────────────────────────────────────────────────
# Keyed by (dir_mtimes_tuple, ) — rebuilt when any skill dir changes.
_cache: tuple[tuple[float, ...], str] | None = None


def build_skill_catalog(
    knowledge_dirs: list[Path],
    *,
    force: bool = False,
) -> str:
    """Return the ``<available_skills>`` system prompt block.

    If no knowledge skills exist, returns an empty string (no block
    injected).
    """
    global _cache

    # Cheap cache key: mtimes of the knowledge dirs
    mtimes: list[float] = []
    for d in knowledge_dirs:
        try:
            mtimes.append(d.stat().st_mtime if d.exists() else 0)
        except OSError:
            mtimes.append(0)
    cache_key = tuple(mtimes)

    if not force and _cache is not None and _cache[0] == cache_key:
        return _cache[1]

    skills = _scan_knowledge_skills(knowledge_dirs)
    if not skills:
        _cache = (cache_key, "")
        return ""

    lines: list[str] = []
    for name, description in skills:
        lines.append(f"  - {name}: {description}")

    catalog = (
        "## Skills\n"
        "Load relevant skills with skill_view(name). Always load developer-pedagogy. "
        "Update skills with skill_manage if they're missing steps or outdated.\n\n"
        "<available_skills>\n" + "\n".join(lines) + "\n"
        "</available_skills>\n"
    )

    _cache = (cache_key, catalog)
    return catalog


def _scan_knowledge_skills(
    knowledge_dirs: list[Path],
) -> list[tuple[str, str]]:
    """Return sorted (name, description) pairs for all knowledge skills."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []

    for d in knowledge_dirs:
        if not d.exists():
            continue
        for skill_md in sorted(d.glob("*/SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            if not text.startswith("---"):
                continue
            frontmatter_end = text.find("\n---", 3)
            if frontmatter_end == -1:
                continue
            try:
                parts = list(yaml.safe_load_all(text[3:frontmatter_end]))
                fm: dict[str, Any] = parts[0] if parts else {}
            except yaml.YAMLError:
                continue
            if not isinstance(fm, dict):
                continue
            if fm.get("type") != "knowledge":
                continue
            name = str(fm.get("name", skill_md.parent.name))
            if name in seen:
                continue
            seen.add(name)
            description = str(fm.get("description", ""))
            result.append((name, description))

    result.sort(key=lambda x: x[0])
    return result
