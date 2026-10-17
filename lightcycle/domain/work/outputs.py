from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

from lightcycle.domain.runs.pass_record import pass_number
from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.behind_marker import BEHIND_NOT_UPDATED

BOOKKEEPING_TYPES = frozenset({
    "session-id", "trusted-authors", "pr-head-sha", "ci-judged-sha", "admitted-comments",
    BEHIND_NOT_UPDATED, "schedule-state", "resolves", "resolved-by", "log",
})


@dataclass(frozen=True)
class ArtifactRecord:
    node_id: str
    seq: int
    artifact: Artifact


@dataclass(frozen=True)
class StepFacts:
    id: str
    pass_id: Optional[str]
    declared: FrozenSet[str]
    at: Optional[str]


@dataclass(frozen=True)
class OutputEntry:
    name: str
    label: Optional[str]
    value: str
    kind: Optional[str]
    step: Optional[str]
    pass_id: Optional[str]
    at: Optional[str]
    seq: int = 0

    @property
    def identity(self):
        return (self.name, self.label)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "value": self.value,
            "kind": self.kind,
            "step": self.step,
            "pass": self.pass_id,
            "at": self.at,
        }

    def as_artifact(self) -> Artifact:
        return Artifact(type=self.name, value=self.value, label=self.label, kind=self.kind)


@dataclass(frozen=True)
class OutputSet:
    artifacts: Tuple[OutputEntry, ...] = ()
    item_level: Tuple[Artifact, ...] = ()
    history: Dict[Tuple[str, Optional[str]], Tuple[OutputEntry, ...]] = field(default_factory=dict)

    @property
    def types(self):
        return {e.name for e in self.artifacts}

    def by_step(self):
        out: Dict[str, List[OutputEntry]] = {}
        for entry in self.artifacts:
            if entry.step is not None:
                out.setdefault(entry.step, []).append(entry)
        return out

    def promoted_artifacts(self):
        return [e.as_artifact() for e in self.artifacts if e.step is not None]

    def history_of(self, entry):
        return self.history.get(entry.identity, ())

    def entry_dicts(self):
        out = []
        for entry in self.artifacts:
            d = entry.as_dict()
            d["history"] = [h.as_dict() for h in self.history_of(entry)]
            out.append(d)
        return out


def classify_step_rows(rows, declared):
    outputs = []
    records = []
    for row in rows:
        if row.type in BOOKKEEPING_TYPES:
            continue
        if not row.internal and row.type in declared:
            outputs.append(row)
        else:
            records.append(row)
    return outputs, records


def _visible_item_row(row):
    return not row.internal and row.type not in BOOKKEEPING_TYPES


def resolve_outputs(item_id, records, steps, reader_pass=None):
    item_rows = []
    step_candidates = []
    for rec in records:
        if rec.node_id == item_id:
            item_rows.append(rec)
            continue
        facts = steps.get(rec.node_id)
        if facts is None:
            continue
        row = rec.artifact
        if row.internal or row.type in BOOKKEEPING_TYPES or row.type not in facts.declared:
            continue
        if reader_pass is not None and pass_number(facts.pass_id) > reader_pass:
            continue
        step_candidates.append((rec, facts))

    item_entries = [
        OutputEntry(
            name=r.artifact.type, label=r.artifact.label, value=r.artifact.value,
            kind=r.artifact.kind, step=None, pass_id=None, at=None, seq=r.seq,
        )
        for r in item_rows if _visible_item_row(r.artifact)
    ]
    item_identities = {e.identity for e in item_entries}

    by_identity: Dict[Tuple[str, Optional[str]], List[OutputEntry]] = {}
    for rec, facts in sorted(step_candidates, key=lambda c: c[0].seq):
        entry = OutputEntry(
            name=rec.artifact.type, label=rec.artifact.label, value=rec.artifact.value,
            kind=rec.artifact.kind, step=facts.id, pass_id=facts.pass_id, at=facts.at,
            seq=rec.seq,
        )
        by_identity.setdefault(entry.identity, []).append(entry)

    current = list(item_entries)
    history: Dict[Tuple[str, Optional[str]], Tuple[OutputEntry, ...]] = {}
    for identity, entries in by_identity.items():
        ordered = list(reversed(entries))
        if identity in item_identities:
            history[identity] = tuple(ordered)
        else:
            current.append(ordered[0])
            if len(ordered) > 1:
                history[identity] = tuple(ordered[1:])
    current.sort(key=lambda e: e.seq)
    return OutputSet(
        artifacts=tuple(current),
        item_level=tuple(r.artifact for r in item_rows),
        history=history,
    )
