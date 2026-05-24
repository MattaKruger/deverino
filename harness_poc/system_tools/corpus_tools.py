"""LLM-callable tool: inventory of context-map corpora."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.system_tools import register as _register

if TYPE_CHECKING:
    from harness_poc.core.storage import BlackboardDatabase


def _list_corpora(database: BlackboardDatabase, **_: Any) -> dict[str, Any]:
    all_keys = set(database.get_all_corpus_keys())
    pending_keys = set(database.get_pending_corpus_keys())

    out: list[dict[str, Any]] = []
    for ck in sorted(all_keys):
        entries = database.get_context_map(ck) or []
        out.append(
            {
                "key": ck,
                "materialized": bool(entries),
                "entry_count": len(entries),
                "cycle": database.get_cycle(ck),
                "has_pending_events": ck in pending_keys,
            }
        )
    return {"corpora": out}


_register(
    name="list_corpora",
    description=(
        "Return a structured inventory of every context-map corpus the "
        "harness knows about, including entry counts, current cycle, and "
        "whether pending events are queued. Use this to discover valid "
        "corpus_key values before observing or citing into a corpus."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_list_corpora,
)
