"""Soul Constitution — Contract 1 of 4.

The Soul is the root governance artifact. It defines the agent's identity,
principles, and operational boundaries. Every agent has exactly one soul.md
file, validated against REQUIRED_SECTIONS at boot time.

Phase 1 implementation: harness_poc/v1/soul.py (SoulV1)
"""

from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Canonical section set — the single source of truth
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS: set[str] = {
    "identity",
    "purpose",
    "principles",
    "constraints",
    "tone",
    "memory_policy",
    "tool_policy",
    "escalation_policy",
}


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class SoulIntegrityError(ValueError):
    """Raised when a soul.md fails validation against REQUIRED_SECTIONS."""

    def __init__(self, missing: set[str], extra: set[str] | None = None) -> None:
        self.missing = missing or set()
        self.extra = extra or set()
        msg = f"Soul integrity error: missing sections={sorted(self.missing)}"
        if self.extra:
            msg += f" extra sections={sorted(self.extra)}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class SoulConstitution(Protocol):
    """A validated soul.md that exposes its parsed sections.

    Implementations MUST validate at construction time using
    REQUIRED_SECTIONS and raise SoulIntegrityError if any section is
    missing or if unknown sections appear (depending on strict mode).
    """

    @property
    def sections(self) -> set[str]:
        """All section headings present in the soul document."""
        ...

    def get(self, section: str) -> str | None:
        """Return the body text of a named section, or None."""
        ...

    def validate(self) -> None:
        """Raise SoulIntegrityError if the soul is not valid.

        Called by ContextEngine at boot. Implementations must check
        that REQUIRED_SECTIONS is a subset of self.sections (and,
        in strict mode, that no unknown sections are present).
        """
        ...
