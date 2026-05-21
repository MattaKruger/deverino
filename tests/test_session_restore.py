from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from harness_poc.core.database import BlackboardDatabase


def test_session_messages_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "blackboard.db"
    db = BlackboardDatabase.from_url(f"sqlite:///{db_path}")
    session_id = db.start_session("test")

    turn_one = [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(parts=[TextPart(content="hi there")]),
    ]
    turn_two = [
        ModelRequest(parts=[UserPromptPart(content="more")]),
        ModelResponse(parts=[TextPart(content="ok")]),
    ]
    blob_one = ModelMessagesTypeAdapter.dump_python(turn_one, mode="json")
    blob_two = ModelMessagesTypeAdapter.dump_python(turn_two, mode="json")

    assert db.append_session_messages(session_id, blob_one) == 1
    assert db.append_session_messages(session_id, blob_two) == 2

    restored_blob = db.load_session_messages(session_id)
    restored = ModelMessagesTypeAdapter.validate_python(restored_blob)
    assert len(restored) == 4
    assert restored[0].parts[0].content == "hello"
    assert restored[3].parts[0].content == "ok"


def test_get_last_session_id(tmp_path: Path) -> None:
    db_path = tmp_path / "blackboard.db"
    db = BlackboardDatabase.from_url(f"sqlite:///{db_path}")
    assert db.get_last_session_id() is None
    first = db.start_session("first")
    second = db.start_session("second")
    last = db.get_last_session_id()
    assert last in {first, second}


def test_session_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "blackboard.db"
    db = BlackboardDatabase.from_url(f"sqlite:///{db_path}")
    session_id = db.start_session("test")
    assert db.session_exists(session_id)
    assert not db.session_exists("does-not-exist")
