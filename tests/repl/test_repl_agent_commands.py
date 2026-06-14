"""Unit tests for /agents, /spawn, /tasks, /result, /cancel, /feed, /slice REPL commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from harness_poc.repl import (
    _is_agents_command,
    _is_cancel_command,
    _is_feed_command,
    _is_result_command,
    _is_slice_command,
    _is_spawn_command,
    _is_tasks_command,
    _parse_cancel_command,
    _parse_feed_command,
    _parse_result_command,
    _parse_slice_command,
    _parse_spawn_command,
    handle_agents_command,
    handle_cancel_command,
    handle_result_command,
    handle_spawn_command,
    handle_tasks_command,
    handle_feed_command,
    handle_slice_command,
)
from harness_poc.v2.execution_engine import (
    SubAgentPoolFullError,
    TaskCancelledError,
    TaskNotFoundError,
)


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


class TestParseSpawnCommand:
    def test_foreground_basic(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("/spawn architect design auth")
        assert persona == "architect"
        assert objective == "design auth"
        assert bg is False
        assert feed is False

    def test_foreground_no_slash(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("spawn reviewer check code")
        assert persona == "reviewer"
        assert objective == "check code"
        assert bg is False
        assert feed is False

    def test_background_with_bg_flag(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("/spawn architect bg design auth")
        assert persona == "architect"
        assert objective == "design auth"
        assert bg is True
        assert feed is False

    def test_background_bg_only_no_objective(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("/spawn coder bg")
        assert persona == "coder"
        assert objective == ""
        assert bg is True
        assert feed is False

    def test_empty_persona(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("/spawn ")
        assert persona == ""
        assert bg is False
        assert feed is False

    def test_no_bg_keyword_in_objective(self) -> None:
        """'bg' inside the objective text is not treated as a flag."""
        persona, objective, bg, feed = _parse_spawn_command("/spawn reviewer check bg color")
        assert persona == "reviewer"
        assert objective == "check bg color"
        assert bg is False
        assert feed is False

    def test_feed_flag(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("/spawn architect --feed design auth")
        assert persona == "architect"
        assert objective == "design auth"
        assert bg is False
        assert feed is True

    def test_feed_flag_only_no_objective(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("/spawn coder --feed")
        assert persona == "coder"
        assert objective == ""
        assert bg is False
        assert feed is True

    def test_bg_and_feed_flags(self) -> None:
        persona, objective, bg, feed = _parse_spawn_command("/spawn architect bg --feed design auth")
        assert persona == "architect"
        assert objective == "design auth"
        assert bg is True
        assert feed is True

    def test_feed_before_bg(self) -> None:
        """--feed before bg token: --feed is stripped, bg becomes part of objective."""
        persona, objective, bg, feed = _parse_spawn_command("/spawn reviewer --feed bg check code")
        assert persona == "reviewer"
        assert objective == "bg check code"
        assert bg is False
        assert feed is True


class TestParseResultCommand:
    def test_extracts_task_id(self) -> None:
        assert _parse_result_command("/result abc123") == "abc123"

    def test_extracts_task_id_no_slash(self) -> None:
        assert _parse_result_command("result def456") == "def456"


class TestParseCancelCommand:
    def test_extracts_task_id(self) -> None:
        assert _parse_cancel_command("/cancel abc123") == "abc123"

    def test_extracts_task_id_no_slash(self) -> None:
        assert _parse_cancel_command("cancel def456") == "def456"


class TestParseFeedCommand:
    def test_extracts_task_id(self) -> None:
        assert _parse_feed_command("/feed abc123") == "abc123"

    def test_extracts_task_id_no_slash(self) -> None:
        assert _parse_feed_command("feed def456") == "def456"


class TestParseSliceCommand:
    def test_extracts_task_id(self) -> None:
        assert _parse_slice_command("/slice abc123") == "abc123"

    def test_extracts_task_id_no_slash(self) -> None:
        assert _parse_slice_command("slice def456") == "def456"


class TestCommandDetectors:
    def test_is_agents(self) -> None:
        assert _is_agents_command("/agents")
        assert _is_agents_command("agents")
        assert not _is_agents_command("/agents x")
        assert not _is_agents_command("agent")

    def test_is_spawn(self) -> None:
        assert _is_spawn_command("/spawn arch task")
        assert _is_spawn_command("spawn arch task")
        assert not _is_spawn_command("/spawn")
        assert not _is_spawn_command("spawn")

    def test_is_tasks(self) -> None:
        assert _is_tasks_command("/tasks")
        assert _is_tasks_command("tasks")
        assert not _is_tasks_command("/tasks x")

    def test_is_result(self) -> None:
        assert _is_result_command("/result abc")
        assert _is_result_command("result abc")
        assert not _is_result_command("/result")

    def test_is_cancel(self) -> None:
        assert _is_cancel_command("/cancel abc")
        assert _is_cancel_command("cancel abc")
        assert not _is_cancel_command("/cancel")

    def test_is_feed(self) -> None:
        assert _is_feed_command("/feed abc123")
        assert _is_feed_command("feed abc123")
        assert not _is_feed_command("/feed")
        assert not _is_feed_command("feed")

    def test_is_slice(self) -> None:
        assert _is_slice_command("/slice abc123")
        assert _is_slice_command("slice abc123")
        assert not _is_slice_command("/slice")
        assert not _is_slice_command("slice")


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEngine:
    """Minimal ExecutionEngine double for testing REPL handlers."""

    def __init__(self) -> None:
        self.spawn_calls: list[dict[str, Any]] = []
        self._results: dict[str, dict[str, Any]] = {}
        self._cancelled: set[str] = set()
        self._next_id = 0

    def spawn_sub_agent(self, **kwargs: Any) -> dict[str, Any]:
        self._next_id += 1
        tid = f"task-{self._next_id}"
        self.spawn_calls.append(kwargs)
        mode = kwargs.get("mode", "foreground")
        if mode == "background":
            self._results[tid] = {
                "task_id": tid,
                "output_label": "running",
                "summary": f"Queued: {kwargs.get('agent_type', '?')}",
                "raw_output": "",
                "metadata": {"agent_type": kwargs.get("agent_type", "?")},
                "session_id": kwargs.get("session_id", ""),
                "background": True,
            }
            return self._results[tid]
        return {
            "task_id": tid,
            "output_label": "completed",
            "summary": f"Done: {kwargs.get('agent_type', '?')}",
            "raw_output": "mock output",
            "metadata": {},
            "session_id": kwargs.get("session_id", ""),
            "background": False,
        }

    def list_tasks(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for tid in self._cancelled:
            result[tid] = {"status": "cancelled", "persona": "mock", "summary": ""}
        for tid, data in self._results.items():
            result[tid] = {
                "status": "done",
                "persona": data.get("metadata", {}).get("agent_type", "mock"),
                "summary": data.get("summary", ""),
            }
        return result

    def result(self, task_id: str) -> dict[str, Any]:
        if task_id in self._cancelled:
            raise TaskCancelledError(f"Task '{task_id}' was cancelled")
        if task_id not in self._results:
            raise TaskNotFoundError(f"No task found with id '{task_id}'")
        return self._results.pop(task_id)

    def cancel(self, task_id: str) -> bool:
        if task_id in self._cancelled:
            return False
        if task_id not in self._results:
            raise TaskNotFoundError(f"No task found with id '{task_id}'")
        self._cancelled.add(task_id)
        self._results.pop(task_id)
        return True


class MockDatabase:
    """Minimal blackboard database double with read_memory."""

    def __init__(self) -> None:
        self._memory: dict[str, dict[str, Any] | str | None] = {}

    def read_memory(self, session_id: str, key: str) -> dict[str, Any] | str | None:
        return self._memory.get(f"{session_id}:{key}")

    def write_memory(self, session_id: str, key: str, payload: dict[str, Any] | str) -> None:
        self._memory[f"{session_id}:{key}"] = payload


@dataclass
class MockV2Runtime:
    execution_engine: MockEngine = field(default_factory=MockEngine)


@dataclass
class MockAppState:
    v2_runtime: MockV2Runtime | None = None
    session_id: str = "mock-session"
    config: Any = None
    pydantic_messages: list[Any] = field(default_factory=list)
    database: MockDatabase = field(default_factory=MockDatabase)

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = MockConfig()


class MockConfig:
    def __init__(self) -> None:
        import pathlib
        self.project_root = pathlib.Path("/tmp")


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------


class TestHandleAgentsCommand:
    def test_no_personas_dir(self) -> None:
        app_state = MockAppState()
        with patch("harness_poc.repl.print_text") as print_text:
            handle_agents_command(app_state)  # type: ignore[arg-type]
            print_text.assert_called_once()
            assert "No personas" in print_text.call_args[0][0]


class TestHandleSpawnCommand:
    def test_missing_engine_prints_error(self) -> None:
        app_state = MockAppState(v2_runtime=None)
        with patch("harness_poc.repl.print_error") as print_error:
            handle_spawn_command(app_state, "/spawn arch task")  # type: ignore[arg-type]
            print_error.assert_called_once()
            assert "not available" in print_error.call_args[0][0]

    def test_foreground_spawn(self) -> None:
        engine = MockEngine()
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_text") as print_text, patch(
            "harness_poc.repl.print_markdown"
        ):
            handle_spawn_command(app_state, "/spawn architect design auth")  # type: ignore[arg-type]
            assert len(engine.spawn_calls) == 1
            assert engine.spawn_calls[0]["mode"] == "foreground"
            assert engine.spawn_calls[0]["agent_type"] == "architect"

    def test_background_spawn(self) -> None:
        engine = MockEngine()
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_text") as print_text:
            handle_spawn_command(app_state, "/spawn reviewer bg check PR")  # type: ignore[arg-type]
            assert len(engine.spawn_calls) == 1
            assert engine.spawn_calls[0]["mode"] == "background"
            assert engine.spawn_calls[0]["agent_type"] == "reviewer"

    def test_missing_persona(self) -> None:
        engine = MockEngine()
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_text") as print_text:
            handle_spawn_command(app_state, "/spawn ")  # type: ignore[arg-type]
            assert "Usage:" in print_text.call_args_list[0][0][0]

    def test_spawn_pool_full(self) -> None:
        engine = MockEngine()

        def failing_spawn(**kwargs: Any) -> dict[str, Any]:
            raise SubAgentPoolFullError("pool full")

        engine.spawn_sub_agent = failing_spawn  # type: ignore[assignment]
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_error") as print_error:
            handle_spawn_command(app_state, "/spawn coder bg task")  # type: ignore[arg-type]
            print_error.assert_called_once()

    def test_spawn_with_feed_flag(self) -> None:
        """--feed flag spawns and calls _feed_task_to_chat."""
        engine = MockEngine()
        db = MockDatabase()
        app_state = MockAppState(
            v2_runtime=MockV2Runtime(execution_engine=engine),
            database=db,
        )

        # The spawn will produce task-1.  Pre-populate blackboard so
        # _feed_task_to_chat can find the delegated result.
        db.write_memory("mock-session", "delegated:task-1", {
            "task_id": "task-1",
            "output_label": "completed",
            "summary": "Designed auth",
            "raw_output": {"text": "Use OAuth2 with PKCE"},
            "metadata": {"agent_type": "architect"},
        })

        with patch("harness_poc.repl.print_text"), patch(
            "harness_poc.repl.print_markdown"
        ):
            handle_spawn_command(app_state, "/spawn architect --feed design auth")  # type: ignore[arg-type]

        # Verify the result was fed to chat
        assert len(app_state.pydantic_messages) == 1
        msg = app_state.pydantic_messages[0]
        part = msg.parts[0]
        assert "OAuth2" in part.content
        assert "<!--fed:task-1" in part.content


class TestHandleTasksCommand:
    def test_no_engine(self) -> None:
        app_state = MockAppState(v2_runtime=None)
        with patch("harness_poc.repl.print_error") as print_error:
            handle_tasks_command(app_state)  # type: ignore[arg-type]
            print_error.assert_called_once()

    def test_empty_tasks(self) -> None:
        engine = MockEngine()
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_text") as print_text:
            handle_tasks_command(app_state)  # type: ignore[arg-type]
            assert "No background tasks" in print_text.call_args[0][0]

    def test_lists_tasks(self) -> None:
        engine = MockEngine()
        engine._results["task-1"] = {
            "task_id": "task-1",
            "output_label": "completed",
            "summary": "Done",
            "metadata": {"agent_type": "architect"},
            "background": True,
        }
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_text") as print_text:
            handle_tasks_command(app_state)  # type: ignore[arg-type]
            output = print_text.call_args_list[1][0][0]
            assert "task-1" in output
            assert "architect" in output


class TestHandleResultCommand:
    def test_no_engine(self) -> None:
        app_state = MockAppState(v2_runtime=None)
        with patch("harness_poc.repl.print_error") as print_error:
            handle_result_command(app_state, "/result abc")  # type: ignore[arg-type]
            print_error.assert_called_once()

    def test_not_found(self) -> None:
        engine = MockEngine()
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_error") as print_error:
            handle_result_command(app_state, "/result nonexistent")  # type: ignore[arg-type]
            assert "No task" in print_error.call_args[0][0]

    def test_retrieves_result(self) -> None:
        engine = MockEngine()
        result = engine.spawn_sub_agent(agent_type="architect", task_payload={"objective": "x"}, mode="background")
        tid = result["task_id"]
        engine._results[tid] = {
            "task_id": tid,
            "output_label": "completed",
            "summary": "All done",
            "raw_output": "mock",
            "metadata": {},
            "background": True,
        }
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_text") as print_text:
            handle_result_command(app_state, f"/result {tid}")  # type: ignore[arg-type]
            assert tid not in engine._results


class TestHandleCancelCommand:
    def test_no_engine(self) -> None:
        app_state = MockAppState(v2_runtime=None)
        with patch("harness_poc.repl.print_error") as print_error:
            handle_cancel_command(app_state, "/cancel abc")  # type: ignore[arg-type]
            print_error.assert_called_once()

    def test_not_found(self) -> None:
        engine = MockEngine()
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_error") as print_error:
            handle_cancel_command(app_state, "/cancel nonexistent")  # type: ignore[arg-type]
            assert "No task" in print_error.call_args[0][0]

    def test_cancels_task(self) -> None:
        engine = MockEngine()
        result = engine.spawn_sub_agent(agent_type="architect", task_payload={"objective": "x"}, mode="background")
        tid = result["task_id"]
        app_state = MockAppState(v2_runtime=MockV2Runtime(execution_engine=engine))
        with patch("harness_poc.repl.print_text") as print_text:
            handle_cancel_command(app_state, f"/cancel {tid}")  # type: ignore[arg-type]
            assert "Cancelled" in print_text.call_args[0][0]
            assert tid in engine._cancelled


# ---------------------------------------------------------------------------
# /feed command tests
# ---------------------------------------------------------------------------


class TestHandleFeedCommand:
    def test_no_task_id_prints_usage(self) -> None:
        app_state = MockAppState()
        with patch("harness_poc.repl.print_text") as print_text:
            handle_feed_command(app_state, "/feed ")  # type: ignore[arg-type]
            assert "Usage:" in print_text.call_args[0][0]

    def test_task_not_found(self) -> None:
        db = MockDatabase()
        app_state = MockAppState(database=db)
        with patch("harness_poc.repl.print_error") as print_error:
            handle_feed_command(app_state, "/feed nonexistent")  # type: ignore[arg-type]
            assert "No result found" in print_error.call_args[0][0]

    def test_feeds_result_to_chat(self) -> None:
        db = MockDatabase()
        db.write_memory("mock-session", "delegated:task-1", {
            "task_id": "task-1",
            "output_label": "completed",
            "summary": "Architect findings",
            "raw_output": {"text": "Use OAuth2 with PKCE", "result": "OK"},
            "metadata": {"agent_type": "architect"},
        })
        app_state = MockAppState(database=db)
        assert len(app_state.pydantic_messages) == 0

        with patch("harness_poc.repl.print_text") as print_text:
            handle_feed_command(app_state, "/feed task-1")  # type: ignore[arg-type]

        assert len(app_state.pydantic_messages) == 1
        msg = app_state.pydantic_messages[0]
        content = msg.parts[0].content
        assert "<!--fed:task-1-->" in content
        assert "OAuth2" in content
        assert "architect" in content.lower() or "Architect" in content
        confirmation = print_text.call_args[0][0]
        assert "Fed" in confirmation
        assert "architect" in confirmation

    def test_feeds_result_no_raw_output(self) -> None:
        """When raw_output is empty, falls back to summary."""
        db = MockDatabase()
        db.write_memory("mock-session", "delegated:task-2", {
            "task_id": "task-2",
            "output_label": "completed",
            "summary": "Short summary only",
            "raw_output": "",
            "metadata": {"agent_type": "reviewer"},
        })
        app_state = MockAppState(database=db)

        with patch("harness_poc.repl.print_text"):
            handle_feed_command(app_state, "/feed task-2")  # type: ignore[arg-type]

        assert len(app_state.pydantic_messages) == 1
        content = app_state.pydantic_messages[0].parts[0].content
        assert "Short summary only" in content
        assert "<!--fed:task-2-->" in content

    def test_feed_not_a_dict(self) -> None:
        """When blackboard value is a plain string, prints error."""
        db = MockDatabase()
        db.write_memory("mock-session", "delegated:task-3", "plain string")
        app_state = MockAppState(database=db)

        with patch("harness_poc.repl.print_error") as print_error:
            handle_feed_command(app_state, "/feed task-3")  # type: ignore[arg-type]

        assert "no feed-able output" in print_error.call_args[0][0]
        assert len(app_state.pydantic_messages) == 0


# ---------------------------------------------------------------------------
# /slice command tests
# ---------------------------------------------------------------------------


class TestHandleSliceCommand:
    def test_no_task_id_prints_usage(self) -> None:
        app_state = MockAppState()
        with patch("harness_poc.repl.print_text") as print_text:
            handle_slice_command(app_state, "/slice ")  # type: ignore[arg-type]
            assert "Usage:" in print_text.call_args[0][0]

    def test_slice_removes_fed_messages(self) -> None:
        db = MockDatabase()
        db.write_memory("mock-session", "delegated:task-1", {
            "task_id": "task-1",
            "output_label": "completed",
            "summary": "Findings",
            "raw_output": "some output",
            "metadata": {"agent_type": "architect"},
        })
        app_state = MockAppState(database=db)

        # First feed the task
        with patch("harness_poc.repl.print_text"):
            handle_feed_command(app_state, "/feed task-1")  # type: ignore[arg-type]
        assert len(app_state.pydantic_messages) == 1

        # Add an unrelated message
        from pydantic_ai.messages import ModelRequest, TextPart
        app_state.pydantic_messages.append(ModelRequest(parts=[TextPart(content="hello")]))
        assert len(app_state.pydantic_messages) == 2

        # Slice the fed message
        with patch("harness_poc.repl.print_text") as print_text:
            handle_slice_command(app_state, "/slice task-1")  # type: ignore[arg-type]

        # Only the unrelated message should remain
        assert len(app_state.pydantic_messages) == 1
        assert "hello" in app_state.pydantic_messages[0].parts[0].content
        confirmation = print_text.call_args[0][0]
        assert "Sliced 1 message" in confirmation

    def test_slice_no_match(self) -> None:
        app_state = MockAppState()
        from pydantic_ai.messages import ModelRequest, TextPart
        app_state.pydantic_messages.append(ModelRequest(parts=[TextPart(content="hello")]))

        with patch("harness_poc.repl.print_text") as print_text:
            handle_slice_command(app_state, "/slice nonexistent")  # type: ignore[arg-type]

        assert len(app_state.pydantic_messages) == 1
        assert "No fed messages found" in print_text.call_args[0][0]
