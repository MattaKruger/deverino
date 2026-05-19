from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from harness_poc.core.pydantic_runtime import AgentDeps, _emit_tool_progress
from harness_poc.core.skill_context import SkillContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import RunContext


def _make_ctx(
    on_tool_event: Callable[[str], None] | None = None,
) -> RunContext[AgentDeps]:
    deps = AgentDeps(
        session_id="test",
        database=MagicMock(),
        config=MagicMock(),
        skill_runner=MagicMock(),
        on_tool_event=on_tool_event,
    )
    ctx = MagicMock()
    ctx.deps = deps
    return cast("RunContext[AgentDeps]", ctx)


def test_emit_tool_progress_calls_handler() -> None:
    events: list[str] = []
    ctx = _make_ctx(on_tool_event=events.append)
    _emit_tool_progress(ctx, "my_skill: running...")
    assert events == ["my_skill: running..."]


def test_emit_tool_progress_noop_when_no_handler() -> None:
    ctx = _make_ctx(on_tool_event=None)
    _emit_tool_progress(ctx, "my_skill: running...")  # must not raise


def test_agent_deps_on_tool_event_defaults_none() -> None:
    deps = AgentDeps(
        session_id="s",
        database=MagicMock(),
        config=MagicMock(),
        skill_runner=MagicMock(),
    )
    assert deps.on_tool_event is None


def test_skill_context_emits_tool_events() -> None:
    events: list[str] = []
    ctx = SkillContext(
        session_id="s",
        skill_name="sample",
        database=MagicMock(),
        config=MagicMock(),
        on_tool_event=events.append,
    )

    ctx.emit_tool_event("sample: running")

    assert events == ["sample: running"]
