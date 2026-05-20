from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy import event as sa_event


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

    return engine
