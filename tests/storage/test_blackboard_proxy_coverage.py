"""Regression guard: every write-named BlackboardDatabase method must be in _WRITE_METHODS.

If this test fails, a new write method was added to BlackboardDatabase but not
classified in _WRITE_METHODS — it would silently get a read-guard instead of
failing closed. Fix: add the method name to _WRITE_METHODS.
"""

import inspect

from harness_poc.core.storage.blackboard_proxy import _WRITE_METHODS
from harness_poc.core.storage.database import BlackboardDatabase

_WRITE_PREFIXES = ("write_", "set_", "upsert_", "append_", "create_", "approve_", "reject_", "start_")


def _db_write_candidates() -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(BlackboardDatabase, predicate=inspect.isfunction)
        if not name.startswith("_") and name.startswith(_WRITE_PREFIXES)
    }


def test_all_write_named_db_methods_are_classified() -> None:
    unclassified = _db_write_candidates() - _WRITE_METHODS
    assert not unclassified, (
        f"BlackboardDatabase has write-named methods not in _WRITE_METHODS: {sorted(unclassified)}. "
        "Add them to _WRITE_METHODS in blackboard_proxy.py, or rename if they are reads."
    )
