"""ContextEngine — materializes prompt context through persona+pedagogy lens.

  - materialize_context_map()  — builds filtered context window
  - warm_up_context_from_failure() — extracts sandbox constraints

The engine queries the latest verified state from PostgreSQL, extracts the
specific persona.md and its adapted developer-pedagogy.md profile, and uses
them to filter and format the working context map for model injection.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from harness_poc.core.context_map.format import (
    format_context_window,
    format_persona_lens,
    format_verified_state,
    format_working_context,
)
from harness_poc.core.events.context_map_events import ContextEventBridge
from harness_poc.core.events.events import ContextWarmed, ProbeFailed

if TYPE_CHECKING:
    from pathlib import Path

    from harness_poc.core.events.event_bus import EventBus
    from harness_poc.core.events.events import BaseEvent
    from harness_poc.core.storage.database import BlackboardDatabase
    from harness_poc.v2.contracts.context_map_pipeline import ContextMapMaterializer
logger = logging.getLogger(__name__)


class ContextEngineError(RuntimeError):
    """Raised when the ContextEngine cannot complete an operation."""


class PersonaNotFoundError(ContextEngineError):
    """No persona file found for the requested persona_id."""


class PedagogyNotFoundError(ContextEngineError):
    """No developer-pedagogy profile found at the expected path."""


class ContextEngine:
    """Orchestrates persona-driven context map materialization.

    Binds the three descending layers from the spec:
        SOUL.md → Unified Persona (persona + pedagogy) → Materialized Context Map
    """

    def __init__(  # noqa: PLR0913
        self,
        db: BlackboardDatabase,
        materializer: ContextMapMaterializer,
        *,
        personas_dir: Path,
        pedagogy_path: Path,
        project_id: str = "deverino",
        event_bus: EventBus | None = None,
    ) -> None:
        self._db = db
        self._materializer = materializer
        self._personas_dir = personas_dir
        self._pedagogy_path = pedagogy_path
        self._project_id = project_id
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # materialize_context_map  (spec §4, ContextEngine interface)
    # ------------------------------------------------------------------

    def materialize_context_map(
        self,
        working_context: dict[str, Any],
        persona_id: str,
        *,
        corpus_path: str = "docs/",
    ) -> dict[str, Any]:
        """Construct the customized prompt context window.

        Pipeline:
          1. Load persona markdown from personas_dir
          2. Load developer-pedagogy profile
          3. Query latest verified state from PostgreSQL
          4. Run the context map materializer pipeline
          5. Filter and format through the unified persona+pedagogy lens
          6. Persist the materialized context map snapshot

        Args:
            working_context: Dict with active session context (corpus, goals, etc.)
            persona_id: The persona to use (e.g. "code_reviewer", "architect")
            corpus_path: Path to the document corpus for the materializer pipeline

        Returns:
            A dict with keys: persona, pedagogy, verified_state, context_map,
            rendered_prompt — ready for model injection.

        Raises:
            PersonaNotFoundError: If the persona markdown file is missing.
            PedagogyNotFoundError: If the pedagogy profile is missing.
            MaterializationError: If the context map pipeline fails.
        """
        # Step 1: load persona markdown
        persona_text = self._load_persona(persona_id)

        # Step 2: load pedagogy profile
        pedagogy_text = self._load_pedagogy()

        # Step 3: get latest verified state from DB
        verified_state = self._get_verified_state()

        # Step 4: run context map materializer pipeline
        try:
            db_map = self._materializer.materialize(corpus_path)
        except Exception as exc:
            msg = f"Context map materialization failed for corpus '{corpus_path}': {exc}"
            raise ContextEngineError(msg) from exc

        # Step 5: unify persona + pedagogy into a filtering lens
        unified_lens = self._unify_persona_pedagogy(persona_text, pedagogy_text)

        # Step 6: format the rendered context for model injection
        rendered_prompt = self._format_context_window(
            db_map.rendered,
            persona_text=persona_text,
            pedagogy_text=pedagogy_text,
            verified_state=verified_state,
            working_context=working_context,
        )

        return {
            "persona_id": persona_id,
            "persona": persona_text,
            "pedagogy": pedagogy_text,
            "unified_lens": unified_lens,
            "verified_state": verified_state,
            "context_map": {
                "map_id": db_map.map_id,
                "render_mode": db_map.render_mode,
                "source_paths": db_map.source_paths,
                "token_count": db_map.token_count,
                "stages_run": db_map.stages_run,
            },
            "rendered_prompt": rendered_prompt,
            "rendered_context_map": db_map.rendered,
        }

    # ------------------------------------------------------------------
    # warm_up_context_from_failure  (spec §4, ContextEngine interface)
    # ------------------------------------------------------------------

    def warm_up_context_from_failure(
        self,
        session_id: str,
        execution_error: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the Step #1 exploration loop recovery.

        Commits a PROBE_FAILED event to the stream, extracts semantic
        errors, and returns the mutated context delta with newly discovered
        sandbox constraints.

        Args:
            session_id: The agent session identifier (UUID string).
            execution_error: Dict with keys like stdout, stderr, traceback,
                exit_code from the failed sandbox execution.

        Returns:
            A dict with the context delta — constraints, dependencies,
            invariants discovered from the failure.
        """
        # Extract semantic constraints from the error
        constraints = self._extract_constraints(execution_error)

        event_id = str(uuid.uuid4())

        # Publish PROBE_FAILED event via the event bus (or fall back to db)
        self._publish_event(
            ProbeFailed(
                session_id=session_id,
                team_member="orchestrator",
                execution_error=execution_error,
                extracted_constraints=constraints,
            )
        )

        # Build context delta for the working context
        context_delta = {
            "discovered_constraints": constraints,
            "probe_event_id": event_id,
            "failure_source": {
                "exit_code": execution_error.get("exit_code"),
                "error_summary": self._summarize_error(execution_error),
            },
        }

        # Persist materialized context map with the delta
        self._db.upsert_materialized_context_map(
            project_id=self._project_id,
            active_persona="probe",  # failure warm-up is persona-agnostic
            pedagogy_snapshot={},
            verified_state=context_delta,
            last_event_id="",
        )

        # Publish CONTEXT_WARMED event — signals successful context map update
        self._publish_event(
            ContextWarmed(
                session_id=session_id,
                team_member="orchestrator",
                constraint_count=len(constraints),
                probe_event_id=event_id,
            )
        )

        return context_delta

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish_event(self, event: BaseEvent) -> None:
        """Publish an event through the bus, or fall back to direct db write."""
        if self._event_bus is not None:
            self._event_bus.publish(event)
        else:
            ctx_event = ContextEventBridge(
                session_id=event.session_id,
                corpus_key=f"{self._project_id}:session",
                event_type=event.event_type,
                raw_data=event.model_dump(),
            )
            self._db.append_context_map_event(ctx_event)

    def _load_persona(self, persona_id: str) -> str:
        """Load a persona markdown file from the personas directory."""
        persona_path = self._personas_dir / f"{persona_id}.md"
        if not persona_path.exists():
            msg = f"Persona '{persona_id}' not found at {persona_path}"
            raise PersonaNotFoundError(msg)
        return persona_path.read_text(encoding="utf-8")

    def _load_pedagogy(self) -> str:
        """Load the developer-pedagogy profile."""
        if not self._pedagogy_path.exists():
            msg = f"Developer pedagogy profile not found at {self._pedagogy_path}"
            raise PedagogyNotFoundError(msg)
        return self._pedagogy_path.read_text(encoding="utf-8")

    def _get_verified_state(self) -> dict[str, Any]:
        """Return the latest verified state from PostgreSQL, or empty dict."""
        snapshot = self._db.get_materialized_context_map(self._project_id)
        if snapshot is None:
            return {}
        return snapshot.get("verified_state", {})

    def _unify_persona_pedagogy(
        self,
        persona_text: str,
        pedagogy_text: str,
    ) -> str:
        """Combine persona and pedagogy into a unified filtering lens.

        Delegates to the shared ``format_persona_lens`` so both old and v2
        paths produce identical lens formatting.
        """
        return format_persona_lens(persona_text, pedagogy_text)

    def _format_context_window(
        self,
        rendered_map: str,
        *,
        persona_text: str,
        pedagogy_text: str,
        verified_state: dict[str, Any],
        working_context: dict[str, Any],
    ) -> str:
        """Format the complete prompt context window for model injection.

        Delegates to the shared ``format_context_window`` so both old and v2
        paths produce identical section formatting.
        """
        return format_context_window(
            rendered_map,
            persona_text=persona_text,
            pedagogy_text=pedagogy_text,
            verified_state=verified_state or None,
            working_context=working_context or None,
            map_label="Materialized Context Map",
        )

    @staticmethod
    def _format_verified_state(state: dict[str, Any]) -> str:
        """Render verified state as a compact key-value block.

        Delegates to the shared ``format_verified_state``.
        """
        return format_verified_state(state)

    @staticmethod
    def _format_working_context(ctx: dict[str, Any]) -> str:
        """Render working context as a compact summary block.

        Delegates to the shared ``format_working_context``.
        """
        return format_working_context(ctx)

    def _extract_constraints(
        self,
        execution_error: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Extract semantic constraints from a sandbox failure.

        Parses stderr/traceback for missing dependencies, import errors,
        type errors, and unstated architectural invariants.
        """
        constraints: list[dict[str, str]] = []
        stderr = execution_error.get("stderr", "")
        traceback_lines = execution_error.get("traceback", [])

        # Combine all error text for pattern matching
        error_text = stderr
        if traceback_lines:
            error_text += "\n" + "\n".join(traceback_lines[-20:])  # last 20 lines

        # Pattern: missing imports
        if "ModuleNotFoundError" in error_text or "ImportError" in error_text:
            constraints.append(
                {
                    "type": "missing_dependency",
                    "detail": "Unresolved import detected in sandbox execution",
                }
            )

        # Pattern: type errors
        if "TypeError" in error_text or "AttributeError" in error_text:
            constraints.append(
                {
                    "type": "type_constraint",
                    "detail": "Type or attribute contract violation in sandbox",
                }
            )

        # Pattern: file/IO errors
        if "FileNotFoundError" in error_text or "PermissionError" in error_text:
            constraints.append(
                {
                    "type": "io_boundary",
                    "detail": (
                        "File access boundary hit — may indicate missing corpus or permission gap"
                    ),
                }
            )

        # Pattern: runtime constraint errors
        if "AssertionError" in error_text:
            constraints.append(
                {
                    "type": "invariant_violation",
                    "detail": "An architectural invariant assertion failed in the sandbox",
                }
            )

        return constraints

    @staticmethod
    def _summarize_error(execution_error: dict[str, Any]) -> str:
        """Produce a one-line summary of the execution error."""
        stderr = execution_error.get("stderr", "")
        exit_code = execution_error.get("exit_code", "?")
        if stderr:
            first_line = stderr.strip().split("\n")[0]
            return f"exit={exit_code}: {first_line[:200]}"
        return f"exit={exit_code}: no stderr output"
