"""Integration test for the chat API endpoints.

Run with:
    uv run pytest tests/test_chat_api.py -xvs
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_session_crud() -> None:
    """Session create, list, history, delete all work."""
    from harness_poc.api import create_app

    app = create_app("sqlite:///:memory:")
    from harness_poc.core.config import HarnessConfig

    app.state.config = HarnessConfig.load()

    client = TestClient(app)

    # Create
    r = client.post("/api/sessions/chat")
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert sid

    # List
    r = client.get("/api/sessions/chat")
    assert r.status_code == 200
    assert any(s["session_id"] == sid for s in r.json())

    # History (empty)
    r = client.get(f"/api/sessions/chat/{sid}/history")
    assert r.status_code == 200
    assert r.json() == []

    # Delete
    r = client.delete(f"/api/sessions/chat/{sid}")
    assert r.status_code == 200
    assert r.json()["status"] == "archived"

    # History on deleted session
    r = client.get(f"/api/sessions/chat/{sid}/history")
    assert r.status_code == 404


def test_chat_endpoint_accepts_valid_body() -> None:
    """Chat endpoint accepts proper AG-UI JSON and returns SSE stream."""
    from harness_poc.api import create_app

    app = create_app("sqlite:///:memory:")
    from harness_poc.core.config import HarnessConfig

    app.state.config = HarnessConfig.load()

    client = TestClient(app)

    # Create a session first
    r = client.post("/api/sessions/chat")
    sid = r.json()["session_id"]

    # Send a chat message (this will be slow on first call due to imports)
    r = client.post(
        f"/api/chat?session_id={sid}",
        json={
            "threadId": sid,
            "runId": "r1",
            "state": {},
            "messages": [{"id": "m1", "role": "user", "content": "hello"}],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        },
        timeout=120,  # cold start can take a while
    )

    # Should return 200 with SSE content
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")

    # Should contain AG-UI events
    body = r.text
    assert "RUN_STARTED" in body or "RunStarted" in body or "event:" in body


def test_chat_endpoint_422_on_invalid_body() -> None:
    """Chat endpoint returns 422 for missing required fields."""
    from harness_poc.api import create_app

    app = create_app("sqlite:///:memory:")
    from harness_poc.core.config import HarnessConfig

    app.state.config = HarnessConfig.load()

    client = TestClient(app)

    # Missing threadId, runId, messages, etc.
    r = client.post("/api/chat", json={"garbage": True})
    assert r.status_code == 422
