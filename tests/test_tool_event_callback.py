from __future__ import annotations

from unittest.mock import MagicMock

from harness_poc.core.pydantic_runtime import AgentDeps, _emit_tool_progress


def _make_ctx(on_tool_event: object = None) -> object:
    deps = AgentDeps(
        session_id="test",
        database=MagicMock(),
        config=MagicMock(),
        skill_runner=MagicMock(),
        on_tool_event=on_tool_event,
    )
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


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
