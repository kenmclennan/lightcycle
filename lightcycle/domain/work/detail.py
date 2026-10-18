from dataclasses import dataclass
from typing import Optional, Tuple

EXECUTION_FIELDS = (
    "pr", "branch", "worktree", "outcome", "report", "claimed_by", "model", "session",
    "needs", "reason",
)
RESERVED_INPUT_NAMES = ("description", "repo", "workflow", "report")
IN_PREFIX = "in:"
OUT_PREFIX = "out:"

KIND_FIELD = "field"
KIND_INPUT = "input"
KIND_OUTPUT = "output"


@dataclass(frozen=True)
class DetailEntry:
    key: str
    kind: str
    value: Optional[str] = None

    def as_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "value": self.value}


def parse_detail(value) -> Optional[Tuple[str, ...]]:
    if value is None:
        return None
    text = str(value).strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    names = tuple(n.strip() for n in text[1:-1].split(",") if n.strip())
    return names or None


def detail_value_is_url(value) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if "\n" in text or " " in text:
        return False
    return text.startswith(("http://", "https://")) and len(text.split("://", 1)[1]) > 0


def kind_of(name):
    if name.startswith(IN_PREFIX):
        return KIND_INPUT
    if name.startswith(OUT_PREFIX):
        return KIND_OUTPUT
    return KIND_FIELD


def detail_shape_problem(value):
    text = str(value).strip()
    if not (text.startswith("[") and text.endswith("]")):
        return "detail %r is not a bracketed list like [pr, report, in:findings]" % text
    raw = [n.strip() for n in text[1:-1].split(",")]
    names = [n for n in raw if n]
    if not names:
        return "detail is an empty list"
    if len(names) != len(raw):
        return "detail %r has an empty entry" % text
    seen = set()
    for name in names:
        if name in seen:
            return "detail lists %r twice" % name
        seen.add(name)
    return None


def legacy_presents_key(presents):
    if presents is None:
        return None
    text = str(presents).strip()
    if text == "pr":
        return "pr"
    if text == "description":
        return IN_PREFIX + "description"
    if text.startswith("artifact:") and text[len("artifact:"):].strip():
        return IN_PREFIX + text[len("artifact:"):].strip()
    return None


PARK_FIELDS = ("reason", "needs")


def with_park(names, parked):
    if not parked:
        return tuple(names)
    return PARK_FIELDS + tuple(n for n in names if n not in PARK_FIELDS)


def default_detail(has_run, presents=None):
    names = ["outcome", "report"]
    if has_run:
        names.append("pr")
    legacy = legacy_presents_key(presents)
    if legacy is not None and legacy not in names:
        names.insert(0, legacy)
    return tuple(names)


def detail_presents(presents, entries):
    keys = [e.key for e in entries]
    wanted = legacy_presents_key(presents) or presents
    if wanted in keys:
        return wanted
    return keys[0] if keys else None


def resolve_detail(names, fields, inputs, outputs):
    entries = []
    for name in names:
        kind = kind_of(name)
        if kind == KIND_INPUT:
            value = inputs.get(name[len(IN_PREFIX):])
        elif kind == KIND_OUTPUT:
            value = outputs.get(name[len(OUT_PREFIX):])
        else:
            value = fields.get(name)
        entries.append(DetailEntry(key=name, kind=kind, value=value))
    return entries
