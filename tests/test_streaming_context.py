# ruff: noqa: PLR2004
from __future__ import annotations

from typing import TYPE_CHECKING

from harness_poc.app_factory import StreamingContext

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


def test_default_on_text_prints(capsys: CaptureFixture[str]) -> None:
    ctx = StreamingContext()
    ctx.on_text("hello")
    captured = capsys.readouterr()
    assert captured.out == "hello"


def test_default_on_finish_prints_newline(capsys: CaptureFixture[str]) -> None:
    ctx = StreamingContext()
    ctx.on_finish("some content")
    captured = capsys.readouterr()
    assert captured.out == "\n"


def test_default_on_finish_noop_for_empty(capsys: CaptureFixture[str]) -> None:
    ctx = StreamingContext()
    ctx.on_finish("")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_on_text_is_replaceable() -> None:
    collected: list[str] = []
    ctx = StreamingContext()
    ctx.on_text = collected.append
    ctx.on_text("a")
    ctx.on_text("b")
    assert collected == ["a", "b"]


def test_on_tool_event_defaults_none() -> None:
    ctx = StreamingContext()
    assert ctx.on_tool_event is None


def test_session_tokens_accumulate() -> None:
    ctx = StreamingContext()
    ctx.session_tokens += 100
    ctx.session_tokens += 200
    assert ctx.session_tokens == 300


def test_reset_callbacks_restores_defaults_and_preserves_tokens(
    capsys: CaptureFixture[str],
) -> None:
    ctx = StreamingContext()
    ctx.session_tokens = 500
    ctx.on_text = lambda _: None  # replace default
    ctx.on_tool_event = lambda _: None
    ctx.on_finish = lambda _: None

    ctx.reset_callbacks()

    # Callbacks restored to defaults
    ctx.on_text("x")
    captured = capsys.readouterr()
    assert captured.out == "x"
    assert ctx.on_tool_event is None
    # Token count preserved
    assert ctx.session_tokens == 500
