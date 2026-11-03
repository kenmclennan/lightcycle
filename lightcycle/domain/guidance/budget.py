from dataclasses import dataclass
from typing import Tuple

from lightcycle.domain.guidance.guidance import deliver


@dataclass(frozen=True)
class Overflow:
    project: str
    step: str
    matched_bytes: int
    budget: int
    skipped: Tuple[str, ...]


def overflows(entries, projects, steps, budget):
    found = []
    for identity, facets in projects:
        for origin, stage in steps:
            matched, _, skipped = deliver(entries, facets, stage, origin, budget)
            if skipped:
                found.append(Overflow(
                    project=identity,
                    step="%s/%s" % (origin, stage),
                    matched_bytes=sum(e.size() for e in matched),
                    budget=budget,
                    skipped=tuple(e.id for e in skipped),
                ))
    return sorted(found, key=lambda o: (o.project, o.step))
