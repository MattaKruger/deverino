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

from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.context_map_events import EntityReferenced, MapEntryEvicted, deserialize_event
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.db_engine import create_db_engine
from harness_poc.core.materializer_runner import MaterializerRunner
from harness_poc.core.models import DbContextMapEvent
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.skill_context import SkillContext, SkillResult
from harness_poc.system_skills.append_event.skill import execute as append_event_execute

if TYPE_CHECKING:
    from harness_poc.core.skill_runner import SkillRunner


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
    path = Path(__file__).parents[1] / "skills" / "context-map-materializer" / "skill.py"
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

    db.write_map_and_mark_processed(
        "deverino:codebase",
        {"context_understanding": {"skill_runner": {"content": "Loads skills."}}},
        token_count=12,
        event_ids=[event.event_id],
    )

    assert db.get_pending_context_map_events("deverino:codebase") == []
    assert db.get_context_map("deverino:codebase") == {
        "context_understanding": {"skill_runner": {"content": "Loads skills."}}
    }
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

    db.write_map_and_mark_processed("deverino:codebase", {"a": {"b": "c"}}, 3, [])

    assert db.get_context_map("deverino:codebase") == {"a": {"b": "c"}}


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


def test_apply_edits_add_delete_replace_operations() -> None:
    materializer = _materializer_module()
    current = {
        "context_understanding": {
            "old": {"entry_id": "11111111", "content": "old", "priority_score": 0.8},
            "remove": {"entry_id": "22222222", "content": "remove", "priority_score": 0.1},
        }
    }

    result, applied_count = materializer._apply_edits(
        current,
        [
            {
                "op": "ADD",
                "section": "context_roadmap",
                "entry_key": "new",
                "content": "new content",
                "priority_score": 0.7,
            },
            {
                "op": "DELETE",
                "section": "context_understanding",
                "entry_key": "remove",
            },
            {
                "op": "REPLACE",
                "section": "context_understanding",
                "entry_key": "old",
                "content": "replacement",
                "priority_score": 0.9,
            },
        ],
    )

    assert result["context_roadmap"]["new"]["content"] == "new content"
    assert _is_hex_id(result["context_roadmap"]["new"]["entry_id"])
    assert "remove" not in result["context_understanding"]
    assert result["context_understanding"]["old"]["content"] == "replacement"
    assert result["context_understanding"]["old"]["entry_id"] == "11111111"
    assert applied_count == 3


def test_apply_edits_add_assigns_entry_id() -> None:
    materializer = _materializer_module()

    result, applied_count = materializer._apply_edits(
        {},
        [
            {
                "op": "ADD",
                "section": "context_roadmap",
                "entry_key": "new",
                "content": "new content",
                "priority_score": 0.7,
            }
        ],
    )

    assert _is_hex_id(result["context_roadmap"]["new"]["entry_id"])
    assert applied_count == 1


def test_apply_edits_replace_retains_entry_id() -> None:
    materializer = _materializer_module()
    current = {
        "context_understanding": {
            "existing": {"entry_id": "abc123ef", "content": "old", "priority_score": 0.8}
        }
    }

    result, applied_count = materializer._apply_edits(
        current,
        [
            {
                "op": "REPLACE",
                "section": "context_understanding",
                "entry_key": "existing",
                "content": "new",
                "priority_score": 0.9,
            }
        ],
    )

    assert result["context_understanding"]["existing"]["entry_id"] == "abc123ef"
    assert applied_count == 1


def test_ensure_entry_ids_handles_old_format_entries() -> None:
    materializer = _materializer_module()

    result = materializer._ensure_entry_ids(
        {"context_understanding": {"old": {"content": "old", "priority_score": 0.6}}}
    )

    assert _is_hex_id(result["context_understanding"]["old"]["entry_id"])


def test_apply_edits_reports_no_change_for_missing_delete() -> None:
    materializer = _materializer_module()

    _result, applied_count = materializer._apply_edits(
        {},
        [{"op": "DELETE", "section": "context_understanding", "entry_key": "missing"}],
    )

    assert applied_count == 0


def test_enforce_budget_evicts_lowest_priority_entries() -> None:
    materializer = _materializer_module()
    map_data = {
        "parsing_schema": {
            "low": {"content": "x" * 500, "priority_score": 0.1},
            "high": {"content": "y" * 10, "priority_score": 0.9},
        }
    }

    result, evictions = materializer._enforce_budget(map_data, token_budget=80)

    assert "low" not in result["parsing_schema"]
    assert evictions[0]["entry_key"] == "low"
    assert len(json.dumps(result, sort_keys=True)) <= 80 * 4


def test_enforce_budget_returns_evictions() -> None:
    materializer = _materializer_module()
    map_data = {
        "context_roadmap": {
            "low": {
                "entry_id": "12345678",
                "content": "x" * 500,
                "priority_score": 0.1,
            }
        }
    }

    _result, evictions = materializer._enforce_budget(map_data, token_budget=20)

    assert evictions == [
        {
            "entry_id": "12345678",
            "entry_key": "low",
            "section": "context_roadmap",
            "priority_score": 0.1,
        }
    ]


def test_detect_promotions_detects_upward_moves() -> None:
    materializer = _materializer_module()
    old = {
        "context_roadmap": {
            "entry": {"entry_id": "12345678", "content": "old", "priority_score": 0.5}
        }
    }
    new = {
        "domain_constants": {
            "entry": {"entry_id": "12345678", "content": "new", "priority_score": 0.8}
        }
    }

    promotions = materializer._detect_promotions(old, new)

    assert promotions == [
        {
            "entry_id": "12345678",
            "entry_key": "entry",
            "from_section": "context_roadmap",
            "to_section": "domain_constants",
        }
    ]


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
    db.write_map_and_mark_processed(
        "deverino:codebase",
        {
            "context_understanding": {
                "skill_runner": {
                    "entry_id": "12345678",
                    "content": "Loads skills.",
                    "priority_score": 0.7,
                }
            }
        },
        token_count=12,
        event_ids=[],
    )
    materializer = _materializer_module()
    responses = iter(['{"diagnosis": "", "tags": {}, "observations": []}', '{"edits": []}'])
    monkeypatch.setattr(materializer, "chat_text", lambda *_args, **_kwargs: next(responses))

    result = materializer.execute(ctx, {"corpus_key": "deverino:codebase"})

    assert result.status == "success"
    assert result.artifacts["edits_applied"] == 0
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
    responses = iter(
        [
            '{"diagnosis": "", "tags": {}, "observations": []}',
            json.dumps(
                {
                    "edits": [
                        {
                            "op": "ADD",
                            "section": "context_roadmap",
                            "entry_key": "large",
                            "content": "x" * 500,
                            "priority_score": 0.1,
                        }
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(materializer, "chat_text", lambda *_args, **_kwargs: next(responses))

    result = materializer.execute(
        ctx,
        {"corpus_key": "deverino:codebase", "token_budget": 20, "session_id": ctx.session_id},
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
        "harness_poc.core.materializer_runner.datetime",
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


def test_parse_json_strips_markdown_fences() -> None:
    materializer = _materializer_module()

    result = materializer._parse_json('```json\n{"edits": []}\n```')

    assert result == {"edits": []}
