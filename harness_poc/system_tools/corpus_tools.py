"""LLM-callable tool: inventory of context-map corpora."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_poc.core.tools import ToolContext

from harness_poc.system_tools import register as _register


def _list_corpora(ctx: ToolContext, **_: Any) -> dict[str, Any]:  # noqa: ANN401
    database = ctx.database
    if database is None:
        return {"error": "No database available"}

    all_keys = database.get_all_corpus_keys()
    if not all_keys:
        return {"corpora": []}

    pending_keys = set(database.get_pending_corpus_keys())
    all_maps = database.get_context_maps(all_keys)
    cycles = database.get_cycles(all_keys)

    out: list[dict[str, Any]] = []
    for ck in all_keys:
        entries = all_maps.get(ck, [])
        out.append(
            {
                "key": ck,
                "materialized": bool(entries),
                "entry_count": len(entries),
                "cycle": cycles.get(ck, 0),
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
