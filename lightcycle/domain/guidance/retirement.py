import datetime
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

UNUSED = "unused"
NEVER_DELIVERED = "never-delivered"
COVERS_CLOSED = "covers-closed"
STALE = "stale"

COVERS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Usage:
    deliveries: int = 0
    citations: int = 0
    last_delivered: Optional[str] = None


@dataclass(frozen=True)
class Thresholds:
    unused_after_deliveries: int
    dormant_days: int


@dataclass(frozen=True)
class Flag:
    name: str
    evidence: str

    def as_dict(self):
        return {"name": self.name, "evidence": self.evidence}


@dataclass(frozen=True)
class CoversResult:
    state: str
    note: str = ""


@dataclass(frozen=True)
class GuidanceRow:
    id: str
    status: str
    deliveries: int
    citations: int
    last_delivered: Optional[str]
    flags: Tuple[Flag, ...] = ()
    notes: Tuple[str, ...] = ()

    def as_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "deliveries": self.deliveries,
            "citations": self.citations,
            "last_delivered": self.last_delivered,
            "flags": [f.as_dict() for f in self.flags],
            "notes": list(self.notes),
        }


def _parse_timestamp(value):
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _unused(usage, thresholds):
    needed = thresholds.unused_after_deliveries
    if usage.citations != 0 or usage.deliveries == 0:
        return None, None
    if usage.deliveries >= needed:
        return Flag(UNUSED, "%d deliveries, 0 cited" % usage.deliveries), None
    return None, "too few deliveries to judge (%d of %d needed)" % (usage.deliveries, needed)


def _never_delivered(entry, usage, thresholds, now):
    if entry.status != "stable":
        return None
    if usage.last_delivered is None:
        return Flag(NEVER_DELIVERED, "never delivered")
    delivered = _parse_timestamp(usage.last_delivered)
    if delivered is None:
        return None
    age = now - delivered
    if age > datetime.timedelta(days=thresholds.dormant_days):
        return Flag(
            NEVER_DELIVERED,
            "last delivered %d days ago, more than %d" % (age.days, thresholds.dormant_days),
        )
    return None


def _covers_closed(entry, covers):
    if not entry.covers or covers is None:
        return None, None
    if covers.state == "CLOSED":
        return Flag(
            COVERS_CLOSED,
            "closed upstream: %s; remove only once the fix is installed locally" % entry.covers,
        ), None
    if covers.state == COVERS_UNKNOWN:
        return None, covers.note
    return None, None


def _stale(entry, now):
    if not entry.stale_after:
        return None, None
    try:
        due = datetime.date.fromisoformat(entry.stale_after)
    except ValueError:
        return None, "stale_after is not a YYYY-MM-DD date"
    if len(entry.stale_after) != 10:
        return None, "stale_after is not a YYYY-MM-DD date"
    if due < now.astimezone().date():
        return Flag(STALE, "stale_after %s has passed" % entry.stale_after), None
    return None, None


def evaluate(entry, usage, thresholds, now, covers=None):
    if entry.status == "deprecated":
        return GuidanceRow(
            entry.id, entry.status, usage.deliveries, usage.citations, usage.last_delivered)
    flags, notes = [], []
    flag, note = _unused(usage, thresholds)
    if flag:
        flags.append(flag)
    if note:
        notes.append(note)
    flag = _never_delivered(entry, usage, thresholds, now)
    if flag:
        flags.append(flag)
    flag, note = _covers_closed(entry, covers)
    if flag:
        flags.append(flag)
    if note:
        notes.append(note)
    flag, note = _stale(entry, now)
    if flag:
        flags.append(flag)
    if note:
        notes.append(note)
    return GuidanceRow(
        entry.id, entry.status, usage.deliveries, usage.citations, usage.last_delivered,
        tuple(flags), tuple(notes),
    )


def build_rows(entries, usage_by_id: Dict[str, Usage], thresholds, now, covers_by_id=None):
    covers_by_id = covers_by_id or {}
    rows = [
        evaluate(e, usage_by_id.get(e.id, Usage()), thresholds, now, covers_by_id.get(e.id))
        for e in entries
    ]
    return sorted(rows, key=lambda r: (0 if r.flags else 1, r.id))
