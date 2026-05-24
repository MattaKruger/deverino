"""Tests for active_corpus_key on sessions — Gap 2a."""

from __future__ import annotations

from sqlalchemy import Engine

from harness_poc.core.storage import BlackboardDatabase


def test_start_session_persists_active_corpus(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    sid = db.start_session("obj", active_corpus_key="deverino:dashboard")
    assert db.get_session_corpus_key(sid, default="x") == "deverino:dashboard"


def test_legacy_session_falls_back_to_default(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    sid = db.start_session("obj")  # no active_corpus_key
    assert (
        db.get_session_corpus_key(sid, default="deverino:codebase")
        == "deverino:codebase"
    )


def test_resume_does_not_overwrite_stored_corpus(
    db_engine: Engine,
) -> None:
    """--corpus on resume must be ignored; the session remembers its corpus.

    This is tested at the database layer: start_session writes the key,
    and a second call to get_session_corpus_key still returns it.
    """
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    sid = db.start_session("obj", active_corpus_key="deverino:dashboard")
    # Simulating resume: retrieve the stored value, don't overwrite
    assert db.get_session_corpus_key(sid, default="deverino:codebase") == "deverino:dashboard"


def test_get_session_corpus_key_unknown_session_returns_default(
    db_engine: Engine,
) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    assert (
        db.get_session_corpus_key("nonexistent", default="fallback")
        == "fallback"
    )
