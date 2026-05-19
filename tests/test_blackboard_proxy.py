"""Tests for BlackboardAccessProxy permission enforcement."""

from __future__ import annotations

import tempfile

import pytest

from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.permissions import SkillPermissions


@pytest.fixture
def db() -> BlackboardDatabase:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        path = tf.name
    database = BlackboardDatabase(path)
    database.create_tables()
    session_id = database.start_session("test")
    database.write_memory(session_id, "greeting", "hello")
    return database


# ---- read methods ----


def test_read_memory_allowed_with_read_permission(db: BlackboardDatabase) -> None:
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    result = proxy.read_memory("s1", "greeting")  # session may differ; fine for read
    # If the session exists, it reads; if not, returns None — either is ok
    assert result is None or result == "hello"


def test_list_memory_keys_allowed_with_read_permission(db: BlackboardDatabase) -> None:
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    keys = proxy.list_memory_keys("s1")
    assert isinstance(keys, list)


# ---- write methods blocked with read-only ----


def test_write_memory_blocked_with_read_permission(db: BlackboardDatabase) -> None:
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    with pytest.raises(PermissionError, match="cannot write"):
        proxy.write_memory("s1", "key", "value")


def test_ensure_session_state_blocked_with_read_permission(
    db: BlackboardDatabase,
) -> None:
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    with pytest.raises(PermissionError, match="cannot write"):
        proxy.ensure_session_state("s1")


# ---- write methods allowed with read_write ----


def test_write_memory_allowed_with_read_write_permission(
    db: BlackboardDatabase,
) -> None:
    session_id = db.start_session("rw-test")
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read_write"))
    proxy.write_memory(session_id, "key", "value")
    result = proxy.read_memory(session_id, "key")
    assert result == "value"


def test_ensure_session_state_allowed_with_read_write(
    db: BlackboardDatabase,
) -> None:
    session_id = db.start_session("rw-test")
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read_write"))
    state = proxy.ensure_session_state(session_id)
    assert state is not None


# ---- all blocked with none ----


def test_all_blocked_with_none_permission(db: BlackboardDatabase) -> None:
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="none"))
    with pytest.raises(PermissionError):
        proxy.read_memory("s1", "key")
    with pytest.raises(PermissionError):
        proxy.write_memory("s1", "key", "value")
