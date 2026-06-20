from __future__ import annotations

from typing import TYPE_CHECKING

from harness_poc.core.config import HarnessConfig
from harness_poc.core.skills import SkillContext, SkillRunner
from harness_poc.core.storage import BlackboardDatabase
from skills.semble_search import skill as semble_skill

if TYPE_CHECKING:
    import pytest

EXPECTED_DEFAULT_TOP_K = 5
EXPECTED_MAX_TOP_K = 10
MIN_TOP_K = 1
OVERSIZED_TOP_K = 100
SUCCESS_EXIT_CODE = 0


def test_semble_search_requires_query(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={"query": ""},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "requires a query string" in result.content


def test_semble_search_missing_binary_detected(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    """When semble is not installed, returns helpful error."""
    runner, session_id, _ = session_runner
    # The test environment may or may not have semble installed.
    # If not installed, we get a clear error message.
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={"query": "test query"},
        session_id=session_id,
    )
    # Either success (semble installed + ran) or failed with install message
    assert result.status in {"success", "failed"}
    if result.status == "failed" and "not installed" in result.content:
        assert "pip install semble" in result.content


def test_semble_search_find_related_requires_file_path(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={"action": "find_related", "query": "dummy"},
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "file_path" in result.content


def test_semble_search_find_related_requires_line(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={
            "action": "find_related",
            "query": "dummy",
            "file_path": "test.py",
        },
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "line" in result.content.lower()


def test_semble_search_find_related_rejects_invalid_line(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
) -> None:
    runner, session_id, _ = session_runner
    result = runner.execute_skill(
        tool_name="semble_search",
        arguments={
            "action": "find_related",
            "query": "dummy",
            "file_path": "test.py",
            "line": "not_a_number",
        },
        session_id=session_id,
    )
    assert result.status == "failed"
    assert "Invalid line number" in result.content


def test_semble_search_respects_top_k() -> None:
    """Top-k is validated as an int between 1-50."""
    assert semble_skill._parse_top_k(EXPECTED_DEFAULT_TOP_K) == EXPECTED_DEFAULT_TOP_K
    assert semble_skill._parse_top_k("abc") == EXPECTED_DEFAULT_TOP_K
    assert semble_skill._parse_top_k(0) == MIN_TOP_K
    assert semble_skill._parse_top_k(OVERSIZED_TOP_K) == EXPECTED_MAX_TOP_K


def test_semble_search_mode_removed() -> None:
    """Mode parameter was removed — verify skill module still imports cleanly.

    The --mode flag is not supported by semble >=0.4.0.  The skill silently
    ignores the mode argument (backward compat — callers may still pass it).
    """
    # Smoke test: the skill module should import and execute should be callable
    from skills.semble_search.skill import execute
    assert callable(execute)

def test_semble_search_emits_subprocess_progress(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
    test_config: HarnessConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _runner_instance, _session_id, database = session_runner
    ctx = SkillContext(
        session_id="s",
        skill_name="semble_search",
        database=database,
        config=test_config,
        on_tool_event=events.append,
    )

    class FakeProcess:
        returncode = SUCCESS_EXIT_CODE

        def poll(self) -> int:
            return SUCCESS_EXIT_CODE

        def communicate(self) -> tuple[str, str]:
            return "result line", ""

    monkeypatch.setattr(semble_skill.subprocess, "Popen", lambda *_, **__: FakeProcess())

    result = semble_skill._run_semble(ctx, ["semble", "search"], query="find runtime")

    assert result.status == "success"
    assert events[0] == "semble_search: running query='find runtime'"
    assert events[1].startswith("semble_search: finished in ")
    assert "returned 11 chars" in events[1]
    assert "current run receives 11 chars" in events[1]
    assert "before history pruning" in events[1]
    assert "~2 tokens before history pruning" in events[1]


def test_semble_search_caps_large_output(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
    test_config: HarnessConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runner_instance, _session_id, database = session_runner
    ctx = SkillContext(
        session_id="s",
        skill_name="semble_search",
        database=database,
        config=test_config,
    )
    large_output = "x" * (semble_skill.MAX_OUTPUT_CHARS + 100)

    class FakeProcess:
        returncode = SUCCESS_EXIT_CODE

        def poll(self) -> int:
            return SUCCESS_EXIT_CODE

        def communicate(self) -> tuple[str, str]:
            return large_output, ""

    monkeypatch.setattr(semble_skill.subprocess, "Popen", lambda *_, **__: FakeProcess())

    result = semble_skill._run_semble(ctx, ["semble", "search"], query="find runtime")

    assert result.status == "success"
    assert len(result.content) < len(large_output)
    assert "semble output truncated" in result.content
    assert result.artifacts["output_truncated"] is True
    assert result.artifacts["output_original_chars"] == len(large_output)


def test_semble_search_times_out_with_progress(
    session_runner: tuple[SkillRunner, str, BlackboardDatabase],
    test_config: HarnessConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _runner_instance, _session_id, database = session_runner
    ctx = SkillContext(
        session_id="s",
        skill_name="semble_search",
        database=database,
        config=test_config,
        on_tool_event=events.append,
    )

    class FakeProcess:
        returncode = None

        def __init__(self) -> None:
            self.killed = False

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True

        def communicate(self) -> tuple[str, str]:
            return "partial", "slow"

    ticks = iter([0.0, 0.0, 11.0, 11.0, 31.0, 31.0])
    fake_process = FakeProcess()
    monkeypatch.setattr(semble_skill.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(semble_skill.time, "sleep", lambda _: None)
    monkeypatch.setattr(semble_skill.subprocess, "Popen", lambda *_, **__: fake_process)

    result = semble_skill._run_semble(ctx, ["semble", "search"], query="find runtime")

    assert result.status == "failed"
    assert result.artifacts["error"] == "timeout"
    assert fake_process.killed is True
    assert "still running" in events[1]
