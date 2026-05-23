"""Tests for knowledge skill tools and catalog (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_poc.core.skill_catalog import build_skill_catalog
from harness_poc.core.skill_preprocessing import (
    expand_inline_shell,
    substitute_template_vars,
)
from harness_poc.system_tools.knowledge_tools import (
    _discover_knowledge_skills,
    _strip_frontmatter,
    init_knowledge_context,
    skill_manage,
    skill_view,
    skills_list,
)

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_skills_dir(tmp_path: Path) -> Path:
    """Create a temp skills dir with one knowledge skill."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "test-knowledge-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: test-knowledge-skill
type: knowledge
description: A test knowledge skill for unit tests.
version: 1.0.0
---

# Test Skill

Project root: ${PROJECT_ROOT}
Session: ${SESSION_ID}

## Instructions

Do the thing.
"""
    )
    # Supporting reference file
    refs_dir = skill_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "api.md").write_text("# API Reference\n\nGET /test\n")
    return skills_dir


@pytest.fixture
def knowledge_ctx(tmp_skills_dir: Path) -> None:
    """Init the knowledge context pointing at the temp skills dir."""
    init_knowledge_context(
        [tmp_skills_dir],
        project_root=Path("/fake/project"),
        session_id="test-session-123",
    )


# ── Preprocessing ─────────────────────────────────────────────────────


class TestSubstituteTemplateVars:
    def test_replaces_project_root(self) -> None:
        result = substitute_template_vars(
            "Root is ${PROJECT_ROOT}.", project_root=Path("/my/project")
        )
        assert result == "Root is /my/project."

    def test_replaces_session_id(self) -> None:
        result = substitute_template_vars("Session: ${SESSION_ID}", session_id="abc-123")
        assert result == "Session: abc-123"

    def test_replaces_multiple_tokens(self) -> None:
        result = substitute_template_vars(
            "Root=${PROJECT_ROOT}, Session=${SESSION_ID}",
            project_root=Path("/x"),
            session_id="s1",
        )
        assert result == "Root=/x, Session=s1"

    def test_leaves_unresolved_unchanged(self) -> None:
        result = substitute_template_vars("Root=${PROJECT_ROOT}", project_root=None)
        assert result == "Root=${PROJECT_ROOT}"

    def test_empty_string(self) -> None:
        assert substitute_template_vars("", project_root=Path("/x")) == ""

    def test_no_tokens(self) -> None:
        assert substitute_template_vars("Hello world", project_root=Path("/x")) == "Hello world"

    def test_unknown_token_left_unchanged(self) -> None:
        result = substitute_template_vars("${UNKNOWN}", project_root=Path("/x"))
        assert result == "${UNKNOWN}"


class TestExpandInlineShell:
    def test_no_shell_markers_returns_unchanged(self) -> None:
        result = expand_inline_shell("No shell here.", skill_dir=None)
        assert result == "No shell here."

    def test_expands_shell_command(self) -> None:
        result = expand_inline_shell("Date: !`echo hello`", skill_dir=None)
        assert result == "Date: hello"

    def test_empty_command(self) -> None:
        # Empty backtick commands (``) don't match the regex — left unchanged
        result = expand_inline_shell("Empty: !``", skill_dir=None)
        assert result == "Empty: !``"


# ── Frontmatter stripping ─────────────────────────────────────────────


class TestStripFrontmatter:
    def test_strips_frontmatter(self) -> None:
        md = "---\nname: test\ntype: knowledge\n---\n\n# Body\nContent here."
        result = _strip_frontmatter(md)
        assert result == "# Body\nContent here."

    def test_no_frontmatter_returns_unchanged(self) -> None:
        md = "# Just a heading"
        assert _strip_frontmatter(md) == md

    def test_unclosed_frontmatter(self) -> None:
        md = "---\nname: test"
        assert _strip_frontmatter(md) == md


# ── Knowledge skill discovery ─────────────────────────────────────────


class TestDiscoverKnowledgeSkills:
    def test_discovers_knowledge_skill(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        skills = _discover_knowledge_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "test-knowledge-skill"
        assert "test knowledge skill" in skills[0]["description"].lower()

    def test_skips_non_knowledge_skills(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        # Add a type:tool skill — should NOT appear in knowledge list
        tool_dir = tmp_skills_dir / "some-tool"
        tool_dir.mkdir()
        (tool_dir / "SKILL.md").write_text(
            "---\nname: some-tool\ntype: tool\ndescription: A tool\n---\n"
        )
        skills = _discover_knowledge_skills()
        names = {s["name"] for s in skills}
        assert "test-knowledge-skill" in names
        assert "some-tool" not in names

    def test_empty_dir(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty-skills"
        empty_dir.mkdir()
        init_knowledge_context([empty_dir])
        assert _discover_knowledge_skills() == []


# ── skills_list ───────────────────────────────────────────────────────


class TestSkillsList:
    def test_lists_knowledge_skills(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        result = skills_list()
        assert result["success"] is True
        assert result["count"] == 1
        assert result["skills"][0]["name"] == "test-knowledge-skill"

    def test_hint_included(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        result = skills_list()
        assert "skill_view" in result["hint"]


# ── skill_view ────────────────────────────────────────────────────────


class TestSkillView:
    def test_loads_skill_content(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        result = skill_view("test-knowledge-skill")
        assert result["success"] is True
        assert "# Test Skill" in result["content"]
        # Template substitution applied
        assert "/fake/project" in result["content"]
        assert "test-session-123" in result["content"]

    def test_missing_skill(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        result = skill_view("nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_empty_name(self) -> None:
        init_knowledge_context([])
        result = skill_view("")
        assert result["success"] is False

    def test_linked_files_hint(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        result = skill_view("test-knowledge-skill")
        assert result["success"] is True
        assert "linked_files" in result
        assert "references/api.md" in str(result["linked_files"])

    def test_load_supporting_file(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        result = skill_view("test-knowledge-skill", file_path="references/api.md")
        assert result["success"] is True
        assert "API Reference" in result["content"]

    def test_supporting_file_path_escape(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        result = skill_view("test-knowledge-skill", file_path="../../../etc/passwd")
        assert result["success"] is False
        assert "escapes" in result["error"].lower()


# ── skill_manage ──────────────────────────────────────────────────────


class TestSkillManage:
    def test_create_and_delete(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        # Create
        r = skill_manage(
            action="create",
            name="new-skill",
            content="---\nname: new-skill\ntype: knowledge\ndescription: New.\n---\n\nBody",
        )
        assert r["success"] is True
        assert (tmp_skills_dir / "new-skill" / "SKILL.md").exists()

        # Delete
        r2 = skill_manage(action="delete", name="new-skill")
        assert r2["success"] is True
        assert not (tmp_skills_dir / "new-skill").exists()

    def test_patch(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        r = skill_manage(
            action="patch",
            name="test-knowledge-skill",
            old_string="Do the thing.",
            new_string="Do the OTHER thing.",
        )
        assert r["success"] is True
        content = (tmp_skills_dir / "test-knowledge-skill" / "SKILL.md").read_text()
        assert "Do the OTHER thing." in content

    def test_patch_not_found(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        r = skill_manage(
            action="patch",
            name="test-knowledge-skill",
            old_string="NOT IN FILE",
            new_string="X",
        )
        assert r["success"] is False
        assert "not found" in r["error"].lower()

    def test_create_no_name(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        r = skill_manage(action="create")
        assert r["success"] is False

    def test_unknown_action(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        r = skill_manage(action="rename")
        assert r["success"] is False
        assert "unknown action" in r["error"].lower()


# ── Catalog ───────────────────────────────────────────────────────────


class TestSkillCatalog:
    def test_builds_catalog_block(self, tmp_skills_dir: Path, knowledge_ctx: None) -> None:
        catalog = build_skill_catalog([tmp_skills_dir])
        assert "<available_skills>" in catalog
        assert "</available_skills>" in catalog
        assert "test-knowledge-skill" in catalog
        assert "A test knowledge skill" in catalog

    def test_empty_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        catalog = build_skill_catalog([empty])
        assert catalog == ""

    def test_no_knowledge_skills_returns_empty(self, tmp_path: Path) -> None:
        # Only type:tool skills — no knowledge skills
        d = tmp_path / "tools-only"
        d.mkdir()
        tool_dir = d / "a-tool"
        tool_dir.mkdir()
        (tool_dir / "SKILL.md").write_text(
            "---\nname: a-tool\ntype: tool\ndescription: Just a tool\n---\n"
        )
        init_knowledge_context([d])
        catalog = build_skill_catalog([d])
        assert catalog == ""


# ── SkillRunner: type:knowledge excluded ──────────────────────────────


class TestSkillRunnerExcludesKnowledge:
    def test_knowledge_skills_not_in_executable_tools(
        self,
        tmp_path: Path,
    ) -> None:
        """Knowledge skills should NOT appear as executable PydanticAI tools."""
        from pathlib import Path as P

        from harness_poc.core.config import (
            HarnessConfig,
            HarnessPaths,
            LLMConfig,
            ObservabilityConfig,
            RuntimeConfig,
        )
        from harness_poc.core.skill_runner import SkillRunner
        from harness_poc.core.storage import BlackboardDatabase

        repo_root = P.cwd()
        # Use tmp_path for DB + a custom skills dir
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "my-knowledge" / "SKILL.md").parent.mkdir(parents=True)
        (skills_dir / "my-knowledge" / "SKILL.md").write_text(
            "---\nname: my-knowledge\ntype: knowledge\ndescription: K\n---\n"
        )

        config = HarnessConfig(
            project_root=repo_root,
            config_path=repo_root / "harness.yaml",
            paths=HarnessPaths(
                soul=repo_root / "harness_poc/system_prompts/SOUL.md",
                system_skills=repo_root / "harness_poc/system_skills",
                project_skills=skills_dir,
                system_tools=repo_root / "harness_poc/system_tools",
                workflows=repo_root / "workflows",
                pipelines=repo_root / "pipelines",
                personas=repo_root / "personas",
            ),
            runtime=RuntimeConfig(
                database_url="sqlite:///:memory:",
                default_container_image="python:3.14-slim",
            ),
            observability=ObservabilityConfig(logfire_enabled=False),
            llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
        )
        db = BlackboardDatabase.from_url(config.runtime.database_url)
        runner = SkillRunner(database=db, config=config)
        discovered = runner.discover_skills()
        names = {t["function"]["name"] for t in discovered}
        assert "my-knowledge" not in names, "Knowledge skills should not appear in executable tools"
