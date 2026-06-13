"""Adaptive priority-weight learning — offline calibration CLI.

Reads MapEntryReferenced, MapEntryEvicted, and MapEntryInserted events from a window,
computes target priority_weights using a multiplicative formula, and optionally
writes them back to harness.yaml.

See docs/superpowers/specs/2026-05-24-deterministic-cartographer-deferred-features.md §4.4.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from sqlmodel import Session, select

from harness_poc.core.context_map.config import (
    _DEFAULT_PRIORITY_WEIGHTS,
    _REQUIRED_WEIGHT_KEYS,
)
from harness_poc.core.context_map.sections import SECTION_MAP

if TYPE_CHECKING:
    from harness_poc.core.storage.database import BlackboardDatabase

logger = logging.getLogger(__name__)

_OBSERVATION_TYPES = sorted(_REQUIRED_WEIGHT_KEYS)


def run_calibration(
    db: BlackboardDatabase,
    corpus_key: str,
    *,
    window_days: int = 14,
    min_events: int = 50,
    dry_run: bool = True,
    config_path: str | None = None,
) -> CalibrationResult:
    """Run one calibration cycle and return a result object.

    In dry_run mode, only computes; in apply mode, writes to harness.yaml.
    """
    cutoff = (datetime.now(tz=UTC) - timedelta(days=window_days)).isoformat(timespec="seconds")

    ref_events = _count_references(db, corpus_key, cutoff)
    eviction_events = _count_evictions(db, corpus_key, cutoff)
    insertion_events = _count_insertions(db, corpus_key, cutoff)

    current_map = db.get_context_map(corpus_key) or []
    mat_counts: dict[str, int] = dict.fromkeys(_OBSERVATION_TYPES, 0)
    for entry in current_map:
        t = entry.observation_type
        if t in mat_counts:
            mat_counts[t] += entry.materialization_count

    for t in _OBSERVATION_TYPES:
        mat_counts[t] += eviction_events.get(t, {}).get("mat_sum", 0)

    total_refs = sum(ref_events.values())
    if total_refs < min_events:
        return CalibrationResult(
            status="insufficient_data",
            corpus_key=corpus_key,
            window_days=window_days,
            total_references=total_refs,
            total_evictions=sum(eviction_events.get(t, {}).get("count", 0) for t in _OBSERVATION_TYPES),
            total_insertions=sum(insertion_events.values()),
            weights={},
            message=(
                f"Only {total_refs} reference events in the {window_days}-day window "
                f"(minimum {min_events}). Calibration refused to avoid tuning on noise."
            ),
        )

    current_weights = _read_current_weights(config_path)

    target_weights: dict[str, float] = {}
    deltas: dict[str, float] = {}

    for t in _OBSERVATION_TYPES:
        refs = ref_events.get(t, 0)
        insertions = insertion_events.get(t, 0)
        evict_data = eviction_events.get(t, {})

        mat_sum = max(mat_counts.get(t, 0), 1)
        ref_rate = refs / mat_sum

        budget_evictions = evict_data.get("budget_count", 0)
        if insertions > 0:
            survival = 1.0 - (budget_evictions / insertions)
            survival = max(0.0, survival)
        else:
            survival = 1.0

        base = current_weights.get(t, _DEFAULT_PRIORITY_WEIGHTS.get(t, 0.5))

        # Zero-signal guard: if no references and no materializations beyond
        # the floor, keep the base weight unchanged (don't drift to 0.25).
        target = (
            base
            if (refs == 0 and mat_sum <= 1)
            else base * (0.5 + ref_rate) * (0.5 + survival)
        )
        target = max(0.1, min(1.0, target))

        target_weights[t] = round(target, 2)
        deltas[t] = round(target_weights[t] - base, 2)

    result = CalibrationResult(
        status="success",
        corpus_key=corpus_key,
        window_days=window_days,
        total_references=total_refs,
        total_evictions=sum(eviction_events.get(t, {}).get("count", 0) for t in _OBSERVATION_TYPES),
        total_insertions=sum(insertion_events.values()),
        weights={
            t: {
                "current": current_weights.get(t, _DEFAULT_PRIORITY_WEIGHTS.get(t, 0.5)),
                "target": target_weights[t],
                "delta": deltas[t],
            }
            for t in _OBSERVATION_TYPES
        },
        message=None,
    )

    if not dry_run and config_path:
        _write_weights_to_config(
            config_path,
            target_weights,
            total_refs,
            sum(eviction_events.get(t, {}).get("count", 0) for t in _OBSERVATION_TYPES),
        )

    return result


def _count_references(db: BlackboardDatabase, corpus_key: str, cutoff: str) -> dict[str, int]:
    """Count MapEntryReferenced events per observation_type in the window."""
    from harness_poc.core.storage.models import DbContextMapEvent

    counts: dict[str, int] = dict.fromkeys(_OBSERVATION_TYPES, 0)
    with Session(db.engine) as session:
        rows = session.exec(
            select(DbContextMapEvent)
            .where(DbContextMapEvent.corpus_key == corpus_key)
            .where(DbContextMapEvent.event_type == "map_entry_referenced")
            .where(DbContextMapEvent.timestamp >= cutoff)
        ).all()

    for row in rows:
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            continue
        section = payload.get("section", "")
        _type = _section_to_type(section)
        if _type in counts:
            counts[_type] += 1
    return counts


def _count_evictions(db: BlackboardDatabase, corpus_key: str, cutoff: str) -> dict[str, dict[str, int]]:
    """Count MapEntryEvicted events per observation_type, split by reason type."""
    from harness_poc.core.storage.models import DbContextMapEvent

    result: dict[str, dict[str, int]] = {
        t: {"count": 0, "budget_count": 0, "stale_count": 0, "mat_sum": 0} for t in _OBSERVATION_TYPES
    }

    with Session(db.engine) as session:
        rows = session.exec(
            select(DbContextMapEvent)
            .where(DbContextMapEvent.corpus_key == corpus_key)
            .where(DbContextMapEvent.event_type == "map_entry_evicted")
            .where(DbContextMapEvent.timestamp >= cutoff)
        ).all()

    for row in rows:
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            continue
        section = payload.get("section", "")
        reason = payload.get("reason", "")
        mat_count = int(payload.get("materialization_count", 0))
        _type = _section_to_type(section)
        if _type not in result:
            continue
        result[_type]["count"] += 1
        result[_type]["mat_sum"] += mat_count
        if reason.startswith("budget@"):
            result[_type]["budget_count"] += 1
        elif reason.startswith("stale@"):
            result[_type]["stale_count"] += 1
    return result


def _count_insertions(db: BlackboardDatabase, corpus_key: str, cutoff: str) -> dict[str, int]:
    """Count MapEntryInserted events per observation_type in the window."""
    from harness_poc.core.storage.models import DbContextMapEvent

    counts: dict[str, int] = dict.fromkeys(_OBSERVATION_TYPES, 0)
    with Session(db.engine) as session:
        rows = session.exec(
            select(DbContextMapEvent)
            .where(DbContextMapEvent.corpus_key == corpus_key)
            .where(DbContextMapEvent.event_type == "map_entry_inserted")
            .where(DbContextMapEvent.timestamp >= cutoff)
        ).all()

    for row in rows:
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            continue
        obs_type = payload.get("observation_type", "")
        if obs_type in counts:
            counts[obs_type] += 1
    return counts


def _section_to_type(section: str) -> str:
    """Map section name back to observation_type (best-effort)."""
    reverse: dict[str, str] = {}
    for obs_type, sec in SECTION_MAP.items():
        if sec not in reverse:
            reverse[sec] = obs_type
    return reverse.get(section, "insight")


def _read_current_weights(config_path: str | None) -> dict[str, float]:
    """Read current priority_weights from harness.yaml or fall back to defaults."""
    if config_path:
        try:
            raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cartographer_raw = raw.get("cartographer")
                if isinstance(cartographer_raw, dict):
                    weights_raw = cartographer_raw.get("priority_weights")
                    if isinstance(weights_raw, dict):
                        return {k: float(weights_raw[k]) for k in _REQUIRED_WEIGHT_KEYS if k in weights_raw}
        except Exception:
            logger.debug("Failed to read weights from config, using defaults", exc_info=True)
    return dict(_DEFAULT_PRIORITY_WEIGHTS)


def _write_weights_to_config(
    config_path: str,
    weights: dict[str, float],
    total_refs: int,
    total_evictions: int,
) -> None:
    """Write new weights to harness.yaml with a comment line above them."""
    path = Path(config_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "harness.yaml is not a mapping"
        raise TypeError(msg)

    cartographer_section = raw.setdefault("cartographer", {})
    if not isinstance(cartographer_section, dict):
        cartographer_section = {}
        raw["cartographer"] = cartographer_section

    # Write backup
    backup_path = path.with_suffix(f".yaml.bak-{datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')}")
    path.rename(backup_path)

    today = datetime.now(tz=UTC).date().isoformat()
    comment_line = f"# auto-tuned {today} from {total_refs} reference events, {total_evictions} eviction events\n"

    cartographer_section["priority_weights"] = {k: round(v, 2) for k, v in weights.items()}

    buf = io.StringIO()
    yaml.dump(raw, buf, default_flow_style=False, allow_unicode=True, sort_keys=False)
    content = buf.getvalue()

    lines = content.splitlines(keepends=True)
    result_lines: list[str] = []
    for line in lines:
        if line.strip().startswith("priority_weights:"):
            result_lines.append(comment_line)
        result_lines.append(line)

    path.write_text("".join(result_lines), encoding="utf-8")


class CalibrationResult:
    """Result of a calibration run."""

    def __init__(
        self,
        status: str,
        corpus_key: str,
        window_days: int,
        total_references: int,
        total_evictions: int,
        total_insertions: int,
        weights: dict[str, dict[str, float]],
        message: str | None = None,
    ) -> None:
        self.status = status
        self.corpus_key = corpus_key
        self.window_days = window_days
        self.total_references = total_references
        self.total_evictions = total_evictions
        self.total_insertions = total_insertions
        self.weights = weights
        self.message = message
