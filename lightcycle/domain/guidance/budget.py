from dataclasses import dataclass
from typing import Tuple

from lightcycle.domain.guidance.guidance import deliver, matches_step
from lightcycle.domain.work.project_identity import ProjectIdentity


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
        label = ProjectIdentity.short_name(identity)
        for origin, stage in steps:
            matched, _, skipped = deliver(
                entries, facets, identity, label, stage, origin, budget)
            if skipped:
                found.append(Overflow(
                    project=identity,
                    step="%s/%s" % (origin, stage),
                    matched_bytes=sum(e.size() for e in matched),
                    budget=budget,
                    skipped=tuple(e.id for e in skipped),
                ))
    return sorted(found, key=lambda o: (o.project, o.step))


def is_universal(entry):
    return entry.is_candidate() and not entry.facets and not entry.projects


def heaviest_universal_step(entries, steps):
    universal = [e for e in entries if is_universal(e)]
    if not steps:
        return None, sum(e.size() for e in universal)
    best = None
    for origin, stage in steps:
        total = sum(e.size() for e in universal if matches_step(e, stage, origin))
        if best is None or total > best[1]:
            best = ("%s/%s" % (origin, stage), total)
    return best
