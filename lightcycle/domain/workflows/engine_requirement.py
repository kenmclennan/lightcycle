import re
from dataclasses import dataclass
from typing import Tuple

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CLAUSE_RE = re.compile(r"^(>=|<=|>|<)\s*(\d+\.\d+\.\d+)$")

_OPERATORS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
}


def parse_version(text):
    if not isinstance(text, str) or not _VERSION_RE.match(text.strip()):
        raise ValueError("version %r is not three dotted integers" % (text,))
    return tuple(int(part) for part in text.strip().split("."))


@dataclass(frozen=True)
class EngineRequirement:
    clauses: Tuple[Tuple[str, Tuple[int, ...]], ...]

    def satisfied_by(self, version):
        have = parse_version(version)
        return all(_OPERATORS[op](have, bound) for op, bound in self.clauses)

    def describe(self):
        return ",".join(
            "%s%s" % (op, ".".join(str(p) for p in bound)) for op, bound in self.clauses
        )


def parse_engine_requirement(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("engine requirement must be a non-empty string (got %r)" % (text,))
    clauses = []
    for raw in text.split(","):
        match = _CLAUSE_RE.match(raw.strip())
        if not match:
            raise ValueError("engine requirement clause %r is not <op><x.y.z>" % raw.strip())
        clauses.append((match.group(1), parse_version(match.group(2))))
    return EngineRequirement(clauses=tuple(clauses))
