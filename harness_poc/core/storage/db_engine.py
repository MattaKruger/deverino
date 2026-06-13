from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy import event as sa_event

if TYPE_CHECKING:
    from sqlalchemy import Engine


def create_db_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        @sa_event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn: object, _conn_record: object) -> None:
            import sqlite3  # noqa: PLC0415

            if isinstance(dbapi_conn, sqlite3.Connection):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.close()

    if engine.dialect.name == "postgresql":
        _register_pgvector()

    return engine


def _register_pgvector() -> None:
    """Register pgvector adapter for psycopg2 so vector columns serialize correctly."""
    try:
        from pgvector.psycopg2 import register_vector_adapter  # noqa: PLC0415  # ty: ignore

        register_vector_adapter()
    except ImportError:
        pass  # pgvector not installed — CopT gate will be disabled
