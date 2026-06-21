"""Tests for token efficiency changes — Phase 1.

Validates that the compact tool listing format and SOUL compact
variant produce smaller prompts without breaking functionality.
"""

from __future__ import annotations

from pathlib import Path

from harness_poc.core.runtime.goal_runner import (
    GoalRunner,
    _summarize_event_list,
)

# ---------------------------------------------------------------------------
# Decision prompt budget tests
# ---------------------------------------------------------------------------

_MOCK_TOOLS: list[dict[str, object]] = [
    {
        "function": {
            "name": "read_file",
            "description": "Read a file from disk",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "limit": {"type": "integer", "description": "Max lines"},
                },
                "required": ["path"],
            },
        }
    },
    {
        "function": {
            "name": "search_documents",
            "description": "Search indexed documents",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        }
    },
    {
        "function": {
            "name": "run_terminal",
            "description": "Execute a shell command in a sandbox container",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                },
                "required": ["command"],
            },
        }
    },
    {
        "function": {
            "name": "delegate_task",
            "description": (
                "Spawn a sub-agent to work on an objective autonomously. "
                "The sub-agent receives its own persona prompt and can call tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "objective": {"type": "string"},
                    "persona": {"type": "string"},
                },
                "required": ["objective", "persona"],
            },
        }
    },
    {
        "function": {
            "name": "write_file",
            "description": "Write content to a file on disk",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target file path"},
                    "content": {"type": "string", "description": "File contents"},
                },
                "required": ["path", "content"],
            },
        }
    },
]


def test_decision_prompt_uses_compact_tool_names() -> None:
    """The decision prompt must NOT contain full JSON tool schemas."""
    prompt = GoalRunner._build_decision_prompt([], _MOCK_TOOLS)
    # Should contain a compact comma-separated name list, not JSON schema blobs
    assert "read_file, run_terminal" in prompt or "run_terminal, read_file" in prompt

    # Should NOT contain full JSON parameter schemas
    assert '"type": "object"' not in prompt
    assert '"properties"' not in prompt

    # The prompt should still have the structure we expect
    assert "## Available Tools:" in prompt
    assert "Choose the next concrete action" in prompt


def test_decision_prompt_with_events_stays_under_budget() -> None:
    """Prompt with realistic tool count and event history must fit within a reasonable budget."""
    # Simulate 50 events (mix of tool calls and results)
    from harness_poc.core.events import SkillCalled, SkillCompleted

    events: list = []
    for i in range(25):
        events.append(
            SkillCalled(
                session_id="test-session",
                tool_name=f"tool_{i % 5}",
                arguments={"query": f"search query number {i}"},
            )
        )
        events.append(
            SkillCompleted(
                session_id="test-session",
                tool_name=f"tool_{i % 5}",
                status="success",
                content=f"Result for query {i}: found 3 matching files in the repository.",
            )
        )

    prompt = GoalRunner._build_decision_prompt(events, _MOCK_TOOLS)
    # After compression, the prompt should be well under 8K chars
    assert len(prompt) < 8000, f"Prompt is {len(prompt)} chars, exceeds 8000 budget"
    # But not empty
    assert len(prompt) > 200


def test_empty_events_produces_valid_prompt() -> None:
    """Prompt with no prior events should still be well-formed."""
    prompt = GoalRunner._build_decision_prompt([], _MOCK_TOOLS)
    assert "No prior events" in prompt
    assert "## Required Response" in prompt


def test_decision_prompt_with_one_event() -> None:
    """Single recent event: no summary needed, just the raw event."""
    from harness_poc.core.events import SkillCalled

    events = [
        SkillCalled(
            session_id="test-session",
            tool_name="read_file",
            arguments={"path": "/some/file.py"},
        )
    ]
    prompt = GoalRunner._build_decision_prompt(events, _MOCK_TOOLS)
    # Single event is recent (<= keep_raw_last threshold)
    assert "read_file" in prompt
    # No "Prior Context Summary" for single event
    assert "Prior Context Summary" not in prompt


def test_event_summary_deduplicates_tool_calls() -> None:
    """Summarize_event_list deduplicates repeated tool calls."""
    from harness_poc.core.events import SkillCalled, SkillCompleted

    events: list = []
    for _ in range(5):
        events.append(
            SkillCalled(
                session_id="test-session",
                tool_name="read_file",
                arguments={"path": "/some/file.py"},
            )
        )
    events.append(
        SkillCompleted(
            session_id="test-session",
            tool_name="read_file",
            status="success",
            content="file contents here",
        )
    )

    summary = _summarize_event_list(events)
    # read_file appears once in the unique calls list (deduped) and once in results —
    # so total count should be ≤ 2, not 6
    assert summary.count("read_file") <= 2, f"Expected ≤ 2 read_file, got:\n{summary}"
    # The deduped calls line should contain read_file only once
    calls_line = summary.split("\n")[0]
    assert calls_line.count("read_file") == 1, f"Expected 1 read_file in calls, got:\n{calls_line}"


# ---------------------------------------------------------------------------
# SOUL compact toggle tests
# ---------------------------------------------------------------------------


def test_soul_compact_prompt_is_smaller(tmp_path: Path) -> None:
    """SOUL-compact.md should be measurably smaller than SOUL.md."""
    # Build a test config that points at the real SOUL files
    project_root = Path(__file__).resolve().parents[1]
    soul_full = project_root / "harness_poc" / "system_prompts" / "SOUL.md"
    soul_compact = project_root / "harness_poc" / "system_prompts" / "SOUL-compact.md"

    full_text = soul_full.read_text(encoding="utf-8")
    compact_text = soul_compact.read_text(encoding="utf-8")

    # Compact should be strictly smaller
    assert len(compact_text) < len(full_text), (
        f"SOUL-compact ({len(compact_text)} chars) is not smaller "
        f"than SOUL ({len(full_text)} chars)"
    )
    # Should be at least 30% smaller
    reduction = 1.0 - (len(compact_text) / len(full_text))
    assert reduction > 0.30, f"SOUL-compact only {reduction:.0%} smaller — target is > 30%"

    # Essential sections must be preserved
    essential_snippets = [
        "Operating Principles",
        "Runtime Self-Model",
        "Knowledge Skills",
        "State, Memory",
        "Work & Delegation",
        "Codebase Grounding",
        "Error Reporting",
        "What I Am Not",
    ]
    for snippet in essential_snippets:
        assert snippet in compact_text, f"Missing essential section: {snippet!r}"

    # Removed sections: Communication Stance (Voice, Structure) should NOT be present
    assert "Emojis" not in compact_text, "Voice/emojis section should be removed"
    assert "Communication Stance" not in compact_text
    # §9.1 "Handling Tool Results" is duplicated by _with_tool_policy() — should be removed
    assert "Handling Tool Results" not in compact_text, (
        "§9.1 duplicates _with_tool_policy() — should be removed from compact variant"
    )


def test_soul_compact_empty_events_under_budget():
    """SOUL-compact.md should be well under 1000 tokens."""
    import tiktoken

    project_root = Path(__file__).resolve().parents[1]
    soul_compact = project_root / "harness_poc" / "system_prompts" / "SOUL-compact.md"
    text = soul_compact.read_text(encoding="utf-8")

    enc = tiktoken.get_encoding("cl100k_base")
    token_count = len(enc.encode(text))
    assert token_count < 1000, f"SOUL-compact is {token_count} tokens, target is < 1000"


# ---------------------------------------------------------------------------
# skill catalog compact tests
# ---------------------------------------------------------------------------


def test_skill_catalog_preamble_is_compact() -> None:
    """The skill catalog preamble should be a few lines, not a verbose paragraph block."""
    # Create a temp dir with one knowledge skill
    import tempfile
    from pathlib import Path

    from harness_poc.core.skills.skill_catalog import build_skill_catalog
    from harness_poc.system_tools.knowledge_tools import init_knowledge_context

    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ntype: knowledge\ndescription: A test skill\n---\n"
            "# Test Skill\n\nSome instructions here.\n"
        )

        init_knowledge_context([Path(tmp)], project_root=Path("/fake"), session_id="test")
        catalog = build_skill_catalog([Path(tmp)], force=True)

        # The preamble should be compact — no verbose paragraphs
        assert "Before replying, scan the skills below" not in catalog, (
            "Verbose preamble should be replaced with compact version"
        )
        assert "Err on the side of loading" not in catalog
        assert "Skills contain specialized knowledge" not in catalog

        # But the core content should still be there
        assert "## Skills" in catalog
        assert "<available_skills>" in catalog
        assert "skill_view" in catalog
        assert "test-skill" in catalog

# ---------------------------------------------------------------------------
# Phase 2 — distiller map down-sampling tests
# ---------------------------------------------------------------------------


def test_render_current_map_down_samples_large_map() -> None:
    from datetime import UTC, datetime, timedelta

    from harness_poc.core.context_map.distiller import _render_current_map
    from harness_poc.core.context_map.schema import MapEntry

    now = datetime.now(tz=UTC)
    entries = []
    for i in range(50):
        entries.append(
            MapEntry(
                entry_id=f"id-{i:03d}",
                key=f"key-{i:03d}",
                section="context_understanding",
                observation_type="entity",
                summary=f"Summary for entry {i}",
                priority=0.5 + (i * 0.01),
                source_event_ids=[f"ev-{i}"],
                first_seen=now - timedelta(days=i),
                last_updated=now - timedelta(days=i),
                materialization_count=1,
                first_seen_cycle=i,
                last_seen_cycle=i,
                token_estimate=20,
            )
        )

    rendered = _render_current_map(entries)
    import json
    data = json.loads(rendered)
    assert len(data["prior_keys"]) == 50
    assert len(data["recent_entries"]) <= 10


def test_render_current_map_no_entries() -> None:
    from harness_poc.core.context_map.distiller import _render_current_map
    rendered = _render_current_map([])
    import json
    data = json.loads(rendered)
    assert data["prior_keys"] == []


# ---------------------------------------------------------------------------
# Phase 2 — message history compression tests
# ---------------------------------------------------------------------------


def test_compress_message_history_noop_under_threshold() -> None:
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from harness_poc.core.runtime.message_history import compress_message_history

    messages = [
        ModelRequest(parts=[UserPromptPart(content="Hello")]),
        ModelRequest(parts=[UserPromptPart(content="World")]),
    ]
    result = compress_message_history(messages, max_tokens=10000, recent_turns=2)
    assert len(result) == len(messages)


def test_compress_message_history_handles_empty() -> None:
    from harness_poc.core.runtime.message_history import compress_message_history
    result = compress_message_history([], max_tokens=1000, recent_turns=2)
    assert result == []


def test_compress_message_history_preserves_recent_turns() -> None:
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from harness_poc.core.runtime.message_history import compress_message_history

    messages = [
        ModelRequest(parts=[UserPromptPart(content="Turn 1 old")]),
        ModelRequest(parts=[UserPromptPart(content="Turn 2 old")]),
        ModelRequest(parts=[UserPromptPart(content="Turn 3 old")]),
        ModelRequest(parts=[UserPromptPart(content="Turn 4 recent")]),
        ModelRequest(parts=[UserPromptPart(content="Turn 5 recent")]),
    ]
    result = compress_message_history(messages, max_tokens=50, recent_turns=2)
    assert len(result) >= 2

    recent_contents = [
        str(p.content)
        for m in result
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, UserPromptPart)
    ]
    assert any("Turn 4 recent" in c for c in recent_contents)
    assert any("Turn 5 recent" in c for c in recent_contents)


# ---------------------------------------------------------------------------
# Phase 2 — distiller compact prompt tests
# ---------------------------------------------------------------------------


def test_distiller_compact_prompt_is_smaller() -> None:
    from pathlib import Path

    prompt_dir = (
        Path(__file__).resolve().parents[1]
        / "harness_poc"
        / "core"
        / "context_map"
        / "prompts"
    )
    full = (prompt_dir / "distiller_v2.md").read_text(encoding="utf-8")
    compact = (prompt_dir / "distiller_v2_compact.md").read_text(encoding="utf-8")

    assert len(compact) < len(full)
    assert '"entries"' in compact
    assert '"key"' in compact
    assert '"observation_type"' in compact


def test_distiller_config_compact_template() -> None:
    from harness_poc.core.context_map.config import DistillerConfig, load_distiller_config

    cfg = DistillerConfig()
    assert cfg.prompt_template_compact is None

    cfg2 = load_distiller_config({
        "prompt_template": "distiller_v2",
        "prompt_template_compact": "distiller_v2_compact",
    })
    assert cfg2.prompt_template_compact == "distiller_v2_compact"

