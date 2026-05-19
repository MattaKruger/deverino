from __future__ import annotations

import harness_poc.console as cons


def setup_function() -> None:
    cons.clear_tui_handlers()


def teardown_function() -> None:
    cons.clear_tui_handlers()


def test_print_text_uses_rich_when_no_tui() -> None:
    cons.print_text("hello plain")  # must not raise


def test_set_tui_handlers_routes_markdown() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=received.append,
        on_error=lambda _: None,
        on_text=lambda _t, _m: None,
    )
    cons.print_markdown("# hi")
    assert received == ["# hi"]


def test_set_tui_handlers_routes_error() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=lambda _: None,
        on_error=received.append,
        on_text=lambda _t, _m: None,
    )
    cons.print_error("bad")
    assert received == ["bad"]


def test_set_tui_handlers_routes_text() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=lambda _: None,
        on_error=lambda _: None,
        on_text=lambda t, _m: received.append(t),
    )
    cons.print_text("hello")
    assert received == ["hello"]


def test_clear_tui_handlers_reverts_to_rich() -> None:
    received: list[str] = []
    cons.set_tui_handlers(
        on_markdown=received.append,
        on_error=lambda _: None,
        on_text=lambda _t, _m: None,
    )
    cons.clear_tui_handlers()
    cons.print_markdown("# hi")
    assert received == []


def test_print_text_markup_false_forwarded() -> None:
    received: list[tuple[str, bool]] = []
    cons.set_tui_handlers(
        on_markdown=lambda _: None,
        on_error=lambda _: None,
        on_text=lambda t, m: received.append((t, m)),
    )
    cons.print_text("[state show]", markup=False)
    assert received == [("[state show]", False)]
