"""
Audit log writer.

Every gate transition writes one immutable record: who, what score, what
gaps, which human approved, timestamp. This is what Agent 7 (Governance &
Audit) reads to verify SoD compliance — build the schema in coordination
with Agent 7's requirements, per the implementation guide.

This reference implementation appends newline-delimited JSON to a local
file, standing in for whatever the real Quality Insights & Governance
data store is (a database, an event stream, etc.). Swap write_record()'s
body for a real write — everything else in this module (and every caller)
stays the same.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from models import AuditRecord

AUDIT_LOG_PATH = Path(__file__).parent / "audit_log.jsonl"


def _serialize(record: AuditRecord) -> dict:
    d = dataclasses.asdict(record)
    d["timestamp"] = record.timestamp.isoformat()
    if record.decision is not None:
        d["decision"] = record.decision.value
    return d


def write_record(record: AuditRecord) -> None:
    """Append-only write. Never update or delete an existing record —
    if a decision is later reversed, that reversal is itself a new record."""
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_serialize(record), ensure_ascii=False) + "\n")


def read_records_for_story(story_id: str) -> list[dict]:
    """Convenience reader for tests/demos. A real implementation would query
    the governance data store rather than re-reading a local file."""
    if not AUDIT_LOG_PATH.exists():
        return []
    records = []
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["story_id"] == story_id:
                records.append(rec)
    return records


def read_all_records() -> list[dict]:
    if not AUDIT_LOG_PATH.exists():
        return []
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def list_pending_story_ids() -> list[str]:
    """A story is pending review if its latest audit event is
    'gherkin_generated' (score passed the gate) with no later
    'approved'/'rejected' event. Deriving this from the audit log rather
    than a separate store keeps one source of truth."""
    by_story: dict[str, list[dict]] = {}
    for rec in read_all_records():
        by_story.setdefault(rec["story_id"], []).append(rec)

    pending = []
    for story_id, records in by_story.items():
        records.sort(key=lambda r: r["timestamp"])
        latest_event = records[-1]["event"]
        if latest_event == "gherkin_generated":
            pending.append(story_id)
    return pending


def get_latest_score(story_id: str) -> float | None:
    records = [r for r in read_records_for_story(story_id) if r.get("score") is not None]
    if not records:
        return None
    records.sort(key=lambda r: r["timestamp"])
    return records[-1]["score"]
