from dataclasses import dataclass
from typing import Optional, Tuple

HEADING = "## Guidance for this project"
INTRO = "These entries come from the user's guidance repo. Cite an entry by its id."

NOT_GUIDANCE = "not-guidance"
MALFORMED = "malformed"
ENTRY = "entry"


@dataclass(frozen=True)
class GuidanceEntry:
    id: str
    status: str
    verified: bool
    facets: Tuple[str, ...]
    steps: Tuple[str, ...]
    body: str

    def is_candidate(self):
        return self.status == "stable" and self.verified

    def size(self):
        return len(self.body.encode("utf-8"))


@dataclass(frozen=True)
class Classification:
    kind: str
    entry: Optional[GuidanceEntry] = None
    reason: Optional[str] = None


def _scalar(value):
    return value.strip() if isinstance(value, str) else ""


def _inline_list(key, value):
    if not isinstance(value, str):
        raise ValueError("applies-to %s must be an inline list like [a, b]" % key)
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        raise ValueError("applies-to %s must be an inline list like [a, b]" % key)
    return tuple(i for i in (p.strip() for p in text[1:-1].split(",")) if i)


def classify(entry_id, meta, body):
    if _scalar(meta.get("type")) != "Guidance":
        return Classification(NOT_GUIDANCE)
    applies = meta.get("applies-to")
    if not isinstance(applies, dict):
        return Classification(MALFORMED, reason="type: Guidance entry has no applies-to mapping")
    try:
        facets = _inline_list("facets", applies["facets"]) if "facets" in applies else ()
        steps = _inline_list("steps", applies["steps"]) if "steps" in applies else ()
    except ValueError as e:
        return Classification(MALFORMED, reason=str(e))
    entry = GuidanceEntry(
        id=entry_id,
        status=_scalar(meta.get("status")),
        verified=bool(_scalar(meta.get("verified"))),
        facets=facets,
        steps=steps,
        body=body.rstrip(),
    )
    return Classification(ENTRY, entry=entry)


def matches_project(entry, project_facets):
    return all(f in project_facets for f in entry.facets)


def matches_step(entry, stage, origin):
    if not entry.steps:
        return True
    for name in entry.steps:
        if "/" not in name:
            if name == stage:
                return True
        elif origin is not None and name == "%s/%s" % (origin, stage):
            return True
    return False


def matches_step_key(entry, key):
    if not entry.steps:
        return True
    if key is None:
        return False
    for name in entry.steps:
        if name == key:
            return True
        if "/" not in key and "/" in name and name.rsplit("/", 1)[1] == key:
            return True
    return False


def matches(entry, project_facets, stage, origin):
    return matches_project(entry, project_facets) and matches_step(entry, stage, origin)


def order(entries):
    return sorted(entries, key=lambda e: (0 if e.steps else 1, e.id))


def fill(entries, budget):
    delivered, skipped = [], []
    remaining = budget
    for entry in entries:
        size = entry.size()
        if size <= remaining:
            delivered.append(entry)
            remaining -= size
        else:
            skipped.append(entry)
    return delivered, skipped


def render_section(delivered):
    parts = [HEADING, INTRO]
    for entry in delivered:
        parts.append("### %s" % entry.id)
        parts.append(entry.body)
    return "\n\n".join(parts)


@dataclass(frozen=True)
class GuidanceSelection:
    section: str = ""
    delivered: Tuple[str, ...] = ()
    skipped: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()
