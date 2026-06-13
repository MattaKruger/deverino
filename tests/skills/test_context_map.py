from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

import pytest
from sqlmodel import Session, SQLModel

from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.events import EntityReferenced, MapEntryEvicted, deserialize_event
from harness_poc.core.execution import MaterializerRunner
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.skills import SkillContext, SkillResult
from harness_poc.core.storage import (
    BlackboardAccessProxy,
    BlackboardDatabase,
    DbContextMapEvent,
    create_db_engine,
)
from harness_poc.system_skills.append_event.skill import execute as append_event_execute

if TYPE_CHECKING:
    from harness_poc.core.skills import SkillRunner


def _db() -> BlackboardDatabase:
    engine = create_db_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return BlackboardDatabase(engine)


def _config(tmp_path: Path) -> HarnessConfig:
    return HarnessConfig(
        project_root=tmp_path,
        config_path=tmp_path / "harness.yaml",
        paths=HarnessPaths(
            soul=tmp_path / "SOUL.md",
            system_tools=tmp_path / "system_tools",
            system_skills=tmp_path / "system_skills",
            project_skills=tmp_path / "skills",
            workflows=tmp_path / "workflows",
            pipelines=tmp_path / "pipelines",
            personas=tmp_path / "personas",
        ),
        llm=LLMConfig(provider="deepseek", model="deepseek-v4-flash", base_url=None),
        runtime=RuntimeConfig(
            database_url="sqlite:///:memory:",
            default_container_image="python:3.14-slim",
        ),
        observability=ObservabilityConfig(logfire_enabled=False),
        project_id="deverino",
    )


def _ctx(db: BlackboardDatabase, tmp_path: Path) -> SkillContext:
    session_id = db.start_session("test")
    permissions = SkillPermissions.from_yaml({"blackboard": "read_write", "workspace": "none"})
    return SkillContext(
        session_id=session_id,
        skill_name="append_event",
        database=BlackboardAccessProxy(db, permissions),
        config=_config(tmp_path),
        permissions=permissions,
    )


def _materializer_module() -> ModuleType:
    path = Path(__file__).parents[2] / "skills" / "context-map-materializer" / "skill.py"
    spec = importlib.util.spec_from_file_location("context_map_materializer_skill", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_hex_id(value: str) -> bool:
    return len(value) == 8 and all(char in "0123456789abcdef" for char in value)


def test_append_context_map_event_inserts_pending_row() -> None:
    db = _db()
    session_id = db.start_session("test")
    event = EntityReferenced(
        session_id=session_id,
        corpus_key="deverino:codebase",
        entity_name="BlackboardDatabase",
        entity_type="class",
        context="Owns durable state writes.",
    )

    db.append_context_map_event(event)

    rows = db.get_pending_context_map_events("deverino:codebase")
    assert len(rows) == 1
    assert rows[0].event_id == event.event_id
    assert rows[0].processed == 0


def test_write_map_and_mark_processed_updates_map_and_events() -> None:
    db = _db()
    session_id = db.start_session("test")
    event = EntityReferenced(
        session_id=session_id,
        corpus_key="deverino:codebase",
        entity_name="SkillRunner",
        entity_type="class",
        context="Loads SKILL.md frontmatter.",
    )
    db.append_context_map_event(event)

    from datetime import UTC, datetime

    from harness_poc.core.context_map.schema import MapEntry

    entries = [
        MapEntry(
            entry_id="12345678",
            key="skill_runner",
            section="context_understanding",
            observation_type="entity",
            summary="Loads skills.",
            priority=0.7,
            source_event_ids=[event.event_id],
            first_seen=datetime.now(tz=UTC),
            last_updated=datetime.now(tz=UTC),
            first_seen_cycle=1,
            last_seen_cycle=1,
            token_estimate=12,
        )
    ]

    db.write_map_and_mark_processed(
        "deverino:codebase",
        entries,
        token_count=12,
        event_ids=[event.event_id],
    )

    assert db.get_pending_context_map_events("deverino:codebase") == []
    assert db.get_context_map("deverino:codebase") == entries
    with Session(db.engine) as session:
        row = session.get(DbContextMapEvent, event.event_id)
        assert row is not None
        assert row.processed == 1


def test_is_map_frozen_returns_true_when_frozen() -> None:
    db = _db()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        {},
        token_count=0,
        event_ids=[],
        freeze_until="2026-05-20T12:05:00+00:00",
    )

    assert db.is_map_frozen("deverino:codebase", "2026-05-20T12:00:00+00:00") is True


def test_is_map_frozen_returns_false_when_expired() -> None:
    db = _db()
    db.write_map_and_mark_processed(
        "deverino:codebase",
        {},
        token_count=0,
        event_ids=[],
        freeze_until="2026-05-20T11:55:00+00:00",
    )

    assert db.is_map_frozen("deverino:codebase", "2026-05-20T12:00:00+00:00") is False


def test_get_pending_corpus_keys_returns_only_unprocessed_keys() -> None:
    db = _db()
    session_id = db.start_session("test")
    processed = EntityReferenced(
        session_id=session_id,
        corpus_key="deverino:processed",
        entity_name="A",
        entity_type="thing",
        context="processed",
    )
    pending = EntityReferenced(
        session_id=session_id,
        corpus_key="deverino:pending",
        entity_name="B",
        entity_type="thing",
        context="pending",
    )
    db.append_context_map_event(processed)
    db.append_context_map_event(pending)
    db.write_map_and_mark_processed("deverino:processed", {}, 0, [processed.event_id])

    assert db.get_pending_corpus_keys() == ["deverino:pending"]


def test_get_context_map_returns_none_or_parsed_dict() -> None:
    db = _db()
    assert db.get_context_map("missing") is None

    from datetime import UTC, datetime

    from harness_poc.core.context_map.schema import MapEntry

    entries = [
        MapEntry(
            entry_id="abc123ef",
            key="test",
            section="context_understanding",
            observation_type="entity",
            summary="test content",
            priority=0.5,
            source_event_ids=[],
            first_seen=datetime.now(tz=UTC),
            last_updated=datetime.now(tz=UTC),
            first_seen_cycle=1,
            last_seen_cycle=1,
            token_estimate=3,
        )
    ]

    db.write_map_and_mark_processed("deverino:codebase", entries, 3, [])

    assert db.get_context_map("deverino:codebase") == entries


def test_append_event_skill_rejects_unknown_event_type(tmp_path: Path) -> None:
    db = _db()
    ctx = _ctx(db, tmp_path)

    result = append_event_execute(
        ctx,
        {"event_type": "unknown", "corpus_key": "deverino:codebase", "payload": {}},
    )

    assert result.status == "failed"
    assert "Unknown event_type" in result.content


def test_append_event_skill_accepts_entity_referenced_payload(tmp_path: Path) -> None:
    db = _db()
    ctx = _ctx(db, tmp_path)

    result = append_event_execute(
        ctx,
        {
            "event_type": "entity_referenced",
            "corpus_key": "deverino:codebase",
            "payload": {
                "entity_name": "ContextMapEvent",
                "entity_type": "model",
                "context": "Base Pydantic event model.",
            },
        },
    )

    assert result.status == "success"
    rows = db.get_pending_context_map_events("deverino:codebase")
    assert len(rows) == 1
    assert rows[0].event_type == "entity_referenced"


def test_execute_reports_map_changed_false_for_noop_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    ctx = _ctx(db, tmp_path)
    event = EntityReferenced(
        session_id=ctx.session_id,
        corpus_key="deverino:codebase",
        entity_name="SkillRunner",
        entity_type="class",
        context="Loads skills.",
    )
    db.append_context_map_event(event)

    from datetime import UTC, datetime

    from harness_poc.core.context_map.schema import MapEntry

    # The base priority weight for 'entity' is 0.6. Use it to prevent priority recalculation delta.
    entries = [
        MapEntry(
            entry_id="12345678",
            key="skill_runner",
            section="context_understanding",
            observation_type="entity",
            summary="Loads skills.",
            priority=0.6,
            source_event_ids=[event.event_id],
            first_seen=datetime.now(tz=UTC),
            last_updated=datetime.now(tz=UTC),
            first_seen_cycle=1,
            last_seen_cycle=1,
            token_estimate=12,
        )
    ]
    db.write_map_and_mark_processed(
        "deverino:codebase",
        entries,
        token_count=12,
        event_ids=[],
    )
    materializer = _materializer_module()

    async def mock_run_distiller(*args, **kwargs):
        return []
    monkeypatch.setattr(materializer, "run_distiller", mock_run_distiller)

    result = asyncio.run(materializer.execute(ctx, {"corpus_key": "deverino:codebase"}))

    assert result.status == "success"
    assert result.artifacts["map_changed"] is False


def test_materializer_emits_derivation_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    ctx = _ctx(db, tmp_path)
    event = EntityReferenced(
        session_id=ctx.session_id,
        corpus_key="deverino:codebase",
        entity_name="LargeEntry",
        entity_type="concept",
        context="Needs budget eviction.",
    )
    db.append_context_map_event(event)
    materializer = _materializer_module()

    from harness_poc.core.context_map.schema import DistillerEntry
    async def mock_run_distiller(*args, **kwargs):
        return [
            DistillerEntry(
                key="large",
                observation_type="insight",
                summary="x" * 500,
                source_event_ids=[event.event_id],
            )
        ]
    monkeypatch.setattr(materializer, "run_distiller", mock_run_distiller)

    from dataclasses import replace
    ctx = replace(
        ctx,
        config=replace(
            ctx.config,
            cartographer=replace(ctx.config.cartographer, token_budget=20)
        )
    )

    result = asyncio.run(
        materializer.execute(
            ctx,
            {"corpus_key": "deverino:codebase", "session_id": ctx.session_id},
        )
    )

    assert result.status == "success"
    rows = db.get_pending_context_map_events("deverino:codebase")
    payloads = [deserialize_event(json.loads(row.payload)) for row in rows]
    evicted = [payload for payload in payloads if isinstance(payload, MapEntryEvicted)]
    assert len(evicted) == 1
    assert evicted[0].entry_key == "large"
    assert evicted[0].entry_id is not None


class _FakeSkillRunner:
    def __init__(self, artifacts: dict[str, object]) -> None:
        self.artifacts = artifacts

    def execute_skill(self, *_args: object) -> SkillResult:
        return SkillResult(status="success", content="ok", artifacts=self.artifacts)


def test_materializer_skips_frozen_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    config = _config(tmp_path)
    session_id = db.start_session("test")
    event = EntityReferenced(
        session_id=session_id,
        corpus_key="deverino:codebase",
        entity_name="A",
        entity_type="thing",
        context="pending",
    )
    db.append_context_map_event(event)
    db.write_map_and_mark_processed(
        "deverino:codebase",
        {},
        token_count=0,
        event_ids=[],
        freeze_until="2026-05-20T12:05:00+00:00",
    )
    skill_runner = cast("SkillRunner", _FakeSkillRunner({}))
    runner = MaterializerRunner(db, skill_runner, config, session_id=session_id)
    calls: list[str] = []

    async def fake_materialize(corpus_key: str) -> None:
        calls.append(corpus_key)

    class FrozenDatetime:
        @staticmethod
        def now(*, tz: object | None = None) -> datetime:
            del tz
            return datetime.fromisoformat("2026-05-20T12:00:00+00:00")

    monkeypatch.setattr(runner, "_materialize", fake_materialize)
    monkeypatch.setattr(
        "harness_poc.core.execution.materializer_runner.datetime",
        FrozenDatetime,
    )

    asyncio.run(runner._poll_once())

    assert calls == []


def test_materializer_freezes_after_three_no_change_cycles(tmp_path: Path) -> None:
    db = _db()
    config = _config(tmp_path)
    session_id = db.start_session("test")
    db.write_map_and_mark_processed("deverino:codebase", {}, token_count=0, event_ids=[])
    runner = MaterializerRunner(
        db,
        cast("SkillRunner", _FakeSkillRunner({"map_changed": False})),
        config,
        session_id=session_id,
    )

    asyncio.run(runner._materialize("deverino:codebase"))
    assert db.is_map_frozen("deverino:codebase") is False
    asyncio.run(runner._materialize("deverino:codebase"))
    assert db.is_map_frozen("deverino:codebase") is False
    asyncio.run(runner._materialize("deverino:codebase"))
    assert db.is_map_frozen("deverino:codebase") is True


# Deleted obsolete tests for parse_json.
