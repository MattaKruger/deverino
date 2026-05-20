from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sqlmodel import Session, SQLModel

from harness_poc.core.blackboard_proxy import BlackboardAccessProxy
from harness_poc.core.config import (
    HarnessConfig,
    HarnessPaths,
    LLMConfig,
    ObservabilityConfig,
    RuntimeConfig,
)
from harness_poc.core.context_map_events import EntityReferenced
from harness_poc.core.database import BlackboardDatabase
from harness_poc.core.db_engine import create_db_engine
from harness_poc.core.models import DbContextMapEvent
from harness_poc.core.permissions import SkillPermissions
from harness_poc.core.skill_context import SkillContext
from harness_poc.system_skills.append_event.skill import execute as append_event_execute


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
            default_container_image="python:3.12-slim",
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
            "old": {"content": "old", "priority_score": 0.8},
            "remove": {"content": "remove", "priority_score": 0.1},
        }
    }

    result = materializer._apply_edits(  # noqa: SLF001
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
    assert "remove" not in result["context_understanding"]
    assert result["context_understanding"]["old"]["content"] == "replacement"


def test_enforce_budget_evicts_lowest_priority_entries() -> None:
    materializer = _materializer_module()
    map_data = {
        "parsing_schema": {
            "low": {"content": "x" * 500, "priority_score": 0.1},
            "high": {"content": "y" * 10, "priority_score": 0.9},
        }
    }

    result = materializer._enforce_budget(map_data, token_budget=80)  # noqa: SLF001

    assert "low" not in result["parsing_schema"]
    assert len(json.dumps(result, sort_keys=True)) <= 80 * 4


def test_parse_json_strips_markdown_fences() -> None:
    materializer = _materializer_module()

    result = materializer._parse_json('```json\n{"edits": []}\n```')  # noqa: SLF001

    assert result == {"edits": []}
