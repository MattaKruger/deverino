"""Unit tests for SkillRunner parsing — skill document loading and normalization.

These test the static methods that parse SKILL.md frontmatter, resolve
aliases, and normalize arguments — without touching the filesystem or
executing any skills.
"""

# ruff: noqa: ANN201

import tempfile
from pathlib import Path

import pytest

from harness_poc.core.skill_runner import SkillRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill_file(  # noqa: PLR0913
    directory: Path,
    name: str,
    *,
    skill_type: str = "tool",
    description: str = "A test skill.",
    extra_frontmatter: str = "",
    body: str = "# Test Skill\n",
) -> Path:
    """Create a minimal SKILL.md with valid frontmatter and return its path."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = f"""---
name: {name}
type: {skill_type}
description: {description}
version: "1.0"
auto_invokable: false
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query.
entrypoint:
  module: skill
  function: execute
permissions:
  blackboard: read
  workspace: none
{extra_frontmatter}---
"""
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(frontmatter + body, encoding="utf-8")
    return skill_file


# ---------------------------------------------------------------------------
# parse_skill_document — happy path
# ---------------------------------------------------------------------------


def test_parse_valid_skill_document():
    """A well-formed SKILL.md parses into a SkillDocument with all fields."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = _write_skill_file(Path(tmp), "test_skill")
        result = SkillRunner.parse_skill_document(skill_file)

    assert result["metadata"]["name"] == "test_skill"
    assert result["metadata"]["type"] == "tool"
    assert result["metadata"]["description"] == "A test skill."
    assert result["metadata"]["auto_invokable"] is False
    assert result["metadata"]["permissions"] == {
        "blackboard": "read",
        "workspace": "none",
    }
    assert result["body"] == "# Test Skill"
    assert result["path"] == skill_file
    assert result["entrypoint"]["module"] == "skill"
    assert result["entrypoint"]["function"] == "execute"


def test_parse_knowledge_skill():
    """Knowledge-type skills parse correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = _write_skill_file(
            Path(tmp), "my_knowledge", skill_type="knowledge",
            description="A knowledge document.",
        )
        result = SkillRunner.parse_skill_document(skill_file)

    assert result["metadata"]["type"] == "knowledge"
    assert result["metadata"]["name"] == "my_knowledge"


def test_parse_skill_with_auto_invokable():
    """auto_invokable: true is parsed as a boolean."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = _write_skill_file(
            Path(tmp), "auto_skill",
            extra_frontmatter="auto_invokable: true\n",
        )
        result = SkillRunner.parse_skill_document(skill_file)

    assert result["metadata"]["auto_invokable"] is True


def test_parse_skill_without_permissions():
    """Skills without a permissions key default to empty dict."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "no_perms"
        skill_dir.mkdir()
        content = """---
name: no_perms
type: tool
description: No permissions listed.
parameters:
  type: object
  properties: {}
entrypoint:
  module: skill
  function: execute
---
# Body
"""
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(content, encoding="utf-8")
        result = SkillRunner.parse_skill_document(skill_file)

    assert result["metadata"]["permissions"] == {}


def test_parse_skill_without_entrypoint():
    """Skills without an explicit entrypoint default to skill.execute."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "default_entry"
        skill_dir.mkdir()
        content = """---
name: default_entry
type: tool
description: Default entrypoint.
parameters:
  type: object
  properties: {}
---
# Body
"""
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(content, encoding="utf-8")
        result = SkillRunner.parse_skill_document(skill_file)

    assert result["entrypoint"]["module"] == "skill"
    assert result["entrypoint"]["function"] == "execute"


# ---------------------------------------------------------------------------
# parse_skill_document — error cases
# ---------------------------------------------------------------------------


def test_parse_missing_frontmatter():
    """A file without YAML frontmatter raises ValueError."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "bad" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("# No frontmatter here\n", encoding="utf-8")

        with pytest.raises(ValueError, match="YAML frontmatter"):
            SkillRunner.parse_skill_document(skill_file)


def test_parse_unclosed_frontmatter():
    """A file with an unclosed frontmatter block raises ValueError."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "bad" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("---\nname: unfinished\n", encoding="utf-8")

        with pytest.raises(ValueError, match="YAML frontmatter"):
            SkillRunner.parse_skill_document(skill_file)


def test_parse_missing_name():
    """A skill without a name raises TypeError."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "bad" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("""---
type: tool
description: Missing name.
parameters:
  type: object
  properties: {}
---
""", encoding="utf-8")

        with pytest.raises(TypeError, match="name"):
            SkillRunner.parse_skill_document(skill_file)


def test_parse_invalid_type():
    """A skill with an invalid type raises TypeError."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "bad" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("""---
name: bad_type
type: executable
description: Invalid type.
parameters:
  type: object
  properties: {}
---
""", encoding="utf-8")

        with pytest.raises(TypeError, match="type must be"):
            SkillRunner.parse_skill_document(skill_file)


def test_parse_missing_parameters_defaults_to_empty():
    """A skill without parameters gets the default empty schema."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "bad" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("""---
name: no_params
type: tool
description: Missing parameters.
---
""", encoding="utf-8")

        result = SkillRunner.parse_skill_document(skill_file)
        assert result["metadata"]["parameters"] == {
            "type": "object",
            "properties": {},
        }


# ---------------------------------------------------------------------------
# _resolve_alias
# ---------------------------------------------------------------------------


def test_resolve_known_alias():
    """delegate_to_subagent maps to delegate_task."""
    assert SkillRunner._resolve_alias("delegate_to_subagent") == "delegate_task"  # type: ignore[arg-type]


def test_resolve_read_global_context_alias():
    """read_global_context maps to read_memory."""
    assert SkillRunner._resolve_alias("read_global_context") == "read_memory"  # type: ignore[arg-type]


def test_resolve_unknown_name_passes_through():
    """An unknown name is returned unchanged."""
    assert SkillRunner._resolve_alias("read_memory") == "read_memory"  # type: ignore[arg-type]


def test_resolve_empty_string():
    """Empty string passes through unchanged."""
    assert SkillRunner._resolve_alias("") == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _normalize_arguments
# ---------------------------------------------------------------------------


def test_normalize_delegate_task_with_template_name():
    """template_name is copied to persona for delegate_task."""
    result = SkillRunner._normalize_arguments(  # type: ignore[arg-type]
        "delegate_task",
        {"template_name": "reviewer", "objective": "Review this code."},
    )
    assert result["template_name"] == "reviewer"
    assert result["persona"] == "reviewer"
    assert result["objective"] == "Review this code."


def test_normalize_delegate_task_with_both():
    """When both template_name and persona are present, persona is kept."""
    result = SkillRunner._normalize_arguments(  # type: ignore[arg-type]
        "delegate_task",
        {"template_name": "old", "persona": "explicit"},
    )
    assert result["persona"] == "explicit"
    assert result["template_name"] == "old"


def test_normalize_other_skills_passthrough():
    """Non-delegate_task skills pass through unchanged."""
    result = SkillRunner._normalize_arguments(  # type: ignore[arg-type]
        "read_memory",
        {"memory_key": "test", "extra": "value"},
    )
    assert result == {"memory_key": "test", "extra": "value"}


def test_normalize_empty_arguments():
    """Empty arguments dict passes through."""
    result = SkillRunner._normalize_arguments(  # type: ignore[arg-type]
        "read_memory",
        {},
    )
    assert result == {}
