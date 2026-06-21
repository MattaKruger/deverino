from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, cast

StateSection = Literal["notes", "decisions", "next_actions", "open_questions", "changelog"]
ProposalStatus = Literal["pending", "approved", "rejected"]


@dataclass(frozen=True, slots=True)
class StatePayload:
    summary: str = ""
    notes: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> StatePayload:
        if payload is None:
            return cls()

        return cls(
            summary=_string(payload.get("summary")),
            notes=_string_list(payload.get("notes")),
            decisions=_string_list(payload.get("decisions")),
            next_actions=_string_list(payload.get("next_actions")),
            open_questions=_string_list(payload.get("open_questions")),
            constraints=_string_list(payload.get("constraints")),
            changelog=_string_list(payload.get("changelog")),
            facts=_string_dict(payload.get("facts")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "notes": self.notes,
            "decisions": self.decisions,
            "next_actions": self.next_actions,
            "open_questions": self.open_questions,
            "constraints": self.constraints,
            "changelog": self.changelog,
            "facts": self.facts,
        }

    def append(self, section: StateSection, text: str) -> StatePayload:
        values = self.to_dict()
        section_values = _string_list(values[section])
        section_values.append(text)
        values[section] = section_values

        return StatePayload.from_dict(values)

    def append_payload(self, payload: StatePayload) -> StatePayload:
        return StatePayload(
            summary=self.summary or payload.summary,
            notes=[*self.notes, *payload.notes],
            decisions=[*self.decisions, *payload.decisions],
            next_actions=[*self.next_actions, *payload.next_actions],
            open_questions=[*self.open_questions, *payload.open_questions],
            constraints=[*self.constraints, *payload.constraints],
            changelog=[*self.changelog, *payload.changelog],
            facts={**self.facts, **payload.facts},
        )

    def set_fact(self, key: str, value: str) -> StatePayload:
        """Return a new StatePayload with *key* set to *value* in facts."""
        return StatePayload(
            summary=self.summary,
            notes=self.notes,
            decisions=self.decisions,
            next_actions=self.next_actions,
            open_questions=self.open_questions,
            constraints=self.constraints,
            changelog=self.changelog,
            facts={**self.facts, key: value},
        )

    def is_empty(self) -> bool:
        return not any(
            (
                self.summary,
                self.notes,
                self.decisions,
                self.next_actions,
                self.open_questions,
                self.constraints,
                self.changelog,
                self.facts,
            ),
        )

    def to_markdown(self, title: str) -> str:
        sections = [
            f"## {title}",
            "",
            self.summary or "_No summary yet._",
            "",
            _section_to_markdown("Notes", self.notes),
            _section_to_markdown("Decisions", self.decisions),
            _section_to_markdown("Next Actions", self.next_actions),
            _section_to_markdown("Open Questions", self.open_questions),
            _section_to_markdown("Constraints", self.constraints),
            _section_to_markdown("Changelog", self.changelog),
            _facts_to_markdown("Facts", self.facts),
        ]
        return "\n".join(sections).strip()


@dataclass(frozen=True, slots=True)
class StateProposal:
    proposal_id: str
    session_id: str
    status: ProposalStatus
    payload: StatePayload

    @classmethod
    def create(cls, session_id: str, payload: StatePayload) -> StateProposal:
        return cls(
            proposal_id=str(uuid.uuid4()),
            session_id=session_id,
            status="pending",
            payload=payload,
        )

    @classmethod
    def from_row_payload(
        cls,
        *,
        proposal_id: str,
        session_id: str,
        status: str,
        proposal_payload: str,
    ) -> StateProposal:
        payload = json.loads(proposal_payload)
        if not isinstance(payload, dict):
            msg = f"Invalid state proposal payload for {proposal_id}"
            raise TypeError(msg)
        return cls(
            proposal_id=proposal_id,
            session_id=session_id,
            status=_proposal_status(status),
            payload=StatePayload.from_dict(cast("dict[str, Any]", payload)),
        )

    def to_database_payload(self) -> str:
        return json.dumps(self.payload.to_dict(), sort_keys=True)


def build_state_context(project_state: StatePayload, session_state: StatePayload) -> str:
    return "\n\n".join(
        [
            "Runtime STATE is compact durable context, not a transcript.",
            project_state.to_markdown("Project State"),
            session_state.to_markdown("Current Session State"),
        ],
    )


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def _proposal_status(status: str) -> ProposalStatus:
    if status in {"pending", "approved", "rejected"}:
        return cast("ProposalStatus", status)
    msg = f"Invalid proposal status: {status}"
    raise ValueError(msg)


def _section_to_markdown(title: str, values: list[str]) -> str:
    if not values:
        return f"### {title}\n_None._\n"
    items = "\n".join(f"- {value}" for value in values)
    return f"### {title}\n{items}\n"


def _facts_to_markdown(title: str, facts: dict[str, str]) -> str:
    if not facts:
        return f"### {title}\n_None._\n"
    items = "\n".join(f"- **{k}**: {v}" for k, v in facts.items())
    return f"### {title}\n{items}\n"
