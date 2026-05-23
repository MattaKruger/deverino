from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import Session, select

from harness_poc.core.storage import BlackboardDatabase, DbDocumentChunk, DbDocumentSource


def test_document_source_table_created(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    with Session(db_engine) as session:
        rows = session.exec(select(DbDocumentSource)).all()
    assert rows == []


def test_document_chunk_table_created(db_engine: Engine) -> None:
    db = BlackboardDatabase(db_engine)
    db.create_tables()
    with Session(db_engine) as session:
        rows = session.exec(select(DbDocumentChunk)).all()
    assert rows == []
