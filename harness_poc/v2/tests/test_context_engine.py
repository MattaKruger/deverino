"""Tests for ContextEngine — persona-driven materialization and failure warm-up.

Uses in-memory spies (no database, no real materializer) so tests run in
milliseconds and are safe for CI.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from harness_poc.v2.context_engine import (
    ContextEngine,
    ContextEngineError,
    PedagogyNotFoundError,
    PersonaNotFoundError,
)
from harness_poc.v2.contracts.context_map_pipeline import (
    DbContextMap,
    MaterializationError,
)

# ---------------------------------------------------------------------------
# Test doubles (spies)
# ---------------------------------------------------------------------------

class DatabaseSpy:
    """Records DB calls for assertion — no real database."""

    def __init__(self) -> None:
        self.context_events: list[dict] = []
        self.materialized_maps: dict[str, dict] = {}
        self._next_event_id = 1

    def append_context_event(
        self,
        session_id: str,
        team_member: str,
        event_type: str,
        payload: dict,
    ) -> int:
        event_id = self._next_event_id
        self._next_event_id += 1
        self.context_events.append(
            {
                "id": event_id,
                "session_id": session_id,
                "team_member": team_member,
                "event_type": event_type,
                "payload": payload,
            }
        )
        return event_id

    def get_materialized_context_map(self, project_id: str) -> dict | None:
        return self.materialized_maps.get(project_id)

    def upsert_materialized_context_map(
        self,
        project_id: str,
        active_persona: str,
        pedagogy_snapshot: dict,
        verified_state: dict,
        last_event_id: int,
    ) -> None:
        self.materialized_maps[project_id] = {
            "project_id": project_id,
            "active_persona": active_persona,
            "pedagogy_snapshot": pedagogy_snapshot,
            "verified_state": verified_state,
            "last_event_id": last_event_id,
        }


class MaterializerSpy:
    """Returns a predictable DbContextMap without running the real pipeline."""

    def __init__(self, rendered: str = "cycle: 1\nsection: context_architecture\n  - [entry:abc123] (p=0.85) Test entry") -> None:
        self._rendered = rendered
        self.calls: list[str] = []

    def materialize(self, corpus_path: str) -> DbContextMap:
        self.calls.append(corpus_path)
        return DbContextMap(
            map_id="test-map-001",
            rendered=self._rendered,
            render_mode="full",
            source_paths=[corpus_path],
            token_count=120,
            stages_run=["ingest", "index", "retrieve", "assemble", "render"],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_temp_persona_dir(persona_files: dict[str, str]) -> Path:
    """Create a temporary personas directory with the given files."""
    tmpdir = Path(tempfile.mkdtemp(prefix="deverino-test-personas-"))
    for name, content in persona_files.items():
        (tmpdir / f"{name}.md").write_text(content)
    return tmpdir


def make_temp_pedagogy(content: str) -> Path:
    """Create a temporary pedagogy file."""
    tmpfile = Path(tempfile.mktemp(suffix=".md", prefix="deverino-test-pedagogy-"))
    tmpfile.write_text(content)
    return tmpfile


# ---------------------------------------------------------------------------
# Tests: persona loading
# ---------------------------------------------------------------------------

class TestPersonaLoading:
    def test_loads_existing_persona(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder Persona\nWrite code."})
        pedagogy_path = make_temp_pedagogy("# Pedagogy\nBe direct.")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.materialize_context_map(
            working_context={"goal": "test"},
            persona_id="coder",
        )

        assert result["persona_id"] == "coder"
        assert "Write code" in result["persona"]

    def test_missing_persona_raises(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        with pytest.raises(PersonaNotFoundError, match="architect"):
            engine.materialize_context_map(
                working_context={},
                persona_id="architect",
            )

    def test_missing_pedagogy_raises(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = Path("/nonexistent/pedagogy.md")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        with pytest.raises(PedagogyNotFoundError, match="pedagogy"):
            engine.materialize_context_map(
                working_context={},
                persona_id="coder",
            )


# ---------------------------------------------------------------------------
# Tests: materialize_context_map output shape
# ---------------------------------------------------------------------------

class TestMaterializeOutput:
    def test_returns_all_expected_keys(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder Persona\nBuild features."})
        pedagogy_path = make_temp_pedagogy("# Developer Pedagogy\nDirect communication.")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.materialize_context_map(
            working_context={"goal": "implement feature X"},
            persona_id="coder",
        )

        for key in (
            "persona_id",
            "persona",
            "pedagogy",
            "unified_lens",
            "verified_state",
            "context_map",
            "rendered_prompt",
            "rendered_context_map",
        ):
            assert key in result, f"Missing key: {key}"

    def test_unified_lens_contains_both_persona_and_pedagogy(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder Persona\nWrite clean code."})
        pedagogy_path = make_temp_pedagogy("# Pedagogy\nBe terse.")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.materialize_context_map(
            working_context={},
            persona_id="coder",
        )

        lens = result["unified_lens"]
        assert "Coder Persona" in lens
        assert "Write clean code" in lens
        assert "Pedagogy" in lens
        assert "Be terse" in lens

    def test_rendered_prompt_includes_context_map(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy(rendered="cycle: 5\nsection: parsing_schema")

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.materialize_context_map(
            working_context={},
            persona_id="coder",
        )

        assert "cycle: 5" in result["rendered_prompt"]
        assert "parsing_schema" in result["rendered_prompt"]

    def test_verified_state_included_when_present(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        # Pre-populate verified state
        db.materialized_maps["deverino"] = {
            "verified_state": {
                "gate_passed": True,
                "discovered_constraints": [{"type": "io_boundary"}],
            }
        }
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.materialize_context_map(
            working_context={},
            persona_id="coder",
        )

        assert "io_boundary" in result["rendered_prompt"]

    def test_materializer_called_with_corpus_path(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        engine.materialize_context_map(
            working_context={},
            persona_id="coder",
            corpus_path="custom/corpus/",
        )

        assert materializer.calls == ["custom/corpus/"]

    def test_materializer_error_wrapped(self):
        """When the materializer raises, ContextEngine wraps it."""
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()

        class ExplodingMaterializer(MaterializerSpy):
            def materialize(self, corpus_path: str) -> DbContextMap:
                msg = "Pipeline exploded"
                raise MaterializationError(msg)

        engine = ContextEngine(
            db=db,
            materializer=ExplodingMaterializer(),
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        with pytest.raises(ContextEngineError, match="Pipeline exploded"):
            engine.materialize_context_map(
                working_context={},
                persona_id="coder",
            )


# ---------------------------------------------------------------------------
# Tests: warm_up_context_from_failure
# ---------------------------------------------------------------------------

class TestWarmUpFromFailure:
    def test_persists_probe_failed_event(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.warm_up_context_from_failure(
            session_id="sess-probe-1",
            execution_error={
                "exit_code": 1,
                "stderr": "ModuleNotFoundError: No module named 'requests'",
                "stdout": "",
                "traceback": [
                    "Traceback (most recent call last):",
                    '  File "<sandbox>", line 3, in <module>',
                    "ModuleNotFoundError: No module named 'requests'",
                ],
            },
        )

        # Events persisted (PROBE_FAILED + CONTEXT_WARMED)
        assert len(db.context_events) == 2
        event_types = {e["event_type"] for e in db.context_events}
        assert "ProbeFailed" in event_types
        assert "ContextWarmed" in event_types

        probe_event = next(e for e in db.context_events if e["event_type"] == "ProbeFailed")
        assert probe_event["session_id"] == "sess-probe-1"
        assert probe_event["team_member"] == "orchestrator"

        # Context delta returned
        assert "discovered_constraints" in result
        assert len(result["discovered_constraints"]) >= 1
        assert any(
            c["type"] == "missing_dependency" for c in result["discovered_constraints"]
        )

    def test_extracts_type_constraints(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.warm_up_context_from_failure(
            session_id="sess-probe-2",
            execution_error={
                "exit_code": 1,
                "stderr": "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
                "stdout": "",
                "traceback": [],
            },
        )

        assert any(
            c["type"] == "type_constraint" for c in result["discovered_constraints"]
        )

    def test_extracts_io_boundary(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.warm_up_context_from_failure(
            session_id="sess-probe-3",
            execution_error={
                "exit_code": 2,
                "stderr": "FileNotFoundError: [Errno 2] No such file or directory: 'config.json'",
                "stdout": "",
                "traceback": [],
            },
        )

        assert any(
            c["type"] == "io_boundary" for c in result["discovered_constraints"]
        )

    def test_extracts_invariant_violation(self):
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.warm_up_context_from_failure(
            session_id="sess-probe-4",
            execution_error={
                "exit_code": 1,
                "stderr": "AssertionError: Expected state to be valid",
                "stdout": "",
                "traceback": [],
            },
        )

        assert any(
            c["type"] == "invariant_violation" for c in result["discovered_constraints"]
        )

    def test_no_constraints_on_clean_error(self):
        """Errors without recognizable patterns produce empty constraints."""
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        result = engine.warm_up_context_from_failure(
            session_id="sess-probe-5",
            execution_error={
                "exit_code": 1,
                "stderr": "Something went wrong but we don't know what",
                "stdout": "",
                "traceback": [],
            },
        )

        assert result["discovered_constraints"] == []

    def test_materialized_map_updated_on_failure(self):
        """Failure warm-up should update the materialized context map."""
        tmpdir = make_temp_persona_dir({"coder": "# Coder"})
        pedagogy_path = make_temp_pedagogy("# Pedagogy")
        db = DatabaseSpy()
        materializer = MaterializerSpy()

        engine = ContextEngine(
            db=db,
            materializer=materializer,
            personas_dir=tmpdir,
            pedagogy_path=pedagogy_path,
        )

        engine.warm_up_context_from_failure(
            session_id="sess-probe-6",
            execution_error={
                "exit_code": 1,
                "stderr": "ModuleNotFoundError",
                "stdout": "",
                "traceback": [],
            },
        )

        assert "deverino" in db.materialized_maps
        mmap = db.materialized_maps["deverino"]
        assert mmap["active_persona"] == "probe"
        assert "discovered_constraints" in mmap["verified_state"]
