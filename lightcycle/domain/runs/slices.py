import re
from dataclasses import dataclass
from typing import Optional, Tuple

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class Slice:
    number: int
    name: str
    base: Optional[int] = None


def parse_slices(text) -> Tuple[Slice, ...]:
    parsed = []
    by_name = {}
    for line_no, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 1:
            name, base_name = parts[0], None
        elif len(parts) == 3 and parts[1] == "on":
            name, base_name = parts[0], parts[2]
        else:
            raise ValueError(
                "line %d: expected '<name>' or '<name> on <base-name>', got %r" % (line_no, line)
            )
        if not _NAME.match(name):
            raise ValueError(
                "line %d: slice name %r must match [a-z0-9][a-z0-9-]*" % (line_no, name)
            )
        if name in by_name:
            raise ValueError("line %d: duplicate slice name %r" % (line_no, name))
        number = len(parsed) + 1
        if base_name is None:
            base = number - 1 if number > 1 else None
        elif base_name not in by_name:
            raise ValueError(
                "line %d: base %r is not an earlier slice name" % (line_no, base_name)
            )
        else:
            base = by_name[base_name]
        by_name[name] = number
        parsed.append(Slice(number, name, base))
    return tuple(parsed)
