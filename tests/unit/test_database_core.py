"""Unit tests for BlackboardDatabase core CRUD operations.

Tests the foundational blackboard operations — session lifecycle,
memory read/write, and key listing — using an in-memory SQLite engine.
No Postgres required.
"""

# ruff: noqa: ANN201, FBT003

from sqlalchemy import Engine

from harness_poc.core.database import BlackboardDatabase


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def test_start_session_returns_unique_id(in_memory_engine: Engine) -> None:
    """Each call to start_session produces a unique session_id."""
    db = BlackboardDatabase(in_memory_engine)
    id1 = db.start_session("First session")
    id2 = db.start_session("Second session")
    assert id1 != id2
    assert len(id1) == 36  # UUID format
    assert len(id2) == 36


def test_session_exists_after_start(in_memory_engine: Engine) -> None:
    """session_exists returns True for a started session."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test session")
    assert db.session_exists(sid) is True


def test_session_does_not_exist_for_unknown_id(in_memory_engine: Engine) -> None:
    """session_exists returns False for an unknown ID."""
    db = BlackboardDatabase(in_memory_engine)
    assert db.session_exists("nonexistent-id") is False


def test_get_last_session_id(in_memory_engine: Engine) -> None:
    """get_last_session_id returns the most recently created session.

    _utc_now() truncates to seconds, so we sleep to ensure distinct
    created_at values.
    """
    import time

    db = BlackboardDatabase(in_memory_engine)
    db.start_session("First")
    time.sleep(1.1)  # ensure distinct created_at timestamps (second precision)
    last = db.start_session("Last")
    assert db.get_last_session_id() == last


def test_get_last_session_id_empty(in_memory_engine: Engine) -> None:
    """get_last_session_id returns None when no sessions exist."""
    db = BlackboardDatabase(in_memory_engine)
    assert db.get_last_session_id() is None


# ---------------------------------------------------------------------------
# Memory write and read
# ---------------------------------------------------------------------------


def test_write_and_read_memory_string(in_memory_engine: Engine) -> None:
    """A string payload written to memory can be read back."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test")

    db.write_memory(sid, "greeting", "hello world")
    result = db.read_memory(sid, "greeting")

    assert result == "hello world"


def test_write_and_read_memory_dict(in_memory_engine: Engine) -> None:
    """A dict payload is JSON-serialized and deserialized transparently."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test")

    payload = {"status": "complete", "count": 42, "nested": {"key": "value"}}
    db.write_memory(sid, "result", payload)
    result = db.read_memory(sid, "result")

    assert result == payload
    assert result["count"] == 42
    assert result["nested"]["key"] == "value"


def test_read_memory_returns_none_for_unknown_key(in_memory_engine: Engine) -> None:
    """Reading a key that was never written returns None."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test")

    assert db.read_memory(sid, "nonexistent") is None


def test_read_memory_returns_none_for_unknown_session(in_memory_engine: Engine) -> None:
    """Reading from a session that doesn't exist returns None."""
    db = BlackboardDatabase(in_memory_engine)
    assert db.read_memory("no-such-session", "any_key") is None


def test_write_memory_overwrites_existing_key(in_memory_engine: Engine) -> None:
    """Writing to the same key multiple times returns the latest value."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test")

    db.write_memory(sid, "status", "first")
    db.write_memory(sid, "status", "second")

    assert db.read_memory(sid, "status") == "second"


def test_memory_is_isolated_by_session(in_memory_engine: Engine) -> None:
    """Memory written in one session is not visible in another."""
    db = BlackboardDatabase(in_memory_engine)
    sid1 = db.start_session("Session 1")
    sid2 = db.start_session("Session 2")

    db.write_memory(sid1, "data", "session-1-data")
    db.write_memory(sid2, "data", "session-2-data")

    assert db.read_memory(sid1, "data") == "session-1-data"
    assert db.read_memory(sid2, "data") == "session-2-data"


# ---------------------------------------------------------------------------
# Memory key listing
# ---------------------------------------------------------------------------


def test_list_memory_keys_empty(in_memory_engine: Engine) -> None:
    """An empty session returns an empty key list."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test")

    assert db.list_memory_keys(sid) == []


def test_list_memory_keys_returns_all_keys(in_memory_engine: Engine) -> None:
    """list_memory_keys returns all distinct keys for a session, sorted."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test")

    db.write_memory(sid, "zebra", "z")
    db.write_memory(sid, "apple", "a")
    db.write_memory(sid, "mango", "m")

    keys = db.list_memory_keys(sid)
    assert keys == ["apple", "mango", "zebra"]


def test_list_memory_keys_deduplicates(in_memory_engine: Engine) -> None:
    """Writing the same key multiple times returns it only once."""
    db = BlackboardDatabase(in_memory_engine)
    sid = db.start_session("Test")

    db.write_memory(sid, "key", "first")
    db.write_memory(sid, "key", "second")
    db.write_memory(sid, "key", "third")

    assert db.list_memory_keys(sid) == ["key"]


def test_list_memory_keys_unknown_session(in_memory_engine: Engine) -> None:
    """Listing keys for an unknown session returns an empty list."""
    db = BlackboardDatabase(in_memory_engine)
    assert db.list_memory_keys("no-such-session") == []
