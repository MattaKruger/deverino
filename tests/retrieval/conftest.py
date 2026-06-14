"""Skip logic for Vespa integration tests — opt-in via --run-vespa.

All retrieval tests make real HTTP calls to a Vespa container and are skipped
by default.  Pass ``--run-vespa`` to run them.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Skip logic: Vespa tests are opt-in via --run-vespa
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-vespa",
        action="store_true",
        default=False,
        help="Run Vespa integration tests (real HTTP calls — skipped by default)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "vespa: mark test as requiring a running Vespa container",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if not config.getoption("--run-vespa", default=False):
        skip_vespa = pytest.mark.skip(reason="--run-vespa not set")
        for item in items:
            if "retrieval" in str(item.fspath):
                item.add_marker(skip_vespa)
