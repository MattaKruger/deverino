"""ContextEngine — materializes prompt context through persona+pedagogy lens.

Implements planning_specv2.md §4 core interfaces:
  - materialize_context_map()  — builds filtered context window
  - warm_up_context_from_failure() — extracts sandbox constraints

The engine queries the latest verified state from PostgreSQL, extracts the
specific persona.md and its adapted developer-pedagogy.md profile, and uses
them to filter and format the working context map for model injection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

    def __init__(
        self,
        db: BlackboardDatabase,
        materializer: ContextMapMaterializer,
        *,
        personas_dir: Path,
        pedagogy_path: Path,
        project_id: str = "deverino",
    ) -> None:
        self._db = db
        self._materializer = materializer
        self._personas_dir = personas_dir
        self._pedagogy_path = pedagogy_path
        self._project_id = project_id

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
            raise ContextEngineError(
                f"Context map materialization failed for corpus '{corpus_path}': {exc}"
            ) from exc

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

        # Commit PROBE_FAILED event
        event_id = self._db.append_context_event(
            session_id=session_id,
            team_member="orchestrator",
            event_type="PROBE_FAILED",
            payload={
                "execution_error": execution_error,
                "extracted_constraints": constraints,
            },
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
            last_event_id=event_id,
        )

        # Emit CONTEXT_WARMED event — signals successful context map update
        self._db.append_context_event(
            session_id=session_id,
            team_member="orchestrator",
            event_type="CONTEXT_WARMED",
            payload={
                "constraint_count": len(constraints),
                "probe_event_id": event_id,
            },
        )

        return context_delta

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_persona(self, persona_id: str) -> str:
        """Load a persona markdown file from the personas directory."""
        persona_path = self._personas_dir / f"{persona_id}.md"
        if not persona_path.exists():
            raise PersonaNotFoundError(
                f"Persona '{persona_id}' not found at {persona_path}"
            )
        return persona_path.read_text(encoding="utf-8")

    def _load_pedagogy(self) -> str:
        """Load the developer-pedagogy profile."""
        if not self._pedagogy_path.exists():
            raise PedagogyNotFoundError(
                f"Developer pedagogy profile not found at {self._pedagogy_path}"
            )
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

        The persona defines *what* role the agent plays; the pedagogy
        defines *how* the agent communicates and makes decisions. Together
        they form a single conceptual layer that filters what matters in
        the context map.
        """
        return (
            "--- Unified Persona + Pedagogy Lens ---\n\n"
            f"{persona_text}\n\n"
            "--- Developer Pedagogy Profile ---\n\n"
            f"{pedagogy_text}\n\n"
            "--- End Unified Lens ---"
        )

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

        Follows the spec hierarchy: SOUL → Unified Persona → Context Map.
        The SOUL is injected separately by the harness; this method produces
        the lower two layers.
        """
        parts: list[str] = []

        # Layer 1: Unified Persona + Pedagogy
        unified = self._unify_persona_pedagogy(persona_text, pedagogy_text)
        parts.append(unified)

        # Layer 2: Verified state constraints (from prior gate passes / probes)
        if verified_state:
            parts.append("\n--- Verified Implementation State ---\n")
            parts.append(self._format_verified_state(verified_state))

        # Layer 3: Materialized context map
        parts.append("\n--- Materialized Context Map ---\n")
        parts.append(rendered_map)

        # Layer 4: Working context summary
        if working_context:
            parts.append("\n--- Active Working Context ---\n")
            parts.append(self._format_working_context(working_context))

        return "\n".join(parts)

    @staticmethod
    def _format_verified_state(state: dict[str, Any]) -> str:
        """Render verified state as a compact key-value block."""
        lines: list[str] = []
        for k, v in state.items():
            if isinstance(v, dict):
                lines.append(f"{k}:")
                for sk, sv in v.items():
                    lines.append(f"  {sk}: {sv}")
            elif isinstance(v, list):
                lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
            else:
                lines.append(f"{k}: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_working_context(ctx: dict[str, Any]) -> str:
        """Render working context as a compact summary block."""
        lines: list[str] = []
        # Only surface the most relevant keys
        relevant = {"corpus", "goal", "session_id", "active_skill", "constraints"}
        for k in sorted(relevant & set(ctx)):
            lines.append(f"  {k}: {ctx[k]}")
        return "\n".join(lines)

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
                        "File access boundary hit — "
                        "may indicate missing corpus or permission gap"
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
