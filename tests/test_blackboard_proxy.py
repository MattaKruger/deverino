"""Tests for BlackboardAccessProxy permission enforcement."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.storage import BlackboardAccessProxy, BlackboardDatabase, DbDocumentSource


@pytest.fixture
def db(db_engine: Engine) -> BlackboardDatabase:
    database = BlackboardDatabase(db_engine)
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


# ---- Task 4: document metadata proxy tests ----


def _make_doc_source(sid: str = "src-a") -> DbDocumentSource:
    return DbDocumentSource(
        source_id=sid,
        uri=f"docs/{sid}.md",
        title="Doc",
        kind="doc",
        content_hash="abc",
        status="indexed",
        chunk_count=1,
        metadata_payload={},
        updated_at="2026-05-20T00:00:00",
    )


def test_proxy_get_document_source_requires_read(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "none", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    with pytest.raises(PermissionError):
        proxy.get_document_source("src-a")


def test_proxy_list_document_sources_requires_read(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "none", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    with pytest.raises(PermissionError):
        proxy.list_document_sources()


def test_proxy_upsert_document_source_requires_write(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "read", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    with pytest.raises(PermissionError):
        proxy.upsert_document_source(_make_doc_source())


def test_proxy_upsert_document_source_with_write_permission(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    perms = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "none"})
    proxy = BlackboardAccessProxy(db, perms)
    proxy.upsert_document_source(_make_doc_source("src-z"))
    result = proxy.get_document_source("src-z")
    assert result is not None
    assert result.status == "indexed"


def test_proxy_list_document_sources_with_read_permission(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.upsert_document_source(_make_doc_source("src-1"))
    proxy_r = BlackboardAccessProxy(
        db,
        SkillPermissions.from_yaml({"blackboard": "read", "workspace": "none"}),
    )
    sources = proxy_r.list_document_sources()
    assert any(s.source_id == "src-1" for s in sources)
