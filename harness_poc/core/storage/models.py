from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Column, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

# JSONB on PostgreSQL, JSON on everything else (SQLite for tests)
_StateJSON = JSON().with_variant(JSONB(), "postgresql")


class DbSession(SQLModel, table=True):
    __tablename__ = "sessions"  # type: ignore[assignment]

    session_id: str = Field(primary_key=True)
    global_objective: str
    status: str
    created_at: str
    active_corpus_key: str | None = Field(default=None)


class DbSharedMemory(SQLModel, table=True):
    __tablename__ = "shared_memory"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "idx_shared_memory_session_key",
            "session_id",
            "memory_key",
            "created_at",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.session_id")
    memory_key: str
    # TEXT: can be a raw string or a JSON-encoded string (str | dict via write_memory)
    data_payload: str = Field(sa_column=Column(Text, nullable=False))
    created_at: str


class DbProjectState(SQLModel, table=True):
    __tablename__ = "project_state"  # type: ignore[assignment]

    project_id: str = Field(primary_key=True)
    state_payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    version: int
    updated_at: str


class DbSessionState(SQLModel, table=True):
    __tablename__ = "session_state"  # type: ignore[assignment]

    session_id: str = Field(primary_key=True, foreign_key="sessions.session_id")
    state_payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    version: int
    dirty: bool
    updated_at: str


class DbStateProposal(SQLModel, table=True):
    __tablename__ = "state_proposals"  # type: ignore[assignment]

    proposal_id: str = Field(primary_key=True)
    session_id: str = Field(foreign_key="sessions.session_id")
    status: str
    proposal_payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    created_at: str
    resolved_at: str | None = Field(default=None, sa_column=Column(DateTime, nullable=True))


class DbStateEvent(SQLModel, table=True):
    __tablename__ = "state_events"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    scope: str
    scope_id: str
    event_type: str
    payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    created_at: str


class DbContextMapCycle(SQLModel, table=True):
    __tablename__ = "context_map_cycles"  # type: ignore[assignment]

    corpus_key: str = Field(primary_key=True)
    cycle_n: int = Field(default=0)
    updated_at: str


class DbSessionSnapshot(SQLModel, table=True):
    __tablename__ = "session_snapshots"  # type: ignore[assignment]

    session_id: str = Field(primary_key=True)
    last_offset: int
    state_payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    updated_at: str | None = Field(default=None)


class DbSessionMessage(SQLModel, table=True):
    __tablename__ = "session_messages"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "idx_session_messages_session_ordinal",
            "session_id",
            "ordinal",
        ),
    )

    session_id: str = Field(primary_key=True, foreign_key="sessions.session_id")
    ordinal: int = Field(primary_key=True)
    messages_blob: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    created_at: str


class DbDocumentSource(SQLModel, table=True):
    __tablename__ = "document_sources"  # type: ignore[assignment]

    source_id: str = Field(primary_key=True)
    uri: str
    title: str
    kind: str
    content_hash: str
    status: str  # pending | indexed | skipped | failed
    chunk_count: int = Field(default=0)
    indexed_at: str | None = Field(default=None)
    error: str | None = Field(default=None)
    metadata_payload: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    updated_at: str


class DbDocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"  # type: ignore[assignment]
    __table_args__ = (Index("idx_document_chunks_source", "source_id", "chunk_index"),)

    chunk_id: str = Field(primary_key=True)
    source_id: str = Field(foreign_key="document_sources.source_id")
    chunk_index: int
    content_hash: str
    vespa_id: str
    indexed_at: str | None = Field(default=None)


class DbContextMapEvent(SQLModel, table=True):
    __tablename__ = "context_map_events"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "idx_context_map_events_corpus_unprocessed",
            "corpus_key",
            "processed",
            "timestamp",
        ),
    )

    event_id: str = Field(primary_key=True)
    corpus_key: str
    session_id: str
    event_type: str
    payload: str = Field(sa_column=Column(Text, nullable=False))
    timestamp: str
    processed: int = Field(default=0)


class DbContextMap(SQLModel, table=True):
    __tablename__ = "context_map"  # type: ignore[assignment]

    corpus_key: str = Field(primary_key=True)
    map_json: str = Field(sa_column=Column(Text, nullable=False))
    token_count: int
    version: int = Field(default=1)
    last_updated: str
    freeze_until: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    schema_version: int = Field(default=1)



class DbMaterializedContextMap(SQLModel, table=True):
    """V2 materialized context map snapshot."""

    __tablename__ = "materialized_context_maps_v2"  # type: ignore[assignment]

    project_id: str = Field(primary_key=True)
    active_persona: str = Field(nullable=False)
    pedagogy_snapshot: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    verified_state: Any = Field(sa_column=Column(_StateJSON, nullable=False))
    last_event_id: str | None = Field(default=None)
    updated_at: str


# ---------------------------------------------------------------------------
# CopT Gate — embedding table (pgvector-only, created via raw SQL on PostgreSQL)
# ---------------------------------------------------------------------------

@dataclass
class DbContextMapEmbedding:
    """A single embedding row for the CopT gate.

    Stored in the ``context_map_embeddings`` table (created via raw SQL,
    not SQLModel metadata, because pgvector is PostgreSQL-only).
    """

    corpus_key: str
    entry_key: str
    embedding: list[float]



@dataclass
class DbContextMapRetrievalEmbedding:
    """A single retrieval embedding row for semantic corpus retrieval.

    Stored in the ``context_map_retrieval_embeddings`` table (created via raw SQL,
    not SQLModel metadata, because pgvector is PostgreSQL-only).

    Uses BAAI/bge-base-en-v1.5 (768-dim), separate from the CopT gate's
    all-MiniLM-L6-v2 (384-dim) embeddings in ``context_map_embeddings``.
    """

    corpus_key: str
    entry_key: str
    embedding: list[float]
    model: str = "BAAI/bge-base-en-v1.5"
