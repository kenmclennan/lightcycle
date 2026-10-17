import re
from typing import NamedTuple, Optional

_FORWARDED = re.compile(r"^from (\S+) \((\S+)\): (.*?)(?=^outcome: |\Z)", re.MULTILINE | re.DOTALL)
_FORWARDED_LINE = re.compile(r"^from \S+ \(\S+\):", re.MULTILINE)


class Forwarded(NamedTuple):
    stage: str
    outcome: str
    text: str


def parse_forwarded(notes) -> Optional[Forwarded]:
    if not notes:
        return None
    m = _FORWARDED.search(notes)
    if m is None:
        return None
    return Forwarded(m.group(1), m.group(2), m.group(3).rstrip("\n"))


def has_forwarded_line(notes) -> bool:
    return bool(notes) and _FORWARDED_LINE.search(notes) is not None


def shim_notes(previous_stage, previous_outcome, report, stored):
    if not report or has_forwarded_line(stored):
        return stored
    forwarded = "from %s (%s): %s" % (previous_stage, previous_outcome, report)
    return forwarded + "\n" + stored if stored else forwarded
